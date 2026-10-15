from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import func, select

from config import CONFIG
from db import SessionLocal
from models import OutboxEvent, SyncEvent


class SyncMonitor:
    @staticmethod
    def _local_db():
        return Path(__file__).resolve().parent / "client_retry_queue.db"

    @classmethod
    def local_pending(cls):
        p = cls._local_db()
        if not p.exists(): return 0
        with sqlite3.connect(p, timeout=5) as c:
            return int(c.execute("SELECT count(*) FROM pending_sales WHERE status IN ('PENDING','RETRY')").fetchone()[0])

    @classmethod
    def local_failed(cls):
        p = cls._local_db()
        if not p.exists(): return 0
        with sqlite3.connect(p, timeout=5) as c:
            return int(c.execute("SELECT count(*) FROM pending_sales WHERE status='FAILED'").fetchone()[0])

    @staticmethod
    def central_pending():
        try:
            with SessionLocal() as s:
                return int(s.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status.in_(("PENDING", "FAILED")),
                    (OutboxEvent.next_attempt_at.is_(None)) | (OutboxEvent.next_attempt_at <= __import__('datetime').datetime.now()))) or 0)
        except Exception:
            return -1

    @staticmethod
    def central_failed():
        try:
            with SessionLocal() as s:
                return int(s.scalar(select(func.count(OutboxEvent.id)).where(OutboxEvent.status == "FAILED")) or 0)
        except Exception:
            return -1

    @staticmethod
    def last_events(limit=25):
        try:
            with SessionLocal() as s:
                return s.scalars(select(SyncEvent).order_by(SyncEvent.id.desc()).limit(int(limit))).all()
        except Exception:
            return []

    @classmethod
    def snapshot(cls):
        return {
            "local_pending": cls.local_pending(),
            "local_failed": cls.local_failed(),
            "central_pending": cls.central_pending(),
            "central_failed": cls.central_failed(),
            "warning_threshold": int(CONFIG.get("queue_warning_threshold", 5)),
        }
