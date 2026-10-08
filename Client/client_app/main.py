from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from runtime_bootstrap import ensure_runtime
code = ensure_runtime("client_app/main.py")
if code is not None:
    raise SystemExit(code)
os.environ["POS_ROLE"] = "CLIENT"

from client_runtime import ClientRuntime
from webview_client import run_webview_client
from usb_monitor import USBMonitor


def main():
    runtime = ClientRuntime()
    runtime.start()
    usb_monitor = USBMonitor(runtime, poll_seconds=float(runtime.cfg.get("usb_poll_seconds", 2.0))) if runtime.cfg.get("usb_monitor_enabled", True) else None
    if usb_monitor:
        usb_monitor.start()
    try:
        runtime.ensure_server()
        return run_webview_client(runtime)
    finally:
        if usb_monitor:
            usb_monitor.stop()
        runtime.stop()


if __name__ == "__main__":
    raise SystemExit(main())
