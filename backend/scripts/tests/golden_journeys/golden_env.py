"""
Shared harness for the Golden Journey suites (ship-readiness plan item A1).

Every golden suite imports its tenant slug, accounts, tokens, state files and
per-run identifiers from this one module, so no suite can drift back to the
live `logismart` tenant.

Spring analogy: this is the shared `@TestConfiguration` + test-profile
properties that every `@SpringBootTest` class pulls in, plus a small
`TestDataFactory` for random UTRs.

Safety rules enforced here (all raise `GoldenEnvError` before any HTTP call):
1. The slug comes from `GOLDEN_TENANT_SLUG` (default `logismart-test`) and must
   be in `scripts.tenant_data_core.ALLOWED_TEST_SLUGS`. This check runs at
   import time, so even `pytest --collect-only` refuses a live slug.
2. The tenant row must carry `settings["environment"] == "test"`.
3. Tokens are minted only for the canonical accounts fixture, only for the
   user row that belongs to the test tenant, never for an email in
   `PROTECTED_LIVE_EMAILS`, and never for a Supabase identity (`sub`) that
   also backs a protected live user row.
"""

import asyncio
from contextlib import contextmanager
import fcntl
import json
import os
from datetime import date
from pathlib import Path
import secrets
import socket
import time
from typing import IO, Any, Dict, FrozenSet, Iterator, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID

from app.core.config import settings
from app.models.pickups import PaymentDetails, PickupRequest
from app.models.tenants import Tenant, User
from app.models.wallet import UserWallet, WalletTransaction
from app.services import mvp_scope
from app.services.delhivery_modules import (
    document_number_prefix,
    format_document_number,
    indian_financial_year_label,
)
from jose import jwt
from scripts.tenant_data_core import ALLOWED_TEST_SLUGS, PROTECTED_LIVE_EMAILS
from sqlalchemy import event
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

# --- Constants -------------------------------------------------------------

GOLDEN_SLUG_ENV_VAR = "GOLDEN_TENANT_SLUG"
DEFAULT_GOLDEN_SLUG = "logismart-test"
TEST_ENVIRONMENT_VALUE = "test"
SETTINGS_ENVIRONMENT_KEY = "environment"

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
ACCOUNTS_FIXTURE_PATH = FIXTURES_DIR / "logismart_test_accounts.json"
SETTINGS_FIXTURE_PATH = FIXTURES_DIR / "logismart_test_settings.json"
ADDRESSES_FIXTURE_PATH = FIXTURES_DIR / "logismart_test_addresses.json"

STATE_DIR = Path("/tmp")
STATE_FILE_PREFIX = "naviera_golden"
LOCK_FILE_SUFFIX = ".lock"
LOCK_FILE_MODE = "w"

TOKEN_TTL_SECONDS = 86_400
JWT_AUDIENCE = "authenticated"
JWT_ROLE = "authenticated"

UTR_LENGTH = 12
UTR_LEADING_DIGIT = "6"
BANK_UTR_PREFIX = "GLDN"
BANK_UTR_DIGITS = 10
RUN_TAG_HEX_BYTES = 3
MONEY_DECIMALS = 2
FIRST_DOCUMENT_SERIAL = 1

# Canonical account emails (must match `fixtures/logismart_test_accounts.json`).
OWNER_EMAIL = "owner@logismart.in"
ADMIN_EMAIL = "admin@logismart.in"
OPERATIONS_EMAIL = "operations@logismart.in"
SUPPORT_EMAIL = "support@logismart.in"
READONLY_EMAIL = "readonly@logismart.in"
CUSTOMER_B2C_EMAIL = "customerb2c@logismart.in"
CUSTOMER_B2B_EMAIL = "customerb2b@logismart.in"
B2B_ONBOARDING_EMAIL = "b2bonboarding@logismart.in"

# Saved addresses created by the seed (see `fixtures/logismart_test_addresses.json`).
SEEDED_WAREHOUSE_PINCODE = "122001"


class GoldenEnvError(RuntimeError):
    """Raised when the golden harness would touch a non-test tenant or identity."""


