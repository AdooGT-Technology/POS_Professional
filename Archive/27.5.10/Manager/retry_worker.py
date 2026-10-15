from __future__ import annotations

import json
import time

from client_retry_queue import pending, success, retry
from config import CONFIG
from ha import db_health
from services import SalesService


def run_once(limit=20):
    health = db_health()
    if not health["ok"]:
        return {"status": "SKIPPED", "reason": health["status"], "processed": 0, "failed": 0}
    processed = failed = 0
    for row in pending(limit=limit):
        row_id, rid, payload_json, attempts = row
        try:
            payload = json.loads(payload_json)
            SalesService.create(
                payload["user_id"], payload["cart"], payload.get("discount", 0),
                payload.get("payment_method", "نقدي"), payload.get("paid", 0),
                payload.get("customer_id"), payload.get("tax_rate", 0),
                payload.get("branch_id"), payload.get("warehouse_id"),
                client_request_id=rid,
            )
            success(row_id); processed += 1
        except Exception as exc:
            retry(row_id, attempts, exc, int(CONFIG.get("db_retry_max_attempts", 12)))
            failed += 1
    return {"status": "OK", "processed": processed, "failed": failed}


def run_forever():
    print("POS V11 Client Retry Worker started.")
    while True:
        try: print(run_once(), flush=True)
        except Exception as exc: print("retry worker error:", exc, flush=True)
        time.sleep(float(CONFIG.get("outbox_poll_seconds", 3)))


if __name__ == "__main__":
    run_forever()
