"""
One-time wipe of golden-test data from the LIVE `logismart` tenant (plan item A6, decision D43 c).

DRY RUN BY DEFAULT. A dry run still:
  1. exports a CSV backup of every affected row (COPY in a REPEATABLE READ, READ ONLY snapshot)
     plus `manifest.json` with row counts and SHA-256 per file, under the git-ignored
     `llm_resources/.agents/backups/`;
  2. executes EVERY DELETE/UPDATE of the wipe inside one transaction, runs all verifications,
     and then ROLLS BACK, which proves the FK order and the checks on the real data.
`--execute --confirm-slug logismart` does the same and COMMITS. It needs the user's go-ahead #2.

Usage (from `naviera/backend`):
    poetry run python -m scripts.wipe_tenant_test_data --tenant logismart
    poetry run python -m scripts.wipe_tenant_test_data --tenant logismart --execute --confirm-slug logismart

Transaction order (testenv.md section 5.3, plus D43 c):
  guard       every row about to be deleted must have been created by one of the 7 test identities
              (`count_foreign_actor_rows`); otherwise abort, e.g. if the owner booked a real order
  steps 1-15  shared FK-ordered operational deletes (`tenant_data_core.OPERATIONAL_DELETE_STEPS`)
  step 16     settings: drop b2b_access_requests of deleted users / stale keys / the new owner's
              test request; pin company.invoice_prefix = "LOGI" (D45)
  step 17     promote prashantnk2001@gmail.com to owner / BOTH / active (BEFORE step 18)
  step 18     delete the 7 @logismart.in test users
  verify      zero rows left, exactly one user (the new owner), next GST serial = 1 for I/C/D,
              no dangling user references, other tenants' counts unchanged

Spring Boot mapping: one `@Transactional` service method; the dry run is the same method with a
forced `TransactionAspectSupport.currentTransactionStatus().setRollbackOnly()` at the end.
"""

import argparse
import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Sequence, Tuple

