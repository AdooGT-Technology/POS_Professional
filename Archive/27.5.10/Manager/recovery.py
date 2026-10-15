from services import BackupService
from v10_migration import RecoveryService

if __name__ == "__main__":
    backup = BackupService.backup()
    print("BACKUP:", backup)
    if str(backup).endswith(".db"):
        print("RESTORE TEST:", RecoveryService.test_restore_separate_copy(backup))
