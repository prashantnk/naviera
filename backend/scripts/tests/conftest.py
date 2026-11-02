import inspect
import os
import sys

# Both side effects must run before `app` is imported: no .pyc files next to the test
# sources, and Logfire stays silent in tests. Hence the E402 waivers below.
sys.dont_write_bytecode = True
os.environ["LOGFIRE_TOKEN"] = ""

import pytest  # noqa: E402
from sqlmodel import select, text  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402
from app.main import app  # noqa: E402
from app.core import db as app_db_module  # noqa: E402
from app.core.db import AsyncSessionLocal, async_engine, get_session  # noqa: E402
from app.core.dependencies import get_current_active_user, get_tenant_from_header  # noqa: E402
from app.models.prime import PrimeLane  # noqa: E402
from app.models.tenants import Tenant, User, UserRole  # noqa: E402
from app.repositories.prime_rates import PrimeRatesRepository  # noqa: E402
from app.repositories.wallet import WalletRepository  # noqa: E402
from golden_journeys.golden_env import test_engine  # noqa: E402
from idempotency_default import IdempotencyKeyDefaultMiddleware  # noqa: E402
from response_audit import ResponseAuditMiddleware  # noqa: E402
from scripts.seed_prime_zones import apply_test_fixture  # noqa: E402
from scripts.tenant_data_core import ALLOWED_TEST_SLUGS  # noqa: E402

# Every in-process API call made by any suite fails if it leaks a server-only pricing field,
# and keyless `POST /api/v1/shipments` calls get a fresh UUID Idempotency-Key by default.
app.add_middleware(ResponseAuditMiddleware)
app.add_middleware(IdempotencyKeyDefaultMiddleware)

_PYTEST_CONFIG: dict = {}
"""Holds the pytest config (set in `pytest_configure`) to find the terminal reporter later."""
FAILURE_TAIL_CHARS = 4000
"""How much of a failure's traceback to echo immediately (the full one is in the final summary)."""


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    """
    Echoes a failing journey's traceback as soon as it fails. A full golden run takes about
    an hour against the remote database, so waiting for the end-of-run summary wastes it.
    Applies to every suite under `scripts/tests` (golden journeys, UI and unit suites).
    """
    if not report.failed or report.when not in ("setup", "call"):
        return
    config = _PYTEST_CONFIG.get("config")
    reporter = config.pluginmanager.get_plugin("terminalreporter") if config else None
    if reporter is not None:
        reporter.write_line(f"\n[golden] FAILED {report.nodeid} ({report.when}):")
        reporter.write_line(report.longreprtext[-FAILURE_TAIL_CHARS:])


def pytest_configure(config: pytest.Config) -> None:
    """Keeps a handle on the config: the terminal reporter may register after this hook."""
    _PYTEST_CONFIG["config"] = config


_cached_user = None
_cached_tenant = None
_cache_unavailable_reason = None

# Unit tests run with mocked auth inside a rolled-back transaction. They are
# pinned to the dedicated test tenant (ship-readiness plan A3): the slug must be
# allow-listed and the tenant must carry settings.environment == "test". There
# is NO fallback to any other tenant: DB-backed tests are skipped instead.
PINNED_TEST_TENANT_SLUG = os.getenv("GOLDEN_TENANT_SLUG", "logismart-test")
TEST_ENVIRONMENT_VALUE = "test"
E2E_MODULE_MARKER = "test_exhaustive_api_and_forms_e2e"


async def _resolve_cache_identity(session):
    """
    Returns `(user, tenant, reason)` for the mocked unit-test identity.

    `user`/`tenant` are the earliest admin (then any user, deterministic ORDER BY)
    of the pinned TEST tenant. When the slug is not allow-listed, the tenant is
    missing, it is not flagged `environment == "test"`, or it has no users, both
    are None and `reason` explains why (the DB-backed tests are then skipped).
    """
    if PINNED_TEST_TENANT_SLUG not in ALLOWED_TEST_SLUGS:
        return None, None, (
            f"GOLDEN_TENANT_SLUG={PINNED_TEST_TENANT_SLUG!r} is not an allowed test slug "
            f"{sorted(ALLOWED_TEST_SLUGS)}; DB-backed unit tests refuse to run."
        )
    pinned_tenant = (
        await session.exec(select(Tenant).where(Tenant.slug == PINNED_TEST_TENANT_SLUG))
    ).first()
    if pinned_tenant is None:
        return None, None, (
            f"Test tenant {PINNED_TEST_TENANT_SLUG!r} is not seeded yet "
            "(backend/scripts/seed_logismart_test.py); DB-backed unit tests skipped."
        )
    if (pinned_tenant.settings or {}).get("environment") != TEST_ENVIRONMENT_VALUE:
        return None, None, (
            f"Tenant {PINNED_TEST_TENANT_SLUG!r} is not flagged environment='test'; "
            "DB-backed unit tests refuse to run."
        )
    user = (
        await session.exec(
            select(User)
            .where(User.tenant_id == pinned_tenant.id)
            .order_by(User.role != UserRole.admin, User.created_at, User.id)
            .limit(1)
        )
    ).first()
    if user is None:
        return None, None, f"Test tenant {PINNED_TEST_TENANT_SLUG!r} has no users; re-run the seed."
    return user, pinned_tenant, None


def _item_needs_test_tenant(item) -> bool:
    """True when a collected pytest item needs the DB or FastAPI app."""
    if "db_session" in getattr(item, "fixturenames", ()):
        return True
    module = getattr(item, "module", None)
    if module is None:
        return True
    db_objects = (app, AsyncSessionLocal, async_engine)
    return any(
        any(value is obj for obj in db_objects) for value in vars(module).values()
    )