from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import AsyncSessionLocal, async_engine
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from scripts.tenant_data_core import (
    ALLOWED_TEST_SLUGS,
    BACKEND_ROOT,
    FIRST_DOCUMENT_SERIAL,
    OPERATIONAL_DELETE_STEPS,
    USER_TABLE,
    AddressPurge,
    DeleteContext,
    TenantGuardError,
    TenantIntegrityError,
    apply_invoice_prefix,
    apply_transaction_timeouts,
    assert_no_foreign_rows,
    collect_other_tenant_counts,
    collect_tenant_counts,
    count_foreign_actor_rows,
    count_matching_rows,
    count_references_to_users,
    delete_tenant_operational_rows,
    delete_tenant_users,
    find_tenant_users_by_email,
    full_tenant_context,
    list_tenant_users,
    lock_tenant_row,
    next_gst_serials,
    prune_b2b_access_requests,
    require_tenant,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WIPE_ALLOWED_SLUGS: FrozenSet[str] = frozenset({"logismart"})
"""Live tenants this one-time wipe may target. Test tenants use reset_test_tenant() instead."""

LIVE_TEST_ACCOUNT_EMAILS: FrozenSet[str] = frozenset(
    {
        "owner@logismart.in",
        "admin@logismart.in",
        "operations@logismart.in",
        "support@logismart.in",
        "readonly@logismart.in",
        "customerb2c@logismart.in",
        "customerb2b@logismart.in",
    }
)
"""The 7 golden-test identities removed from live (their auth.users rows stay for logismart-test)."""

LIVE_OWNER_EMAIL: str = "prashantnk2001@gmail.com"
"""D43 (c): the real human promoted to Owner of live logismart."""

LIVE_OWNER_ROLE: UserRole = UserRole.owner
LIVE_OWNER_SCOPE: ServiceScope = ServiceScope.BOTH
LIVE_INVOICE_PREFIX: str = "LOGI"
"""D45: pin the live GST series prefix so a slug rename can never start a new series."""

REPO_ROOT: Path = BACKEND_ROOT.parent
DEFAULT_BACKUP_ROOT: Path = REPO_ROOT / "llm_resources" / ".agents" / "backups"
MANIFEST_FILE_NAME: str = "manifest.json"
AUTH_USERS_BACKUP_NAME: str = "auth_users"
TENANT_BACKUP_NAME: str = "tenant"
SNAPSHOT_SQL = text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
COPY_STATUS_PREFIX: str = "COPY "
HASH_CHUNK_BYTES: int = 1 << 16
BANNER_WIDTH: int = 78
PITR_REMINDER: str = (
    "BEFORE --execute: confirm in the Supabase dashboard (Database > Backups) that the daily "
    "backup / PITR is ON and take a manual backup; the CSV export above is the second safety net."
)
EXIT_OK: int = 0
EXIT_FAILED: int = 1
EXIT_USAGE: int = 2


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def assert_wipe_allowed(slug: str, execute: bool, confirm_slug: str) -> None:
    """
    Refuses test tenants, any slug outside `WIPE_ALLOWED_SLUGS`, and an `--execute` whose
    `--confirm-slug` does not repeat the tenant slug.

    Raises:
        TenantGuardError: on any violation.
    """
    if slug in ALLOWED_TEST_SLUGS:
        raise TenantGuardError(f"'{slug}' is a test tenant: use reset_test_tenant(), not the wipe.")
    if slug not in WIPE_ALLOWED_SLUGS:
        raise TenantGuardError(f"The wipe only targets {sorted(WIPE_ALLOWED_SLUGS)}, not '{slug}'.")
    if execute and confirm_slug != slug:
        raise TenantGuardError("--execute requires --confirm-slug equal to --tenant.")


def assert_owner_not_dropped() -> None:
    """The promoted owner can never be in the delete list (configuration sanity check)."""
    if LIVE_OWNER_EMAIL in LIVE_TEST_ACCOUNT_EMAILS:
        raise TenantGuardError(f"{LIVE_OWNER_EMAIL} is listed both as owner and as a test account.")


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BackupEntry:
    """One exported CSV file."""

    name: str
    file: str
    rows: int
    sha256: str


@dataclass
class BackupManifest:
    """What was exported, so the execute run can prove nothing changed since."""

    tenant_slug: str
    tenant_id: str
    created_at: str
    directory: str
    entries: List[BackupEntry] = field(default_factory=list)

    def rows_by_name(self) -> Dict[str, int]:
        """Row count per exported table name."""
        return {entry.name: entry.rows for entry in self.entries}


def compile_literal_sql(stmt: Select) -> str:
    """
    Renders a SELECT with literal values (tenant UUIDs only) so it can run inside `COPY (<query>) TO STDOUT`.
    Values come from `uuid.UUID` objects, never from user input.
    """
    compiled = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    return str(compiled)


def build_backup_queries(tenant_id: uuid.UUID) -> List[Tuple[str, str]]:
    """
    (name, SQL) for every table to export: the tenant row, its users, every operational table
    (the same WHERE clauses the wipe deletes with, full-tenant scope), and the matching
    auth.users identities (no password hashes).
    """
    ctx = full_tenant_context(tenant_id)
    queries: List[Tuple[str, str]] = [
        (TENANT_BACKUP_NAME, compile_literal_sql(select(Tenant).where(Tenant.id == tenant_id))),
        (USER_TABLE, compile_literal_sql(select(User).where(User.tenant_id == tenant_id))),
    ]
    for step in OPERATIONAL_DELETE_STEPS:
        queries.append((step.table, compile_literal_sql(select(step.model).where(step.where(ctx)))))
    auth_sql = (
        "SELECT id, email, created_at, last_sign_in_at, email_confirmed_at FROM auth.users "
        f"WHERE id::text IN (SELECT supabase_user_id FROM \"user\" WHERE tenant_id = '{tenant_id}')"
    )
    queries.append((AUTH_USERS_BACKUP_NAME, auth_sql))
    return queries


def _sha256_of(path: Path) -> str:
    """SHA-256 hex digest of a file, read in chunks."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rows_from_copy_status(status: str) -> int:
    """Parses asyncpg's `COPY <n>` status string."""
    return int(status[len(COPY_STATUS_PREFIX):]) if status.startswith(COPY_STATUS_PREFIX) else -1


async def _copy_query_to_csv(session: AsyncSession, sql: str, path: Path) -> int:
    """Streams `COPY (sql) TO STDOUT` into `path` on the session's own connection/transaction."""
    connection = await session.connection()
    raw = await connection.get_raw_connection()
    driver = raw.driver_connection
    status = await driver.copy_from_query(sql, output=str(path), format="csv", header=True)
    return _rows_from_copy_status(str(status))


async def export_backup(tenant_slug: str, tenant_id: uuid.UUID, backup_root: Path) -> BackupManifest:
    """
    Exports every affected row to CSV inside one REPEATABLE READ, READ ONLY transaction (a single
    consistent snapshot) and writes `manifest.json`. Never writes to the database.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = backup_root / f"{tenant_slug}_{stamp}"
    directory.mkdir(parents=True, exist_ok=False)
    manifest = BackupManifest(
        tenant_slug=tenant_slug,
        tenant_id=str(tenant_id),
        created_at=stamp,
        directory=str(directory),
    )
    async with AsyncSessionLocal() as session:
        await session.exec(SNAPSHOT_SQL)  # type: ignore[call-overload]
        for index, (name, sql) in enumerate(build_backup_queries(tenant_id), start=1):
            path = directory / f"{index:02d}_{name}.csv"
            rows = await _copy_query_to_csv(session, sql, path)
            manifest.entries.append(BackupEntry(name, path.name, rows, _sha256_of(path)))
        await session.rollback()
    (directory / MANIFEST_FILE_NAME).write_text(
        json.dumps(
            {
                "tenant_slug": manifest.tenant_slug,
                "tenant_id": manifest.tenant_id,
                "created_at": manifest.created_at,
                "entries": [entry.__dict__ for entry in manifest.entries],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest


# ---------------------------------------------------------------------------
# Wipe transaction
# ---------------------------------------------------------------------------


@dataclass
class WipeResult:
    """Everything the summary prints."""

    before: Dict[str, int] = field(default_factory=dict)
    deleted: Dict[str, int] = field(default_factory=dict)
    after: Dict[str, int] = field(default_factory=dict)
    gst_next: Dict[str, int] = field(default_factory=dict)
    remaining_users: List[str] = field(default_factory=list)
    dangling: Dict[str, int] = field(default_factory=dict)
    other_tenants_unchanged: bool = False
    test_users_found: List[str] = field(default_factory=list)
    foreign_rows: Dict[str, int] = field(default_factory=dict)


def assert_counts_match_backup(current: Mapping[str, int], manifest: BackupManifest) -> None:
    """Aborts when any table changed between the backup snapshot and the wipe transaction."""
    backed_up = manifest.rows_by_name()
    drift = {
        table: (backed_up.get(table), rows)
        for table, rows in current.items()
        if backed_up.get(table) != rows
    }
    if drift:
        raise TenantIntegrityError(f"Rows changed since the backup (backup, now): {drift}")


async def _promote_live_owner(session: AsyncSession, owner: User) -> None:
    """Step 17 (D43 c): owner / BOTH / active, before any test user is deleted."""
    owner.role = LIVE_OWNER_ROLE
    owner.service_scope = LIVE_OWNER_SCOPE
    owner.is_active = True
    session.add(owner)
    await session.flush()


async def _rewrite_settings(
    session: AsyncSession, tenant: Tenant, keep_user_ids: FrozenSet[uuid.UUID]
) -> None:
    """Step 16: prune b2b_access_requests and pin the live GST prefix."""
    pruned = prune_b2b_access_requests(tenant.settings or {}, keep_user_ids)
    tenant.settings = apply_invoice_prefix(pruned, LIVE_INVOICE_PREFIX)
    session.add(tenant)
    await session.flush()


async def _verify(
    session: AsyncSession,
    tenant: Tenant,
    ctx: DeleteContext,
    dropped_ids: FrozenSet[uuid.UUID],
    other_before: Mapping[str, int],
    result: WipeResult,
) -> None:
    """In-transaction checks. Any failure raises `TenantIntegrityError` (caller rolls back)."""
    leftovers = await count_matching_rows(session, ctx)
    result.after = await collect_tenant_counts(session, tenant.id)
    non_zero = {table: rows for table, rows in leftovers.items() if rows}
    if non_zero:
        raise TenantIntegrityError(f"Rows left after the wipe: {non_zero}")
    users = await list_tenant_users(session, tenant.id)
    result.remaining_users = [f"{u.email} ({u.role.value}/{u.service_scope.value})" for u in users]
    only_owner = (
        len(users) == 1
        and users[0].email == LIVE_OWNER_EMAIL
        and users[0].role == LIVE_OWNER_ROLE
        and users[0].service_scope == LIVE_OWNER_SCOPE
        and users[0].is_active
    )
    if not only_owner:
        raise TenantIntegrityError(f"Expected only {LIVE_OWNER_EMAIL} as owner, found {result.remaining_users}")
    result.gst_next = await next_gst_serials(session, tenant)
    if any(serial != FIRST_DOCUMENT_SERIAL for serial in result.gst_next.values()):
        raise TenantIntegrityError(f"GST numbering did not restart: {result.gst_next}")
    result.dangling = await count_references_to_users(session, dropped_ids)
    if any(result.dangling.values()):
        raise TenantIntegrityError(f"Dangling user references: {result.dangling}")
    other_after = await collect_other_tenant_counts(session, tenant.id)
    result.other_tenants_unchanged = dict(other_after) == dict(other_before)
    if not result.other_tenants_unchanged:
        raise TenantIntegrityError(f"Other tenants changed: {other_before} -> {other_after}")


async def run_wipe_transaction(
    slug: str, manifest: BackupManifest, execute: bool
) -> WipeResult:
    """Steps 1-18 plus verification in ONE transaction; commits only when `execute`."""
    result = WipeResult()
    async with AsyncSessionLocal() as session:
        await apply_transaction_timeouts(session)
        tenant = await require_tenant(session, slug)
        await lock_tenant_row(session, tenant.id)
        result.before = await collect_tenant_counts(session, tenant.id)
        assert_counts_match_backup(result.before, manifest)
        other_before = await collect_other_tenant_counts(session, tenant.id)
        test_users = await find_tenant_users_by_email(session, tenant.id, sorted(LIVE_TEST_ACCOUNT_EMAILS))
        result.test_users_found = sorted(test_users)
        owner = (await find_tenant_users_by_email(session, tenant.id, [LIVE_OWNER_EMAIL])).get(LIVE_OWNER_EMAIL)
        if owner is None:
            raise TenantIntegrityError(f"{LIVE_OWNER_EMAIL} has no row in '{slug}'; cannot promote.")
        dropped_ids = frozenset(user.id for user in test_users.values())
        ctx = DeleteContext(
            tenant_id=tenant.id,
            address_purge=AddressPurge.UNSAVED_AND_DROPPED_USERS,
            dropped_user_ids=dropped_ids,
            include_settings_history=True,
        )
        result.foreign_rows = await count_foreign_actor_rows(session, ctx, dropped_ids)
        assert_no_foreign_rows(result.foreign_rows)  # only rows created by the 7 test identities
        result.deleted = await delete_tenant_operational_rows(session, ctx)  # steps 1-15
        all_ids = frozenset(user.id for user in await list_tenant_users(session, tenant.id))
        await _rewrite_settings(session, tenant, all_ids - dropped_ids - {owner.id})  # step 16
        await _promote_live_owner(session, owner)  # step 17
        result.deleted[USER_TABLE] = await delete_tenant_users(session, tenant.id, dropped_ids)  # 18
        await _verify(session, tenant, ctx, dropped_ids, other_before, result)
        if execute:
            await session.commit()
        else:
            await session.rollback()
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    """CLI flags: dry run unless `--execute --confirm-slug <slug>`."""
    parser = argparse.ArgumentParser(description="Wipe golden-test data from a live tenant.")
    parser.add_argument("--tenant", required=True, help="Live tenant slug (only 'logismart').")
    parser.add_argument("--execute", action="store_true", help="COMMIT the wipe (go-ahead #2).")
    parser.add_argument("--confirm-slug", default="", help="Must repeat --tenant with --execute.")
    parser.add_argument("--backup-root", type=Path, default=DEFAULT_BACKUP_ROOT)
    return parser.parse_args()


def _print_table(title: str, columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> None:
    """Fixed-width table for the console summary."""
    print(title)
    print("  " + " | ".join(f"{c:<26}" if i == 0 else f"{c:>8}" for i, c in enumerate(columns)))
    for row in rows:
        print("  " + " | ".join(f"{str(v):<26}" if i == 0 else f"{str(v):>8}" for i, v in enumerate(row)))


def _print_summary(manifest: BackupManifest, result: WipeResult, execute: bool) -> None:
    """Human-readable outcome."""
    print("=" * BANNER_WIDTH)
    print(f"WIPE {manifest.tenant_slug}: {'EXECUTED (COMMITTED)' if execute else 'DRY RUN (ROLLED BACK)'}")
    print("=" * BANNER_WIDTH)
    print(f"Backup directory : {manifest.directory}")
    _print_table(
        "Backup files:",
        ["file", "rows"],
        [(entry.file, entry.rows) for entry in manifest.entries],
    )
    tables = list(result.before.keys())
    _print_table(
        "Per table (before / deleted / after):",
        ["table", "before", "deleted", "after"],
        [(t, result.before.get(t, 0), result.deleted.get(t, 0), result.after.get(t, 0)) for t in tables],
    )
    print(f"Total deleted    : {sum(result.deleted.values())}")
    print(f"Test users found : {result.test_users_found}")
    print(f"Users remaining  : {result.remaining_users}")
    print(f"Next GST serials : {result.gst_next}")
    print(f"Rows NOT created by the 7 test identities (must be 0): {result.foreign_rows}")
    print(f"Dangling refs    : {result.dangling}")
    print(f"Other tenants unchanged: {result.other_tenants_unchanged}")
    print("ALL IN-TRANSACTION CHECKS PASSED.")
    if not execute:
        print(PITR_REMINDER)


async def _run(args: argparse.Namespace) -> int:
    """Backup, then the wipe transaction, then the summary."""
    assert_wipe_allowed(args.tenant, args.execute, args.confirm_slug)
    assert_owner_not_dropped()
    try:
        async with AsyncSessionLocal() as session:
            tenant = await require_tenant(session, args.tenant)
            tenant_id: uuid.UUID = tenant.id
            await session.rollback()
        manifest = await export_backup(args.tenant, tenant_id, args.backup_root)
        result = await run_wipe_transaction(args.tenant, manifest, args.execute)
        _print_summary(manifest, result, args.execute)
        return EXIT_OK
    except (TenantGuardError, TenantIntegrityError) as exc:
        print(f"ABORTED, nothing committed: {exc}")
        return EXIT_FAILED
    finally:
        await async_engine.dispose()


def main() -> None:
    """CLI entry point."""
    args = _parse_args()
    try:
        assert_wipe_allowed(args.tenant, args.execute, args.confirm_slug)
    except TenantGuardError as exc:
        print(str(exc))
        raise SystemExit(EXIT_USAGE) from None
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
