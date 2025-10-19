from typing import AsyncGenerator

from app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

# Create the async database engine
async_engine = create_async_engine(settings.DATABASE_URL, echo=settings.DB_ECHO_LOG)

# Create a sessionmaker to generate new AsyncSession objects
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
