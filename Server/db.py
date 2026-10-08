from sqlalchemy import create_engine, select, inspect, text, Index
from sqlalchemy.orm import sessionmaker, selectinload
from models import Base, Role, Permission, User, Branch, Warehouse, OutboxEvent, MigrationRun
from security import hash_password
from config import CONFIG

engine = None
SessionLocal = None

PERMISSIONS = [
    ("pos.sell","إنشاء مبيعات"),("pos.return","إنشاء مرتجعات"),
    ("invoice.view","عرض الفواتير"),("invoice.reprint","إعادة طباعة الفواتير"),
    ("invoice.void.request","طلب إلغاء فاتورة"),("invoice.void.approve","اعتماد إلغاء فاتورة"),
    ("cash.open","فتح الوردية"),("cash.close","إقفال الوردية"),("cash.drawer","فتح درج النقود"),("cash.adjust","حركات الخزينة"),
    ("backup.run","تشغيل النسخ الاحتياطي"),("backup.restore","استعادة النسخ الاحتياطي"),
    ("settings.database","إدارة اتصال قاعدة البيانات"),("settings.printer","إدارة إعدادات الطابعة"),
    ("products.manage","إدارة المنتجات"),("customers.manage","إدارة العملاء"),
    ("suppliers.manage","إدارة الموردين"),("purchases.manage","إدارة المشتريات"),
    ("reports.view","مشاهدة التقارير"),("users.manage","إدارة المستخدمين"),
    ("settings.manage","إدارة الإعدادات"),("branches.manage","إدارة الفروع والمخازن"),
    ("cash.manage","إدارة الخزينة والورديات"),("database.migrate","ترحيل واستعادة قاعدة البيانات"),
    ("outbox.manage","إدارة طابور الإعادة"),("inventory.transfer","تحويلات المخزون"),("inventory.count","الجرد وتسوية المخزون"),
    ("ha.view","عرض حالة النظام والتزامن"),
]


def _engine_kwargs(target: str) -> dict:
    kwargs = {
        "future": True,
        "pool_pre_ping": True,
        "pool_recycle": int(CONFIG.get("db_pool_recycle", 1800)),
        "pool_timeout": int(CONFIG.get("db_pool_timeout", 15)),
    }
    if target.startswith("sqlite"):
        # Tkinter callbacks and optional workers may use separate threads.
        kwargs["connect_args"] = {"check_same_thread": False}
    else:
        kwargs.update({
            "pool_size": int(CONFIG.get("db_pool_size", 10)),
            "max_overflow": int(CONFIG.get("db_max_overflow", 20)),
            "pool_use_lifo": bool(CONFIG.get("db_pool_use_lifo", True)),
        })
    return kwargs


def configure_engine(url=None, initialize=True):
    global engine, SessionLocal
    target = url or CONFIG["database_url"]
    engine = create_engine(target, **_engine_kwargs(target))
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    if initialize:
        init_db()
    return engine


def test_connection(url):
    test_engine = create_engine(url, future=True, pool_pre_ping=True)
    try:
        with test_engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        return True, "الاتصال ناجح."
    except Exception as exc:
        return False, str(exc)
    finally:
        test_engine.dispose()


def pool_snapshot() -> dict:
    """Return safe pool counters for the HA status screen."""
    if engine is None:
        return {"pool": "NOT_INITIALIZED"}
    pool = engine.pool
    result = {
        "class": pool.__class__.__name__,
        "size": None,
        "checked_in": None,
        "checked_out": None,
        "overflow": None,
    }
    for key, getter in (
        ("size", getattr(pool, "size", None)),
        ("checked_in", getattr(pool, "checkedin", None)),
        ("checked_out", getattr(pool, "checkedout", None)),
        ("overflow", getattr(pool, "overflow", None)),
    ):
        if callable(getter):
            try:
                result[key] = int(getter())
            except Exception:
                pass
    return result


def _add_missing_columns():
    inspector = inspect(engine)
    specs = {
        "sales": [("document_status", "VARCHAR(20) DEFAULT 'POSTED'")],
        "purchases": [("document_status", "VARCHAR(20) DEFAULT 'POSTED'")],
        "returns": [("document_status", "VARCHAR(20) DEFAULT 'POSTED'"), ("refund_method", "VARCHAR(20) DEFAULT 'نقدي'")],
        "client_control_telemetry": [
            ("cpu_temperature", "NUMERIC(8,2)"), ("ram_used_gb", "NUMERIC(12,2)"), ("ram_total_gb", "NUMERIC(12,2)"),
            ("gpu_name", "VARCHAR(180) DEFAULT ''"), ("gpu_percent", "NUMERIC(8,2)"), ("gpu_temperature", "NUMERIC(8,2)"),
            ("gpu_memory_percent", "NUMERIC(8,2)"), ("disk_health_percent", "NUMERIC(8,2)"),
            ("disk_temperature", "NUMERIC(8,2)"), ("disk_usage_percent", "NUMERIC(8,2)"), ("disks_json", "TEXT DEFAULT '[]'"),
        ],
    }
    with engine.begin() as conn:
        for table, fields in specs.items():
            if not inspect(conn).has_table(table):
                continue
            cols = {c["name"] for c in inspect(conn).get_columns(table)}
            for column, ddl in fields:
                if column not in cols:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {ddl}'))
                    if column == 'document_status': conn.execute(text(f"UPDATE {table} SET {column}='POSTED' WHERE {column} IS NULL"))
                    if column == 'refund_method': conn.execute(text(f"UPDATE {table} SET {column}='نقدي' WHERE {column} IS NULL"))

