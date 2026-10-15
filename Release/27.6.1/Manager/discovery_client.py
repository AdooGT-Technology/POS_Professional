from __future__ import annotations
import json, socket

def discover(timeout=1.5, port=8788):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.settimeout(timeout)
    try:
        sock.sendto(json.dumps({"type":"POS_DISCOVER","version":"V16"}).encode("utf-8"), ("<broadcast>", int(port)))
        while True:
            data, _ = sock.recvfrom(4096)
            msg = json.loads(data.decode("utf-8"))
            if msg.get("type") != "POS_SERVER":
                continue
            host = str(msg.get("host") or "").strip()
            port_value = int(msg.get("port", 8787))
            if host:
                return f"http://{host}:{port_value}"
    except Exception:
        return None
    finally:
        sock.close()
    return None
