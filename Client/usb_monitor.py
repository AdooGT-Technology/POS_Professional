from __future__ import annotations
import ctypes, hashlib, json, os, threading, time
from pathlib import Path
import requests

DRIVE_REMOVABLE = 2

def removable_drives() -> dict[str, dict]:
    result = {}
    if os.name != "nt":
        return result
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    get_type = ctypes.windll.kernel32.GetDriveTypeW
    for i in range(26):
        if not (bitmask & (1 << i)):
            continue
        root = f"{chr(65+i)}:\\"
        if get_type(root) != DRIVE_REMOVABLE:
            continue
        label = ""
        try:
            vol_name = ctypes.create_unicode_buffer(261)
            fs_name = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(root, vol_name, 260, None, None, None, fs_name, 260)
            label = vol_name.value
        except Exception:
            pass
        result[root] = {"root": root, "label": label or root.rstrip("\\")}
    return result

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()

class USBMonitor:
    """Safe baseline monitor: detects removable-drive attach/detach and filesystem changes.
    It never records file contents. FROM_USB detection requires an endpoint adapter/app integration;
    created/modified files on the removable drive are recorded as TO_USB events.
    """
    def __init__(self, runtime, poll_seconds: float = 2.0):
        self.runtime = runtime
        self.poll_seconds = poll_seconds
        self.stop_event = threading.Event()
        self.thread = None
        self.sessions: dict[str, int] = {}
        self.snapshots: dict[str, dict[str, tuple[int, int]]] = {}
        self.policy = {"policy":"ALLOW", "sha256_enabled":False}

    @property
    def client_id(self):
        return self.runtime.cfg.get("client_id") or self.runtime.device_id

    def _url(self): return (self.runtime.server_url or self.runtime.ensure_server()).rstrip("/")
    def _get_policy(self):
        try:
            r=requests.get(self._url()+f"/api/v17/usb/policy/{self.client_id}",timeout=3); r.raise_for_status(); self.policy=r.json()
        except Exception: pass

    def _snapshot(self, root: str):
        data={}
        base=Path(root)
        try:
            for p in base.rglob("*"):
                if not p.is_file(): continue
                try:
                    st=p.stat(); rel=str(p.relative_to(base))
                    data[rel]=(int(st.st_size),int(st.st_mtime_ns))
                    if len(data)>=2000: break
                except OSError: continue
        except OSError: pass
        return data

    def _start_session(self, d):
        try:
            payload={"client_id":self.client_id,"volume_id":d["root"],"volume_label":d["label"],"mount_path":d["root"],"customer_name": self.runtime.cfg.get("current_customer", "")}
            r=requests.post(self._url()+"/api/v17/usb/session/start",json=payload,timeout=4); r.raise_for_status(); data=r.json(); sid=data.get("session_id")
            if sid: self.sessions[d["root"]]=int(sid)
        except Exception:
            pass

    def _close_session(self, root):
        sid=self.sessions.pop(root,None)
        if sid is None: return
        try:
            requests.post(self._url()+f"/api/v17/usb/session/{sid}/close",params={"client_id":self.client_id},timeout=4)
        except Exception: pass

    def _record_change(self, root, rel, size, status):
        sid=self.sessions.get(root)
        if sid is None: return
        digest=""
        if self.policy.get("sha256_enabled"):
            try: digest=file_sha256(Path(root)/rel)
            except Exception: digest=""
        try:
            payload={"client_id":self.client_id,"file_name":rel,"file_size_bytes":int(size),"direction":"TO_USB","status":status,"sha256":digest}
            r=requests.post(self._url()+f"/api/v17/usb/session/{sid}/event",json=payload,timeout=4); r.raise_for_status()
        except Exception: pass

    def _loop(self):
        self._get_policy()
        previous=set()
        while not self.stop_event.is_set():
            try:
                drives=removable_drives(); current=set(drives)
                for root in sorted(current-previous):
                    self._start_session(drives[root]); self.snapshots[root]=self._snapshot(root)
                for root in sorted(current & previous):
                    old=self.snapshots.get(root,{})
                    new=self._snapshot(root)
                    for rel,(size,mtime) in new.items():
                        if rel not in old or old[rel] != (size,mtime):
                            self._record_change(root,rel,size,"CREATED" if rel not in old else "MODIFIED")
                    self.snapshots[root]=new
                for root in sorted(previous-current):
                    self._close_session(root); self.snapshots.pop(root,None)
                previous=current
            except Exception:
                pass
            self.stop_event.wait(self.poll_seconds)
        for root in list(self.sessions): self._close_session(root)

    def start(self):
        if self.thread and self.thread.is_alive(): return self.thread
        self.stop_event.clear(); self.thread=threading.Thread(target=self._loop,name="POS-USB-Monitor",daemon=True); self.thread.start(); return self.thread
    def stop(self):
        self.stop_event.set()
        if self.thread and self.thread.is_alive(): self.thread.join(timeout=3)


class USBEndpointAdapter:
    """Integration hook for an approved Windows endpoint adapter.
    The base package only records policy and never applies kernel-level blocking.
    """
    def __init__(self, monitor: USBMonitor):
        self.monitor = monitor

    def apply_policy(self, policy: str) -> tuple[bool, str]:
        policy = str(policy).upper().strip()
        if policy == "ALLOW":
            return True, "ALLOW يحتاج إلى إجراء إضافي."
        if policy in {"READ_ONLY", "BLOCK"}:
            return False, "يلزم Adapter/GPO/EDR/Driver معتمد لفرض السياسة فعليًا."
        return False, "Policy غير صالحة."

    def report_transfer(self, session_id: int, file_name: str, size_bytes: int, direction: str, status: str = "RECORDED", sha256: str = ""):
        """Optional hook used by a real endpoint adapter to report FROM_USB or other transfer metadata."""
        url = self.monitor._url()
        payload = {
            "client_id": self.monitor.client_id,
            "file_name": file_name,
            "file_size_bytes": int(size_bytes),
            "direction": direction,
            "status": status,
            "sha256": sha256,
        }
        r = requests.post(url + f"/api/v17/usb/session/{int(session_id)}/event", json=payload, timeout=4)
        r.raise_for_status()
        return r.json()
