from __future__ import annotations
import json
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "client_config.json"
DEFAULT_CONFIG = {"discovery_port": 8788, "theme": "gaming_dark"}
def _load():
    if not CONFIG_FILE.exists(): return dict(DEFAULT_CONFIG)
    try:
        data=json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        out=dict(DEFAULT_CONFIG); out.update(data); return out
    except Exception:
        return dict(DEFAULT_CONFIG)
CONFIG=_load()
