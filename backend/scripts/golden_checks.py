"""
Read-only checks used by `scripts/run_golden.sh` (ship-readiness plan E5 / A "Done when").

Subcommands (run from `naviera/backend`):
    poetry run python -m scripts.golden_checks live-counts --tenant logismart --out before.json
    poetry run python -m scripts.golden_checks compare-counts before.json after.json
    poetry run python -m scripts.golden_checks integrity --tenant logismart-test
    poetry run python -m scripts.golden_checks junit-summary api.xml ui.xml

* `live-counts` snapshots every operational table, `user` and the next GST serials of one tenant
  (SELECT only), so a golden run can prove it left live `logismart` untouched.
* `integrity` runs the B11/C6 integrity audit (`IntegrityAuditService`) over a TEST tenant as its
  owner and exits non-zero on any discrepancy. It refuses non-test slugs.
* `junit-summary` prints pass / fail / error / skip counts per test file from pytest JUnit XML.

Spring analogy: a small `CommandLineRunner` with read-only `@Transactional(readOnly = true)` jobs.
"""

import argparse
import asyncio
import collections
import json
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Dict, List, Mapping, Sequence

from sqlmodel import select

import app.main  # noqa: F401  (loads the service graph in the app's own order: the

# wallet <-> integrity_audit <-> repricing <-> delhivery_modules imports form a cycle that only
# resolves in that order)
from app.core.db import AsyncSessionLocal, async_engine
from app.models.tenants import User, UserRole
from app.repositories.wallet import WalletRepository
from app.services.integrity_audit import IntegrityAuditService
from scripts.tenant_data_core import (
    apply_transaction_timeouts,
    assert_test_tenant_marked,
    assert_test_tenant_slug,
    collect_tenant_counts,
    next_gst_serials,
    require_tenant,
)

EXIT_OK = 0
EXIT_FAILED = 1
MAX_DISCREPANCIES_SHOWN = 25
OUTCOMES = ("passed", "failed", "error", "skipped")
SUMMARY_HEADER = f"{'suite':<58} {'pass':>5} {'fail':>5} {'err':>5} {'skip':>5}"


# --- live-counts / compare-counts -------------------------------------------


async def _tenant_snapshot(slug: str) -> Dict[str, int]:
    """Row count per table + user count + next GST serials of one tenant (SELECT only)."""
    async with AsyncSessionLocal() as session:
        await apply_transaction_timeouts(session)
        tenant = await require_tenant(session, slug)
        counts = await collect_tenant_counts(session, tenant.id)
        counts.update({f"next_serial:{k}": v for k, v in (await next_gst_serials(session, tenant)).items()})
        await session.rollback()
    return counts


def _write_counts(counts: Mapping[str, int], out: Path) -> None:
    """Stores a snapshot as sorted JSON and echoes it."""
    out.write_text(json.dumps(dict(sorted(counts.items())), indent=2), encoding="utf-8")
    print(json.dumps(dict(sorted(counts.items()))))


def compare_counts(before: Mapping[str, int], after: Mapping[str, int]) -> List[str]:
    """Human-readable differences between two snapshots (empty list == unchanged)."""
    return [
        f"{key}: {before.get(key)} -> {after.get(key)}"
        for key in sorted(set(before) | set(after))
        if before.get(key) != after.get(key)
    ]


# --- integrity ---------------------------------------------------------------


async def _run_integrity(slug: str) -> int:
    """Runs the integrity audit as the test tenant's owner; prints the result."""
    assert_test_tenant_slug(slug)
    async with AsyncSessionLocal() as session:
        await apply_transaction_timeouts(session)
        tenant = await require_tenant(session, slug)
        assert_test_tenant_marked(tenant)
        owner = (
            await session.exec(
                select(User).where(User.tenant_id == tenant.id, User.role == UserRole.owner).limit(1)
            )
        ).first()
        if owner is None:
            print(f"INTEGRITY FAILED: tenant {slug!r} has no owner")
            return EXIT_FAILED
        result = await IntegrityAuditService(WalletRepository(session)).audit_tenant_integrity(owner, tenant)
        await session.rollback()
    print(
        f"integrity {slug}: passed={result.passed} wallets={result.wallets_checked} "
        f"txns={result.transactions_checked} shipments={result.shipments_checked} "
        f"invoices={result.invoices_checked} remittances={result.remittances_checked} "
        f"discrepancies={result.discrepancy_count} warnings={len(result.warnings)}"
    )
    for item in result.discrepancies[:MAX_DISCREPANCIES_SHOWN]:
        print(f"  DISCREPANCY [{item.category}] {item.reference}: {item.detail}")
    for item in result.warnings[:MAX_DISCREPANCIES_SHOWN]:
        print(f"  warning [{item.category}] {item.reference}: {item.detail}")
    return EXIT_OK if result.passed else EXIT_FAILED


