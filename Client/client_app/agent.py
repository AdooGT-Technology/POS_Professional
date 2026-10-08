from __future__ import annotations

import json
import os
import socket
import threading
import time
import uuid
import ctypes
import base64
import io
from datetime import datetime
from pathlib import Path

import requests
import psutil

from config import CONFIG
from discovery_client import discover


class ClientRuntime:
    def __init__(self):
        self.cfg_file = Path(__file__).resolve().parent / "client_config.json"
        self.cfg = self._load()
        self.device_id = self.cfg.get("device_id") or str(uuid.uuid4())
        self.cfg["device_id"] = self.device_id
        self.cfg["device_name"] = self.cfg.get("device_name") or socket.gethostname()
        self.state = "OFFLINE"
        self.last_error = ""
        self.last_heartbeat = None
        self.server_url = str(self.cfg.get("server_url") or "").rstrip("/")
        self.control_token = str(self.cfg.get("device_token") or "")
        self.session_paused = bool(self.cfg.get("session_paused", False))
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
            found = discover(timeout=float(self.cfg.get("discovery_timeout", 1.5)), port=int(CONFIG.get("discovery_port", 8788)))
            if found:
                self.server_url = found.rstrip("/")
                self.cfg["server_url"] = self.server_url
                self._save()
                return self.server_url
        return ""

    def register_control(self):
        url = self.ensure_server()
        if not url: return False
        try:
            response = requests.post(url + f"/api/v19/client/{self.device_id}/register", json={"device_name":self.cfg["device_name"],"device_type":"CLIENT","app_version":"V27.5.7"}, timeout=4)
            response.raise_for_status(); data=response.json(); token=str(data.get("device_token") or "")
            if token:
                self.control_token=token; self.cfg["device_token"]=token; self._save()
            return bool(self.control_token)
        except Exception as exc:
            self.last_error=str(exc)[:1000]; return False

    def _ps_temperature(self):
        if os.name != 'nt': return None
        try:
            import subprocess
            cmd=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',
                 "Get-CimInstance MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty CurrentTemperature"]
            out=subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
            if out and out.isdigit(): return round((float(out)-2732)/10,1)
        except Exception: pass
        return None

    def _gpu_stats(self):
        result={'name':'','percent':0.0,'temperature':None,'memory_percent':0.0}
        try:
            import subprocess
            out=subprocess.check_output(['nvidia-smi','--query-gpu=name,utilization.gpu,temperature.gpu,memory.used,memory.total','--format=csv,noheader,nounits'],text=True,stderr=subprocess.DEVNULL,timeout=2)
            line=out.strip().splitlines()[0] if out.strip() else ''
            parts=[x.strip() for x in line.split(',')]
            if len(parts)>=5:
                used=float(parts[3]); total=max(float(parts[4]),1)
                result={'name':parts[0],'percent':float(parts[1]),'temperature':float(parts[2]),'memory_percent':used*100/total}
        except Exception: pass
        return result

    def _disk_stats(self):
        disks=[]; health=[]; temps=[]
        try:
            for part in psutil.disk_partitions(all=False):
                if not part.mountpoint or 'cdrom' in (part.opts or '').lower(): continue
                try:
                    u=psutil.disk_usage(part.mountpoint); disks.append({'mount':part.mountpoint,'usage_percent':round(float(u.percent),1),'free_gb':round(u.free/1024**3,2),'total_gb':round(u.total/1024**3,2),'health_percent':None,'temperature':None})
                except Exception: pass
        except Exception: pass
        if os.name=='nt':
            try:
                import subprocess, json as _json
                cmd=['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',
                     "Get-PhysicalDisk | Select-Object FriendlyName,HealthStatus,OperationalStatus,Size | ConvertTo-Json -Compress"]
                raw=subprocess.check_output(cmd,text=True,stderr=subprocess.DEVNULL,timeout=3).strip()
                arr=_json.loads(raw) if raw else []
                if isinstance(arr,dict): arr=[arr]
                for d in arr:
                    hp=100.0 if str(d.get('HealthStatus','')).lower()=='healthy' else (0.0 if d.get('HealthStatus') else None)
                    if hp is not None: health.append(hp)
                for item in disks: item['health_percent']=min(health) if health else None
            except Exception: pass
        return disks, (min(health) if health else None), (sum(temps)/len(temps) if temps else None)

    def _lan_stats(self):
        best_speed=0.0; adapter=""
        try:
            for name,stat in psutil.net_if_stats().items():
                if not stat.isup: continue
                lname=name.lower()
                if lname.startswith(("loopback","lo","bluetooth","pseudo")): continue
                speed=float(stat.speed or 0)
                if speed > best_speed:
                    best_speed=speed; adapter=name
        except Exception:
            pass
        return best_speed, adapter

    def _telemetry(self):
        try:
            vm=psutil.virtual_memory(); cpu=float(psutil.cpu_percent(interval=None)); ram=float(vm.percent); ram_speed=None
            if os.name=='nt':
                try:
                    import subprocess, json as _json
                    raw=subprocess.check_output(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command','Get-CimInstance Win32_PhysicalMemory | Measure-Object -Property Speed -Average | Select-Object -ExpandProperty Average'],text=True,stderr=subprocess.DEVNULL,timeout=2).strip()
                    if raw: ram_speed=float(raw)
                except Exception: pass
            gpu=self._gpu_stats(); disks,disk_health,disk_temp=self._disk_stats(); cpu_temp=self._ps_temperature(); lan_speed,lan_adapter=self._lan_stats()
            apps=[]
            for p in psutil.process_iter(["name"]):
                try:
                    name=(p.info.get("name") or "").strip()
                    if name and name.lower().endswith((".exe",)) and name.lower() not in {"system idle process","system"}: apps.append(name[:120])
                except Exception: pass
            seen=[]
            for x in apps:
                if x not in seen: seen.append(x)
            return {'cpu_percent':cpu,'cpu_temperature':cpu_temp,'ram_percent':ram,'ram_used_gb':vm.used/1024**3,'ram_total_gb':vm.total/1024**3,'ram_speed_mhz':ram_speed,'gpu':gpu,'disks':disks,'disk_health_percent':disk_health,'disk_temperature':disk_temp,'running_apps':seen[:30],'lan_speed_mbps':lan_speed,'lan_adapter':lan_adapter}
        except Exception:
            return {'cpu_percent':0.0,'cpu_temperature':None,'ram_percent':0.0,'ram_used_gb':0,'ram_total_gb':0,'ram_speed_mhz':None,'gpu':{'name':'','percent':0,'temperature':None,'memory_percent':0},'disks':[],'disk_health_percent':None,'disk_temperature':None,'running_apps':[],'lan_speed_mbps':None,'lan_adapter':''}

    def send_telemetry(self):
        if not self.control_token or not self.server_url: return False
        try:
            t=self._telemetry(); gpu=t['gpu']
            r=requests.post(self.server_url+f"/api/v19/client/{self.device_id}/telemetry", headers={"X-Device-Token":self.control_token}, json={"cpu_percent":t['cpu_percent'],"cpu_temperature":t['cpu_temperature'],"ram_percent":t['ram_percent'],"ram_used_gb":t['ram_used_gb'],"ram_total_gb":t['ram_total_gb'],"ram_speed_mhz":t['ram_speed_mhz'],"gpu_name":gpu['name'],"gpu_percent":gpu['percent'],"gpu_temperature":gpu['temperature'],"gpu_memory_percent":gpu['memory_percent'],"disk_health_percent":t['disk_health_percent'],"disk_temperature":t['disk_temperature'],"disk_usage_percent":max([float(x.get('usage_percent',0)) for x in t['disks']] or [0]),"disks":t['disks'],"running_apps":t['running_apps'],"current_user":self.cfg.get("current_customer", ""),"session_paused":self.session_paused,"lan_speed_mbps":t.get("lan_speed_mbps"),"lan_adapter":t.get("lan_adapter",""),"status":"BUSY" if self.state=="BUSY" else ("SYNCING" if self.state=="SYNCING" else "ONLINE")}, timeout=4)
            r.raise_for_status(); return True
        except Exception: return False

    def _capture_screen(self):
        try:
            from PIL import ImageGrab
            img=ImageGrab.grab(all_screens=True)
            bio=io.BytesIO(); img.save(bio,format="JPEG",quality=65,optimize=True); return base64.b64encode(bio.getvalue()).decode("ascii")
        except Exception as exc:
            raise RuntimeError(f"Screen capture failed: {exc}")

    def poll_control_commands(self):
        if not self.control_token or not self.server_url: return
        try:
            r=requests.get(self.server_url+f"/api/v19/client/{self.device_id}/commands/poll", headers={"X-Device-Token":self.control_token}, timeout=4); r.raise_for_status()
            for cmd in r.json().get("commands",[]):
                command=str(cmd.get("command") or "").upper(); cid=str(cmd.get("command_id") or "")
                try:
                    if command=="LOCK":
                        if os.name=="nt": ctypes.windll.user32.LockWorkStation()
                        result={"locked":True}
                    elif command=="SESSION_PAUSE":
                        self.session_paused=bool((cmd.get("payload") or {}).get("paused", True)); self.cfg["session_paused"]=self.session_paused; self._save(); result={"paused":self.session_paused}
                    elif command=="REFRESH_UI":
                        self.cfg["ui_refresh_requested"]=True; self._save(); result={"refresh_requested":True}
                    elif command=="SCREENSHOT":
                        img=self._capture_screen(); up=requests.post(self.server_url+f"/api/v19/client/{self.device_id}/screen", headers={"X-Device-Token":self.control_token}, params={"command_id":cid,"image_base64":img}, timeout=12); up.raise_for_status(); result=up.json()
                    elif command=="TASK_EXECUTE":
                        pay=cmd.get("payload") or {}; target=str(pay.get("path") or '').strip(); args=str(pay.get("arguments") or '').strip(); cwd=str(pay.get("working_dir") or '').strip() or None; task_type=str(pay.get("type") or 'PROCESS').upper(); service=str(pay.get("service") or '').strip(); service_action=str(pay.get("service_action") or 'start').lower()
                        import subprocess as _subprocess
                        if task_type=='SERVICE' and service:
                            if service_action=='restart':
                                _subprocess.run(['sc.exe','stop',service],capture_output=True,timeout=20); proc=_subprocess.Popen(['sc.exe','start',service],stdout=_subprocess.DEVNULL,stderr=_subprocess.DEVNULL); result={"started":True,"service":service,"action":service_action,"pid":proc.pid}
                            else:
                                proc=_subprocess.Popen(['sc.exe',service_action,service],stdout=_subprocess.DEVNULL,stderr=_subprocess.DEVNULL); result={"started":True,"service":service,"action":service_action,"pid":proc.pid}
                        else:
                            if not target: raise RuntimeError('Task path is empty')
                            proc=_subprocess.Popen(target + (' '+args if args else ''), cwd=cwd, shell=True, stdout=_subprocess.DEVNULL, stderr=_subprocess.DEVNULL)
                            result={"started":True,"pid":proc.pid}
                    else: result={"ignored":True}
                    requests.post(self.server_url+f"/api/v19/client/{self.device_id}/commands/{cid}/ack", headers={"X-Device-Token":self.control_token}, json={"status":"SUCCESS","result":result}, timeout=4)
                except Exception as exc:
                    try: requests.post(self.server_url+f"/api/v19/client/{self.device_id}/commands/{cid}/ack", headers={"X-Device-Token":self.control_token}, json={"status":"FAILED","result":{"error":str(exc)[:500]}}, timeout=4)
                    except Exception: pass
        except Exception: return

    def start_control_agent(self):
        if getattr(self, "control_thread", None) and self.control_thread.is_alive(): return self.control_thread
        self.control_stop=threading.Event()
        def loop():
            self.register_control()
            while not self.control_stop.is_set():
                self.send_telemetry(); self.poll_control_commands(); self.control_stop.wait(2.0)
        self.control_thread=threading.Thread(target=loop,name="POS-ClientControlAgent",daemon=True); self.control_thread.start(); return self.control_thread

    def stop_control_agent(self):
        if getattr(self,"control_stop",None): self.control_stop.set()
        if getattr(self,"control_thread",None) and self.control_thread.is_alive(): self.control_thread.join(timeout=1.5)

    def heartbeat_once(self):
        url = self.ensure_server()
        if not url:
            self.state = "OFFLINE"; self.last_error = "لم يتم اكتشاف الخادم"; return False
        try:
            response = requests.post(url + "/api/v1/heartbeat", json={
                "device_id": self.device_id,
                "device_name": self.cfg["device_name"],
                "device_type": self.cfg.get("device_type", "POS"),
                "branch_id": self.cfg.get("branch_id"),
                "warehouse_id": self.cfg.get("warehouse_id"),
                "app_version": "V21",
                "status": self.state if self.state in {"SYNCING", "ONLINE"} else "ONLINE",
                "last_error": self.last_error,
            }, timeout=float(self.cfg.get("heartbeat_timeout", 3)))
            response.raise_for_status()
            self.last_heartbeat = datetime.now()
            if self.state != "SYNCING": self.state = "ONLINE"
            self.last_error = ""
            return True
        except Exception as exc:
            self.state = "OFFLINE"; self.last_error = str(exc)[:1000]; return False

    def start(self):
        if self._thread and self._thread.is_alive(): return self._thread
        self.stop_event.clear()
        def loop():
            while not self.stop_event.is_set():
                self.heartbeat_once()
                self.stop_event.wait(float(self.cfg.get("heartbeat_seconds", 5)))
        self._thread = threading.Thread(target=loop, name="POS-ClientHeartbeat", daemon=True)
        self._thread.start()
        try: self.start_control_agent()
        except Exception: pass
        return self._thread

    def stop(self):
        self.stop_event.set()
        try: self.stop_control_agent()
        except Exception: pass
        if self._thread and self._thread.is_alive(): self._thread.join(timeout=1.5)

    def set_syncing(self): self.state = "SYNCING"
    def set_online(self): self.state = "ONLINE"
    def set_offline(self, error=""): self.state = "OFFLINE"; self.last_error = str(error)[:1000]