@pytest.fixture(autouse=True, scope="session")
async def init_db_cache(request):
    global _cached_user, _cached_tenant, _cache_unavailable_reason
    if all(
        E2E_MODULE_MARKER in item.nodeid or not _item_needs_test_tenant(item)
        for item in request.session.items
    ):
        yield
        return
    print("INIT DB CACHE STARTED")
    async with AsyncSessionLocal() as session:
        print("EXECUTING SELECT 1")
        await session.exec(text("SELECT 1"))
        print("SELECT 1 DONE")
        user, tenant, _cache_unavailable_reason = await _resolve_cache_identity(session)
        if _cache_unavailable_reason:
            print(f"WARNING: {_cache_unavailable_reason}")
        if user:
            u_dump = user.model_dump()
            u_dump["role"] = UserRole.admin
            _cached_user = User(**u_dump)
        if tenant:
            t_dump = tenant.model_dump()
            t_settings = dict(t_dump.get("settings") or {})
            w_cfg = dict(t_settings.get("wallet_config") or {})
            w_cfg["strict_finlock"] = False
            t_settings["wallet_config"] = w_cfg
            t_settings.setdefault(
                "pricing_policy",
                {
                    "delhivery_markup_percent": 0.0,
                    "prime_default_markup_percent": 20.0,
                    "cod_fee_percent": 2.0,
                    "cod_fee_min": 1.0,
                    "enabled_options": [
                        "DELHIVERY_SURFACE",
                        "DELHIVERY_EXPRESS",
                        "PRIME_SURFACE",
                    ],
                },
            )
            t_dump["settings"] = t_settings
            _cached_tenant = Tenant(**t_dump)
            lane_exists = (
                await session.exec(
                    select(PrimeLane.id).where(PrimeLane.tenant_id == tenant.id).limit(1)
                )
            ).first()
            if lane_exists is None:
                await apply_test_fixture(PrimeRatesRepository(session), tenant.id)
                await session.commit()
            else:
                await session.rollback()
        else:
            await session.rollback()
    try:
        yield
    finally:
        await test_engine.dispose()


def _test_requests_fixture(request, name: str) -> bool:
    """True when the test function itself declares `name` as a parameter."""
    func = getattr(request.node, "function", None)
    return func is not None and name in inspect.signature(func).parameters


def _module_uses_app_or_db(request) -> bool:
    """
    True when the test module holds the FastAPI app or a DB session factory/engine
    (any alias), i.e. it needs the pinned test tenant. Pure modules return False.
    """
    db_objects = (app, AsyncSessionLocal, async_engine)
    return any(
        any(value is obj for obj in db_objects) for value in vars(request.module).values()
    )


def _needs_test_tenant(request) -> bool:
    """True for tests that need the mocked app or the database."""
    return _test_requests_fixture(request, "db_session") or _module_uses_app_or_db(request)


@pytest.fixture
async def db_session(request):
    if E2E_MODULE_MARKER in request.node.nodeid:
        yield None
        return
    if not _needs_test_tenant(request):
        # Pure tests (no app, no DB objects, no `db_session` parameter) never open a
        # connection: each one costs seconds against the remote pooler.
        yield None
        return
    if _cache_unavailable_reason:
        pytest.skip(_cache_unavailable_reason)
    async with test_engine.connect() as conn:
        transaction = await conn.begin()
        # Bind the session to the connection with savepoints so endpoint commits
        # stay inside the outer transaction and roll back cleanly after the test.
        async with AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        ) as session:
            if (
                "test_wallet_and_otp_e2e" not in request.node.nodeid
                and _cached_user is not None
                and _cached_tenant is not None
            ):
                w_repo = WalletRepository(session)
                wallet = await w_repo.get_or_create_wallet(
                    user_id=_cached_user.id,
                    tenant_id=_cached_tenant.id,
                    for_update=False,
                )
                if float(wallet.balance) < 10000.0:
                    wallet.balance = 50000.0
                    session.add(wallet)
                    await session.flush()
                lane_exists = (
                    await session.exec(
                        select(PrimeLane.id)
                        .where(PrimeLane.tenant_id == _cached_tenant.id)
                        .limit(1)
                    )
                ).first()
                if lane_exists is None:
                    await apply_test_fixture(PrimeRatesRepository(session), _cached_tenant.id)
            yield session
        await transaction.rollback()


@pytest.fixture(autouse=True)
async def global_dependency_overrides(request, db_session):
    if E2E_MODULE_MARKER in request.node.nodeid:
        yield
        return
    if _cache_unavailable_reason or db_session is None:
        # db_session already skipped app/DB tests; pure tests run without overrides.
        yield
        return

    async def mock_get_current_active_user():
        return _cached_user

    async def mock_get_tenant_from_header():
        return _cached_tenant

    async def mock_get_session():
        yield db_session

    conn = db_session.bind

    def _savepoint_session():
        return AsyncSession(
            bind=conn,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )

    original_session_local = app_db_module.AsyncSessionLocal
    app_db_module.AsyncSessionLocal = _savepoint_session
    app.dependency_overrides[get_current_active_user] = mock_get_current_active_user
    app.dependency_overrides[get_tenant_from_header] = mock_get_tenant_from_header
    app.dependency_overrides[get_session] = mock_get_session
    try:
        yield
    finally:
        app_db_module.AsyncSessionLocal = original_session_local
        app.dependency_overrides.pop(get_current_active_user, None)
        app.dependency_overrides.pop(get_tenant_from_header, None)
        app.dependency_overrides.pop(get_session, None)