# --- junit-summary -------------------------------------------------------------


def _testcase_outcome(case: ElementTree.Element) -> str:
    """Maps one JUnit `<testcase>` to passed / failed / error / skipped."""
    for tag in ("failure", "error", "skipped"):
        if case.find(tag) is not None:
            return "failed" if tag == "failure" else tag
    return "passed"


def _suite_name(case: ElementTree.Element) -> str:
    """`file` attribute when present, else the module part of `classname`."""
    file_attr = case.get("file")
    if file_attr:
        return file_attr
    return case.get("classname", "?").rsplit(".", 1)[-1] + ".py"


def junit_counts(paths: Sequence[Path]) -> Dict[str, Dict[str, int]]:
    """Outcome counts per test file, in the order files first appear."""
    per_suite: Dict[str, Dict[str, int]] = collections.OrderedDict()
    for path in paths:
        if not path.exists():
            continue
        for case in ElementTree.parse(path).getroot().iter("testcase"):
            bucket = per_suite.setdefault(_suite_name(case), dict.fromkeys(OUTCOMES, 0))
            bucket[_testcase_outcome(case)] += 1
    return per_suite


def _print_junit_summary(paths: Sequence[Path], fail_on_skip: bool = False) -> int:
    """
    Prints the per-suite table and a total line. Non-zero exit on any failure or error, and on
    any skip when `fail_on_skip` (a skipped UI journey was never exercised).
    """
    per_suite = junit_counts(paths)
    totals = dict.fromkeys(OUTCOMES, 0)
    print(SUMMARY_HEADER)
    for suite, counts in per_suite.items():
        print(f"{suite:<58} {counts['passed']:>5} {counts['failed']:>5} {counts['error']:>5} {counts['skipped']:>5}")
        for key in OUTCOMES:
            totals[key] += counts[key]
    print(f"{'TOTAL':<58} {totals['passed']:>5} {totals['failed']:>5} {totals['error']:>5} {totals['skipped']:>5}")
    if totals["failed"] or totals["error"]:
        return EXIT_FAILED
    if fail_on_skip and totals["skipped"]:
        print(f"{totals['skipped']} test(s) skipped: not allowed for this phase")
        return EXIT_FAILED
    return EXIT_OK


# --- CLI -------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    """CLI definition (see module docstring)."""
    parser = argparse.ArgumentParser(description="Read-only golden-run checks.")
    sub = parser.add_subparsers(dest="command", required=True)
    live = sub.add_parser("live-counts", help="Snapshot a tenant's row counts + next GST serials.")
    live.add_argument("--tenant", required=True)
    live.add_argument("--out", type=Path, required=True)
    cmp_parser = sub.add_parser("compare-counts", help="Fail when two snapshots differ.")
    cmp_parser.add_argument("before", type=Path)
    cmp_parser.add_argument("after", type=Path)
    integrity = sub.add_parser("integrity", help="Integrity audit of a TEST tenant.")
    integrity.add_argument("--tenant", required=True)
    junit = sub.add_parser("junit-summary", help="Per-suite counts from JUnit XML files.")
    junit.add_argument("paths", type=Path, nargs="+")
    junit.add_argument("--fail-on-skip", action="store_true", help="Treat any skipped test as a failure.")
    return parser.parse_args(argv)


async def _run_async(args: argparse.Namespace) -> int:
    """Runs a DB-touching subcommand, then disposes the engine whatever happened."""
    try:
        if args.command == "live-counts":
            _write_counts(await _tenant_snapshot(args.tenant), args.out)
            return EXIT_OK
        return await _run_integrity(args.tenant)
    finally:
        await async_engine.dispose()


def main(argv: Sequence[str]) -> int:
    """CLI entry point; returns the process exit code."""
    args = _parse_args(argv)
    if args.command == "junit-summary":
        return _print_junit_summary(args.paths, fail_on_skip=args.fail_on_skip)
    if args.command == "compare-counts":
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
        diffs = compare_counts(before, after)
        for line in diffs:
            print(f"  CHANGED {line}")
        print("live counts unchanged" if not diffs else f"live counts CHANGED ({len(diffs)} keys)")
        return EXIT_FAILED if diffs else EXIT_OK
    return asyncio.run(_run_async(args))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
