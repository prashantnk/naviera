#!/usr/bin/env python3
"""
Client Handover & Demo Reset Utility for Naviera Multi-Tenant Logistics Platform.

Safely audits (in `--dry-run` mode, the default) or transactionally cleans (in `--execute` mode)
all transient operational and test records for a target tenant prior to client production
handover:
  - Preserves:
      * `Tenant` identity, `branding`, and `settings` (validating and hydrating
        `wallet_config`, `pricing_policy`, `merchant_vpa`, `min_wallet_balance_b2c`,
        `min_wallet_balance_b2b`, `strict_finlock`, and `gstin` if any key is missing).
      * All `User` accounts (`owner`, `admin`, `customer`).
      * All saved Address Book entries (`Address.is_saved == True`).
      * The settings history (`tenant_settings_history`).
  - Cleans (on `--execute`), through the shared FK-ordered delete core
    (`scripts/tenant_data_core.py`, `OPERATIONAL_DELETE_STEPS`), so this utility, the test-tenant
    reset and the live wipe can never disagree on the delete order:
      * Support tickets + messages, weight disputes, COD remittances, GST documents.
      * `WalletTransaction` ledger rows and `UserWallet` rows (wallets are recreated lazily at
        ₹0.00 by `WalletRepository.get_or_create_wallet` on first use).
      * `ShipmentActivity`, `PackageDetails`, `PaymentDetails`, `PickupDocument`, `PickupRequest`
        (shipments), `Manifest` (pickup requests) and unsaved snapshot `Address` rows.

For the one-time go-live wipe of live `logismart` (backup, test-user removal, owner promotion and
GST restart checks) use `scripts/wipe_tenant_test_data.py` instead.

Usage (from `naviera/backend`):
    poetry run python -m scripts.prepare_logismart_handover --tenant <slug>            # dry run
    poetry run python -m scripts.prepare_logismart_handover --tenant <slug> --execute --confirm-slug <slug>
"""

import argparse
import asyncio
import copy
from typing import Any, Dict, List, Tuple

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import AsyncSessionLocal, async_engine
from app.models.tenants import Tenant
from app.services.pricing.policy import PRICING_POLICY_SETTINGS_KEY
from scripts.migrate_pricing_policy import migrated_settings
from scripts.tenant_data_core import (
    AddressPurge,
    DeleteContext,
    apply_transaction_timeouts,
    collect_tenant_counts,
    count_matching_rows,
    delete_tenant_operational_rows,
    list_tenant_users,
    lock_tenant_row,
    require_tenant,
)

# Module-level Constants
BANNER_WIDTH: int = 76
EXIT_OK: int = 0
EXIT_USAGE: int = 2

DEFAULT_WALLET_CONFIG: Dict[str, Any] = {
    "merchant_name": "LogiSmart Enterprise Logistics",
    "min_wallet_balance_b2c": 0.0,
    "min_wallet_balance_b2b": 500.0,
    "strict_finlock": False,
    "auto_detect_upi": True,
    "auto_detect_delay_seconds": 5,
    "gstin": "06AAECL2138H1ZQ",
}
"""Defaults for missing wallet keys only. `merchant_vpa` is deliberately absent: a UPI VPA is a
real bank account and must be entered by the tenant Owner in Settings, never defaulted."""

TupleSettingsUpdate = Tuple[Dict[str, Any], List[str]]


def _parse_args() -> argparse.Namespace:
    """
    Parses CLI arguments for tenant targeting and dry-run vs execution mode.
    The tenant is required (no default), dry run is the default, and `--execute` also requires
    `--confirm-slug` repeating the tenant slug.
    """
    parser = argparse.ArgumentParser(
        description="Prepare a Naviera tenant for clean client handover."
    )
    parser.add_argument("--tenant", type=str, required=True, help="Target tenant slug.")
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Execute the transactional cleanup (default is a read-only dry run).",
    )
    parser.add_argument(
        "--confirm-slug", type=str, default="", help="Must repeat --tenant with --execute."
    )
    return parser.parse_args()


def execute_confirmed(tenant_slug: str, execute: bool, confirm_slug: str) -> bool:
    """True for dry runs, or for `--execute` with a matching `--confirm-slug`."""
    return not execute or confirm_slug == tenant_slug


def handover_delete_context(tenant: Tenant) -> DeleteContext:
    """
    Handover scope: every operational row, but only UNSAVED addresses (no user is dropped, so
    the address book survives) and the settings history is kept.
    """
    return DeleteContext(
        tenant_id=tenant.id,
        address_purge=AddressPurge.UNSAVED_AND_DROPPED_USERS,
        dropped_user_ids=frozenset(),
        include_settings_history=False,
    )


