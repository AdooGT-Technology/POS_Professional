import json, os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
SERVER_CONFIG_FILE = BASE_DIR / "server_config.json"
BACKUP_DIR = BASE_DIR / "backups"
EXPORT_DIR = BASE_DIR / "exports"
BACKUP_DIR.mkdir(exist_ok=True)
EXPORT_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "database_url": "sqlite:///pos_v7.db",
    "store_name": "متجري",
    "store_address": "العنوان",
    "store_phone": "",
    "currency": "جنيه",
    "tax_rate": 14.0,
    "printer_type": "windows_raw",
    "printer_name": "",
    "receipt_width": 48,
    "auto_print": False,
    "branch_id": None,
    "warehouse_id": None,
    "theme": "gaming_dark",
    "touch_mode": True,
    "cash_drawer": True,
    "backup_dir": "backups",
    "mysql_dump_path": "",
    "sqlserver_tools_path": "",
    "audit_mode": "strict",
    "backup_schedule_hours": 24,
    "startup_auto_schema_upgrade": True,
    "v10_backup_before_migration": True,
    "v10_auto_rollback_on_failure": False,
    "outbox_max_attempts": 8,
    "outbox_backoff_seconds": 5,
    "db_pool_size": 10,
    "db_max_overflow": 20,
    "db_pool_timeout": 15,
    "db_pool_recycle": 1800,
    "db_pool_use_lifo": True,
    "health_check_seconds": 10,
    "circuit_failure_threshold": 3,
    "circuit_recovery_seconds": 20,
    "queue_warning_threshold": 5,
    "ha_worker_enabled": False,
    "outbox_poll_seconds": 3,
    "db_retry_max_attempts": 12,
    "db_retry_backoff_seconds": 2,
    "discovery_port": 8788,
    "server_port": 8787,
    "offline_after_seconds": 15,
    "heartbeat_seconds": 5,
}


def _load_json(path: Path):
    if not path.exists(): return {}
    try: return json.loads(path.read_text(encoding="utf-8"))
    except Exception: return {}


def load_config():
    data = dict(DEFAULT_CONFIG)
    if os.getenv("POS_SERVER_MODE") == "1":
        # Server process gets its own central DB/network settings.
        data.update(_load_json(SERVER_CONFIG_FILE))
    else:
        data.update(_load_json(CONFIG_FILE))
    return data


def load_server_config():
    data = {
        "server_host": "0.0.0.0",
        "server_port": 8787,
        "discovery_port": 8788,
        "heartbeat_seconds": 5,
        "offline_after_seconds": 15,
        "database_url": "sqlite:///pos_v12_server.db",
        "store_name": "متجري",
    }
    data.update(_load_json(SERVER_CONFIG_FILE))
    return data


def save_config(data):
    CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


CONFIG = load_config()
