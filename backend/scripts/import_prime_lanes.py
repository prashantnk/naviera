"""
Imports Logismart Prime lanes from the rate sheet's Sheet1 (DESIGN.md v4 §C.1, Q5).

DRY RUN BY DEFAULT (`--dry-run` is on unless `--execute`): prints a review report of the
sheet's data-quality issues and what the import would create/update/deactivate, then rolls
back. Live `logismart` needs the user's go-ahead before `--execute`. Zones must exist first
(`scripts/seed_prime_zones.py`).

Usage (from `naviera/backend`):
    poetry run python -m scripts.import_prime_lanes --tenant-slug logismart \
        --file ../llm_resources/.agents/pricing/sheet_raw_all_tabs.tsv
    poetry run python -m scripts.import_prime_lanes --tenant-slug logismart --file sheet1.csv --offline

Input: a TSV/CSV export of the sheet. When the file holds several tabs separated by
`--- SheetN ---` lines, only Sheet1 is read. Each transporter block repeats a 2-line header;
the second header line gives the TAT unit ("IN HRS" / "IN DAYS") and the header text gives
the per-kg charge minimums ("MINIMUM RS 800"). Rules (the importer reports, never guesses):
- a city or booking point not in `PRIME_ZONE_SPECS` → error (row skipped);
- a non-numeric rate ("NA") or unknown TAT unit → error (row skipped);
- a state that is not the zone's state, routing text in a city ("VIA", "- ATQ"), a merged
  spelling → warning;
- per route the cheapest transporter (rate/kg) is activated, the others are kept inactive;
  a tie is broken by door delivery, then shorter TAT, then name, and reported.

Spring Boot mapping: a hand-run `CommandLineRunner` with a `@Transactional` import that rolls
back unless `--execute`.
"""

import argparse
import asyncio
import csv
import io
import re
from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from app.core.db import AsyncSessionLocal, async_engine
from app.core.money import to_money
from app.models.prime import (
    DEFAULT_PRIME_MARKUP_PERCENT,
    PrimeDeliveryType,
    PrimeLaneMode,
)
from app.repositories.prime_rates import PrimeRatesRepository
from app.schemas.v1.prime import PrimeImportIssue
from app.services.prime_admin import (
    LaneImportPlan,
    LaneInput,
    apply_lane_plan,
    plan_lane_import,
)
from scripts.seed_prime_zones import (
    ZoneSpec,
    has_routing_text,
    normalize_place,
    zone_for_place,
)
from scripts.tenant_data_core import apply_transaction_timeouts, get_tenant_by_slug

EXIT_OK = 0
EXIT_FAILED = 1
BANNER_WIDTH = 78
SHEET_NAME = "Sheet1"
TAB_MARKER = re.compile(r"^---\s*(?P<name>[^-]+?)\s*---$")
HEADER_FIRST_CELLS = ("FROM CITY", "DELHI NCR", "LOGISMART PVT LTD", "FROM/TO")
TAT_UNIT_HOURS = {"IN HRS": 1, "IN DAYS": 24}
MINIMUM_PATTERN = re.compile(r"MINIMUM\s+RS\s*(?P<amount>\d+(?:\.\d+)?)", re.IGNORECASE)
DIVISOR_PATTERN = re.compile(r"^L\s*\*\s*[WB]\s*\*\s*H\s*/\s*(?P<divisor>\d+(?:\.\d+)?)$", re.IGNORECASE)
ODD_SIZE_NOT_ALLOWED = "NOT ALLOWED"
MAX_DIMENSION_CM = Decimal("240.00")
"""Sheet "ODD SIZE: MORE THAN 7.9 FEET → NOT ALLOWED" (7.9 ft = 240.8 cm; DESIGN §C.3 uses 240 cm)."""
EXPECTED_PICKUP = "DOOR"
MIN_COLUMNS = 19

