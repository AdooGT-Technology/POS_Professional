from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path

DB = Path(__file__).resolve().parent / "client_retry_queue.db"


def _con():
    c = sqlite3.connect(DB, timeout=15)
    c.execute("""CREATE TABLE IF NOT EXISTS pending_sales(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_request_id TEXT UNIQUE NOT NULL,
        payload_json TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        processed_at TEXT
    )""")
    c.commit()
    return c


def enqueue(payload, client_request_id=None, error=""):
    rid = client_request_id or str(uuid.uuid4())
    now = datetime.now()
    with _con() as c:
        c.execute("""INSERT OR IGNORE INTO pending_sales
            (client_request_id,payload_json,attempts,next_attempt_at,status,last_error)
            VALUES(?,?,?,?,?,?)""", (rid, json.dumps(payload, ensure_ascii=False), 0, now.isoformat(), "PENDING", str(error)))
    return rid


def pending(limit=20):
    with _con() as c:
        return c.execute("""SELECT id,client_request_id,payload_json,attempts FROM pending_sales
            WHERE status IN ('PENDING','RETRY') AND next_attempt_at<=?
            ORDER BY id LIMIT ?""", (datetime.now().isoformat(), int(limit))).fetchall()


def success(row_id):
    with _con() as c:
        c.execute("UPDATE pending_sales SET status='DONE',processed_at=? WHERE id=?", (datetime.now().isoformat(), row_id))


def retry(row_id, attempts, error, max_attempts=12):
    attempts = int(attempts or 0)
    status = "FAILED" if attempts + 1 >= int(max_attempts) else "RETRY"
    delay = min(300, 2 ** min(attempts, 7))
    when = (datetime.now() + timedelta(seconds=delay)).isoformat()
    with _con() as c:
        c.execute("""UPDATE pending_sales SET attempts=?,status=?,next_attempt_at=?,last_error=? WHERE id=?""",
                  (attempts + 1, status, when, str(error)[:4000], row_id))


def counts():
    with _con() as c:
        rows = c.execute("SELECT status, count(*) FROM pending_sales GROUP BY status").fetchall()
    return {status: int(count) for status, count in rows}
