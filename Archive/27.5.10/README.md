# POS Professional V27.5.10

Architecture: Central Server / Manager / Customer Client.

This corrective maintenance pass restores Manager startup, wires Client control and telemetry into the launched runtime, repairs command acknowledgements and screenshot uploads, and makes the product, contact, branch, warehouse, and inventory views actionable. Manager control APIs now require a persistent shared secret rather than trusting a caller-supplied Manager ID.

For Manager control setup, start the Server once, copy `manager_control_token` from `Server/server_config.json`, and enter it in the Manager Server Connection panel. The Manager stores it in the ignored `Manager/manager_control_secret.txt`; keep both secret files private. Choose HTTPS when using a TLS-terminating proxy on an untrusted network.

The project continues to exclude diskless/iSCSI/PXE/PXI/WriteBack/Cache features.