COL_FROM_CITY, COL_FROM_STATE, COL_TO_CITY, COL_TO_STATE, COL_MODE, COL_TRANSPORTER = range(6)
COL_TAT, COL_RATE, COL_MIN_LR, COL_PICKUP, COL_DELIVERY, COL_DOCKET, COL_MIN_WEIGHT = range(6, 13)
COL_ODD_SIZE, COL_ODD_WEIGHT, COL_ODA, COL_PICKUP_CHARGE, COL_DELIVERY_CHARGE, COL_VOLUME = range(13, 19)
MINIMUM_COLUMNS: Mapping[int, str] = {
    COL_ODD_WEIGHT: "odd_weight_min",
    COL_ODA: "oda_min",
    COL_PICKUP_CHARGE: "pickup_min",
    COL_DELIVERY_CHARGE: "door_delivery_min",
}
"""Columns whose header text carries the charge minimum, and the lane field it fills."""


@dataclass
class BlockHeader:
    """What the current transporter block's header says (TAT unit, charge minimums)."""

    tat_hours_per_unit: Optional[int] = None
    minimums: Dict[str, Decimal] = field(default_factory=dict)


@dataclass
class SheetReport:
    """Lanes read from the sheet plus everything the reviewer should look at."""

    lanes: List[LaneInput] = field(default_factory=list)
    errors: List[PrimeImportIssue] = field(default_factory=list)
    warnings: List[PrimeImportIssue] = field(default_factory=list)


def _split(line: str, delimiter: str) -> List[str]:
    """Cells of one line (CSV quoting honoured)."""
    return [cell.strip() for cell in next(csv.reader(io.StringIO(line), delimiter=delimiter))]


def _sheet1_lines(text: str) -> List[Tuple[int, str]]:
    """(line number, line) of Sheet1 only; the whole file when it has no tab markers."""
    lines = text.splitlines()
    if not any(TAB_MARKER.match(line.strip()) for line in lines):
        return list(enumerate(lines, start=1))
    selected: List[Tuple[int, str]] = []
    current: Optional[str] = None
    for number, line in enumerate(lines, start=1):
        marker = TAB_MARKER.match(line.strip())
        if marker:
            current = marker.group("name").strip()
        elif current == SHEET_NAME:
            selected.append((number, line))
    return selected


def _update_header(cells: Sequence[str], header: BlockHeader) -> None:
    """Reads the TAT unit and the charge minimums from a header line."""
    unit = cells[COL_TAT].upper() if len(cells) > COL_TAT else ""
    if unit in TAT_UNIT_HOURS:
        header.tat_hours_per_unit = TAT_UNIT_HOURS[unit]
    for column, name in MINIMUM_COLUMNS.items():
        match = MINIMUM_PATTERN.search(cells[column]) if len(cells) > column else None
        if match:
            header.minimums[name] = to_money(match.group("amount"))


def _number(raw: str, label: str) -> Decimal:
    """
    A non-negative number cell.

    Raises:
        ValueError: blank, "NA" or not a number.
    """
    try:
        value = Decimal(raw.strip())
    except InvalidOperation as exc:
        raise ValueError(f"{label} '{raw}' is not a number.") from exc
    if not value.is_finite() or value < 0:
        raise ValueError(f"{label} '{raw}' is not a valid amount.")
    return value


def _zone(raw_city: str, label: str) -> ZoneSpec:
    """
    The zone of a sheet city cell.

    Raises:
        ValueError: the city is not in the alias table.
    """
    zone = zone_for_place(raw_city)
    if zone is None:
        raise ValueError(f"{label} '{raw_city}' is not a known Prime zone; add it to PRIME_ZONE_SPECS.")
    return zone


