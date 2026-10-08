
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
from config import CONFIG
from models import Base
config=context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata=Base.metadata

def run_migrations_offline():
    context.configure(url=CONFIG["database_url"],target_metadata=target_metadata,literal_binds=True,compare_type=True)
    with context.begin_transaction(): context.run_migrations()

def run_migrations_online():
    connectable=engine_from_config({"sqlalchemy.url":CONFIG["database_url"]},prefix="",poolclass=pool.NullPool,future=True)
    with connectable.connect() as connection:
        context.configure(connection=connection,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction(): context.run_migrations()

if context.is_offline_mode(): run_migrations_offline()
else: run_migrations_online()