# --- Test-only database engine ----------------------------------------------
# Production `app/core/db.py` is never modified for tests (AGENTS §5, DO NOT TOUCH).
# The golden harness builds its own engine on the same DATABASE_URL:
# * a small connection pool (the prod engine's NullPool opens a new TLS connection to the
#   remote PgBouncer for every session, which made one golden journey take about a minute);
#   every pooled connection is rolled back on check-in and pinged on check-out;
# * asyncpg's *unnamed* prepared statement, which PgBouncer (transaction pooling) overwrites
#   with the next query instead of piling up one named statement per query.
# Spring analogy: a `@TestConfiguration` DataSource bean (HikariCP) that replaces the prod one.

TEST_ENGINE_CONNECT_ARGS: Dict[str, Any] = {
    "statement_cache_size": 0,
    "prepared_statement_name_func": lambda: "",
    "command_timeout": 30,
    "timeout": 15,
}
"""asyncpg connect args of the test-only engine (no statement cache, unnamed statements)."""
TEST_POOL_SIZE = 2
TEST_POOL_MAX_OVERFLOW = 4
TEST_POOL_RECYCLE_SECONDS = 45
TCP_KEEPIDLE_SECONDS = 10
TCP_KEEPINTVL_SECONDS = 5
TCP_KEEPCNT_PROBES = 3
TCP_USER_TIMEOUT_MS = 15_000
ACCOUNT_LOOKUP_ATTEMPTS = 3
ACCOUNT_LOOKUP_RETRY_DELAY_S = 1.0
"""Recycle pooled connections well before PgBouncer / Supavisor idle timeouts."""


class GoldenReadSession(AsyncSession):
    """
    Session for the harness's read-only DB oracles.

    The helpers read rows, `rollback()` (they never write) and use the rows after the session
    closed. A plain rollback expires every loaded row, so a later attribute access raises
    `DetachedInstanceError`. Expunging first keeps the loaded values on the detached rows.
    """

    async def rollback(self) -> None:
        """Detaches loaded rows with their current values, then rolls back."""
        self.expunge_all()
        await super().rollback()


def _configure_socket_keepalive(dbapi_conn: Any, _conn_record: Any) -> None:
    """Enables aggressive TCP keepalives + TCP_USER_TIMEOUT so NAT/PgBouncer never hangs."""
    raw = getattr(dbapi_conn, "_connection", None)
    transport = getattr(raw, "_transport", None)
    sock = transport.get_extra_info("socket") if transport is not None else None
    if sock is None:
        return
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, TCP_KEEPIDLE_SECONDS)
        if hasattr(socket, "TCP_KEEPINTVL"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, TCP_KEEPINTVL_SECONDS)
        if hasattr(socket, "TCP_KEEPCNT"):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, TCP_KEEPCNT_PROBES)
        tcp_user_timeout = getattr(socket, "TCP_USER_TIMEOUT", 18)
        sock.setsockopt(socket.IPPROTO_TCP, tcp_user_timeout, TCP_USER_TIMEOUT_MS)
    except OSError:
        pass


def _build_test_engine() -> AsyncEngine:
    """Creates the test-only async engine (small pool, pre-ping, periodic recycle, TCP keepalives)."""
    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=TEST_POOL_SIZE,
        max_overflow=TEST_POOL_MAX_OVERFLOW,
        pool_pre_ping=True,
        pool_recycle=TEST_POOL_RECYCLE_SECONDS,
        connect_args=TEST_ENGINE_CONNECT_ARGS,
    )
    event.listens_for(engine.sync_engine, "connect")(_configure_socket_keepalive)
    return engine


test_engine: AsyncEngine = _build_test_engine()

GoldenSessionLocal = sessionmaker(  # type: ignore[call-overload]
    bind=test_engine, class_=GoldenReadSession, expire_on_commit=False
)
"""Sessions for harness reads / resets (rows stay readable after rollback or close)."""

TestAppSessionLocal = sessionmaker(  # type: ignore[call-overload]
    bind=test_engine, class_=AsyncSession, expire_on_commit=False
)
"""Plain sessions injected into the in-process app through `get_session` overrides."""


# --- Slug guard (runs at import time) --------------------------------------


def resolve_golden_slug() -> str:
    """Returns the golden tenant slug from the environment (default `logismart-test`)."""
    return os.getenv(GOLDEN_SLUG_ENV_VAR, DEFAULT_GOLDEN_SLUG).strip()