def _add_client_ui_columns():
    with engine.begin() as conn:
        if inspect(conn).has_table("client_ui_profiles"):
            cols={c["name"] for c in inspect(conn).get_columns("client_ui_profiles")}
            for col in ("video_asset","main_image_asset","icon_games","icon_apps","icon_shop","icon_events","icon_ads","icon_my_files","icon_profile"):
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE client_ui_profiles ADD COLUMN {col} VARCHAR(500) DEFAULT ''"))

def ensure_v8_schema():
    legacy_tables = [
        table for name, table in Base.metadata.tables.items()
        if name not in {"outbox_events", "migration_runs", "health_check_logs", "sync_events"}
    ]
    Base.metadata.create_all(engine, tables=legacy_tables)
    _add_missing_columns()
    _add_client_ui_columns()


def _ensure_v9_schema():
    insp = inspect(engine)
    specs = {
        "sales": [("client_request_id", "VARCHAR(80)")],
        "audit_logs": [("previous_hash", "VARCHAR(64)"), ("hash_value", "VARCHAR(64)")],
    }
    with engine.begin() as conn:
        for table, fields in specs.items():
            if not insp.has_table(table):
                continue
            cols = {c["name"] for c in inspect(conn).get_columns(table)}
            for col, ddl in fields:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        if not insp.has_table("backup_runs"):
            Base.metadata.tables["backup_runs"].create(bind=conn, checkfirst=True)
    if insp.has_table("sales"):
        try:
            existing_indexes = {idx.get("name") for idx in inspect(engine).get_indexes("sales")}
            if "uq_sales_client_request_id" not in existing_indexes:
                Index("uq_sales_client_request_id", Base.metadata.tables["sales"].c.client_request_id, unique=True).create(bind=engine)
        except Exception:
            pass


def _ensure_v27_3_3_schema():
    with engine.begin() as conn:
        if inspect(conn).has_table("client_control_telemetry"):
            cols={c["name"] for c in inspect(conn).get_columns("client_control_telemetry")}
            if "lan_speed_mbps" not in cols:
                conn.execute(text("ALTER TABLE client_control_telemetry ADD COLUMN lan_speed_mbps NUMERIC(10,2)"))
            if "lan_adapter" not in cols:
                conn.execute(text("ALTER TABLE client_control_telemetry ADD COLUMN lan_adapter VARCHAR(180) DEFAULT ''"))

def ensure_v9_schema():
    ensure_v8_schema()
    _ensure_v9_schema()


def ensure_v11_base_schema():
    """Ensure HA tables exist after V10 has completed its tracked migration."""
    from models import HealthCheckLog, SyncEvent
    Base.metadata.tables[HealthCheckLog.__tablename__].create(bind=engine, checkfirst=True)
    Base.metadata.tables[SyncEvent.__tablename__].create(bind=engine, checkfirst=True)


def init_db():
    from esports_service import _ensure_seed
    ensure_v9_schema()
    _ensure_v27_3_3_schema()
    with SessionLocal() as s:
        permissions = {}
        for code,name in PERMISSIONS:
            p = s.scalar(select(Permission).where(Permission.code==code))
            if not p:
                p = Permission(code=code,name=name); s.add(p)
            permissions[code]=p
        admin = s.scalar(select(Role).where(Role.name=="مدير"))
        if not admin:
            admin=Role(name="مدير",description="صلاحيات كاملة"); s.add(admin); s.flush()
        admin.permissions=list(permissions.values())
        cashier = s.scalar(select(Role).where(Role.name=="كاشير"))
        if not cashier:
            cashier=Role(name="كاشير",description="المبيعات والخزينة والمرتجعات"); s.add(cashier); s.flush()
        cashier.permissions=[permissions[c] for c in ("pos.sell","pos.return","invoice.view","invoice.reprint","invoice.void.request","cash.manage","cash.drawer") if c in permissions]
        if not s.scalar(select(User).where(User.username=="admin")):
            s.add(User(username="admin",full_name="مدير النظام",password_hash=hash_password("admin123"),active=True,role_id=admin.id))
        if not s.scalar(select(User).where(User.username=="cashier")):
            s.add(User(username="cashier",full_name="الكاشير",password_hash=hash_password("cashier123"),active=True,role_id=cashier.id))
        if not s.scalar(select(Branch)):
            b=Branch(code="MAIN",name="الفرع الرئيسي",address="",phone="",active=True); s.add(b); s.flush()
            s.add(Warehouse(branch_id=b.id,code="MAIN-WH",name="المخزن الرئيسي",active=True))
        s.commit()
    _ensure_seed()

configure_engine()
