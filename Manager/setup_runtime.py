from runtime_bootstrap import ensure_runtime
if __name__ == "__main__":
    raise SystemExit(ensure_runtime("setup_runtime.py") or 0)
