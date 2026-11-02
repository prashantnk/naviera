"""
Unit tests for Phase A data tooling (plan items A4, A5, A6). Pure Python: no database access.

Run from `naviera/backend`:
    poetry run python -m pytest --noconftest scripts/tests/test_tenant_data_core.py -q

`--noconftest` skips the shared conftest, whose session fixtures open DB connections these tests
do not need.

Covers: the test-tenant slug guard and DB marker guard, the GST invoice-prefix override (the
`LOGI` collision trap), FK-safe delete order and table coverage checked against the SQLModel
metadata, fixture safety rules, B2B access helpers, and the live-wipe guards.
"""

import copy
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

import pytest
from sqlalchemy import Table
from sqlalchemy.dialects import postgresql
from sqlmodel import SQLModel

from app.models.pickups import PickupRequest
from app.models.tenants import ServiceScope, Tenant, UserRole
from app.services.delhivery_modules import tenant_document_prefix
from scripts.prepare_logismart_handover import DEFAULT_WALLET_CONFIG, execute_confirmed
from scripts.tenant_data_core import (
    ALLOWED_TEST_SLUGS,
    DERIVED_FROM_PICKUPS,
    LIVE_INVOICE_PREFIXES,
    OPERATIONAL_DELETE_STEPS,
    OPERATIONAL_TABLES,
    PROTECTED_LIVE_EMAILS,
    SETTINGS_B2B_ACCESS_KEY,
    TENANT_TABLE,
    USER_TABLE,
    AccountSpec,
    FixtureError,
    TenantGuardError,
    TenantIntegrityError,
    apply_invoice_prefix,
    assert_no_foreign_rows,
    assert_seedable_email,
    assert_test_tenant_marked,
    assert_test_tenant_slug,
    build_b2b_access_requests,
    expected_reset_counts,
    foreign_actor_clause,
    load_seed_fixtures,
    parse_seed_fixtures,
    prune_b2b_access_requests,
    validate_test_settings,
)
from scripts.wipe_tenant_test_data import (
    LIVE_OWNER_EMAIL,
    LIVE_TEST_ACCOUNT_EMAILS,
    BackupEntry,
    BackupManifest,
    assert_counts_match_backup,
    assert_wipe_allowed,
    build_backup_queries,
)

