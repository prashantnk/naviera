#!/usr/bin/env python3
"""
Settings data script for the pricing redesign (DESIGN.md v4 §D, user-approved 2026-10-30).

For one tenant: removes the old `pricing_config` rate card and writes `pricing_policy`
(Delhivery markup 0 %, Prime default markup 20 %, all options enabled). The COD fee stays
EMPTY (= COD off) for live tenants until the admin sets it in Settings › Pricing; the golden
test tenant gets the calibration fee (2 %, minimum ₹1) so the money suites keep their numbers.

Dry run by default (prints the before/after); `--execute --confirm-slug <slug>` writes it in
one row-locked transaction and snapshots the previous settings in the settings history.

Usage (from `naviera/backend`):
    poetry run python -m scripts.migrate_pricing_policy --tenant logismart-test
    poetry run python -m scripts.migrate_pricing_policy --tenant logismart-test --execute --confirm-slug logismart-test
"""

import argparse
import asyncio
import copy
import json
from typing import Any, Dict, Tuple

from sqlalchemy.orm.attributes import flag_modified
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import AsyncSessionLocal, async_engine
from app.models.tenants import TenantSettingsHistory
from app.repositories.tenants import TenantRepository
from app.schemas.v1.pricing import PricingPolicy
from app.services.pricing.fake_delhivery import FAKE_PROVIDER_TENANT_SLUGS
from app.services.pricing.policy import PRICING_POLICY_SETTINGS_KEY
from scripts.tenant_data_core import (
    apply_transaction_timeouts,
    lock_tenant_row,
    require_tenant,
)

LEGACY_RATE_CARD_KEY = "pricing_config"
TEST_TENANT_COD_FEE_PERCENT = 2.0
TEST_TENANT_COD_FEE_MIN = 20.0
"""Standard Delhivery One COD charge (max(₹20, 2% of COD value))."""
CHANGED_SECTIONS = [LEGACY_RATE_CARD_KEY, PRICING_POLICY_SETTINGS_KEY]
EXIT_OK = 0
EXIT_USAGE = 2


def target_policy(slug: str) -> PricingPolicy:
    """The policy to write: COD empty for live tenants, calibration fee for the test tenant."""
    if slug in FAKE_PROVIDER_TENANT_SLUGS:
        return PricingPolicy(cod_fee_percent=TEST_TENANT_COD_FEE_PERCENT, cod_fee_min=TEST_TENANT_COD_FEE_MIN)
    return PricingPolicy()


def migrated_settings(settings: Dict[str, Any], slug: str) -> Tuple[Dict[str, Any], bool]:
    """
    The new settings dict and whether anything changed. An existing valid `pricing_policy`
    is kept (the admin may already have set the COD fee); only a missing one is written.
    """
    updated = copy.deepcopy(settings or {})
    changed = updated.pop(LEGACY_RATE_CARD_KEY, None) is not None
    if PRICING_POLICY_SETTINGS_KEY not in updated:
        updated[PRICING_POLICY_SETTINGS_KEY] = target_policy(slug).model_dump(mode="json")
        changed = True
    return updated, changed


async def _next_version(session: AsyncSession, tenant_id: Any) -> int:
    """Next settings-history version number for the tenant."""
    return await TenantRepository(session).next_settings_version(tenant_id)


async def _run(session: AsyncSession, slug: str, execute: bool) -> None:
    """Prints the change and applies it in execute mode."""
    await apply_transaction_timeouts(session)
    tenant = await require_tenant(session, slug)
    if execute:
        await lock_tenant_row(session, tenant.id)
    before = copy.deepcopy(tenant.settings or {})
    after, changed = migrated_settings(before, slug)
    print(f"Tenant {tenant.slug} ({tenant.id})")
    print(f"  {LEGACY_RATE_CARD_KEY} before: {json.dumps(before.get(LEGACY_RATE_CARD_KEY))}")
    print(f"  {PRICING_POLICY_SETTINGS_KEY} after: {json.dumps(after.get(PRICING_POLICY_SETTINGS_KEY))}")
    if not changed:
        print("  Nothing to change.")
        await session.rollback()
        return
    if not execute:
        print("  DRY RUN: nothing written (use --execute --confirm-slug <slug>).")
        await session.rollback()
        return
    session.add(
        TenantSettingsHistory(
            tenant_id=tenant.id,
            version=await _next_version(session, tenant.id),
            settings=before,
            changed_by_user_id=None,
            changed_sections=CHANGED_SECTIONS,
        )
    )
    tenant.settings = after
    flag_modified(tenant, "settings")
    session.add(tenant)
    await session.commit()
    print("  WRITTEN.")


def _parse_args() -> argparse.Namespace:
    """CLI flags."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant", required=True, help="Tenant slug")
    parser.add_argument("--execute", action="store_true", help="Write the change (default: dry run)")
    parser.add_argument("--confirm-slug", default=None, help="Must equal --tenant with --execute")
    return parser.parse_args()


async def _async_main() -> int:
    """Entry point with session lifecycle."""
    args = _parse_args()
    if args.execute and args.confirm_slug != args.tenant:
        print("--execute requires --confirm-slug equal to --tenant; nothing was changed.")
        return EXIT_USAGE
    try:
        async with AsyncSessionLocal() as session:
            await _run(session, args.tenant, bool(args.execute))
    finally:
        await async_engine.dispose()
    return EXIT_OK


def main() -> None:
    """CLI entry point."""
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
