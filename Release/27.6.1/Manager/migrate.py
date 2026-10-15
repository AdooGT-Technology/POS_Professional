import argparse
from db import configure_engine, SessionLocal
from v10_migration import RecoveryService
from ha_migration import HAMigrationService
from models import MigrationRun
from sqlalchemy import select


def main():
    ap = argparse.ArgumentParser(description="POS Professional V11 HA Database Migration")
    ap.add_argument("action", choices=["upgrade", "upgrade-v10", "upgrade-v11", "preflight", "preflight-v11", "current", "history", "restore-test"])
    ap.add_argument("--backup", default="")
    args = ap.parse_args()
    configure_engine(initialize=False)

    if args.action in ("upgrade", "upgrade-v10"):
        report = RecoveryService.upgrade_to_v10()
        print(f"V10: {report.status} | backup={report.backup_path or '-'} | restore_test={report.restore_test} | {report.details}")
        if args.action == "upgrade":
            result = HAMigrationService.upgrade_to_v11()
            print(f"V11: {result['status']} | revision={result['revision']}")
    elif args.action == "upgrade-v11":
        RecoveryService.upgrade_to_v10()
        result = HAMigrationService.upgrade_to_v11()
        print(f"V11: {result['status']} | revision={result['revision']}")
    elif args.action in ("preflight", "current"):
        print("V10:", RecoveryService.preflight())
        print("V11:", HAMigrationService.preflight())
    elif args.action == "preflight-v11":
        print(HAMigrationService.preflight())
    elif args.action == "restore-test":
        print(RecoveryService.test_restore_separate_copy(args.backup or None))
    else:
        with SessionLocal() as s:
            rows = s.scalars(select(MigrationRun).order_by(MigrationRun.id)).all()
            for r in rows:
                print(r.id, r.revision, r.status, r.restore_test_status, r.backup_path)

if __name__ == "__main__":
    main()
