from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parents[1]
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from runtime_bootstrap import ensure_runtime

code = ensure_runtime("manager_app/main.py")
if code is not None:
    raise SystemExit(code)

os.environ["POS_ROLE"] = "MANAGER"
print("[POS MANAGER] Shared Runtime ready — launching Manager WebView2 UI...", flush=True)
from manager_app.runtime import ManagerRuntime
from manager_app.web_manager import main as web_manager_main


if __name__ == "__main__":
    runtime = ManagerRuntime()
    try:
        raise SystemExit(web_manager_main(runtime))
    finally:
        runtime.stop()