def _ensure_tenant_settings_defaults(tenant: Tenant) -> TupleSettingsUpdate:
    """
    Inspects `tenant.settings` and populates any missing DB-driven Pricing Rate Card
    (`pricing_policy`) or Wallet (`wallet_config` + top-level keys) defaults while
    strictly preserving `branding` and existing customized values.
    """
    current_settings: Dict[str, Any] = copy.deepcopy(tenant.settings or {})
    populated_keys: List[str] = []

    # 1. Ensure wallet_config dictionary and top-level aliases exist
    wallet_cfg: Dict[str, Any] = dict(current_settings.get("wallet_config") or {})
    for key, default_val in DEFAULT_WALLET_CONFIG.items():
        if wallet_cfg.get(key) is None:
            wallet_cfg[key] = current_settings.get(key, default_val)
            populated_keys.append(f"wallet_config.{key}")
        if current_settings.get(key) is None:
            current_settings[key] = wallet_cfg[key]
            populated_keys.append(key)
    current_settings["wallet_config"] = wallet_cfg

    # 2. Pricing redesign: drop the old `pricing_config` rate card and make sure a
    #    `pricing_policy` exists (COD stays OFF for live tenants until the Owner sets it).
    migrated, changed = migrated_settings(current_settings, tenant.slug)
    if changed:
        populated_keys.append(PRICING_POLICY_SETTINGS_KEY)
    return migrated, populated_keys


def _print_handover_summary(
    tenant_label: str,
    user_emails: List[str],
    targets: Dict[str, int],
    inventory: Dict[str, int],
    populated_keys: List[str],
    executed: bool,
) -> None:
    """
    Prints a structured, human-readable summary of preserved and cleaned records.
    """
    mode_banner = (
        "EXECUTED TRANSACTIONAL CLEANUP" if executed else "DRY-RUN AUDIT (NO DB MUTATIONS)"
    )
    print("=" * BANNER_WIDTH)
    print(f"NAVIERA CLIENT HANDOVER UTILITY — {mode_banner}")
    print("=" * BANNER_WIDTH)
    print(f"Target Tenant      : {tenant_label}")
    print("-" * BANNER_WIDTH)
    print("[PRESERVED CONFIGURATION & MASTER DATA]")
    print(f"  • User Accounts Preserved          : {len(user_emails)}")
    for email_str in user_emails:
        print(f"      - {email_str}")
    saved_addresses = inventory.get("addresses", 0) - targets.get("addresses", 0)
    print(f"  • Saved Address Book Entries       : {saved_addresses}")
    print(
        "  • Settings Keys Hydrated/Verified  : "
        + (
            ", ".join(populated_keys)
            if populated_keys
            else "All wallet_config & pricing_policy keys already present"
        )
    )
    print("-" * BANNER_WIDTH)
    action_verb = "Cleaned" if executed else "Would Clean"
    print(f"[OPERATIONAL RECORDS ({action_verb.upper()})]")
    for table, rows in targets.items():
        print(f"  • {table:<26}: {rows}")
    print("=" * BANNER_WIDTH)


async def _run_handover(session: AsyncSession, slug: str, execute: bool) -> None:
    """
    Audits the tenant and, in execute mode, cleans it in one transaction through the shared core.
    """
    await apply_transaction_timeouts(session)
    tenant = await require_tenant(session, slug)
    ctx = handover_delete_context(tenant)
    tenant_label = f"{tenant.name} (slug='{tenant.slug}', id={tenant.id})"
    updated_settings, populated_keys = _ensure_tenant_settings_defaults(tenant)
    inventory = await collect_tenant_counts(session, tenant.id)
    targets = await count_matching_rows(session, ctx)
    users = await list_tenant_users(session, tenant.id)
    user_emails = [f"{u.email} ({u.role.value})" for u in users]

    if execute:
        await lock_tenant_row(session, tenant.id)
        tenant.settings = updated_settings
        session.add(tenant)
        targets = await delete_tenant_operational_rows(session, ctx)
        await session.commit()
    else:
        await session.rollback()
    _print_handover_summary(tenant_label, user_emails, targets, inventory, populated_keys, execute)


async def _async_main() -> int:
    """
    Async entry point coordinating session lifecycle, audit reporting, and execution.
    """
    args = _parse_args()
    if not execute_confirmed(args.tenant, bool(args.execute), args.confirm_slug):
        print("--execute requires --confirm-slug equal to --tenant; nothing was changed.")
        return EXIT_USAGE
    try:
        async with AsyncSessionLocal() as session:
            await _run_handover(session, args.tenant, bool(args.execute))
    finally:
        await async_engine.dispose()
    return EXIT_OK


def main() -> None:
    """
    CLI entry point.
    """
    raise SystemExit(asyncio.run(_async_main()))


if __name__ == "__main__":
    main()
