from __future__ import annotations

import json
import socket

from server_config import SERVER_CONFIG


def _server_ip(addr):
    # Prefer the local IP used to reach the requesting LAN host.
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect((addr[0], 1))
        return probe.getsockname()[0]
    except Exception:
        return socket.gethostbyname(socket.gethostname())
    finally:
        probe.close()


def run():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind(("", int(SERVER_CONFIG.get("discovery_port", 8788))))
    print(f"POS Discovery Server listening on UDP {SERVER_CONFIG.get('discovery_port', 8788)}", flush=True)
    while True:
        data, addr = sock.recvfrom(4096)
        try:
            msg = json.loads(data.decode("utf-8"))
            if msg.get("type") != "POS_DISCOVER": continue
            answer = {"type": "POS_SERVER", "host": _server_ip(addr), "port": int(SERVER_CONFIG.get("server_port", 8787)), "version": "V21"}
            sock.sendto(json.dumps(answer, ensure_ascii=False).encode("utf-8"), addr)
        except Exception:
            continue


if __name__ == "__main__": run()