def _row_warnings(cells: Sequence[str], origin: ZoneSpec, dest: ZoneSpec) -> List[str]:
    """Data-quality notes for a valid row (state mismatch, routing text, spelling merged into a zone)."""
    notes: List[str] = []
    for city, state, zone in ((cells[COL_FROM_CITY], cells[COL_FROM_STATE], origin), (cells[COL_TO_CITY], cells[COL_TO_STATE], dest)):
        if normalize_place(state) not in zone.state_keys:
            notes.append(f"state '{state}' for '{city}' is not {zone.state}.")
        if has_routing_text(city):
            notes.append(f"'{city}' carries routing text; mapped to zone {zone.name}.")
        elif normalize_place(city) != normalize_place(zone.name) and zone is dest:
            notes.append(f"'{city}' mapped to zone {zone.name}.")
    if cells[COL_PICKUP].upper() != EXPECTED_PICKUP:
        notes.append(f"pickup '{cells[COL_PICKUP]}' is not DOOR; pickup charge still applied.")
    return notes


def _parse_row(cells: Sequence[str], header: BlockHeader, markup: Decimal) -> Tuple[LaneInput, List[str]]:
    """
    One sheet data row → lane input (inactive; activation is decided per route later).

    Raises:
        ValueError: the first blocking problem.
    """
    if header.tat_hours_per_unit is None:
        raise ValueError("TAT unit unknown (no 'IN HRS'/'IN DAYS' header above this row).")
    missing_minimums = [name for name in MINIMUM_COLUMNS.values() if name not in header.minimums]
    if missing_minimums:
        raise ValueError(f"header gives no minimum for {', '.join(missing_minimums)}.")
    if cells[COL_ODD_SIZE].upper() != ODD_SIZE_NOT_ALLOWED:
        raise ValueError(f"odd size '{cells[COL_ODD_SIZE]}' is not '{ODD_SIZE_NOT_ALLOWED}'.")
    divisor = DIVISOR_PATTERN.match(cells[COL_VOLUME].replace(" ", ""))
    if not divisor:
        raise ValueError(f"volume weight '{cells[COL_VOLUME]}' is not 'L*W*H/<divisor>'.")
    origin, dest = _zone(cells[COL_FROM_CITY], "from city"), _zone(cells[COL_TO_CITY], "to city")
    tat = _number(cells[COL_TAT], "TAT")
    rate = _number(cells[COL_RATE], "rate/kg")
    if rate <= 0 or tat <= 0 or tat != tat.to_integral_value():
        raise ValueError(f"rate/kg '{cells[COL_RATE]}' and TAT '{cells[COL_TAT]}' must be positive (TAT whole).")
    rates = {
        "rate_per_kg": to_money(rate),
        "min_lr_charge": to_money(_number(cells[COL_MIN_LR], "minimum LR")),
        "docket_charge": to_money(_number(cells[COL_DOCKET], "docket")),
        "min_chargeable_kg": to_money(_number(cells[COL_MIN_WEIGHT], "minimum weight")),
        "volumetric_divisor": to_money(divisor.group("divisor")),
        "max_dimension_cm": MAX_DIMENSION_CM,
        "oda_per_kg": to_money(_number(cells[COL_ODA], "ODA")),
        "odd_weight_per_kg": to_money(_number(cells[COL_ODD_WEIGHT], "odd weight")),
        "pickup_per_kg": to_money(_number(cells[COL_PICKUP_CHARGE], "pickup charge")),
        "door_delivery_per_kg": to_money(_number(cells[COL_DELIVERY_CHARGE], "delivery charge")),
        **header.minimums,
    }
    try:
        delivery_type = PrimeDeliveryType(cells[COL_DELIVERY].upper())
        mode = PrimeLaneMode(cells[COL_MODE].upper())
    except ValueError as exc:
        raise ValueError(f"mode '{cells[COL_MODE]}' / delivery '{cells[COL_DELIVERY]}' not recognised.") from exc
    lane = LaneInput(
        row=None,
        origin_zone=origin.name,
        dest_zone=dest.name,
        mode=mode,
        transporter_name=cells[COL_TRANSPORTER],
        tat_hours=int(tat) * header.tat_hours_per_unit,
        delivery_type=delivery_type,
        rates=rates,
        markup_percent=markup,
        is_active=False,
    )
    return lane, _row_warnings(cells, origin, dest)


