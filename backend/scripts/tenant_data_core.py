"""
Shared tenant data operations for Phase A (plan items A4 and A5).

One module, three callers:
  * `scripts/seed_logismart_test.py`: idempotent seed of the `logismart-test` tenant.
  * `scripts/wipe_tenant_test_data.py`: one-time wipe of golden-test rows from live `logismart`.
  * `scripts/tests/golden_journeys/conftest.py`: `reset_test_tenant()` once per golden pytest session.

The single source of truth for "which rows belong to a tenant, and in which order can they be
deleted without breaking a foreign key" is `OPERATIONAL_DELETE_STEPS` below. Every caller uses it,
so the reset, the wipe and the handover utility can never drift apart.

Spring Boot mapping:
  * `OPERATIONAL_DELETE_STEPS` is the ordered list of `@Modifying @Query("DELETE FROM x WHERE y")` calls you would
    put in one `@Transactional` cleanup service, children before parents.
  * `seed_test_tenant()` is a hand-run `CommandLineRunner`, not a Flyway migration: test fixtures must
    never ship inside a migration that also runs in production.
  * `reset_test_tenant()` is the `@Sql(executionPhase = BEFORE_TEST_CLASS)` cleanup used instead of
    per-test `@Transactional` rollback, because the golden suites commit through the real API.

No function here commits unless its docstring says so; the caller owns the transaction
(dry runs roll back, `--execute` commits).
"""

import copy
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Callable,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Type,
)

