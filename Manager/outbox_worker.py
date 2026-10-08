from __future__ import annotations

import json
import time
from datetime import datetime

from config import CONFIG
from db import SessionLocal
from ha import db_health
from models import SyncEvent
from services import OutboxService


def publish_event(event) -> bool:
    """Default central publisher.

    V11 keeps the integration boundary explicit: the local Outbox is durable and
    idempotent. Until a real external connector is configured, publishing is
    recorded as a successful synchronization event only; no fake remote write is
    claimed.
    """
    try:
        payload = json.loads(event.payload_json or "{}")
    except Exception:
        payload = {}
    with SessionLocal.begin() as s:
        s.add(SyncEvent(
            source="outbox",
            event_type=event.event_type,
            status="DISPATCHED",
            reference_id=event.event_id,
            details=json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str),
            created_at=datetime.now(),
        ))
    return True


def process_once(limit=25):
    health = db_health()
    if not health["ok"]:
        return {"status": "SKIPPED", "reason": health["status"], "processed": 0, "failed": 0}
    processed = failed = 0
    for event in OutboxService.due(limit=limit):
        try:
            ok = publish_event(event)
            if not ok:
                raise RuntimeError("Publisher returned false")
            OutboxService.mark_sent(event.event_id)
            processed += 1
        except Exception as exc:
            OutboxService.mark_retry(event.event_id, exc)
            failed += 1
    return {"status": "OK", "processed": processed, "failed": failed}


def run_forever():
    print("POS V11 Outbox Worker started.")
    while True:
        try:
            print(process_once(), flush=True)
        except Exception as exc:
            print("outbox worker error:", exc, flush=True)
        time.sleep(float(CONFIG.get("outbox_poll_seconds", 3)))


if __name__ == "__main__":
    run_forever()