def read_sheet1(text: str, markup: Decimal = DEFAULT_PRIME_MARKUP_PERCENT) -> SheetReport:
    """
    Parses Sheet1 into lane inputs (all inactive) with a review report (pure).

    Args:
        text: The file content.
        markup: Markup % for every lane.
    """
    report = SheetReport()
    lines = _sheet1_lines(text)
    delimiter = "\t" if any("\t" in line for _, line in lines) else ","
    header = BlockHeader()
    for number, line in lines:
        cells = _split(line, delimiter) if line.strip() else []
        if not cells or not cells[0]:
            continue
        if cells[0].upper().startswith(HEADER_FIRST_CELLS):
            _update_header(cells, header)
            continue
        if len(cells) < MIN_COLUMNS:
            report.warnings.append(PrimeImportIssue(row=number, message=f"skipped: only {len(cells)} columns."))
            continue
        try:
            lane, notes = _parse_row(cells, header, markup)
        except ValueError as exc:
            report.errors.append(PrimeImportIssue(row=number, message=f"{cells[COL_TO_CITY]} / {cells[COL_TRANSPORTER]}: {exc}"))
            continue
        report.lanes.append(replace(lane, row=number))
        report.warnings.extend(PrimeImportIssue(row=number, message=note) for note in notes)
    return report


def _preference(lane: LaneInput) -> Tuple[Decimal, int, int, str]:
    """Sort key: cheapest rate, then door delivery included, then shorter TAT, then name."""
    door_first = 0 if lane.delivery_type == PrimeDeliveryType.DOOR else 1
    return (lane.rates["rate_per_kg"], door_first, lane.tat_hours, lane.transporter_name.upper())


def choose_active_lanes(report: SheetReport) -> List[LaneInput]:
    """
    Merges same-transporter duplicates (error, first kept) and activates the cheapest lane per route.

    Returns:
        All lanes with `is_active` set; ties and duplicates are added to the report.
    """
    by_route: Dict[Tuple[str, str, PrimeLaneMode], List[LaneInput]] = {}
    seen_keys: Dict[Tuple[str, str, PrimeLaneMode, str], Optional[int]] = {}
    for lane in report.lanes:
        if lane.key in seen_keys:
            report.errors.append(
                PrimeImportIssue(
                    row=lane.row,
                    message=(
                        f"{lane.transporter_name} appears twice for {lane.origin_zone} → {lane.dest_zone} "
                        f"(first on line {seen_keys[lane.key]}); this row is skipped."
                    ),
                )
            )
            continue
        seen_keys[lane.key] = lane.row
        by_route.setdefault(lane.route, []).append(lane)
    chosen: List[LaneInput] = []
    for route, lanes in by_route.items():
        ranked = sorted(lanes, key=_preference)
        if len(ranked) > 1 and ranked[0].rates["rate_per_kg"] == ranked[1].rates["rate_per_kg"]:
            tied = ", ".join(lane.transporter_name for lane in ranked if lane.rates["rate_per_kg"] == ranked[0].rates["rate_per_kg"])
            report.warnings.append(
                PrimeImportIssue(
                    row=ranked[0].row,
                    message=f"tie at ₹{ranked[0].rates['rate_per_kg']}/kg on {route[0]} → {route[1]} ({tied}); activated {ranked[0].transporter_name}.",
                )
            )
        chosen.append(replace(ranked[0], is_active=True))
        chosen.extend(ranked[1:])
    return chosen


def _print_banner(title: str) -> None:
    """Section separator."""
    print("=" * BANNER_WIDTH)
    print(title)
    print("=" * BANNER_WIDTH)


def _print_issues(title: str, issues: Sequence[PrimeImportIssue]) -> None:
    """Numbered issue list."""
    print(f"{title}: {len(issues)}")
    for issue in issues:
        where = f"line {issue.row}" if issue.row is not None else "file"
        print(f"  [{where}] {issue.message}")


