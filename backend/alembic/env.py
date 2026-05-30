import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

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

# We will add future model files here, e.g., from app.models import pickup_models
from app.core.config import settings

# Explicitly import the modules containing your models. This is the most robust way.
from app.models import pickups, tenants  # noqa: F401

target_metadata = SQLModel.metadata

# --- FINAL DEBUGGING STEP: Inspect the metadata object directly ---
print("--- DEBUGGING METADATA ---")
print(f"Tables found in SQLModel.metadata: {SQLModel.metadata.tables.keys()}")
print("--------------------------")

if settings.ALEMBIC_DATABASE_URL:
    config.set_main_option("sqlalchemy.url", settings.ALEMBIC_DATABASE_URL)
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
    import uuid
    from sqlalchemy.ext.asyncio import create_async_engine
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        raise ValueError("Alembic database URL not set")
    connectable = create_async_engine(
        url,
        poolclass=pool.NullPool,
        connect_args={
            "statement_cache_size": 0,
            "prepared_statement_name_func": lambda: f"__asyncpg_{uuid.uuid4().hex}__",
        },
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