def assert_slug_allowed(slug: str) -> str:
    """
    Refuses any slug outside the shared test allow-list.

    Args:
        slug: Candidate tenant slug.

    Returns:
        The same slug, when allowed.

    Raises:
        GoldenEnvError: When the slug is not in `ALLOWED_TEST_SLUGS`.
    """
    if slug not in ALLOWED_TEST_SLUGS:
        raise GoldenEnvError(
            f"Golden suites refuse tenant slug {slug!r}: only {sorted(ALLOWED_TEST_SLUGS)} "
            f"are allowed (set {GOLDEN_SLUG_ENV_VAR} to a test slug). Live tenants are never used."
        )
    return slug


GOLDEN_TENANT_SLUG: str = assert_slug_allowed(resolve_golden_slug())

# A short random tag that makes every order reference of this run unique.
RUN_TAG: str = f"{int(time.time())}-{secrets.token_hex(RUN_TAG_HEX_BYTES)}"


# --- Fixture loading -------------------------------------------------------


def _read_json(path: Path) -> Any:
    """Reads one JSON fixture file, failing loudly when it is missing."""
    if not path.exists():
        raise GoldenEnvError(f"Golden fixture missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_account_specs() -> List[Dict[str, Any]]:
    """Returns the canonical account specs (owner first) from the accounts fixture."""
    payload = _read_json(ACCOUNTS_FIXTURE_PATH)
    return list(payload["accounts"])


def canonical_emails() -> FrozenSet[str]:
    """Returns the set of emails the harness is allowed to mint tokens for."""
    return frozenset(spec["email"] for spec in load_account_specs())


def load_settings_fixture() -> Dict[str, Any]:
    """Returns the frozen `tenant.settings` dict of the test tenant."""
    return dict(_read_json(SETTINGS_FIXTURE_PATH))


def load_address_fixtures() -> List[Dict[str, Any]]:
    """Returns the 3 seeded saved-address specs."""
    return list(_read_json(ADDRESSES_FIXTURE_PATH))


# --- Tenant + identity guards ---------------------------------------------


def assert_test_environment(tenant: Optional[Tenant], slug: str) -> Tenant:
    """
    Verifies the tenant exists and is flagged as a test tenant.

    Raises:
        GoldenEnvError: When the tenant is missing or not `environment == "test"`.
    """
    if tenant is None:
        raise GoldenEnvError(
            f"Test tenant {slug!r} does not exist yet. Run the seed "
            "(backend/scripts/seed_logismart_test.py) after the user's go-ahead."
        )
    environment = (tenant.settings or {}).get(SETTINGS_ENVIRONMENT_KEY)
    if environment != TEST_ENVIRONMENT_VALUE:
        raise GoldenEnvError(
            f"Tenant {slug!r} has settings.environment={environment!r}; golden suites only "
            f"run on tenants with environment={TEST_ENVIRONMENT_VALUE!r}."
        )
    return tenant


async def load_test_tenant(slug: str = GOLDEN_TENANT_SLUG) -> Tenant:
    """Loads and validates the golden test tenant (slug guard + environment guard)."""
    assert_slug_allowed(slug)
    async with GoldenSessionLocal() as session:
        tenant = (await session.exec(select(Tenant).where(Tenant.slug == slug))).first()
        if tenant:
            _ = tenant.settings
            session.expunge(tenant)
        await session.rollback()
    return assert_test_environment(tenant, slug)


async def get_tenant_id() -> UUID:
    """Returns the UUID of the validated golden test tenant."""
    return (await load_test_tenant()).id


def assert_email_is_test_actor(email: str) -> None:
    """
    Refuses an email that is protected live or not in the canonical fixture.

    Raises:
        GoldenEnvError: When the email may not be used as a test actor.
    """
    normalized = email.strip().lower()
    if normalized in {e.lower() for e in PROTECTED_LIVE_EMAILS}:
        raise GoldenEnvError(
            f"Refusing to mint a token for protected live identity {email!r}."
        )
    if normalized not in {e.lower() for e in canonical_emails()}:
        raise GoldenEnvError(
            f"Refusing to mint a token for {email!r}: it is not in {ACCOUNTS_FIXTURE_PATH.name}."
        )


async def _protected_supabase_ids(session: Any) -> FrozenSet[str]:
    """Returns the Supabase `sub` values of every protected live user row (any tenant)."""
    rows = (
        await session.exec(
            select(User.supabase_user_id).where(
                col(User.email).in_(sorted(PROTECTED_LIVE_EMAILS))
            )
        )
    ).all()
    return frozenset(str(sub) for sub in rows if sub is not None)


def mint_jwt(supabase_user_id: str, email: str) -> str:
    """
    Mints a Supabase-compatible HS256 JWT after the test-actor check.

    Raises:
        GoldenEnvError: When the email is not a canonical test actor.
    """
    assert_email_is_test_actor(email)
    now_ts = int(time.time())
    claims = {
        "sub": str(supabase_user_id),
        "email": email,
        "aud": JWT_AUDIENCE,
        "role": JWT_ROLE,
        "iss": settings.JWT_ISSUER,
        "iat": now_ts,
        "exp": now_ts + TOKEN_TTL_SECONDS,
    }
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def _account_entry(user: User, token: str) -> Dict[str, Any]:
    """Builds the account dict shared by every suite (id, sub, role, token, headers)."""
    return {
        "id": str(user.id),
        "supabase_user_id": str(user.supabase_user_id),
        "sub": str(user.supabase_user_id),
        "email": user.email,
        "role": user.role.value,
        "service_scope": user.service_scope.value,
        "tenant_slug": GOLDEN_TENANT_SLUG,
        "tenant_id": str(user.tenant_id),
        "access_token": token,
        "headers": {
            "Authorization": f"Bearer {token}",
            "X-Tenant-Slug": GOLDEN_TENANT_SLUG,
        },
    }


_ACCOUNTS_CACHE: Dict[str, Dict[str, Any]] = {}


async def _load_canonical_users(
    tenant_id: UUID, emails: FrozenSet[str]
) -> Tuple[List[User], FrozenSet[str]]:
    """
    Reads the canonical test users and the protected live Supabase ids in one session.

    The shared pooler occasionally drops a fresh TLS connection, so the read is retried
    a few times on a DBAPI error before giving up.
    """
    for attempt in range(1, ACCOUNT_LOOKUP_ATTEMPTS + 1):
        try:
            async with GoldenSessionLocal() as session:
                users = (
                    await session.exec(
                        select(User).where(
                            User.tenant_id == tenant_id, col(User.email).in_(sorted(emails))
                        )
                    )
                ).all()
                protected_subs = await _protected_supabase_ids(session)
                session.expunge_all()
                await session.rollback()
                return list(users), protected_subs
        except DBAPIError:
            if attempt == ACCOUNT_LOOKUP_ATTEMPTS:
                raise
            await asyncio.sleep(ACCOUNT_LOOKUP_RETRY_DELAY_S)
    raise GoldenEnvError("unreachable: account lookup loop exited without a result")


async def load_accounts() -> Dict[str, Dict[str, Any]]:
    """
    Resolves every canonical account inside the test tenant and mints its JWT.

    Tokens are always minted for the `logismart-test` user row (tenant-checked
    lookup), never for a live row. The result is memoised per process.

    Raises:
        GoldenEnvError: On a missing account, a protected email, or a Supabase
            identity shared with a protected live user.
    """
    if _ACCOUNTS_CACHE:
        return _ACCOUNTS_CACHE
    tenant = await load_test_tenant()
    emails = canonical_emails()
    for email in emails:
        assert_email_is_test_actor(email)
    users, protected_subs = await _load_canonical_users(tenant.id, emails)
    by_email = {u.email: u for u in users}
    missing = sorted(emails - set(by_email))
    if missing:
        raise GoldenEnvError(
            f"Test tenant {GOLDEN_TENANT_SLUG!r} is missing canonical accounts {missing}; re-run the seed."
        )
    for email, user in by_email.items():
        if str(user.supabase_user_id) in protected_subs:
            raise GoldenEnvError(
                f"Refusing {email!r}: its Supabase identity also backs a protected live user."
            )
        _ACCOUNTS_CACHE[email] = _account_entry(user, mint_jwt(str(user.supabase_user_id), email))
    return _ACCOUNTS_CACHE


def headers(accounts: Mapping[str, Mapping[str, Any]], email: str) -> Dict[str, str]:
    """Returns the Authorization + X-Tenant-Slug headers for one canonical account."""
    return dict(accounts[email]["headers"])


# --- Per-run identifiers ---------------------------------------------------


def make_utr() -> str:
    """Returns a random 12-digit UPI UTR (global unique constraint safe per run)."""
    tail = "".join(secrets.choice("0123456789") for _ in range(UTR_LENGTH - 1))
    return f"{UTR_LEADING_DIGIT}{tail}"


def make_bank_utr() -> str:
    """Returns a random bank UTR for COD remittance batches."""
    digits = "".join(secrets.choice("0123456789") for _ in range(BANK_UTR_DIGITS))
    return f"{BANK_UTR_PREFIX}{digits}"


def order_ref(label: str) -> str:
    """Returns a run-unique `order_reference_id`, e.g. `GOLDEN-J09-ORD1-<run>`."""
    return f"GOLDEN-{label}-{RUN_TAG}"


def document_prefix(note_type: str, on_date: Optional[date] = None) -> str:
    """
    Returns the GST document series prefix of the test tenant for `note_type`
    (e.g. `LTST2627I`), computed with the production numbering helpers from the
    frozen settings fixture, so no suite hard-codes the live `LOGI` series.
    """
    tenant = Tenant(
        slug=GOLDEN_TENANT_SLUG, name=GOLDEN_TENANT_SLUG, settings=load_settings_fixture()
    )
    fiscal_year = indian_financial_year_label(on_date or date.today())
    return document_number_prefix(tenant, fiscal_year, note_type)


def first_document_number(note_type: str) -> str:
    """Returns the first number of a series after a reset, e.g. `LTST2627I000001`."""
    return format_document_number(document_prefix(note_type), FIRST_DOCUMENT_SERIAL)


def receipt_prefix(family: str, on_date: Optional[date] = None) -> str:
    """Wallet receipt prefix `<FAMILY>-<FY>-` (plan B12: FY label, e.g. `INV-2627-`)."""
    return f"{family}-{indian_financial_year_label(on_date or date.today())}-"


# --- State files (namespaced by slug) --------------------------------------


def state_path(batch: str) -> Path:
    """Returns `/tmp/naviera_golden_<slug>_<batch>_state.json`."""
    return STATE_DIR / f"{STATE_FILE_PREFIX}_{GOLDEN_TENANT_SLUG}_{batch}_state.json"


def lock_path() -> Path:
    """Returns the per-slug run lock file path."""
    return STATE_DIR / f"{STATE_FILE_PREFIX}_{GOLDEN_TENANT_SLUG}{LOCK_FILE_SUFFIX}"


_RUN_LOCK_STATE: Dict[str, Any] = {"handle": None, "depth": 0}


def acquire_run_lock() -> IO[str]:
    """
    Takes an exclusive, non-blocking lock on `/tmp/naviera_golden_<slug>.lock`.

    Re-entrant within one pytest process (the golden session fixture and the
    e2e module fixture may both ask for it); a second process is refused.
    A Postgres advisory lock is not reliable through PgBouncer transaction
    pooling (port 6543), so a local file lock serialises runs instead.

    Raises:
        GoldenEnvError: When another process already holds the lock.
    """
    if _RUN_LOCK_STATE["handle"] is not None:
        _RUN_LOCK_STATE["depth"] += 1
        return _RUN_LOCK_STATE["handle"]
    handle = open(lock_path(), LOCK_FILE_MODE, encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise GoldenEnvError(
            f"Another golden run holds {lock_path()}; runs are strictly one at a time."
        ) from exc
    _RUN_LOCK_STATE.update(handle=handle, depth=1)
    return handle


def release_run_lock(handle: IO[str]) -> None:
    """Releases one level of the run lock; unlocks and closes it at depth zero."""
    if _RUN_LOCK_STATE["handle"] is not handle:
        return
    _RUN_LOCK_STATE["depth"] -= 1
    if _RUN_LOCK_STATE["depth"] > 0:
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    handle.close()
    _RUN_LOCK_STATE.update(handle=None, depth=0)


def golden_tmp_files() -> List[Path]:
    """Returns every `/tmp` state file of this slug (the lock file excluded)."""
    pattern = f"{STATE_FILE_PREFIX}_{GOLDEN_TENANT_SLUG}_*_state.json"
    return sorted(STATE_DIR.glob(pattern))


def clear_state_files() -> int:
    """Deletes this slug's state files. Returns how many were removed."""
    removed = 0
    for path in golden_tmp_files():
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def load_state(*batches: str) -> Dict[str, Any]:
    """Merges the given batches' state files (later batches win)."""
    merged: Dict[str, Any] = {}
    for batch in batches:
        path = state_path(batch)
        if path.exists():
            merged.update(json.loads(path.read_text(encoding="utf-8")))
    return merged


def save_state(batch: str, updates: Mapping[str, Any]) -> Dict[str, Any]:
    """Merges `updates` into one batch state file and returns the merged dict."""
    current = load_state(batch)
    current.update(updates)
    state_path(batch).write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def require_state(state: Mapping[str, Any], keys: Sequence[str]) -> None:
    """Fails with a clear message when an earlier suite did not record a key."""
    missing = [k for k in keys if k not in state]
    if missing:
        raise GoldenEnvError(
            f"Golden state is missing {missing}: run the suites in order in ONE pytest session."
        )


# --- Tenant-scoped DB reads used by several suites -------------------------


async def get_wallet_balance(user_id: str) -> float:
    """Reads `user_wallets.balance` for one user inside the test tenant (0.0 if none)."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        wallet = (
            await session.exec(
                select(UserWallet).where(
                    UserWallet.user_id == UUID(str(user_id)),
                    UserWallet.tenant_id == tenant_id,
                )
            )
        ).first()
        await session.rollback()
    return round(float(wallet.balance), MONEY_DECIMALS) if wallet else 0.0


async def find_wallet_txn_by_utr(utr: str) -> Optional[WalletTransaction]:
    """Looks up a wallet transaction by UTR, always filtered by the test tenant."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        txn = (
            await session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.tenant_id == tenant_id,
                    WalletTransaction.utr_number == utr,
                )
            )
        ).first()
        await session.rollback()
    return txn