def print_sheet_report(report: SheetReport, lanes: Sequence[LaneInput]) -> None:
    """The reviewer's view: active choice per route, then errors and warnings."""
    active = sorted((lane for lane in lanes if lane.is_active), key=lambda lane: lane.dest_zone)
    print(f"Lanes read: {len(lanes)} ({len(active)} routes, {len(lanes) - len(active)} standby transporters)")
    for lane in active:
        standby = [other.transporter_name for other in lanes if other.route == lane.route and not other.is_active]
        print(
            f"  {lane.origin_zone} → {lane.dest_zone:<12} ₹{lane.rates['rate_per_kg']}/kg  "
            f"{lane.tat_hours:>3} h  {lane.delivery_type.value:<6} {lane.transporter_name}"
            + (f"   (standby: {', '.join(standby)})" if standby else "")
        )
    _print_issues("ERRORS (rows skipped)", report.errors)
    _print_issues("WARNINGS (review)", report.warnings)


def _print_plan(plan: LaneImportPlan) -> None:
    """Database plan summary."""
    report = plan.report()
    print(f"DB plan: create {report.created}, update {report.updated}, deactivate {report.deactivated}")
    _print_issues("DB plan errors (nothing is written when any)", report.errors)
    _print_issues("DB plan warnings", report.warnings)


def _parse_args() -> argparse.Namespace:
    """CLI flags (dry run unless `--execute`)."""
    parser = argparse.ArgumentParser(description="Import Prime lanes from Sheet1 (dry run by default).")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--file", type=Path, required=True, help="TSV/CSV export of the rate sheet")
    parser.add_argument("--markup", type=Decimal, default=DEFAULT_PRIME_MARKUP_PERCENT, help="Markup %% for every lane")
    parser.add_argument("--offline", action="store_true", help="Sheet report only; no database access")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", dest="execute", action="store_false", help="Roll back (default)")
    group.add_argument("--execute", dest="execute", action="store_true", help="Commit (needs go-ahead for live)")
    parser.set_defaults(execute=False)
    return parser.parse_args()


async def _import_once(args: argparse.Namespace, lanes: List[LaneInput]) -> int:
    """Plans against the tenant's zones/lanes and commits (execute) or rolls back."""
    async with AsyncSessionLocal() as session:
        await apply_transaction_timeouts(session)
        tenant = await get_tenant_by_slug(session, args.tenant_slug)
        if tenant is None:
            print(f"Tenant '{args.tenant_slug}' not found.")
            return EXIT_FAILED
        repo = PrimeRatesRepository(session)
        zones = {zone.name: zone.id for zone in await repo.list_zones(tenant.id)}
        plan = plan_lane_import(lanes, await repo.list_lanes(tenant.id), set(zones))
        _print_plan(plan)
        if plan.errors:
            await session.rollback()
            print("NOT WRITTEN (fix the errors above).")
            return EXIT_FAILED
        await apply_lane_plan(repo, tenant.id, plan, zones, None)
        if args.execute:
            await session.commit()
            print("COMMITTED.")
        else:
            await session.rollback()
            print("ROLLED BACK (dry run).")
    return EXIT_OK


async def _run(args: argparse.Namespace, lanes: List[LaneInput]) -> int:
    """Imports, then disposes the engine."""
    try:
        return await _import_once(args, lanes)
    finally:
        await async_engine.dispose()


def main() -> None:
    """CLI entry point."""
    args = _parse_args()
    mode = "OFFLINE REPORT" if args.offline else ("EXECUTE (COMMIT)" if args.execute else "DRY RUN (ROLLBACK)")
    _print_banner(f"PRIME LANES {args.tenant_slug} from {args.file.name} : {mode}")
    report = read_sheet1(args.file.read_text(encoding="utf-8-sig"), markup=to_money(args.markup))
    lanes = choose_active_lanes(report)
    print_sheet_report(report, lanes)
    if args.offline:
        raise SystemExit(EXIT_OK)
    raise SystemExit(asyncio.run(_run(args, lanes)))


if __name__ == "__main__":
    main()
