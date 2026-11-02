"""
Conftest for the Golden Journeys (`J01-J63`), ship-readiness plan item A3.

1. Shadows the parent `conftest.py` fixtures (`init_db_cache`, `db_session`,
   `clean_db`) with no-ops, so golden tests use real JWTs and real committed
   PostgreSQL state instead of mocked users.
2. Adds the session-scoped `golden_tenant_ready` guard. Before the first test
   it (a) refuses any slug outside the shared allow-list (also enforced at
   import time by `golden_env`), (b) refuses a tenant whose
   `settings.environment` is not "test", (c) takes an exclusive file lock so
   only one golden run touches the tenant at a time, (d) resets the test tenant
   once through `scripts.tenant_data_core.reset_test_tenant`, and (e) deletes
   the slug's `/tmp` state files.
3. Points the in-process app's `get_session` (and idempotency's session factory) at the
   harness's test-only engine
   (`golden_env.test_engine`); production `app/core/db.py` stays untouched.

Spring analogy: a JUnit 5 `BeforeAllCallback` extension combined with an
`@ActiveProfiles("test")` check, an `@Sql(BEFORE_TEST_CLASS)` reset script and a
`@TestConfiguration` that swaps the DataSource bean.
"""

from typing import AsyncIterator, Dict, Iterator

from app.core import db as app_db_module
from app.core.db import get_session
from app.main import app
from app.models.pricing import DelhiveryPriceCache
from app.models.prime import PrimeLane
from app.repositories.prime_rates import PrimeRatesRepository
import pytest
from scripts.seed_prime_zones import apply_test_fixture
from scripts.tenant_data_core import assert_test_tenant_slug, require_tenant, reset_test_tenant
from sqlalchemy import delete
from sqlmodel.ext.asyncio.session import AsyncSession

from .golden_env import (
    GOLDEN_TENANT_SLUG,
    GoldenSessionLocal,
    TestAppSessionLocal,
    acquire_run_lock,
    assert_slug_allowed,
    clear_state_files,
    load_test_tenant,
    release_run_lock,
    test_engine,
)


async def _reset_golden_tenant() -> Dict[str, int]:
    """Runs the shared FK-ordered reset + Prime/price-cache reset for the guarded test tenant."""
    async with GoldenSessionLocal() as session:
        counts = await reset_test_tenant(session, GOLDEN_TENANT_SLUG, commit=False)
        tenant = await require_tenant(session, GOLDEN_TENANT_SLUG)
        await session.exec(
            delete(DelhiveryPriceCache).where(DelhiveryPriceCache.tenant_id == tenant.id)
        )
        await session.exec(delete(PrimeLane).where(PrimeLane.tenant_id == tenant.id))
        await apply_test_fixture(PrimeRatesRepository(session), tenant.id)
        await session.commit()
        return counts


async def _test_get_session() -> AsyncIterator[AsyncSession]:
    """`get_session` replacement: one session of the test-only engine per request."""
    async with TestAppSessionLocal() as session:
        yield session


@pytest.fixture(autouse=True, scope="session")
async def golden_tenant_ready() -> AsyncIterator[None]:
    """Session guard + one reset of the test tenant before the first golden test."""
    assert_slug_allowed(GOLDEN_TENANT_SLUG)
    assert_test_tenant_slug(GOLDEN_TENANT_SLUG)
    await load_test_tenant(GOLDEN_TENANT_SLUG)
    lock_handle = acquire_run_lock()
    # `app.core.idempotency` opens its own sessions through the `app.core.db` module attribute
    # (looked up at call time). Point it at the pooled test engine for this test process only;
    # the file `app/core/db.py` is untouched and uvicorn keeps the production engine.
    session_factory_patch = pytest.MonkeyPatch()
    session_factory_patch.setattr(app_db_module, "AsyncSessionLocal", TestAppSessionLocal)
    try:
        counts = await _reset_golden_tenant()
        removed = clear_state_files()
        print(
            f"[golden] reset tenant {GOLDEN_TENANT_SLUG!r}: {counts}; "
            f"removed {removed} state file(s)"
        )
        yield
    finally:
        session_factory_patch.undo()
        release_run_lock(lock_handle)
        await test_engine.dispose()


@pytest.fixture(autouse=True, scope="session")
async def init_db_cache() -> AsyncIterator[None]:
    """No-op shadow of the parent session cache fixture."""
    yield


@pytest.fixture
async def db_session() -> AsyncIterator[None]:
    """No-op shadow of the parent rollback session fixture."""
    yield None


@pytest.fixture(autouse=True)
async def global_dependency_overrides() -> AsyncIterator[None]:
    """Routes the in-process app's DB sessions to the test-only engine (no mocked users)."""
    app.dependency_overrides[get_session] = _test_get_session
    yield
    app.dependency_overrides.pop(get_session, None)


@pytest.fixture(autouse=True)
def clean_db() -> Iterator[None]:
    """No-op shadow: wallet balances are only reset by `golden_tenant_ready`."""
    yield
