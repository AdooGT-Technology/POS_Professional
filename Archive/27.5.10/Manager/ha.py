from __future__ import annotations

import threading
import time
from datetime import datetime

from sqlalchemy import select, text

from config import CONFIG
import db as dbmod
from models import HealthCheckLog


class CircuitBreaker:
    """Small process-local circuit breaker protecting the central database."""

    def __init__(self, threshold=3, recovery=20):
        self.threshold = max(1, int(threshold))
        self.recovery = max(1, int(recovery))
        self.failures = 0
        self.state = "CLOSED"
        self.opened_at = 0.0
        self.lock = threading.Lock()

    def allow(self):
        with self.lock:
            if self.state != "OPEN":
                return True
            if time.time() - self.opened_at >= self.recovery:
                self.state = "HALF_OPEN"
                return True
            return False

    def success(self):
        with self.lock:
            self.failures = 0
            self.state = "CLOSED"
            self.opened_at = 0.0

    def failure(self):
        with self.lock:
            self.failures += 1
            if self.failures >= self.threshold:
                self.state = "OPEN"
                self.opened_at = time.time()

    def snapshot(self):
        with self.lock:
            return {
                "state": self.state,
                "failures": self.failures,
                "threshold": self.threshold,
                "recovery_seconds": self.recovery,
            }


breaker = CircuitBreaker(
    CONFIG.get("circuit_failure_threshold", 3),
    CONFIG.get("circuit_recovery_seconds", 20),
)


def _log(component, status, latency_ms=None, details=""):
    try:
        with dbmod.SessionLocal.begin() as s:
            s.add(HealthCheckLog(component=component, status=status, latency_ms=latency_ms, details=str(details)[:4000]))
    except Exception:
        # Health monitoring must never hide an application failure.
        pass


def db_health() -> dict:
    if dbmod.engine is None or dbmod.SessionLocal is None:
        return {"ok": False, "status": "NOT_INITIALIZED", "latency_ms": None}
    if not breaker.allow():
        return {"ok": False, "status": "CIRCUIT_OPEN", "latency_ms": None}
    started = time.perf_counter()
    try:
        with dbmod.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        latency = round((time.perf_counter() - started) * 1000, 2)
        breaker.success()
        _log("database", "UP", latency, "SELECT 1")
        return {"ok": True, "status": "UP", "latency_ms": latency}
    except Exception as exc:
        breaker.failure()
        _log("database", "DOWN", None, str(exc))
        return {"ok": False, "status": "DOWN", "latency_ms": None, "error": str(exc)}


def circuit_snapshot():
    return breaker.snapshot()


def system_snapshot() -> dict:
    health = db_health()
    return {
        "database": health,
        "circuit": circuit_snapshot(),
        "pool": dbmod.pool_snapshot(),
        "dialect": dbmod.engine.dialect.name if dbmod.engine is not None else "unknown",
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }
