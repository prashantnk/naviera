import asyncio
import sys
from pathlib import Path
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Add the project's root directory to the Python path.
sys.path.append(str(Path(__file__).resolve().parents[1]))

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# --- CUSTOM SETUP FOR OUR PROJECT ---
from sqlmodel import SQLModel
# Explicitly import the modules containing your models. This is the most robust way.
from app.models import tenant_models
# We will add future model files here, e.g., from app.models import pickup_models
from app.core.config import settings

target_metadata = SQLModel.metadata

# --- FINAL DEBUGGING STEP: Inspect the metadata object directly ---
print("--- DEBUGGING METADATA ---")
print(f"Tables found in SQLModel.metadata: {SQLModel.metadata.tables.keys()}")
print("--------------------------")

if settings.DATABASE_URL:
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
# --- END CUSTOM SETUP ---


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    ini_section = config.get_section(config.config_ini_section)
    if ini_section is None:
        raise ValueError("Alembic config section not found")
    connectable = async_engine_from_config(
        ini_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()