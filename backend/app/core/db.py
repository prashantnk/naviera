# backend/app/core/db.py
from typing import AsyncGenerator
from uuid import uuid4  # 🟢 Added this import

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings

# 🟢 Create the engine with the PgBouncer UUID fix
async_engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DB_ECHO_LOG,
    poolclass=NullPool,
    connect_args={
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    },
)

AsyncSessionLocal = sessionmaker(
    bind=async_engine,  # type: ignore
    class_=AsyncSession,
    expire_on_commit=False,
)  # type: ignore


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function that provides a database session to API endpoints.
    """
    async with AsyncSessionLocal() as session:  # type: ignore
        yield session
