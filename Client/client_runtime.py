from __future__ import annotations

import json
import socket
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import requests

from config import CONFIG
from discovery_client import discover


class ClientRuntime:
    def __init__(self):
        self.cfg_file = Path(__file__).resolve().parent / "client_config.json"
        self.cfg = self._load()
        # V27.5.7: Client configuration is customer-facing only; Manager owns all administration.
        # Remove legacy PIN/admin keys even on upgrades from older builds.
        self.cfg.pop("admin_pin", None)
        self.cfg.pop("admin_settings_enabled", None)
        self.device_id = self.cfg.get("client_id") or self.cfg.get("device_id") or str(uuid.uuid4())
        self.cfg["client_id"] = self.device_id
        self.cfg["device_id"] = self.device_id
        self.cfg["device_name"] = self.cfg.get("device_name") or socket.gethostname()
        self.state = "OFFLINE"
        self.last_error = ""
        self.last_heartbeat = None
        self.server_url = str(self.cfg.get("server_url") or "").rstrip("/")
        # Customer sessions are ephemeral: never reopen the last player after a Client restart.
        self.cfg["current_customer"] = ""
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
                "app_version": "V27.5.8-Client-WebView2",
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
        return self._thread

    def stop(self):
        self.stop_event.set()
        if self._thread and self._thread.is_alive(): self._thread.join(timeout=1.5)

    def set_syncing(self): self.state = "SYNCING"
    def set_online(self): self.state = "ONLINE"
    def set_offline(self, error=""): self.state = "OFFLINE"; self.last_error = str(error)[:1000]
