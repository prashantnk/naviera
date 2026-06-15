import sys
sys.dont_write_bytecode = True

import os

os.environ["LOGFIRE_TOKEN"] = ""

import pytest
import asyncio
from sqlmodel import select, text
from app.main import app
from app.core.db import AsyncSessionLocal, async_engine, get_session
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.tenants import User, Tenant

_cached_user = None
_cached_tenant = None


@pytest.fixture(autouse=True, scope="session")
async def init_db_cache():
    global _cached_user, _cached_tenant
    print("INIT DB CACHE STARTED")
    async with AsyncSessionLocal() as session:
        print("EXECUTING SELECT 1")
        await session.exec(text("SELECT 1"))
        print("SELECT 1 DONE")
        user = (await session.exec(select(User).limit(1))).first()
        tenant = (await session.exec(select(Tenant).limit(1))).first()
        if user:
            _cached_user = User(**user.model_dump())
        if tenant:
            _cached_tenant = Tenant(**tenant.model_dump())
        await session.rollback()
    yield




@pytest.fixture
async def db_session():
    async with async_engine.connect() as conn:
        transaction = await conn.begin()
        # Bind the session to the connection so it participates in the transaction
        async with AsyncSessionLocal(bind=conn) as session:
            yield session
        await transaction.rollback()

@pytest.fixture(autouse=True)
async def global_dependency_overrides(db_session):
    async def mock_get_current_active_user():
        return _cached_user

    async def mock_get_tenant_from_header():
        return _cached_tenant

    async def mock_get_session():
        yield db_session

    app.dependency_overrides[get_current_active_user] = mock_get_current_active_user
    app.dependency_overrides[get_tenant_from_header] = mock_get_tenant_from_header
    app.dependency_overrides[get_session] = mock_get_session
    yield
    app.dependency_overrides.pop(get_current_active_user, None)
    app.dependency_overrides.pop(get_tenant_from_header, None)
    app.dependency_overrides.pop(get_session, None)
