from __future__ import annotations
import os, subprocess, sys, traceback, webbrowser
from pathlib import Path
APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
from runtime_bootstrap import ensure_runtime
code = ensure_runtime("run_server.py")
if code is not None:
    raise SystemExit(code)

def main():
    try:
        os.environ["POS_SERVER_MODE"] = "1"
        os.environ["POS_ROLE"] = "SERVER"
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        with (LOG_DIR / "discovery.log").open("a", encoding="utf-8") as log:
            p = subprocess.Popen(
                [sys.executable, "-u", str(APP_DIR / "run_discovery.py")],
                cwd=APP_DIR, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=creationflags
            )
        print("=" * 64, flush=True)
        print("  POS Professional V27.5.7 - CENTRAL SERVER", flush=True)
        print("=" * 64, flush=True)
        print(f"Discovery: UDP 8788 (PID {p.pid})", flush=True)
        from server_app.server import run
        return run() or 0
    except Exception as exc:
        with (LOG_DIR / "server_startup_error.log").open("a", encoding="utf-8") as f:
            traceback.print_exc(file=f)
        print(f"POS V27.5.7 Central Server startup error: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
