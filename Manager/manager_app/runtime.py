from __future__ import annotations

import json
import socket
import threading
import uuid
from datetime import datetime
from pathlib import Path

import requests

from config import CONFIG
from discovery_client import discover


class ManagerRuntime:
    """Lightweight Manager↔Server connection runtime.

    Manager is an operator client of the Central Server; it is not the customer Client.
    """
    def __init__(self):
        self.cfg_file = Path(__file__).resolve().parents[1] / "manager_config.json"
        self.cfg = self._load()
        self.device_id = self.cfg.get("device_id") or str(uuid.uuid4())
        self.cfg["device_id"] = self.device_id
        self.cfg["device_name"] = self.cfg.get("device_name") or (socket.gethostname() + "-MANAGER")
        self.cfg["device_type"] = "MANAGER"
        self.state = "OFFLINE"
        self.last_error = ""
        self.last_heartbeat = None
        self.server_url = str(self.cfg.get("server_url") or "").rstrip("/")
        # Migrate the known V27.3.x pywebview bridge port; Central Server is 8787.
        legacy_url = self.server_url.lower().rstrip("/")
        legacy_port = int(self.cfg.get("server_port") or 0)
        if legacy_port == 38797 or legacy_url.endswith(":38797"):
            self.server_url = "http://127.0.0.1:8787"
            self.cfg["server_ip"] = "127.0.0.1"
            self.cfg["server_port"] = 8787
        if not self.server_url and self.cfg.get("server_ip"):
            self.server_url = f"http://{self.cfg.get('server_ip')}:{int(self.cfg.get('server_port') or 8787)}"
        if not self.server_url:
            self.server_url = f"http://127.0.0.1:{int(self.cfg.get('server_port') or 8787)}"
        self.stop_event = threading.Event()
        self._thread = None
        self._save()

    def _load(self):
        try:
            return json.loads(self.cfg_file.read_text(encoding="utf-8")) if self.cfg_file.exists() else {}
        except Exception:
            return {}

    def _save(self):
        self.cfg_file.write_text(json.dumps(self.cfg, ensure_ascii=False, indent=2), encoding="utf-8")

    def ensure_server(self):
        if self.server_url:
            return self.server_url
        if self.cfg.get("auto_discover", True):
            self.state = "DISCOVERING"
            found = discover(timeout=float(self.cfg.get("discovery_timeout", 1.5)), port=8788)
            if found:
                self.server_url = found.rstrip("/")
                self.cfg["server_url"] = self.server_url
                self._save()
                return self.server_url
        return ""

    def _probe_health(self, url):
        r = requests.get(url.rstrip("/") + "/health", timeout=max(1.0, float(self.cfg.get("heartbeat_timeout", 3))))
        r.raise_for_status()
        data = r.json() if r.content else {}
        return data if isinstance(data, dict) else {}

    def heartbeat_once(self):
        candidates=[]
        if self.server_url: candidates.append(self.server_url.rstrip("/"))
        ip=str(self.cfg.get("server_ip") or "").strip()
        port=int(self.cfg.get("server_port") or 8787)
        if ip: candidates.append(f"http://{ip}:{port}")
        if self.cfg.get("allow_local_fallback", True): candidates.append(f"http://127.0.0.1:{port}")
        if self.cfg.get("auto_discover", True) and not candidates:
            try:
                found=discover(timeout=float(self.cfg.get("discovery_timeout", 1.5)), port=8788)
                if found: candidates.append(found.rstrip("/"))
            except Exception: pass
        seen=[]
        for url in candidates:
            if not url or url in seen: continue
            seen.append(url)
            try:
                health=self._probe_health(url)
                self.server_url=url
                self.cfg["server_url"]=url
                self.cfg["server_ip"]=url.split("://",1)[-1].rsplit(":",1)[0] if ":" in url.split("://",1)[-1] else url.split("://",1)[-1]
                self.cfg["server_port"]=int(url.rsplit(":",1)[-1]) if ":" in url.rsplit("/",1)[-1] else port
                self.last_heartbeat=datetime.now(); self.state="ONLINE"; self.last_error=""; self._save()
                # Heartbeat is best-effort; health is authoritative for the UI connection badge.
                try:
                    requests.post(url+"/api/v1/heartbeat", json={"device_id":self.device_id,"device_name":self.cfg["device_name"],"device_type":"MANAGER","branch_id":CONFIG.get("branch_id"),"warehouse_id":CONFIG.get("warehouse_id"),"app_version":"V27.5.7-Manager","status":"ONLINE","last_error":""}, timeout=float(self.cfg.get("heartbeat_timeout",3)))
                except Exception: pass
                return True
            except Exception as exc:
                self.last_error=f"{url}: {exc}"
        self.state="OFFLINE"
        return False

    def connection_status(self):
        # Return cached state. The heartbeat thread updates it asynchronously, keeping the WebView responsive.
        return {"connected": self.state == "ONLINE", "last_error": str(self.last_error or ""), "server_url": self.server_url}

    def start(self):
        if self._thread and self._thread.is_alive(): return self._thread
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                self.heartbeat_once()
                self.stop_event.wait(float(self.cfg.get("heartbeat_seconds", 10)))
        self._thread = threading.Thread(target=loop, name="POS-ManagerHeartbeat", daemon=True)
        self._thread.start()
        return self._thread

    def stop(self):
        self.stop_event.set()
        if self._thread and self._thread.is_alive(): self._thread.join(timeout=1.5)