from sqlalchemy import delete, false, func, not_, or_, select, text
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import SQLModel, col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.delhivery_modules import (
    BillingInvoice,
    CodRemittance,
    InvoiceNoteType,
    SupportTicket,
    SupportTicketMessage,
    WeightDispute,
)
from app.models.manifests import Manifest
from app.models.pickups import (
    Address,
    AddressCategory,
    AddressScope,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    ShipmentActivity,
)
from app.models.repricing import (
    IdempotencyKey,
    ShipmentChargeAdjustment,
    ShipmentMeasurement,
)
from app.models.tenants import (
    ServiceScope,
    Tenant,
    TenantSettingsHistory,
    User,
    UserRole,
)
from app.models.wallet import UserWallet, WalletTransaction
from app.repositories.delhivery_modules import DelhiveryModulesRepository
from app.repositories.tenants import TenantRepository
from app.services.addresses import generate_address_signature
from app.services.delhivery_modules import (
    IST,
    document_number_prefix,
    indian_financial_year_label,
    tenant_document_prefix,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKEND_ROOT: Path = Path(__file__).resolve().parents[1]
"""`naviera/backend`, resolved from this file so the scripts work from any cwd."""

FIXTURES_DIR: Path = BACKEND_ROOT / "scripts" / "tests" / "golden_journeys" / "fixtures"
"""Frozen test-tenant fixtures, owned by the golden harness and read-only here."""

SETTINGS_FIXTURE_NAME: str = "logismart_test_settings.json"
ACCOUNTS_FIXTURE_NAME: str = "logismart_test_accounts.json"
ADDRESSES_FIXTURE_NAME: str = "logismart_test_addresses.json"

ALLOWED_TEST_SLUGS: FrozenSet[str] = frozenset({"logismart-test"})
"""The ONE allow-list of tenants that tests may reset. golden_env imports it from here."""

PROTECTED_LIVE_EMAILS: FrozenSet[str] = frozenset({"prashantnk2001@gmail.com"})
"""Real humans (D43 c: the live Owner) who must never become a test actor or a seeded account."""

TEST_ACCOUNT_EMAIL_DOMAIN: str = "@logismart.in"
"""Every seeded test account must use this domain."""

LIVE_INVOICE_PREFIXES: FrozenSet[str] = frozenset({"LOGI"})
"""GST series prefixes used by live tenants; a test tenant must never print one of them."""

SETTINGS_ENVIRONMENT_KEY: str = "environment"
TEST_ENVIRONMENT_VALUE: str = "test"
SETTINGS_COMPANY_KEY: str = "company"
SETTINGS_INVOICE_PREFIX_KEY: str = "invoice_prefix"
SETTINGS_B2B_ACCESS_KEY: str = "b2b_access_requests"
B2B_ACCESS_STATUS_KEY: str = "status"
B2B_ACCESS_GSTIN_KEY: str = "gstin"
B2B_ACCESS_REVIEWED_AT_KEY: str = "reviewed_at"
B2B_ACCESS_REVIEWED_BY_KEY: str = "reviewed_by"
B2B_ACCESS_APPROVED: str = "APPROVED"
B2B_ENABLED_SCOPES: FrozenSet[ServiceScope] = frozenset({ServiceScope.B2B, ServiceScope.BOTH})

ZERO_BALANCE: float = 0.0
FIRST_DOCUMENT_SERIAL: int = 1
USER_TABLE: str = User.__tablename__  # type: ignore[attr-defined]
TENANT_TABLE: str = Tenant.__tablename__  # type: ignore[attr-defined]

LOCK_TIMEOUT_SQL = text("SET LOCAL lock_timeout = '5s'")
STATEMENT_TIMEOUT_SQL = text("SET LOCAL statement_timeout = '120s'")


class TenantGuardError(RuntimeError):
    """Raised when an operation targets a tenant it must never touch (slug or marker mismatch)."""


class TenantIntegrityError(RuntimeError):
    """Raised when an in-transaction verification fails; the caller must roll back."""


class FixtureError(ValueError):
    """Raised when the frozen fixtures are malformed or violate a safety rule."""


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def assert_test_tenant_slug(slug: str) -> None:
    """
    Refuses any slug outside `ALLOWED_TEST_SLUGS`.

    Args:
        slug: Tenant slug the caller wants to reset or seed.

    Raises:
        TenantGuardError: when the slug is not an allow-listed test tenant (e.g. `logismart`).
    """
    if slug not in ALLOWED_TEST_SLUGS:
        raise TenantGuardError(
            f"Refusing to touch tenant '{slug}': only {sorted(ALLOWED_TEST_SLUGS)} may be "
            "seeded or reset by test tooling."
        )


def is_test_tenant(tenant: Tenant) -> bool:
    """True when the tenant row carries `settings.environment == "test"`."""
    settings_obj: Mapping[str, Any] = tenant.settings or {}
    return settings_obj.get(SETTINGS_ENVIRONMENT_KEY) == TEST_ENVIRONMENT_VALUE


def assert_test_tenant_marked(tenant: Tenant) -> None:
    """
    Second guard: the DB row itself must be marked as a test tenant.

    Raises:
        TenantGuardError: when `settings.environment` is not `"test"`.
    """
    assert_test_tenant_slug(tenant.slug)
    if not is_test_tenant(tenant):
        raise TenantGuardError(
            f"Tenant '{tenant.slug}' exists but is not marked "
            f"settings.{SETTINGS_ENVIRONMENT_KEY} == '{TEST_ENVIRONMENT_VALUE}'; refusing."
        )


def assert_seedable_email(email: str) -> None:
    """
    A seeded account must be a lower-case `@logismart.in` test identity and never a protected human.

    Raises:
        FixtureError: on a protected, foreign-domain or non-normalised email.
    """
    if email != email.strip().lower():
        raise FixtureError(f"Account email '{email}' must be lower-case and trimmed.")
    if email in PROTECTED_LIVE_EMAILS:
        raise FixtureError(f"'{email}' is a protected live identity and can never be seeded.")
    if not email.endswith(TEST_ACCOUNT_EMAIL_DOMAIN):
        raise FixtureError(f"Account '{email}' must use the {TEST_ACCOUNT_EMAIL_DOMAIN} domain.")


# ---------------------------------------------------------------------------
# Pure settings helpers
# ---------------------------------------------------------------------------


def apply_invoice_prefix(settings_obj: Mapping[str, Any], prefix: str) -> Dict[str, Any]:
    """
    Returns a deep copy of `settings_obj` with `company.invoice_prefix = prefix`.

    The GST series prefix otherwise falls back to the first 4 letters of the slug, and both
    `logismart` and `logismart-test` truncate to `LOGI` (see `tenant_document_prefix`).
    """
    updated: Dict[str, Any] = copy.deepcopy(dict(settings_obj))
    company: Dict[str, Any] = dict(updated.get(SETTINGS_COMPANY_KEY) or {})
    company[SETTINGS_INVOICE_PREFIX_KEY] = prefix
    updated[SETTINGS_COMPANY_KEY] = company
    return updated


def validate_test_settings(settings_obj: Mapping[str, Any]) -> None:
    """
    Checks the frozen test settings before they are written anywhere.

    Raises:
        FixtureError: when the environment marker is missing, the GST prefix is missing or equals a
            live prefix (after the same normalisation the invoice code applies), or the fixture
            carries user-id keyed `b2b_access_requests` (ids differ per tenant; the seed builds them).
    """
    if settings_obj.get(SETTINGS_ENVIRONMENT_KEY) != TEST_ENVIRONMENT_VALUE:
        raise FixtureError(
            f"Test settings must contain {SETTINGS_ENVIRONMENT_KEY}='{TEST_ENVIRONMENT_VALUE}'."
        )
    company: Mapping[str, Any] = settings_obj.get(SETTINGS_COMPANY_KEY) or {}
    if not company.get(SETTINGS_INVOICE_PREFIX_KEY):
        raise FixtureError("Test settings must set company.invoice_prefix.")
    probe = Tenant(slug=next(iter(ALLOWED_TEST_SLUGS)), name="probe", settings=dict(settings_obj))
    effective_prefix = tenant_document_prefix(probe)
    if effective_prefix in LIVE_INVOICE_PREFIXES:
        raise FixtureError(
            f"Test GST prefix resolves to '{effective_prefix}', which a live tenant uses."
        )
    if SETTINGS_B2B_ACCESS_KEY in settings_obj:
        raise FixtureError(f"Fixture settings must not contain '{SETTINGS_B2B_ACCESS_KEY}'.")


def build_b2b_access_requests(
    accounts: Sequence["AccountSpec"],
    user_ids_by_email: Mapping[str, uuid.UUID],
    reviewer_email: str,
    reviewed_at: datetime,
) -> Dict[str, Dict[str, str]]:
    """
    APPROVED entries for every account whose scope enables B2B (B2B or BOTH), keyed by `user.id`.

    B2C accounts (e.g. `b2bonboarding@`) get no entry, so J04 starts from a clean request state.
    """
    entries: Dict[str, Dict[str, str]] = {}
    for account in accounts:
        if account.service_scope not in B2B_ENABLED_SCOPES:
            continue
        user_id = user_ids_by_email[account.email]
        entry = {
            B2B_ACCESS_STATUS_KEY: B2B_ACCESS_APPROVED,
            B2B_ACCESS_REVIEWED_AT_KEY: reviewed_at.isoformat(),
            B2B_ACCESS_REVIEWED_BY_KEY: reviewer_email,
        }
        if account.gstin:
            entry[B2B_ACCESS_GSTIN_KEY] = account.gstin
        entries[str(user_id)] = entry
    return entries


def prune_b2b_access_requests(
    settings_obj: Mapping[str, Any], keep_user_ids: FrozenSet[uuid.UUID]
) -> Dict[str, Any]:
    """
    Returns a deep copy of `settings_obj` whose `b2b_access_requests` only keeps entries for
    `keep_user_ids`; entries of deleted users and stale keys are dropped.
    """
    updated: Dict[str, Any] = copy.deepcopy(dict(settings_obj))
    current: Mapping[str, Any] = updated.get(SETTINGS_B2B_ACCESS_KEY) or {}
    keep_keys = {str(user_id) for user_id in keep_user_ids}
    updated[SETTINGS_B2B_ACCESS_KEY] = {
        key: value for key, value in current.items() if key in keep_keys
    }
    return updated


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AccountSpec:
    """One canonical test account (`logismart_test_accounts.json`)."""

    email: str
    role: UserRole
    service_scope: ServiceScope
    full_name: Optional[str]
    phone: Optional[str]
    is_owner: bool
    needs_wallet: bool
    gstin: Optional[str] = None
    """GSTIN on the account's APPROVED B2B profile (drives the GST place of supply)."""


@dataclass(frozen=True)
class AddressSpec:
    """One canonical saved address (`logismart_test_addresses.json`)."""

    owner_email: str
    name: str
    phone: str
    address_line1: str
    city: str
    state: str
    pincode: str
    country: str
    category: AddressCategory
    scope: AddressScope
    company_name: Optional[str] = None
    address_line2: Optional[str] = None
    landmark: Optional[str] = None
    email: Optional[str] = None
    gstin: Optional[str] = None
    alternate_phone: Optional[str] = None


@dataclass(frozen=True)
class SeedFixtures:
    """Everything the seed and the reset need, parsed and validated."""

    slug: str
    name: str
    settings: Dict[str, Any]
    accounts: Sequence[AccountSpec]
    addresses: Sequence[AddressSpec]

    @property
    def owner(self) -> AccountSpec:
        """The single owner account (always first)."""
        return self.accounts[0]

    @property
    def canonical_emails(self) -> FrozenSet[str]:
        """Emails of every canonical account."""
        return frozenset(account.email for account in self.accounts)


def _parse_account(raw: Mapping[str, Any]) -> AccountSpec:
    """Builds an `AccountSpec`, converting role/scope strings into their Enums."""
    email = str(raw["email"])
    assert_seedable_email(email)
    return AccountSpec(
        email=email,
        role=UserRole(raw["role"]),
        service_scope=ServiceScope(raw["service_scope"]),
        full_name=raw.get("full_name"),
        phone=raw.get("phone"),
        is_owner=bool(raw.get("is_owner", False)),
        needs_wallet=bool(raw.get("needs_wallet", False)),
        gstin=raw.get("gstin"),
    )


def _validate_accounts(accounts: Sequence[AccountSpec]) -> None:
    """Owner first, exactly one owner, unique emails."""
    if not accounts:
        raise FixtureError("Accounts fixture is empty.")
    first = accounts[0]
    if not (first.is_owner and first.role == UserRole.owner):
        raise FixtureError("The first account must be the owner (JIT makes the first user OWNER).")
    owners = [a for a in accounts if a.is_owner or a.role == UserRole.owner]
    if len(owners) != 1:
        raise FixtureError(f"Exactly one owner account is required, found {len(owners)}.")
    emails = [a.email for a in accounts]
    if len(set(emails)) != len(emails):
        raise FixtureError("Account emails must be unique.")


def _parse_address(raw: Mapping[str, Any], account_emails: FrozenSet[str]) -> AddressSpec:
    """Builds an `AddressSpec`; its owner must be a canonical account."""
    owner_email = str(raw["owner_email"])
    if owner_email not in account_emails:
        raise FixtureError(f"Address owner '{owner_email}' is not a canonical account.")
    return AddressSpec(
        owner_email=owner_email,
        name=str(raw["name"]),
        phone=str(raw["phone"]),
        address_line1=str(raw["address_line1"]),
        city=str(raw["city"]),
        state=str(raw["state"]),
        pincode=str(raw["pincode"]),
        country=str(raw.get("country") or "IN"),
        category=AddressCategory(raw["category"]),
        scope=AddressScope(raw["scope"]),
        company_name=raw.get("company_name"),
        address_line2=raw.get("address_line2"),
        landmark=raw.get("landmark"),
        email=raw.get("email"),
        gstin=raw.get("gstin"),
        alternate_phone=raw.get("alternate_phone"),
    )


def parse_seed_fixtures(
    settings_raw: Mapping[str, Any],
    accounts_raw: Mapping[str, Any],
    addresses_raw: Sequence[Mapping[str, Any]],
) -> SeedFixtures:
    """
    Validates and converts the three raw JSON documents into `SeedFixtures`.

    Raises:
        FixtureError / TenantGuardError: on any safety-rule violation.
    """
    tenant_raw: Mapping[str, Any] = accounts_raw.get("tenant") or {}
    slug = str(tenant_raw.get("slug", ""))
    assert_test_tenant_slug(slug)
    validate_test_settings(settings_raw)
    accounts = tuple(_parse_account(raw) for raw in accounts_raw.get("accounts") or [])
    _validate_accounts(accounts)
    emails = frozenset(a.email for a in accounts)
    addresses = tuple(_parse_address(raw, emails) for raw in addresses_raw)
    return SeedFixtures(
        slug=slug,
        name=str(tenant_raw.get("name") or slug),
        settings=copy.deepcopy(dict(settings_raw)),
        accounts=accounts,
        addresses=addresses,
    )


def _read_json(path: Path) -> Any:
    """Reads one fixture file with a clear error when it is missing."""
    if not path.exists():
        raise FixtureError(f"Fixture file not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def load_seed_fixtures(fixtures_dir: Path = FIXTURES_DIR) -> SeedFixtures:
    """Loads and validates the three frozen fixture files from `fixtures_dir`."""
    return parse_seed_fixtures(
        _read_json(fixtures_dir / SETTINGS_FIXTURE_NAME),
        _read_json(fixtures_dir / ACCOUNTS_FIXTURE_NAME),
        _read_json(fixtures_dir / ADDRESSES_FIXTURE_NAME),
    )


# ---------------------------------------------------------------------------
# FK-ordered delete core
# ---------------------------------------------------------------------------


class AddressPurge(str, Enum):
    """Which addresses of the tenant a delete run removes."""

    ALL = "ALL"
    """Test-tenant reset: every address row of the tenant."""

    UNSAVED_AND_DROPPED_USERS = "UNSAVED_AND_DROPPED_USERS"
    """Live wipe / handover: snapshot rows plus saved rows owned by users being deleted."""


@dataclass(frozen=True)
class DeleteContext:
    """Scope of one delete run."""

    tenant_id: uuid.UUID
    address_purge: AddressPurge = AddressPurge.ALL
    dropped_user_ids: FrozenSet[uuid.UUID] = frozenset()
    include_settings_history: bool = True


@dataclass(frozen=True)
class DeleteStep:
    """One table in the FK-safe order, with the WHERE clause that scopes it to the tenant."""

    model: Type[SQLModel]
    where: Callable[[DeleteContext], ColumnElement[bool]]

    @property
    def table(self) -> str:
        """Physical table name."""
        return str(self.model.__tablename__)  # type: ignore[attr-defined]


def _tenant_pickup_ids(ctx: DeleteContext):
    """Sub-select of the tenant's shipment ids (children have no tenant_id column)."""
    return select(PickupRequest.id).where(PickupRequest.tenant_id == ctx.tenant_id)


def _tenant_ticket_ids(ctx: DeleteContext):
    """Sub-select of the tenant's support ticket ids."""
    return select(SupportTicket.id).where(SupportTicket.tenant_id == ctx.tenant_id)


def _where_ticket_messages(ctx: DeleteContext) -> ColumnElement[bool]:
    return col(SupportTicketMessage.ticket_id).in_(_tenant_ticket_ids(ctx))


def _where_support_tickets(ctx: DeleteContext) -> ColumnElement[bool]:
    return SupportTicket.tenant_id == ctx.tenant_id


def _where_weight_disputes(ctx: DeleteContext) -> ColumnElement[bool]:
    return WeightDispute.tenant_id == ctx.tenant_id


def _where_cod_remittances(ctx: DeleteContext) -> ColumnElement[bool]:
    return CodRemittance.tenant_id == ctx.tenant_id


def _where_charge_adjustments(ctx: DeleteContext) -> ColumnElement[bool]:
    return ShipmentChargeAdjustment.tenant_id == ctx.tenant_id


def _where_measurements(ctx: DeleteContext) -> ColumnElement[bool]:
    return ShipmentMeasurement.tenant_id == ctx.tenant_id


def _where_billing_invoices(ctx: DeleteContext) -> ColumnElement[bool]:
    return BillingInvoice.tenant_id == ctx.tenant_id


def _where_wallet_transactions(ctx: DeleteContext) -> ColumnElement[bool]:
    return WalletTransaction.tenant_id == ctx.tenant_id


def _where_user_wallets(ctx: DeleteContext) -> ColumnElement[bool]:
    return UserWallet.tenant_id == ctx.tenant_id


def _where_activities(ctx: DeleteContext) -> ColumnElement[bool]:
    return col(ShipmentActivity.pickup_id).in_(_tenant_pickup_ids(ctx))


def _where_packages(ctx: DeleteContext) -> ColumnElement[bool]:
    return col(PackageDetails.pickup_id).in_(_tenant_pickup_ids(ctx))


def _where_payments(ctx: DeleteContext) -> ColumnElement[bool]:
    return col(PaymentDetails.pickup_id).in_(_tenant_pickup_ids(ctx))


def _where_documents(ctx: DeleteContext) -> ColumnElement[bool]:
    return col(PickupDocument.pickup_id).in_(_tenant_pickup_ids(ctx))


def _where_pickups(ctx: DeleteContext) -> ColumnElement[bool]:
    return PickupRequest.tenant_id == ctx.tenant_id


def _where_manifests(ctx: DeleteContext) -> ColumnElement[bool]:
    return Manifest.tenant_id == ctx.tenant_id


def _where_addresses(ctx: DeleteContext) -> ColumnElement[bool]:
    """All tenant addresses, or snapshots + saved rows of users being deleted."""
    in_tenant = Address.tenant_id == ctx.tenant_id
    if ctx.address_purge == AddressPurge.ALL:
        return in_tenant
    unsaved = col(Address.is_saved).is_(False)
    if not ctx.dropped_user_ids:
        return in_tenant & unsaved
    owned_by_dropped = col(Address.user_id).in_(list(ctx.dropped_user_ids))
    return in_tenant & or_(unsaved, owned_by_dropped)


def _where_settings_history(ctx: DeleteContext) -> ColumnElement[bool]:
    """Settings history versions; matches nothing when the caller keeps history."""
    if not ctx.include_settings_history:
        return false()
    return TenantSettingsHistory.tenant_id == ctx.tenant_id


def _where_idempotency_keys(ctx: DeleteContext) -> ColumnElement[bool]:
    return IdempotencyKey.tenant_id == ctx.tenant_id


OPERATIONAL_DELETE_STEPS: Sequence[DeleteStep] = (
    DeleteStep(SupportTicketMessage, _where_ticket_messages),  # FK -> support_tickets (CASCADE)
    DeleteStep(SupportTicket, _where_support_tickets),  # FK -> pickups SET NULL, user CASCADE
    DeleteStep(WeightDispute, _where_weight_disputes),  # FK -> pickups SET NULL
    DeleteStep(CodRemittance, _where_cod_remittances),  # no FK: scoped by hand
    DeleteStep(ShipmentChargeAdjustment, _where_charge_adjustments),  # FK -> billing_invoices, wallet_transactions, pickups
    DeleteStep(ShipmentMeasurement, _where_measurements),  # FK -> pickups CASCADE, user SET NULL
    DeleteStep(BillingInvoice, _where_billing_invoices),  # FK -> pickups SET NULL; restarts GST max+1 numbering
    DeleteStep(WalletTransaction, _where_wallet_transactions),  # FK -> user_wallets, before wallets
    DeleteStep(UserWallet, _where_user_wallets),  # recreated lazily at 0 by get_or_create_wallet
    DeleteStep(ShipmentActivity, _where_activities),  # FK -> pickups NO ACTION, user NO ACTION
    DeleteStep(PackageDetails, _where_packages),  # FK -> pickups NO ACTION
    DeleteStep(PaymentDetails, _where_payments),  # FK -> pickups NO ACTION
    DeleteStep(PickupDocument, _where_documents),  # FK -> pickups NO ACTION
    DeleteStep(PickupRequest, _where_pickups),  # FK -> addresses NO ACTION, manifests SET NULL
    DeleteStep(Manifest, _where_manifests),  # FK -> addresses NO ACTION
    DeleteStep(Address, _where_addresses),  # FK -> user NO ACTION: before any user delete
    DeleteStep(TenantSettingsHistory, _where_settings_history),  # FK -> user SET NULL
    DeleteStep(IdempotencyKey, _where_idempotency_keys),  # FK -> user CASCADE, tenant CASCADE
)
"""Children strictly before parents. Users are deleted separately, after all of these."""

OPERATIONAL_TABLES: Sequence[str] = tuple(step.table for step in OPERATIONAL_DELETE_STEPS)

UNCONSTRAINED_USER_REFERENCES: Sequence[Tuple[Type[SQLModel], str]] = (
    (PickupRequest, "created_by_user_id"),
    (BillingInvoice, "merchant_user_id"),
    (CodRemittance, "merchant_user_id"),
    (WeightDispute, "merchant_user_id"),
    (SupportTicketMessage, "sender_user_id"),
)
"""Columns that hold a user id WITHOUT a foreign key, so Postgres cannot catch a dangling value."""


def full_tenant_context(tenant_id: uuid.UUID) -> DeleteContext:
    """A context that matches every operational row of the tenant (used for inventories)."""
    return DeleteContext(tenant_id=tenant_id, address_purge=AddressPurge.ALL)


async def apply_transaction_timeouts(session: AsyncSession) -> None:
    """`SET LOCAL` lock and statement timeouts so a stuck lock fails fast instead of hanging."""
    await session.exec(LOCK_TIMEOUT_SQL)  # type: ignore[call-overload]
    await session.exec(STATEMENT_TIMEOUT_SQL)  # type: ignore[call-overload]


async def get_tenant_by_slug(session: AsyncSession, slug: str) -> Optional[Tenant]:
    """Loads a tenant by its unique slug."""
    return (await session.exec(select(Tenant).where(Tenant.slug == slug))).scalars().first()  # type: ignore[call-overload]


async def require_tenant(session: AsyncSession, slug: str) -> Tenant:
    """Loads a tenant by slug or raises `TenantGuardError`."""
    tenant = await get_tenant_by_slug(session, slug)
    if tenant is None:
        raise TenantGuardError(f"Tenant '{slug}' does not exist.")
    return tenant


async def lock_tenant_row(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """`SELECT FOR UPDATE` on the tenant row, serialising with concurrent settings saves."""
    stmt = select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
    await session.exec(stmt)  # type: ignore[call-overload]


async def count_matching_rows(session: AsyncSession, ctx: DeleteContext) -> Dict[str, int]:
    """Row count per operational table for the rows `ctx` would delete."""
    counts: Dict[str, int] = {}
    for step in OPERATIONAL_DELETE_STEPS:
        stmt = select(func.count()).select_from(step.model).where(step.where(ctx))
        counts[step.table] = int((await session.exec(stmt)).scalar_one())  # type: ignore[call-overload]
    return counts


async def count_tenant_users(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Number of user rows in the tenant."""
    stmt = select(func.count()).select_from(User).where(User.tenant_id == tenant_id)
    return int((await session.exec(stmt)).scalar_one())  # type: ignore[call-overload]


async def collect_tenant_counts(session: AsyncSession, tenant_id: uuid.UUID) -> Dict[str, int]:
    """Inventory: every operational table plus `user`, for the whole tenant."""
    counts = await count_matching_rows(session, full_tenant_context(tenant_id))
    counts[USER_TABLE] = await count_tenant_users(session, tenant_id)
    return counts


async def collect_other_tenant_counts(
    session: AsyncSession, tenant_id: uuid.UUID
) -> Dict[str, int]:
    """
    Row counts of every operational table, `user` and `tenant` OUTSIDE the given tenant.
    Compared before and after a wipe to prove no other tenant was touched.
    """
    ctx = full_tenant_context(tenant_id)
    counts: Dict[str, int] = {}
    for step in OPERATIONAL_DELETE_STEPS:
        stmt = select(func.count()).select_from(step.model).where(not_(step.where(ctx)))
        counts[step.table] = int((await session.exec(stmt)).scalar_one())  # type: ignore[call-overload]
    users_stmt = select(func.count()).select_from(User).where(User.tenant_id != tenant_id)
    counts[USER_TABLE] = int((await session.exec(users_stmt)).scalar_one())  # type: ignore[call-overload]
    tenants_stmt = select(func.count()).select_from(Tenant).where(Tenant.id != tenant_id)
    counts[TENANT_TABLE] = int((await session.exec(tenants_stmt)).scalar_one())  # type: ignore[call-overload]
    return counts


async def delete_tenant_operational_rows(
    session: AsyncSession, ctx: DeleteContext
) -> Dict[str, int]:
    """
    Runs every `OPERATIONAL_DELETE_STEPS` DELETE in order and returns the rowcount per table.
    Does not commit.
    """
    deleted: Dict[str, int] = {}
    for step in OPERATIONAL_DELETE_STEPS:
        stmt = (
            delete(step.model)
            .where(step.where(ctx))
            .execution_options(synchronize_session=False)
        )
        result = await session.exec(stmt)  # type: ignore[call-overload]
        deleted[step.table] = int(result.rowcount or 0)
    return deleted


async def find_tenant_users_by_email(
    session: AsyncSession, tenant_id: uuid.UUID, emails: Sequence[str]
) -> Dict[str, User]:
    """Tenant users whose email is in `emails`, keyed by email."""
    if not emails:
        return {}
    stmt = select(User).where(User.tenant_id == tenant_id, col(User.email).in_(list(emails)))
    users = (await session.exec(stmt)).scalars().all()  # type: ignore[call-overload]
    return {user.email: user for user in users}


async def list_tenant_users(session: AsyncSession, tenant_id: uuid.UUID) -> List[User]:
    """Every user row of the tenant, ordered by email."""
    stmt = select(User).where(User.tenant_id == tenant_id).order_by(User.email)
    return list((await session.exec(stmt)).scalars().all())  # type: ignore[call-overload]


async def delete_tenant_users(
    session: AsyncSession, tenant_id: uuid.UUID, user_ids: FrozenSet[uuid.UUID]
) -> int:
    """Deletes the given users, always constrained to the tenant. Run after the operational steps."""
    if not user_ids:
        return 0
    stmt = (
        delete(User)
        .where(User.tenant_id == tenant_id, col(User.id).in_(list(user_ids)))
        .execution_options(synchronize_session=False)
    )
    result = await session.exec(stmt)  # type: ignore[call-overload]
    return int(result.rowcount or 0)


async def count_references_to_users(
    session: AsyncSession, user_ids: FrozenSet[uuid.UUID]
) -> Dict[str, int]:
    """
    Rows in ANY tenant that still point at the given user ids through columns WITHOUT a foreign key
    (so Postgres would not stop a dangling reference).
    """
    if not user_ids:
        return {}
    ids = list(user_ids)
    counts: Dict[str, int] = {}
    for model, column_name in UNCONSTRAINED_USER_REFERENCES:
        column = getattr(model, column_name)
        stmt = select(func.count()).select_from(model).where(col(column).in_(ids))
        label = f"{model.__tablename__}.{column_name}"  # type: ignore[attr-defined]
        counts[label] = int((await session.exec(stmt)).scalar_one())  # type: ignore[call-overload]
    return counts


async def next_gst_serials(session: AsyncSession, tenant: Tenant) -> Dict[str, int]:
    """
    Next serial the live allocator would hand out for each GST series (INVOICE, CREDIT_NOTE,
    DEBIT_NOTE) in today's Indian financial year, using the application's own repository code.
    """
    financial_year = indian_financial_year_label(datetime.now(IST).date())
    repo = DelhiveryModulesRepository(session)
    serials: Dict[str, int] = {}
    for note_type in InvoiceNoteType:
        prefix = document_number_prefix(tenant, financial_year, note_type.value)
        serials[prefix] = await repo.next_document_serial(tenant.id, prefix)
    return serials


# ---------------------------------------------------------------------------
# Ownership check (wipe safety): who created each row about to be deleted
# ---------------------------------------------------------------------------


def _not_in_actors(column: Any, actor_ids: FrozenSet[uuid.UUID]) -> ColumnElement[bool]:
    """True for rows whose actor column is NULL or not one of `actor_ids` (NULL counts as foreign)."""
    return or_(col(column).is_(None), not_(col(column).in_(list(actor_ids))))


def _foreign_manifests(actor_ids: FrozenSet[uuid.UUID]) -> ColumnElement[bool]:
    """Manifests have no creator column; their pickup location's owner is the actor."""
    foreign_locations = select(Address.id).where(_not_in_actors(Address.user_id, actor_ids))
    return col(Manifest.pickup_address_id).in_(foreign_locations)


ACTOR_COLUMNS: Mapping[Type[SQLModel], str] = {
    SupportTicketMessage: "sender_user_id",
    SupportTicket: "user_id",
    WeightDispute: "merchant_user_id",
    CodRemittance: "merchant_user_id",
    ShipmentChargeAdjustment: "actor_user_id",
    ShipmentMeasurement: "measured_by_user_id",
    BillingInvoice: "merchant_user_id",
    WalletTransaction: "user_id",
    UserWallet: "user_id",
    ShipmentActivity: "user_id",
    PickupRequest: "created_by_user_id",
    Address: "user_id",
    TenantSettingsHistory: "changed_by_user_id",
    IdempotencyKey: "user_id",
}
"""Per operational model: the column naming the user who created / owns the row."""

DERIVED_FROM_PICKUPS: FrozenSet[Type[SQLModel]] = frozenset({PackageDetails, PaymentDetails, PickupDocument})
"""Child rows with no actor of their own: they belong to whoever created the parent shipment."""


def foreign_actor_clause(
    model: Type[SQLModel], actor_ids: FrozenSet[uuid.UUID]
) -> Optional[ColumnElement[bool]]:
    """
    Clause selecting rows of `model` NOT created by `actor_ids`; None for child tables whose
    actor is their parent shipment (`DERIVED_FROM_PICKUPS`).
    """
    if model is Manifest:
        return _foreign_manifests(actor_ids)
    column_name = ACTOR_COLUMNS.get(model)
    if column_name is None:
        return None
    return _not_in_actors(getattr(model, column_name), actor_ids)


async def count_foreign_actor_rows(
    session: AsyncSession, ctx: DeleteContext, actor_ids: FrozenSet[uuid.UUID]
) -> Dict[str, int]:
    """
    For every row `ctx` would delete, counts those NOT created by `actor_ids` (e.g. a real
    shipment booked by the live owner after the golden runs). The live wipe aborts unless every
    count is 0, so it can only ever delete rows that belong to the test identities.
    """
    counts: Dict[str, int] = {}
    for step in OPERATIONAL_DELETE_STEPS:
        clause = foreign_actor_clause(step.model, actor_ids)
        if clause is None:
            continue
        stmt = select(func.count()).select_from(step.model).where(step.where(ctx), clause)
        counts[step.table] = int((await session.exec(stmt)).scalar_one())  # type: ignore[call-overload]
    return counts


def assert_no_foreign_rows(foreign_counts: Mapping[str, int]) -> None:
    """
    Raises:
        TenantIntegrityError: when any row about to be deleted was created by someone else.
    """
    foreign = {table: rows for table, rows in foreign_counts.items() if rows}
    if foreign:
        raise TenantIntegrityError(
            f"Refusing to delete rows not created by the test identities: {foreign}"
        )


# ---------------------------------------------------------------------------
# Seed (idempotent upserts)
# ---------------------------------------------------------------------------


class SeedAction(str, Enum):
    """What the seed did with one entity."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    UNCHANGED = "UNCHANGED"
    KEEP = "KEEP"


@dataclass
class SeedReport:
    """Human-readable action log plus the ids the caller needs."""

    tenant_id: Optional[uuid.UUID] = None
    user_ids_by_email: Dict[str, uuid.UUID] = field(default_factory=dict)
    actions: List[str] = field(default_factory=list)
    auth_users_to_create: List[str] = field(default_factory=list)

    def record(self, action: SeedAction, entity: str, detail: str = "") -> None:
        """Appends one log line."""
        suffix = f" ({detail})" if detail else ""
        self.actions.append(f"{action.value:<9} {entity}{suffix}")


async def _upsert_test_tenant(
    session: AsyncSession, fixtures: SeedFixtures, refresh_settings: bool, report: SeedReport
) -> Tenant:
    """Creates the test tenant, or verifies the existing row is a marked test tenant."""
    tenant = await get_tenant_by_slug(session, fixtures.slug)
    if tenant is None:
        tenant = Tenant(slug=fixtures.slug, name=fixtures.name, settings=copy.deepcopy(fixtures.settings))
        session.add(tenant)
        await session.flush()
        report.record(SeedAction.CREATE, f"tenant {fixtures.slug}", f"id {tenant.id}")
        return tenant
    assert_test_tenant_marked(tenant)
    if refresh_settings:
        tenant.settings = copy.deepcopy(fixtures.settings)
        tenant.name = fixtures.name
        session.add(tenant)
        report.record(SeedAction.UPDATE, f"tenant {fixtures.slug}", "settings restored from fixture")
    else:
        report.record(SeedAction.UNCHANGED, f"tenant {fixtures.slug}", f"id {tenant.id}")
    return tenant


async def _resolve_auth_user_id(
    repo: TenantRepository,
    account: AccountSpec,
    password: Optional[str],
    allow_auth_create: bool,
    report: SeedReport,
) -> str:
    """
    Returns the global `auth.users.id` for the account, creating it (flush only, inside the caller's
    transaction) when missing and allowed. Existing auth rows are never modified.
    """
    existing = await repo.get_auth_user_by_email(account.email)
    if existing is not None:
        return str(existing["id"])
    if not allow_auth_create or not password:
        raise FixtureError(
            f"auth.users has no row for {account.email}; run the seed with a password to create it."
        )
    created_id = await repo.create_auth_user_with_password(
        email=account.email, password=password, full_name=account.full_name
    )
    if created_id is None:
        raise FixtureError(f"Could not create auth user {account.email} (concurrent insert?).")
    report.auth_users_to_create.append(account.email)
    report.record(SeedAction.CREATE, f"auth.users {account.email}", f"id {created_id}")
    return created_id


def _apply_account_fields(user: User, account: AccountSpec, auth_id: str) -> List[str]:
    """Sets canonical fields on `user`; returns the names of the fields that changed."""
    desired: Dict[str, Any] = {
        "supabase_user_id": auth_id,
        "role": account.role,
        "service_scope": account.service_scope,
        "full_name": account.full_name,
        "phone": account.phone,
        "is_active": True,
    }
    changed: List[str] = []
    for attr, value in desired.items():
        if getattr(user, attr) != value:
            setattr(user, attr, value)
            changed.append(attr)
    return changed


async def _upsert_account(
    session: AsyncSession, tenant: Tenant, account: AccountSpec, auth_id: str, report: SeedReport
) -> User:
    """Creates or restores one canonical user row, keyed by (email, tenant_id)."""
    found = await find_tenant_users_by_email(session, tenant.id, [account.email])
    user = found.get(account.email)
    if user is None:
        user = User(email=account.email, tenant_id=tenant.id, supabase_user_id=auth_id)
        _apply_account_fields(user, account, auth_id)
        session.add(user)
        await session.flush()
        report.record(
            SeedAction.CREATE,
            f"user {account.email}",
            f"{account.role.value}/{account.service_scope.value}",
        )
        return user
    changed = _apply_account_fields(user, account, auth_id)
    if changed:
        session.add(user)
        await session.flush()
        report.record(SeedAction.UPDATE, f"user {account.email}", ", ".join(changed))
    else:
        report.record(SeedAction.UNCHANGED, f"user {account.email}")
    return user


def _address_signature(spec: AddressSpec) -> str:
    """Same signature the address book service computes, so dedupe lookups match the app."""
    return generate_address_signature(
        spec.name, spec.phone, spec.pincode, spec.address_line1, spec.address_line2
    )


async def _ensure_saved_address(
    session: AsyncSession, tenant_id: uuid.UUID, user: User, spec: AddressSpec, report: SeedReport
) -> None:
    """Inserts the saved address unless an identical saved row already exists for that user."""
    signature = _address_signature(spec)
    stmt = select(func.count()).select_from(Address).where(
        Address.tenant_id == tenant_id,
        Address.user_id == user.id,
        Address.address_signature == signature,
        col(Address.is_saved).is_(True),
    )
    if int((await session.exec(stmt)).scalar_one()) > 0:  # type: ignore[call-overload]
        report.record(SeedAction.UNCHANGED, f"address '{spec.name}'", spec.owner_email)
        return
    session.add(
        Address(
            tenant_id=tenant_id,
            user_id=user.id,
            category=spec.category,
            scope=spec.scope,
            alternate_phone=spec.alternate_phone,
            gstin=spec.gstin,
            address_signature=signature,
            is_saved=True,
            name=spec.name,
            phone=spec.phone,
            email=spec.email,
            company_name=spec.company_name,
            address_line1=spec.address_line1,
            address_line2=spec.address_line2,
            landmark=spec.landmark,
            city=spec.city,
            state=spec.state,
            pincode=spec.pincode,
            country=spec.country,
        )
    )
    await session.flush()
    report.record(
        SeedAction.CREATE, f"address '{spec.name}'", f"{spec.owner_email}, {spec.scope.value}"
    )


async def _ensure_zero_wallet(
    session: AsyncSession, tenant_id: uuid.UUID, user: User, report: SeedReport
) -> None:
    """Creates a ₹0.00 wallet when missing; never overwrites an existing balance."""
    stmt = select(UserWallet).where(UserWallet.tenant_id == tenant_id, UserWallet.user_id == user.id)
    wallet = (await session.exec(stmt)).scalars().first()  # type: ignore[call-overload]
    if wallet is None:
        session.add(UserWallet(tenant_id=tenant_id, user_id=user.id, balance=ZERO_BALANCE))
        await session.flush()
        report.record(SeedAction.CREATE, f"wallet {user.email}", "balance 0.00")
        return
    if float(wallet.balance or 0.0) == ZERO_BALANCE:
        report.record(SeedAction.UNCHANGED, f"wallet {user.email}", "balance 0.00")
    else:
        report.record(
            SeedAction.KEEP,
            f"wallet {user.email}",
            f"balance {float(wallet.balance):.2f}; reset_test_tenant() clears it",
        )


def _merge_b2b_access(
    tenant: Tenant, fixtures: SeedFixtures, user_ids_by_email: Mapping[str, uuid.UUID]
) -> None:
    """Writes the APPROVED B2B entries of the canonical accounts into `tenant.settings`."""
    entries = build_b2b_access_requests(
        fixtures.accounts, user_ids_by_email, fixtures.owner.email, datetime.now(timezone.utc)
    )
    updated: Dict[str, Any] = copy.deepcopy(dict(tenant.settings or {}))
    current: Dict[str, Any] = dict(updated.get(SETTINGS_B2B_ACCESS_KEY) or {})
    current.update(entries)
    updated[SETTINGS_B2B_ACCESS_KEY] = current
    tenant.settings = updated  # new object, so SQLAlchemy sees the JSON change


async def seed_test_tenant(
    session: AsyncSession,
    fixtures: SeedFixtures,
    *,
    password: Optional[str],
    allow_auth_create: bool,
    refresh_settings: bool,
) -> SeedReport:
    """
    Idempotent seed of the test tenant. Order matters: tenant, then the OWNER, then the other
    accounts (JIT provisioning would make whoever comes first the owner), then saved addresses,
    zero wallets and the B2B access entries. Does not commit.

    Args:
        session: Open session; the caller commits (execute) or rolls back (dry run).
        fixtures: Parsed frozen fixtures.
        password: Password for auth users that must be created (e.g. b2bonboarding@).
        allow_auth_create: False for resets (auth identities must already exist).
        refresh_settings: Replace an existing tenant's settings with the fixture copy.
    """
    assert_test_tenant_slug(fixtures.slug)
    report = SeedReport()
    tenant = await _upsert_test_tenant(session, fixtures, refresh_settings, report)
    report.tenant_id = tenant.id
    repo = TenantRepository(session)
    users_by_email: Dict[str, User] = {}
    for account in fixtures.accounts:  # owner first, enforced by parse_seed_fixtures
        auth_id = await _resolve_auth_user_id(repo, account, password, allow_auth_create, report)
        users_by_email[account.email] = await _upsert_account(
            session, tenant, account, auth_id, report
        )
    report.user_ids_by_email = {email: user.id for email, user in users_by_email.items()}
    for spec in fixtures.addresses:
        await _ensure_saved_address(session, tenant.id, users_by_email[spec.owner_email], spec, report)
    for account in fixtures.accounts:
        if account.needs_wallet:
            await _ensure_zero_wallet(session, tenant.id, users_by_email[account.email], report)
    _merge_b2b_access(tenant, fixtures, report.user_ids_by_email)
    session.add(tenant)
    await session.flush()
    report.record(SeedAction.UPDATE, f"tenant {fixtures.slug}", f"{SETTINGS_B2B_ACCESS_KEY} merged")
    return report


async def verify_seeded_tenant(session: AsyncSession, fixtures: SeedFixtures) -> List[str]:
    """
    Read-only post-seed checks; returns a list of problems (empty list = healthy).
    Checks: marker, GST prefix, every canonical user present with exactly one owner, saved
    addresses, and no wallet with a non-zero balance.
    """
    problems: List[str] = []
    tenant = await get_tenant_by_slug(session, fixtures.slug)
    if tenant is None:
        return [f"tenant {fixtures.slug} missing"]
    if not is_test_tenant(tenant):
        problems.append("tenant not marked environment=test")
    if tenant_document_prefix(tenant) in LIVE_INVOICE_PREFIXES:
        problems.append(f"GST prefix {tenant_document_prefix(tenant)} collides with live")
    users = await list_tenant_users(session, tenant.id)
    emails = {user.email for user in users}
    missing = fixtures.canonical_emails - emails
    if missing:
        problems.append(f"missing users: {sorted(missing)}")
    owners = [user.email for user in users if user.role == UserRole.owner]
    if owners != [fixtures.owner.email]:
        problems.append(f"owners are {owners}, expected [{fixtures.owner.email}]")
    saved_stmt = select(func.count()).select_from(Address).where(
        Address.tenant_id == tenant.id, col(Address.is_saved).is_(True)
    )
    saved = int((await session.exec(saved_stmt)).scalar_one())  # type: ignore[call-overload]
    if saved < len(fixtures.addresses):
        problems.append(f"saved addresses {saved} < {len(fixtures.addresses)}")
    nonzero_stmt = select(func.count()).select_from(UserWallet).where(
        UserWallet.tenant_id == tenant.id, UserWallet.balance != ZERO_BALANCE
    )
    nonzero = int((await session.exec(nonzero_stmt)).scalar_one())  # type: ignore[call-overload]
    if nonzero:
        problems.append(f"{nonzero} wallet(s) with a non-zero balance")
    return problems


# ---------------------------------------------------------------------------
# Reset (called by the golden session fixture)
# ---------------------------------------------------------------------------


async def _non_canonical_user_ids(
    session: AsyncSession, tenant_id: uuid.UUID, canonical_emails: FrozenSet[str]
) -> FrozenSet[uuid.UUID]:
    """Ids of users in the tenant that are not canonical accounts (e.g. JIT signups during a run)."""
    stmt = select(User.id).where(
        User.tenant_id == tenant_id, not_(col(User.email).in_(list(canonical_emails)))
    )
    return frozenset((await session.exec(stmt)).scalars().all())  # type: ignore[call-overload]


async def reset_test_tenant(
    session: AsyncSession,
    slug: str,
    *,
    commit: bool = True,
    fixtures_dir: Path = FIXTURES_DIR,
) -> Dict[str, int]:
    """
    Puts the test tenant back to its canonical state, once per golden pytest session.

    Steps: slug guard, DB marker guard, row lock, every operational DELETE (all addresses,
    settings history included), delete non-canonical users, then re-seed (settings restored from
    the fixture, canonical users restored, 3 saved addresses, wallets at 0). Commits when `commit`.

    Returns:
        Rows deleted per table, plus `user` (non-canonical users removed).

    Raises:
        TenantGuardError: slug not allow-listed, tenant missing or not marked as a test tenant.
        FixtureError: fixtures invalid, or a canonical auth identity is missing (run the seed).
        TenantIntegrityError: post-reset invariants failed (rolled back, nothing committed).
    """
    assert_test_tenant_slug(slug)
    fixtures = load_seed_fixtures(fixtures_dir)
    if fixtures.slug != slug:
        raise TenantGuardError(f"Fixtures describe '{fixtures.slug}', not '{slug}'.")
    tenant = await require_tenant(session, slug)
    assert_test_tenant_marked(tenant)
    await apply_transaction_timeouts(session)
    await lock_tenant_row(session, tenant.id)
    deleted = await delete_tenant_operational_rows(session, full_tenant_context(tenant.id))
    extras = await _non_canonical_user_ids(session, tenant.id, fixtures.canonical_emails)
    deleted[USER_TABLE] = await delete_tenant_users(session, tenant.id, extras)
    await seed_test_tenant(
        session, fixtures, password=None, allow_auth_create=False, refresh_settings=True
    )
    try:
        await assert_reset_invariants(session, tenant, fixtures)
    except TenantIntegrityError:
        await session.rollback()
        raise
    if commit:
        await session.commit()
    return deleted


def expected_reset_counts(fixtures: SeedFixtures) -> Dict[str, int]:
    """Row counts a freshly reset test tenant must have: only users, wallets and saved addresses."""
    expected = {table: 0 for table in OPERATIONAL_TABLES}
    expected[Address.__tablename__] = len(fixtures.addresses)  # type: ignore[attr-defined]
    expected[UserWallet.__tablename__] = sum(1 for a in fixtures.accounts if a.needs_wallet)  # type: ignore[attr-defined]
    expected[USER_TABLE] = len(fixtures.accounts)
    return expected


async def assert_reset_invariants(
    session: AsyncSession, tenant: Tenant, fixtures: SeedFixtures
) -> None:
    """
    Post-reset checks run before COMMIT (testenv.md section 4.3 step 7): exact row counts,
    verify_seeded_tenant() clean (marker, prefix, owner, wallets at 0), next GST serial = 1.

    Raises:
        TenantIntegrityError: on any mismatch.
    """
    counts = await collect_tenant_counts(session, tenant.id)
    expected = expected_reset_counts(fixtures)
    mismatched = {t: (counts.get(t), rows) for t, rows in expected.items() if counts.get(t) != rows}
    problems: List[str] = [f"row counts (actual, expected): {mismatched}"] if mismatched else []
    problems.extend(await verify_seeded_tenant(session, fixtures))
    serials = await next_gst_serials(session, tenant)
    if any(serial != FIRST_DOCUMENT_SERIAL for serial in serials.values()):
        problems.append(f"GST serials not restarted: {serials}")
    if problems:
        raise TenantIntegrityError("Reset invariants failed: " + "; ".join(problems))
