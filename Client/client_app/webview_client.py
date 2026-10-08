from __future__ import annotations

import json
import shlex
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any

import requests

WEB_UI_DIR = Path(__file__).resolve().parent / "webui"


def _asset_url(server_url: str, value: str) -> str:
    if not value:
        return ""
    if value.startswith(("http://", "https://", "data:", "file:")):
        return value
    return server_url.rstrip("/") + "/" + value.lstrip("/")


class ClientWebAPI:
    """Small, explicit bridge for the customer Client UI.

    The JS bridge intentionally uses `authenticate` instead of `login` because
    the customer page must have a stable, unambiguous API method name.
    """

    def __init__(self, runtime):
        self.runtime = runtime
        self._window = None
        self.server_url = ""
        self.token = ""
        self.kiosk_state = False
        self.runtime.cfg["current_customer"] = ""
        self.runtime.cfg["session_paused"] = False
        self.runtime._save()

    def _url(self, path: str) -> str:
        self.server_url = (self.server_url or self.runtime.server_url or self.runtime.ensure_server()).rstrip("/")
        if not self.server_url:
            raise RuntimeError("Central Server غير متصل")
        return self.server_url + path

    def _request(self, method: str, path: str, **kwargs):
        kwargs.setdefault("timeout", 4)
        response = requests.request(method, self._url(path), **kwargs)
        response.raise_for_status()
        return response

    def _enrich(self, payload: dict[str, Any], include_catalog: bool = True) -> dict[str, Any]:
        payload = dict(payload or {})
        profile = dict(payload.get("profile") or {})
        for key in ("logo_asset", "background_asset", "video_asset", "main_image_asset", "icon_games", "icon_apps", "icon_shop", "icon_events", "icon_ads", "icon_my_files", "icon_profile"):
            profile[key] = _asset_url(self.server_url, str(profile.get(key) or ""))
        if include_catalog:
            for item in payload.get("items", []):
                item["icon_url"] = _asset_url(self.server_url, str(item.get("icon_url") or item.get("icon_asset") or item.get("icon") or ""))
                item["poster_url"] = _asset_url(self.server_url, str(item.get("poster_url") or item.get("poster") or item.get("poster_asset") or ""))
            for banner in payload.get("banners", []):
                banner["image_url"] = _asset_url(self.server_url, str(banner.get("image_asset") or ""))
        payload["profile"] = profile
        payload["customer_name"] = self.runtime.cfg.get("current_customer", "")
        payload["client_id"] = self.runtime.device_id
        payload["client_config"] = {"server_ip": self.runtime.cfg.get("server_ip", ""), "server_port": self.runtime.cfg.get("server_port", 8787), "device_name": self.runtime.cfg.get("device_name", ""), "store_name": self.runtime.cfg.get("store_name", ""), "kiosk_mode": bool(self.runtime.cfg.get("kiosk_mode", False)), "auto_discover": bool(self.runtime.cfg.get("auto_discover", True))}
        return payload

    def get_public_bootstrap(self):
        """Return only data that is safe/needed on the login screen."""
        data = self._request("GET", f"/api/v18/client/{self.runtime.device_id}/ui").json()
        public = {
            "profile": data.get("profile") or {},
            "store_name": data.get("store_name") or self.runtime.cfg.get("store_name") or "متجري",
            "store_logo": data.get("store_logo") or "",
            "client_id": self.runtime.device_id,
            "customer_name": "",
            "items": [],
            "banners": [],
        }
        return self._enrich(public, include_catalog=False)

    def get_bootstrap(self):
        data = self._request("GET", f"/api/v18/client/{self.runtime.device_id}/ui").json()
        return self._enrich(data, include_catalog=True)

    def authenticate(self, payload=None, pin=None):
        """Authenticate from one JSON-compatible payload for a stable pywebview bridge."""
        # pywebview can pass a JSON object or legacy positional arguments. Accept both.
        if isinstance(payload, dict):
            data_payload = payload
        else:
            data_payload = {"customer_name": payload, "pin": pin}
        customer_name = str(data_payload.get("customer_name") or "").strip()
        pin = str(data_payload.get("pin") or "")
        if not customer_name:
            raise ValueError("اكتب اسم العميل")
        data = self._request(
            "POST", "/api/v15/client/login",
            json={"customer_name": customer_name, "pin": pin, "device_id": self.runtime.device_id},
        ).json()
        self.token = str(data.get("token") or "")
        self.runtime.cfg["current_customer"] = customer_name
        self.runtime.session_paused = False
        self.runtime.cfg["session_paused"] = False
        self.runtime._save()
        self.runtime.set_online()
        return {"ok": True, "customer_name": customer_name}

    def logout(self):
        self.runtime.cfg["current_customer"] = ""
        self.runtime._save()
        self.token = ""
        self.runtime.set_online()
        return {"ok": True}

    def _launch_legacy_catalog(self, value: str):
        """Launch legacy v15 catalog identifiers without ever parsing them as integers."""
        raw = str(value or "").strip()
        lowered = raw.lower()
        if lowered.startswith("legacy-game:"):
            kind = "game"
            legacy_id = raw.split(":", 1)[1].strip()
        elif lowered.startswith("legacy-app:"):
            kind = "app"
            legacy_id = raw.split(":", 1)[1].strip()
        elif lowered.startswith("game:"):
            kind = "game"
            legacy_id = raw.split(":", 1)[1].strip()
        elif lowered.startswith("app:"):
            kind = "app"
            legacy_id = raw.split(":", 1)[1].strip()
        else:
            return None
        if not legacy_id:
            raise ValueError("معرّف اللعبة أو التطبيق فارغ")
        data = self._request(
            "POST",
            "/api/v15/client/launch",
            json={"game_id": legacy_id, "device_id": self.runtime.device_id},
        ).json()
        label = "اللعبة" if kind == "game" else "التطبيق"
        return {"ok": True, "legacy": True, "message": f"تم إرسال أمر {label}: {data.get('game_id', legacy_id)}"}

    def launch(self, item_id: Any):
        value = str(item_id or "").strip()
        # IMPORTANT: legacy IDs are string identifiers and must be handled
        # before any numeric conversion. This also protects the Client when
        # an older cached catalog still contains legacy-game:* / legacy-app:*.
        legacy_result = self._launch_legacy_catalog(value)
        if legacy_result is not None:
            return legacy_result
        if not value.isdigit():
            raise ValueError("معرّف التطبيق غير صالح")
        numeric_id = int(value)
        spec = self._request("POST", "/api/v18/client/launch", json={"item_id": numeric_id, "device_id": self.runtime.device_id}).json()
        launch_type = str(spec.get("launch_type") or "").upper()
        target = str(spec.get("target") or "").strip()
        args = str(spec.get("args") or "").strip()
        if launch_type == "URL":
            if not target.startswith(("http://", "https://")):
                raise ValueError("عنوان URL غير مسموح")
            webbrowser.open(target, new=2)
            self.runtime.set_online()
            return {"ok": True, "message": "تم فتح الرابط"}
        if launch_type != "EXE":
            raise ValueError("نوع التشغيل غير مدعوم")
        if not target:
            raise ValueError("مسار التشغيل فارغ")
        exe = Path(target).expanduser()
        if not exe.is_file():
            raise FileNotFoundError(f"ملف التشغيل غير موجود: {target}")
        argv = [str(exe)]
        if args:
            argv.extend(shlex.split(args, posix=(sys.platform != "win32")))
        cwd = str(Path(spec.get("working_dir") or exe.parent))
        subprocess.Popen(argv, cwd=cwd, close_fds=False)
        self.runtime.state = "BUSY"
        return {"ok": True, "message": f"تم تشغيل {spec.get('name') or spec.get('item_type', 'APP')}"}

    def open_external(self, url: str):
        if not str(url).startswith(("http://", "https://")):
            raise ValueError("الرابط غير مسموح")
        webbrowser.open(str(url), new=2)
        return {"ok": True}

    def set_kiosk(self, enabled: bool):
        enabled = bool(enabled)
        if self._window is not None and enabled != self.kiosk_state:
            self._window.toggle_fullscreen()
        self.kiosk_state = enabled
        return {"ok": True, "enabled": enabled}

    def toggle_fullscreen(self):
        if self._window is not None:
            self._window.toggle_fullscreen()
        return {"ok": True}

    def close(self):
        if self._window is not None:
            self._window.destroy()
        return {"ok": True}

    def status(self):
        return {
            "client_id": self.runtime.device_id,
            "state": self.runtime.state,
            "customer": self.runtime.cfg.get("current_customer", ""),
            "session_paused": bool(self.runtime.cfg.get("session_paused", False)),
        }


