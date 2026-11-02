"""
Idempotent seed of the `logismart-test` tenant (plan item A5).

DRY RUN BY DEFAULT: every insert/update runs inside one transaction that is rolled back, so you
see exactly what `--execute` would do. Writing for real needs the user's go-ahead #1.

Usage (from `naviera/backend`):
    poetry run python -m scripts.seed_logismart_test                     # dry run
    GOLDEN_TEST_PASSWORD='<secret>' poetry run python -m scripts.seed_logismart_test --execute
    poetry run python -m scripts.seed_logismart_test --execute --refresh-settings

What it does (owner first, because JIT provisioning makes the first user of an empty tenant OWNER):
  1. tenant `logismart-test` from the frozen fixture settings (environment=test, invoice prefix LTST,
     TEST banner). An existing row is only touched if it is marked environment=test.
  2. the 8 canonical accounts (7 @logismart.in identities reused from auth.users +
     b2bonboarding@logismart.in, created in auth.users when missing).
  3. 3 saved addresses, ₹0.00 wallets, APPROVED b2b_access_requests for B2B/BOTH accounts.
  4. read-only verification of the result.

Spring Boot mapping: a hand-run `CommandLineRunner` wrapped in one `@Transactional` method whose
`rollbackFor` is "always" unless `--execute` is given.
"""

import argparse
import asyncio
import os
import secrets
from pathlib import Path
from typing import Dict, List

from app.core.db import AsyncSessionLocal, async_engine
from scripts.tenant_data_core import (
    FIXTURES_DIR,
    SeedFixtures,
    SeedReport,
    apply_transaction_timeouts,
    collect_tenant_counts,
    get_tenant_by_slug,
    load_seed_fixtures,
    next_gst_serials,
    seed_test_tenant,
    verify_seeded_tenant,
)

PASSWORD_ENV_VAR: str = "GOLDEN_TEST_PASSWORD"
"""Password for auth identities the seed has to create; never stored in source control."""

DRY_RUN_PASSWORD_BYTES: int = 24
"""Entropy of the throwaway password used only inside a rolled-back dry run."""

BANNER_WIDTH: int = 78
EXIT_OK: int = 0
EXIT_VERIFY_FAILED: int = 1
EXIT_USAGE: int = 2


def _parse_args() -> argparse.Namespace:
    """CLI flags: dry run unless `--execute`."""
    parser = argparse.ArgumentParser(description="Seed the logismart-test tenant (dry run by default).")
    parser.add_argument("--execute", action="store_true", help="Commit the seed (needs go-ahead #1).")
    parser.add_argument(
        "--refresh-settings",
        action="store_true",
        help="Replace an existing test tenant's settings with the fixture copy.",
    )
    parser.add_argument(
        "--fixtures-dir", type=Path, default=FIXTURES_DIR, help="Directory with the 3 fixture files."
    )
    return parser.parse_args()


def _resolve_password(execute: bool) -> str:
    """
    Real runs read `GOLDEN_TEST_PASSWORD`; dry runs fall back to a random throwaway password,
    because any auth row they create is rolled back anyway.
    """
    password = os.getenv(PASSWORD_ENV_VAR, "")
    if password or execute:
        return password
    return secrets.token_urlsafe(DRY_RUN_PASSWORD_BYTES)


def _print_banner(title: str) -> None:
    """Section separator for readable console output."""
    print("=" * BANNER_WIDTH)
    print(title)
    print("=" * BANNER_WIDTH)


def _print_report(report: SeedReport, fixtures: SeedFixtures) -> None:
    """Prints the action log in seed order."""
    print(f"Fixtures            : {len(fixtures.accounts)} accounts, {len(fixtures.addresses)} addresses")
    print(f"Owner (seeded first): {fixtures.owner.email}")
    for line in report.actions:
        print(f"  {line}")
    if report.auth_users_to_create:
        print(f"auth.users created  : {', '.join(report.auth_users_to_create)}")


def _print_counts(title: str, counts: Dict[str, int]) -> None:
    """Prints a `table: rows` block."""
    print(title)
    for table, rows in counts.items():
        print(f"  {table:<26}: {rows}")


async def _run(args: argparse.Namespace) -> int:
    """Runs the seed, then disposes the engine whatever happened."""
    try:
        return await _seed_once(args)
    finally:
        await async_engine.dispose()


async def _seed_once(args: argparse.Namespace) -> int:
    """Runs the seed in one transaction, verifies it, then commits (execute) or rolls back."""
    fixtures = load_seed_fixtures(args.fixtures_dir)
    password = _resolve_password(args.execute)
    mode = "EXECUTE (COMMIT)" if args.execute else "DRY RUN (ROLLBACK, NO DB CHANGES)"
    _print_banner(f"SEED {fixtures.slug} : {mode}")
    async with AsyncSessionLocal() as session:
        await apply_transaction_timeouts(session)
        existed = await get_tenant_by_slug(session, fixtures.slug) is not None
        print(f"Tenant existed before: {existed}")
        report = await seed_test_tenant(
            session,
            fixtures,
            password=password or None,
            allow_auth_create=True,
            refresh_settings=args.refresh_settings or not existed,
        )
        _print_report(report, fixtures)
        problems: List[str] = await verify_seeded_tenant(session, fixtures)
        tenant = await get_tenant_by_slug(session, fixtures.slug)
        if tenant is not None:
            _print_counts("Rows in the test tenant after the seed:", await collect_tenant_counts(session, tenant.id))
            _print_counts("Next GST serial per series:", await next_gst_serials(session, tenant))
        if problems:
            print("VERIFY FAILED: " + "; ".join(problems))
            await session.rollback()
            return EXIT_VERIFY_FAILED
        print("VERIFY OK")
        if args.execute:
            await session.commit()
            print("COMMITTED.")
        else:
            await session.rollback()
            print("ROLLED BACK (dry run). Re-run with --execute after go-ahead #1.")
    return EXIT_OK


def main() -> None:
    """CLI entry point."""
    args = _parse_args()
    if args.execute and not os.getenv(PASSWORD_ENV_VAR):
        print(f"--execute needs {PASSWORD_ENV_VAR} (used only if an auth identity must be created).")
        raise SystemExit(EXIT_USAGE)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
