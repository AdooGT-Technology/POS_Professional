from config import CONFIG, load_server_config, save_server_config

SERVER_CONFIG = load_server_config()
# Ensure the Server database engine reads its own configured URL, not Manager defaults.
CONFIG.update(SERVER_CONFIG)