def run_webview_client(runtime) -> int:
    try:
        import webview
    except Exception as exc:
        print(f"WebView2 client dependency error: {exc}", file=sys.stderr)
        print("ثبت pywebview و Microsoft Edge WebView2 Runtime على جهاز العميل.", file=sys.stderr)
        return 10

    api = ClientWebAPI(runtime)
    try:
        api.server_url = runtime.ensure_server()
        if not api.server_url:
            print("Central Server not discovered.", file=sys.stderr)
            return 2
        html_path = WEB_UI_DIR / "index.html"
        if not html_path.is_file():
            raise FileNotFoundError(html_path)
        window = webview.create_window(
            "POS Professional V27.5.9 Client",
            url=html_path.as_uri(),
            js_api=api,
            width=1600,
            height=960,
            min_size=(1150, 720),
            resizable=not bool(runtime.cfg.get("kiosk_mode", False)),
            frameless=bool(runtime.cfg.get("kiosk_frameless", False)),
            maximized=True,
            zoomable=True,
            background_color="#050914",
        )
        api._window = window
        webview.start(gui="edgechromium", debug=False)
        return 0
    except Exception as exc:
        log = Path(__file__).resolve().parents[1] / "logs"
        log.mkdir(exist_ok=True)
        (log / "webview_startup_error.log").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        print(f"WebView2 startup error: {exc}", file=sys.stderr)
        return 11