TEST_SLUG = "logismart-test"
LIVE_SLUG = "logismart"
TEST_PREFIX = "LTST"
LIVE_PREFIX = "LOGI"
MIN_FK_EDGES_BETWEEN_STEPS = 14
"""FK edges across operational steps (including repricing -> invoices/wallet_txns/pickups)."""
NON_OPERATIONAL_TABLES = frozenset(
    {
        TENANT_TABLE,
        USER_TABLE,
        "alembic_version",
        "delhivery_price_cache",
        "prime_zones",
        "prime_zone_pincodes",
        "prime_lanes",
    }
)
PARENT_TABLES_OF_OPERATIONAL_DATA = frozenset(
    {TENANT_TABLE, "pickups", "support_tickets", "user_wallets", "manifests", "addresses"}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _minimal_settings(prefix: str = TEST_PREFIX) -> Dict[str, Any]:
    """Smallest valid test-tenant settings."""
    return {"environment": "test", "company": {"invoice_prefix": prefix}}


def _account(email: str, role: str = "customer", scope: str = "B2C", owner: bool = False) -> Dict[str, Any]:
    """One raw account row as found in the accounts fixture."""
    return {
        "email": email,
        "role": role,
        "service_scope": scope,
        "full_name": None,
        "phone": None,
        "is_owner": owner,
        "needs_wallet": True,
    }


def _accounts_doc(accounts: List[Dict[str, Any]], slug: str = TEST_SLUG) -> Dict[str, Any]:
    """Raw accounts fixture document."""
    return {"tenant": {"slug": slug, "name": "Test"}, "accounts": accounts}


def _owner_row() -> Dict[str, Any]:
    return _account("owner@logismart.in", role="owner", scope="BOTH", owner=True)


def _tables_by_name() -> Dict[str, Table]:
    return dict(SQLModel.metadata.tables)


def _fk_parents(table: Table) -> Set[str]:
    """Names of the tables `table` references through foreign keys (self references ignored)."""
    return {fk.column.table.name for fk in table.foreign_keys if fk.column.table.name != table.name}


# ---------------------------------------------------------------------------
# Slug and marker guards
# ---------------------------------------------------------------------------


def test_slug_guard_accepts_the_test_tenant() -> None:
    assert_test_tenant_slug(TEST_SLUG)
    assert TEST_SLUG in ALLOWED_TEST_SLUGS


@pytest.mark.parametrize("slug", [LIVE_SLUG, "naviera", "", "logismart-test2", "LOGISMART-TEST", " logismart-test"])
def test_slug_guard_refuses_everything_else(slug: str) -> None:
    with pytest.raises(TenantGuardError):
        assert_test_tenant_slug(slug)


def test_marker_guard_requires_environment_test() -> None:
    assert_test_tenant_marked(Tenant(slug=TEST_SLUG, name="t", settings={"environment": "test"}))
    with pytest.raises(TenantGuardError):
        assert_test_tenant_marked(Tenant(slug=TEST_SLUG, name="t", settings={}))
    with pytest.raises(TenantGuardError):
        assert_test_tenant_marked(Tenant(slug=LIVE_SLUG, name="t", settings={"environment": "test"}))


# ---------------------------------------------------------------------------
# GST prefix override
# ---------------------------------------------------------------------------


def test_slug_fallback_collides_with_live_prefix() -> None:
    """The trap: without an override both slugs print the same GST series."""
    assert tenant_document_prefix(Tenant(slug=TEST_SLUG, name="t", settings={})) == LIVE_PREFIX
    assert tenant_document_prefix(Tenant(slug=LIVE_SLUG, name="t", settings={})) == LIVE_PREFIX


def test_prefix_override_gives_the_test_series() -> None:
    settings_obj = apply_invoice_prefix({"company": {"legal_name": "X"}}, TEST_PREFIX)
    assert tenant_document_prefix(Tenant(slug=TEST_SLUG, name="t", settings=settings_obj)) == TEST_PREFIX
    assert settings_obj["company"]["legal_name"] == "X"


def test_apply_invoice_prefix_does_not_mutate_input_and_creates_company() -> None:
    original: Dict[str, Any] = {"brand": {"primary_color": "#dc2626"}}
    snapshot = copy.deepcopy(original)
    updated = apply_invoice_prefix(original, LIVE_PREFIX)
    assert original == snapshot
    assert updated["company"]["invoice_prefix"] == LIVE_PREFIX


def test_validate_test_settings_rules() -> None:
    validate_test_settings(_minimal_settings())
    with pytest.raises(FixtureError):
        validate_test_settings(_minimal_settings(prefix=LIVE_PREFIX))
    with pytest.raises(FixtureError):
        validate_test_settings({"company": {"invoice_prefix": TEST_PREFIX}})
    with pytest.raises(FixtureError):
        validate_test_settings({**_minimal_settings(), SETTINGS_B2B_ACCESS_KEY: {}})
    with pytest.raises(FixtureError):
        validate_test_settings({"environment": "test", "company": {}})


def test_real_fixture_files_pass_every_rule() -> None:
    """The harness-owned fixtures load, put the owner first and never use a live prefix."""
    fixtures = load_seed_fixtures()
    assert fixtures.slug == TEST_SLUG
    assert fixtures.owner.role == UserRole.owner
    assert tenant_document_prefix(Tenant(slug=fixtures.slug, name="t", settings=fixtures.settings)) not in LIVE_INVOICE_PREFIXES
    assert not (fixtures.canonical_emails & PROTECTED_LIVE_EMAILS)
    assert LIVE_TEST_ACCOUNT_EMAILS <= fixtures.canonical_emails
    assert len(fixtures.addresses) == 3


# ---------------------------------------------------------------------------
# Fixture safety rules
# ---------------------------------------------------------------------------


def test_owner_must_be_first() -> None:
    accounts = [_account("customerb2c@logismart.in"), _owner_row()]
    with pytest.raises(FixtureError):
        parse_seed_fixtures(_minimal_settings(), _accounts_doc(accounts), [])


def test_exactly_one_owner() -> None:
    accounts = [_owner_row(), _account("admin@logismart.in", role="owner", scope="BOTH", owner=True)]
    with pytest.raises(FixtureError):
        parse_seed_fixtures(_minimal_settings(), _accounts_doc(accounts), [])


@pytest.mark.parametrize("email", [LIVE_OWNER_EMAIL, "someone@gmail.com", "Owner@logismart.in"])
def test_unsafe_emails_are_refused(email: str) -> None:
    with pytest.raises(FixtureError):
        assert_seedable_email(email)


def test_fixture_for_live_slug_is_refused() -> None:
    with pytest.raises(TenantGuardError):
        parse_seed_fixtures(_minimal_settings(), _accounts_doc([_owner_row()], slug=LIVE_SLUG), [])


def test_address_owner_must_be_canonical() -> None:
    address = {
        "owner_email": "ghost@logismart.in",
        "name": "n",
        "phone": "9000000000",
        "address_line1": "l1",
        "city": "c",
        "state": "s",
        "pincode": "122001",
        "country": "IN",
        "category": "WAREHOUSE",
        "scope": "PRIVATE",
    }
    with pytest.raises(FixtureError):
        parse_seed_fixtures(_minimal_settings(), _accounts_doc([_owner_row()]), [address])


# ---------------------------------------------------------------------------
# B2B access helpers
# ---------------------------------------------------------------------------


def test_b2b_access_only_for_b2b_enabled_scopes() -> None:
    specs = [
        AccountSpec("owner@logismart.in", UserRole.owner, ServiceScope.BOTH, None, None, True, True),
        AccountSpec("customerb2c@logismart.in", UserRole.customer, ServiceScope.B2C, None, None, False, True),
        AccountSpec("customerb2b@logismart.in", UserRole.customer, ServiceScope.B2B, None, None, False, True),
    ]
    ids = {spec.email: uuid.uuid4() for spec in specs}
    entries = build_b2b_access_requests(specs, ids, "owner@logismart.in", datetime.now(timezone.utc))
    assert set(entries) == {str(ids["owner@logismart.in"]), str(ids["customerb2b@logismart.in"])}
    assert all(entry["status"] == "APPROVED" for entry in entries.values())


def test_prune_drops_stale_and_excluded_keys() -> None:
    keep, drop = uuid.uuid4(), uuid.uuid4()
    settings_obj = {SETTINGS_B2B_ACCESS_KEY: {str(keep): {"status": "APPROVED"}, str(drop): {}, "stale": {}}}
    pruned = prune_b2b_access_requests(settings_obj, frozenset({keep}))
    assert list(pruned[SETTINGS_B2B_ACCESS_KEY]) == [str(keep)]
    assert len(settings_obj[SETTINGS_B2B_ACCESS_KEY]) == 3


# ---------------------------------------------------------------------------
# FK order and coverage (checked against the SQLModel metadata)
# ---------------------------------------------------------------------------


def test_every_child_is_deleted_before_its_parent() -> None:
    tables = _tables_by_name()
    position = {name: index for index, name in enumerate(OPERATIONAL_TABLES)}
    edges_checked = 0
    for child in OPERATIONAL_TABLES:
        for parent in _fk_parents(tables[child]):
            if parent in position:
                edges_checked += 1
                assert position[child] < position[parent], f"{child} must be deleted before {parent}"
    assert edges_checked >= MIN_FK_EDGES_BETWEEN_STEPS


def test_users_and_tenant_are_never_in_the_operational_steps() -> None:
    assert USER_TABLE not in OPERATIONAL_TABLES
    assert TENANT_TABLE not in OPERATIONAL_TABLES
    assert len(set(OPERATIONAL_TABLES)) == len(OPERATIONAL_TABLES)


def test_every_tenant_owned_table_is_covered() -> None:
    """Every table holding tenant or operational data must appear in OPERATIONAL_DELETE_STEPS."""
    missing: List[str] = []
    for name, table in _tables_by_name().items():
        if name in NON_OPERATIONAL_TABLES or name in OPERATIONAL_TABLES:
            continue
        owned = "tenant_id" in table.columns or bool(_fk_parents(table) & PARENT_TABLES_OF_OPERATIONAL_DATA)
        if owned:
            missing.append(name)
    assert missing == [], f"Add these tables to OPERATIONAL_DELETE_STEPS: {missing}"


def test_repricing_and_idempotency_tables_are_ordered_before_parents() -> None:
    position = {name: index for index, name in enumerate(OPERATIONAL_TABLES)}
    assert "shipment_charge_adjustments" in position
    assert "shipment_measurements" in position
    assert "idempotency_keys" in position
    assert position["shipment_charge_adjustments"] < position["billing_invoices"]
    assert position["shipment_charge_adjustments"] < position["wallet_transactions"]
    assert position["shipment_charge_adjustments"] < position["pickups"]
    assert position["shipment_measurements"] < position["pickups"]


def test_step_where_clauses_compile_for_every_table() -> None:
    backup = build_backup_queries(uuid.uuid4())
    assert len(backup) == len(OPERATIONAL_DELETE_STEPS) + 3


# ---------------------------------------------------------------------------
# Live wipe guards and backup
# ---------------------------------------------------------------------------


def test_wipe_guard_allows_only_live_logismart_and_needs_confirmation() -> None:
    assert_wipe_allowed(LIVE_SLUG, execute=False, confirm_slug="")
    assert_wipe_allowed(LIVE_SLUG, execute=True, confirm_slug=LIVE_SLUG)
    for slug in (TEST_SLUG, "naviera"):
        with pytest.raises(TenantGuardError):
            assert_wipe_allowed(slug, execute=False, confirm_slug="")
    with pytest.raises(TenantGuardError):
        assert_wipe_allowed(LIVE_SLUG, execute=True, confirm_slug="")


def test_live_owner_is_never_deleted() -> None:
    assert LIVE_OWNER_EMAIL not in LIVE_TEST_ACCOUNT_EMAILS
    assert LIVE_OWNER_EMAIL in PROTECTED_LIVE_EMAILS
    assert len(LIVE_TEST_ACCOUNT_EMAILS) == 7


def test_backup_sql_has_literal_tenant_and_no_bind_markers() -> None:
    tenant_id = uuid.uuid4()
    for name, sql in build_backup_queries(tenant_id):
        assert str(tenant_id) in sql, name
        assert "%(" not in sql and "$1" not in sql, name


def test_backup_drift_aborts_the_wipe() -> None:
    manifest = BackupManifest("logismart", str(uuid.uuid4()), "now", "/tmp")
    manifest.entries.append(BackupEntry("pickups", "03_pickups.csv", 10, "x"))
    assert_counts_match_backup({"pickups": 10}, manifest)
    with pytest.raises(TenantIntegrityError):
        assert_counts_match_backup({"pickups": 11}, manifest)


# ---------------------------------------------------------------------------
# Ownership guard (S-1), reset invariants (S-2), handover confirmation (S-3)
# ---------------------------------------------------------------------------


def test_every_deleted_table_has_an_owner_check() -> None:
    """Each step is either actor-checked directly or is a child of an actor-checked shipment."""
    test_ids = frozenset({uuid.uuid4()})
    for step in OPERATIONAL_DELETE_STEPS:
        clause = foreign_actor_clause(step.model, test_ids)
        assert (clause is not None) != (step.model in DERIVED_FROM_PICKUPS), step.table


def test_foreign_clause_counts_null_and_other_actors_as_foreign() -> None:
    actor = uuid.uuid4()
    clause = foreign_actor_clause(PickupRequest, frozenset({actor}))
    sql = str(clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "created_by_user_id IS NULL" in sql
    assert "NOT IN" in sql and str(actor) in sql


def test_foreign_rows_abort_the_wipe() -> None:
    assert_no_foreign_rows({"pickups": 0, "wallet_transactions": 0})
    with pytest.raises(TenantIntegrityError):
        assert_no_foreign_rows({"pickups": 1, "wallet_transactions": 0})


def test_expected_reset_counts_match_the_fixtures() -> None:
    fixtures = load_seed_fixtures()
    expected = expected_reset_counts(fixtures)
    assert expected["addresses"] == len(fixtures.addresses) == 3
    assert expected["user_wallets"] == sum(1 for a in fixtures.accounts if a.needs_wallet)
    assert expected[USER_TABLE] == len(fixtures.accounts) == 8
    assert all(rows == 0 for table, rows in expected.items() if table not in {"addresses", "user_wallets", USER_TABLE})


def test_handover_execute_needs_confirmation_and_never_defaults_a_vpa() -> None:
    assert execute_confirmed("logismart", execute=False, confirm_slug="")
    assert execute_confirmed("logismart", execute=True, confirm_slug="logismart")
    assert not execute_confirmed("logismart", execute=True, confirm_slug="")
    assert "merchant_vpa" not in DEFAULT_WALLET_CONFIG
