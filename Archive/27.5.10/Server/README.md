# POS Professional V27.5.10 — Central Server
Central backend/API, database, LAN discovery, device heartbeat and authenticated Manager control gateway. Manager POS menus remain in the Manager application.

## Secure Manager control setup
On first start, the Server creates `Server/server_config.json` with a random `manager_control_token`. Keep this file private and copy the token into Manager → Server Connection → **رمز التحكم الآمن**; the Manager stores it in the ignored `Manager/manager_control_secret.txt`. Manager-only control routes reject requests without the matching token. For untrusted networks, select HTTPS in Manager and enable `control_require_https` behind a TLS-terminating proxy.