async def first_tenant_payment_details() -> Optional[PaymentDetails]:
    """Returns one `PaymentDetails` row that belongs to the test tenant (or None)."""
    tenant_id = await get_tenant_id()
    async with GoldenSessionLocal() as session:
        row = (
            await session.exec(
                select(PaymentDetails)
                .join(PickupRequest, PickupRequest.id == PaymentDetails.pickup_id)
                .where(PickupRequest.tenant_id == tenant_id)
                .limit(1)
            )
        ).first()
        await session.rollback()
    return row


async def find_seeded_address_id(
    client: Any, accounts: Mapping[str, Mapping[str, Any]], email: str,
    pincode: str = SEEDED_WAREHOUSE_PINCODE,
) -> str:
    """
    Returns the id of the seeded saved address owned by `email` at `pincode`.

    The seed creates it; the suites never create it on the fly.

    Raises:
        GoldenEnvError: When the seeded address is missing.
    """
    resp = await client.get("/api/v1/addresses", headers=headers(accounts, email))
    if resp.status_code != 200:
        raise GoldenEnvError(f"GET /api/v1/addresses failed for {email}: {resp.text}")
    owner_id = accounts[email]["id"]
    for addr in resp.json():
        if (
            addr.get("user_id") == owner_id
            and addr.get("pincode") == pincode
            and addr.get("is_saved") is True
        ):
            return str(addr["id"])
    raise GoldenEnvError(
        f"Seeded saved address for {email} at {pincode} not found; re-run the reset/seed."
    )


