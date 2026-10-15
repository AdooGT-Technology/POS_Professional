import time
from services import BackupScheduler

if __name__=="__main__":
    scheduler=BackupScheduler.start()
    print("POS V10 backup scheduler started. Press Ctrl+C to stop.",flush=True)
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt:
        scheduler.shutdown()
