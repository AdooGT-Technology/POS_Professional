import os
os.environ["POS_SERVER_MODE"] = "1"
from discovery_server import run
if __name__ == "__main__":
    run()