async def read_otp_as_merchant(
    client: Any, accounts: Mapping[str, Mapping[str, Any]], merchant_email: str, shipment_id: str
) -> str:
    """
    Reads a shipment's 6-digit delivery OTP through the API with the MERCHANT's token.

    Raises:
        GoldenEnvError: When the shipment has no 6-digit OTP yet.
    """
    resp = await client.get(
        f"/api/v1/shipments/{shipment_id}", headers=headers(accounts, merchant_email)
    )
    if resp.status_code != 200:
        raise GoldenEnvError(f"GET shipment {shipment_id} failed: {resp.text}")
    otp = resp.json().get("delivery_otp")
    if not otp or len(otp) != 6 or not otp.isdigit():
        raise GoldenEnvError(f"Shipment {shipment_id} has no 6-digit delivery OTP: {otp!r}")
    return otp


@contextmanager
def allow_to_pay_bookings() -> Iterator[None]:
    """
    Temporarily switches `mvp_scope.TO_PAY_BOOKINGS_ENABLED = True` so a golden test can
    seed a legacy `TO_PAY` row through the real booking endpoint after asserting the
    default 400 refusal.
    """
    previous = mvp_scope.TO_PAY_BOOKINGS_ENABLED
    mvp_scope.TO_PAY_BOOKINGS_ENABLED = True
    try:
        yield
    finally:
        mvp_scope.TO_PAY_BOOKINGS_ENABLED = previous
