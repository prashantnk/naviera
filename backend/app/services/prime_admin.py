"""
Staff administration of the Logismart Prime rate table (API_CONTRACT.md §7, DESIGN.md v4 Q15).

- List zones (with pincode counts) and lanes (zones by name).
- Edit one lane (numbers + active flag); activating a lane deactivates the other active
  lane of the same route (one active lane per route, partial unique index).
- CSV export, and CSV re-import with a report (`dry_run` writes nothing). An import with
  any error writes nothing at all.

Access: every tenant staff role may read; only owner/admin may write; customers get 403.

The CSV parsing and import planning are pure functions (`parse_lanes_csv`,
`plan_lane_import`) so the Sheet1 importer script reuses exactly the same rules.

Spring analogy: a `@Service` with `@PreAuthorize`-style guards, a `@Transactional`
import method, and a pure planner in the same package for unit tests.
"""

import csv
import io
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple

from fastapi import Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.money import to_money
from app.core.permissions import is_tenant_admin, is_tenant_staff
from app.models.prime import DEFAULT_PRIME_MARKUP_PERCENT, PrimeDeliveryType, PrimeLane, PrimeLaneMode
from app.models.tenants import User
from app.repositories.prime_rates import LaneWithZones, PrimeRatesRepository
from app.schemas.v1.prime import (
    MAX_RATE_VALUE,
    MAX_TAT_HOURS,
    PrimeImportIssue,
    PrimeImportReport,
    PrimeLanePatch,
    PrimeLaneRead,
    PrimeZoneRead,
)

LANE_KEY_COLUMNS: Tuple[str, ...] = ("origin_zone", "dest_zone", "mode", "transporter_name")
"""Columns that identify a lane across tenants and re-imports (no database ids in the CSV)."""

POSITIVE_DECIMAL_COLUMNS: Tuple[str, ...] = ("rate_per_kg", "volumetric_divisor", "max_dimension_cm")
NON_NEGATIVE_DECIMAL_COLUMNS: Tuple[str, ...] = (
    "min_lr_charge",
    "docket_charge",
    "min_chargeable_kg",
    "oda_per_kg",
    "oda_min",
    "odd_weight_per_kg",
    "odd_weight_min",
    "pickup_per_kg",
    "pickup_min",
    "door_delivery_per_kg",
    "door_delivery_min",
)
DECIMAL_COLUMNS: Tuple[str, ...] = POSITIVE_DECIMAL_COLUMNS + NON_NEGATIVE_DECIMAL_COLUMNS
"""Every NUMERIC(10,2) rate column except `markup_percent` (handled separately: blank = default)."""

LANE_CSV_COLUMNS: Tuple[str, ...] = (
    LANE_KEY_COLUMNS
    + ("tat_hours", "rate_per_kg", "min_lr_charge", "docket_charge", "min_chargeable_kg")
    + ("volumetric_divisor", "max_dimension_cm", "delivery_type")
    + ("oda_per_kg", "oda_min", "odd_weight_per_kg", "odd_weight_min")
    + ("pickup_per_kg", "pickup_min", "door_delivery_per_kg", "door_delivery_min")
    + ("markup_percent", "is_active")
)
"""Export/import column order (API_CONTRACT §7 "CSV in the export format")."""

MAX_IMPORT_BYTES = 1_000_000
"""Upload cap: Sheet1 is ~10 KB; a megabyte is thousands of lanes."""

HEADER_ROW_NUMBER = 1
TRUE_TOKENS = frozenset({"true", "1", "yes", "y"})
FALSE_TOKENS = frozenset({"false", "0", "no", "n"})
MAX_RATE = Decimal(str(MAX_RATE_VALUE))

READ_FORBIDDEN_DETAIL = "Only Logismart staff can view Prime rates."
WRITE_FORBIDDEN_DETAIL = "Only a Tenant Owner or Admin can change Prime rates."
LANE_NOT_FOUND_DETAIL = "Prime lane not found."
ACTIVE_CONFLICT_DETAIL = "Another lane on this route was activated at the same time. Reload and try again."
FILE_TOO_LARGE_DETAIL = f"The CSV file is larger than {MAX_IMPORT_BYTES // 1_000_000} MB."
FILE_NOT_UTF8_DETAIL = "The CSV file must be UTF-8 text."

RouteKey = Tuple[str, str, PrimeLaneMode]
"""(origin zone name, destination zone name, mode)."""
LaneKey = Tuple[str, str, PrimeLaneMode, str]
"""(origin zone name, destination zone name, mode, transporter name upper-cased)."""


@dataclass(frozen=True)
class LaneInput:
    """One validated lane row (CSV or Sheet1), keyed by zone names + mode + transporter."""

    row: Optional[int]
    origin_zone: str
    dest_zone: str
    mode: PrimeLaneMode
    transporter_name: str
    tat_hours: int
    delivery_type: PrimeDeliveryType
    rates: Mapping[str, Decimal]
    markup_percent: Decimal
    is_active: bool

    @property
    def key(self) -> LaneKey:
        """Identity of the lane."""
        return (self.origin_zone, self.dest_zone, self.mode, self.transporter_name.upper())

    @property
    def route(self) -> RouteKey:
        """Route of the lane."""
        return (self.origin_zone, self.dest_zone, self.mode)


@dataclass
class LaneImportPlan:
    """What an import would change; `errors` non-empty means nothing may be written."""

    creates: List[LaneInput] = field(default_factory=list)
    updates: List[Tuple[PrimeLane, LaneInput]] = field(default_factory=list)
    deactivations: List[PrimeLane] = field(default_factory=list)
    errors: List[PrimeImportIssue] = field(default_factory=list)
    warnings: List[PrimeImportIssue] = field(default_factory=list)

    def report(self) -> PrimeImportReport:
        """The API report for this plan."""
        return PrimeImportReport(
            created=len(self.creates),
            updated=len(self.updates),
            deactivated=len(self.deactivations),
            errors=list(self.errors),
            warnings=list(self.warnings),
        )


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---- CSV parsing (pure) -----------------------------------------------------


def _parse_decimal(raw: str, column: str, *, positive: bool) -> Decimal:
    """
    Parses one rate cell to a 2-dp Decimal within NUMERIC(10,2).

    Raises:
        ValueError: blank, not a number, negative / not positive, or too large.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"{column} is empty.")
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{column} '{text}' is not a number.") from exc
    if not value.is_finite():
        raise ValueError(f"{column} '{text}' is not a number.")
    if positive and value <= 0:
        raise ValueError(f"{column} must be greater than 0.")
    if value < 0:
        raise ValueError(f"{column} cannot be negative.")
    if value > MAX_RATE:
        raise ValueError(f"{column} is too large.")
    return to_money(value)


def _parse_tat_hours(raw: str) -> int:
    """
    Parses `tat_hours` (whole hours, 1 … 60 days).

    Raises:
        ValueError: not a whole positive number of hours within range.
    """
    text = (raw or "").strip()
    if not text.isdigit() or not 0 < int(text) <= MAX_TAT_HOURS:
        raise ValueError(f"tat_hours '{text}' must be a whole number of hours between 1 and {MAX_TAT_HOURS}.")
    return int(text)


def _parse_bool(raw: str, column: str) -> bool:
    """
    Parses true/false, yes/no, 1/0.

    Raises:
        ValueError: anything else.
    """
    text = (raw or "").strip().lower()
    if text in TRUE_TOKENS:
        return True
    if text in FALSE_TOKENS:
        return False
    raise ValueError(f"{column} '{raw}' must be true or false.")


def _parse_enum_cell(raw: str, column: str, enum_cls: type) -> object:
    """
    Parses an enum value case-insensitively.

    Raises:
        ValueError: not one of the enum's values.
    """
    text = (raw or "").strip().upper()
    try:
        return enum_cls(text)
    except ValueError as exc:
        allowed = ", ".join(member.value for member in enum_cls)
        raise ValueError(f"{column} '{raw}' must be one of {allowed}.") from exc


def _required_text(raw: str, column: str) -> str:
    """
    A non-blank trimmed text cell.

    Raises:
        ValueError: blank.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"{column} is empty.")
    return text


def _parse_markup(raw: str, row: int, warnings: List[PrimeImportIssue]) -> Decimal:
    """`markup_percent`; blank means the 20 % default (with a warning)."""
    if not (raw or "").strip():
        warnings.append(
            PrimeImportIssue(row=row, message=f"markup_percent is empty; using {DEFAULT_PRIME_MARKUP_PERCENT}%.")
        )
        return DEFAULT_PRIME_MARKUP_PERCENT
    return _parse_decimal(raw, "markup_percent", positive=False)


def _parse_lane_row(cells: Mapping[str, str], row: int, warnings: List[PrimeImportIssue]) -> LaneInput:
    """
    Validates one CSV row.

    Raises:
        ValueError: the first problem found, in plain English.
    """
    return LaneInput(
        row=row,
        origin_zone=_required_text(cells.get("origin_zone", ""), "origin_zone"),
        dest_zone=_required_text(cells.get("dest_zone", ""), "dest_zone"),
        mode=_parse_enum_cell(cells.get("mode", ""), "mode", PrimeLaneMode),  # type: ignore[arg-type]
        transporter_name=_required_text(cells.get("transporter_name", ""), "transporter_name"),
        tat_hours=_parse_tat_hours(cells.get("tat_hours", "")),
        delivery_type=_parse_enum_cell(  # type: ignore[arg-type]
            cells.get("delivery_type", ""), "delivery_type", PrimeDeliveryType
        ),
        rates={
            column: _parse_decimal(cells.get(column, ""), column, positive=column in POSITIVE_DECIMAL_COLUMNS)
            for column in DECIMAL_COLUMNS
        },
        markup_percent=_parse_markup(cells.get("markup_percent", ""), row, warnings),
        is_active=_parse_bool(cells.get("is_active", ""), "is_active"),
    )


def _check_header(header: Sequence[str], plan: LaneImportPlan) -> bool:
    """Records missing (error) and unknown (warning) columns; True when all required columns exist."""
    present = {name.strip() for name in header}
    missing = [name for name in LANE_CSV_COLUMNS if name not in present]
    unknown = sorted(present - set(LANE_CSV_COLUMNS) - {""})
    if missing:
        plan.errors.append(PrimeImportIssue(row=HEADER_ROW_NUMBER, message=f"Missing columns: {', '.join(missing)}."))
    if unknown:
        plan.warnings.append(PrimeImportIssue(row=HEADER_ROW_NUMBER, message=f"Ignored columns: {', '.join(unknown)}."))
    return not missing


def parse_lanes_csv(text: str) -> Tuple[List[LaneInput], LaneImportPlan]:
    """
    Parses a lanes CSV in the export format.

    Args:
        text: The decoded CSV text.

    Returns:
        The valid rows, and a plan holding the parse errors/warnings (no changes yet).
    """
    plan = LaneImportPlan()
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        plan.errors.append(PrimeImportIssue(row=None, message="The CSV file is empty."))
        return [], plan
    if not _check_header(reader.fieldnames, plan):
        return [], plan
    inputs: List[LaneInput] = []
    for index, raw in enumerate(reader, start=HEADER_ROW_NUMBER + 1):
        cells = {(key or "").strip(): (value or "") for key, value in raw.items() if isinstance(value, str)}
        if not any(value.strip() for value in cells.values()):
            continue
        try:
            inputs.append(_parse_lane_row(cells, index, plan.warnings))
        except ValueError as exc:
            plan.errors.append(PrimeImportIssue(row=index, message=str(exc)))
    if not inputs and not plan.errors:
        plan.errors.append(PrimeImportIssue(row=None, message="The CSV file has no lane rows."))
    return inputs, plan


# ---- Import planning (pure) --------------------------------------------------


def _existing_key(item: LaneWithZones) -> LaneKey:
    """Identity of an existing lane."""
    return (item.origin_zone_name, item.dest_zone_name, PrimeLaneMode(item.lane.mode), item.lane.transporter_name.upper())


def _lane_differs(lane: PrimeLane, data: LaneInput) -> bool:
    """True when any stored value (other than a pure deactivation) differs from the row."""
    if lane.tat_hours != data.tat_hours or PrimeDeliveryType(lane.delivery_type) != data.delivery_type:
        return True
    if lane.transporter_name != data.transporter_name:
        return True
    if to_money(lane.markup_percent) != data.markup_percent:
        return True
    if any(to_money(getattr(lane, column)) != value for column, value in data.rates.items()):
        return True
    return data.is_active and not lane.is_active


def _reject_unknown_zones(inputs: Sequence[LaneInput], zone_names: Set[str], plan: LaneImportPlan) -> List[LaneInput]:
    """Drops rows naming a zone that does not exist (one error each)."""
    known: List[LaneInput] = []
    for data in inputs:
        missing = [name for name in (data.origin_zone, data.dest_zone) if name not in zone_names]
        if missing:
            plan.errors.append(
                PrimeImportIssue(
                    row=data.row,
                    message=f"Unknown zone {', '.join(repr(m) for m in missing)}; create it first (zones seed).",
                )
            )
        else:
            known.append(data)
    return known


def _reject_duplicates(inputs: Sequence[LaneInput], plan: LaneImportPlan) -> List[LaneInput]:
    """Drops repeated lane keys within the file (first row wins, one error per repeat)."""
    seen: Dict[LaneKey, Optional[int]] = {}
    unique: List[LaneInput] = []
    for data in inputs:
        if data.key in seen:
            plan.errors.append(
                PrimeImportIssue(
                    row=data.row,
                    message=(
                        f"Duplicate lane {data.origin_zone} → {data.dest_zone} ({data.transporter_name}); "
                        f"first seen on row {seen[data.key]}."
                    ),
                )
            )
            continue
        seen[data.key] = data.row
        unique.append(data)
    return unique


def _resolve_active_conflicts(
    inputs: Sequence[LaneInput], existing: Mapping[LaneKey, LaneWithZones], plan: LaneImportPlan
) -> List[PrimeLane]:
    """
    Enforces one active lane per route after the import.

    Two active rows for one route in the file → error. One active row in the file and an
    active lane not mentioned in the file → that lane is deactivated (warning).

    Returns:
        Existing lanes not in the file that must be deactivated.
    """
    file_keys = {data.key for data in inputs}
    active_in_file: Dict[RouteKey, List[LaneInput]] = {}
    for data in inputs:
        if data.is_active:
            active_in_file.setdefault(data.route, []).append(data)
    auto_off: List[PrimeLane] = []
    for route, rows in active_in_file.items():
        if len(rows) > 1:
            listed = ", ".join(f"row {row.row} ({row.transporter_name})" for row in rows)
            plan.errors.append(
                PrimeImportIssue(
                    row=rows[1].row,
                    message=f"Only one lane per route can be active: {route[0]} → {route[1]} has {listed}.",
                )
            )
            continue
        for key, item in existing.items():
            if key[:3] == route and key not in file_keys and item.lane.is_active:
                auto_off.append(item.lane)
                plan.warnings.append(
                    PrimeImportIssue(
                        row=rows[0].row,
                        message=(
                            f"{item.lane.transporter_name} on {route[0]} → {route[1]} was active and "
                            f"will be deactivated in favour of {rows[0].transporter_name}."
                        ),
                    )
                )
    return auto_off


def plan_lane_import(
    inputs: Sequence[LaneInput],
    existing: Sequence[LaneWithZones],
    zone_names: Set[str],
    plan: Optional[LaneImportPlan] = None,
) -> LaneImportPlan:
    """
    Decides creates, updates and deactivations for validated lane rows (pure, no writes).

    Lanes not mentioned in the file are left as they are, except an active lane displaced
    by an active row of the file on the same route.

    Args:
        inputs: Validated rows.
        existing: Current lanes of the tenant with zone names.
        zone_names: Names of the tenant's zones.
        plan: A plan already holding parse errors/warnings (extended in place).

    Returns:
        The plan.
    """
    plan = plan or LaneImportPlan()
    rows = _reject_duplicates(_reject_unknown_zones(inputs, zone_names, plan), plan)
    by_key = {_existing_key(item): item for item in existing}
    plan.deactivations.extend(_resolve_active_conflicts(rows, by_key, plan))
    for data in rows:
        current = by_key.get(data.key)
        if current is None:
            plan.creates.append(data)
            continue
        if current.lane.is_active and not data.is_active:
            plan.deactivations.append(current.lane)
        if _lane_differs(current.lane, data):
            plan.updates.append((current.lane, data))
    return plan


def _apply_input(lane: PrimeLane, data: LaneInput, user_id: Optional[uuid.UUID]) -> None:
    """Copies a row's values onto a lane (activation state included)."""
    lane.transporter_name = data.transporter_name
    lane.tat_hours = data.tat_hours
    lane.delivery_type = data.delivery_type
    lane.markup_percent = data.markup_percent
    lane.is_active = data.is_active
    for column, value in data.rates.items():
        setattr(lane, column, value)
    lane.updated_by = user_id
    lane.updated_at = _utc_now_naive()


def _new_lane(tenant_id: uuid.UUID, data: LaneInput, zone_ids: Mapping[str, uuid.UUID], user_id: Optional[uuid.UUID]) -> PrimeLane:
    """A new lane row from a validated input."""
    lane = PrimeLane(
        tenant_id=tenant_id,
        origin_zone_id=zone_ids[data.origin_zone],
        dest_zone_id=zone_ids[data.dest_zone],
        mode=data.mode,
        transporter_name=data.transporter_name,
        tat_hours=data.tat_hours,
        delivery_type=data.delivery_type,
        markup_percent=data.markup_percent,
        is_active=data.is_active,
        **dict(data.rates),
    )
    lane.updated_by = user_id
    return lane


async def apply_lane_plan(
    repository: PrimeRatesRepository,
    tenant_id: uuid.UUID,
    plan: LaneImportPlan,
    zone_ids: Mapping[str, uuid.UUID],
    user_id: Optional[uuid.UUID],
) -> None:
    """
    Stages a plan without errors: deactivations first (flushed, so the one-active index
    never sees two active lanes), then updates and creates. The caller commits.

    Args:
        repository: Repository on the caller's session.
        tenant_id: Tenant scope (new rows).
        plan: An error-free plan.
        zone_ids: Zone name -> id.
        user_id: The acting staff user (None for scripts).
    """
    now = _utc_now_naive()
    for lane in plan.deactivations:
        lane.is_active = False
        lane.updated_by = user_id
        lane.updated_at = now
        repository.add(lane)
    await repository.flush()
    for lane, data in plan.updates:
        _apply_input(lane, data, user_id)
        repository.add(lane)
    for data in plan.creates:
        repository.add(_new_lane(tenant_id, data, zone_ids, user_id))
    await repository.flush()


# ---- Read mapping + CSV export -------------------------------------------------


def _lane_read(lane: PrimeLane, origin_zone: str, dest_zone: str) -> PrimeLaneRead:
    """API shape of a lane (money as floats rounded to the paisa)."""
    numbers = {column: float(to_money(getattr(lane, column))) for column in DECIMAL_COLUMNS}
    return PrimeLaneRead(
        id=lane.id,
        origin_zone=origin_zone,
        dest_zone=dest_zone,
        mode=PrimeLaneMode(lane.mode),
        transporter_name=lane.transporter_name,
        tat_hours=lane.tat_hours,
        delivery_type=PrimeDeliveryType(lane.delivery_type),
        markup_percent=float(to_money(lane.markup_percent)),
        is_active=lane.is_active,
        updated_at=lane.updated_at,
        **numbers,
    )


def lanes_to_csv(items: Sequence[LaneWithZones]) -> str:
    """
    Renders lanes in the import format (round-trips through `parse_lanes_csv`).

    Args:
        items: Lanes with zone names.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(LANE_CSV_COLUMNS)
    for item in items:
        lane = item.lane
        values: Dict[str, str] = {
            "origin_zone": item.origin_zone_name,
            "dest_zone": item.dest_zone_name,
            "mode": PrimeLaneMode(lane.mode).value,
            "transporter_name": lane.transporter_name,
            "tat_hours": str(lane.tat_hours),
            "delivery_type": PrimeDeliveryType(lane.delivery_type).value,
            "markup_percent": str(to_money(lane.markup_percent)),
            "is_active": "true" if lane.is_active else "false",
        }
        values.update({column: str(to_money(getattr(lane, column))) for column in DECIMAL_COLUMNS})
        writer.writerow([values[column] for column in LANE_CSV_COLUMNS])
    return buffer.getvalue()


TEMPLATE_SAMPLE_ROWS: Tuple[Mapping[str, str], ...] = (
    {
        "origin_zone": "Delhi NCR",
        "dest_zone": "Mumbai",
        "mode": PrimeLaneMode.SURFACE.value,
        "transporter_name": "SAMEER TRANSPORT",
        "tat_hours": "30",
        "rate_per_kg": "10.00",
        "min_lr_charge": "500.00",
        "docket_charge": "100.00",
        "min_chargeable_kg": "50.00",
        "volumetric_divisor": "4500.00",
        "max_dimension_cm": "240.00",
        "delivery_type": PrimeDeliveryType.GODOWN.value,
        "oda_per_kg": "2.00",
        "oda_min": "800.00",
        "odd_weight_per_kg": "2.00",
        "odd_weight_min": "800.00",
        "pickup_per_kg": "1.00",
        "pickup_min": "600.00",
        "door_delivery_per_kg": "1.00",
        "door_delivery_min": "600.00",
        "markup_percent": "20.00",
        "is_active": "true",
    },
    {
        "origin_zone": "Bengaluru",
        "dest_zone": "Hyderabad",
        "mode": PrimeLaneMode.SURFACE.value,
        "transporter_name": "SAI CARGO",
        "tat_hours": "24",
        "rate_per_kg": "8.50",
        "min_lr_charge": "450.00",
        "docket_charge": "100.00",
        "min_chargeable_kg": "50.00",
        "volumetric_divisor": "4500.00",
        "max_dimension_cm": "240.00",
        "delivery_type": PrimeDeliveryType.GODOWN.value,
        "oda_per_kg": "2.00",
        "oda_min": "750.00",
        "odd_weight_per_kg": "2.00",
        "odd_weight_min": "800.00",
        "pickup_per_kg": "1.00",
        "pickup_min": "500.00",
        "door_delivery_per_kg": "1.00",
        "door_delivery_min": "500.00",
        "markup_percent": "20.00",
        "is_active": "true",
    },
)
"""Two realistic sample rows included in the downloadable Prime lanes CSV template."""


def template_lanes_csv() -> str:
    """
    Renders a downloadable sample CSV template with `LANE_CSV_COLUMNS` and 2 sample rows.

    Returns:
        CSV text ready for download and directly compatible with `parse_lanes_csv`.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(LANE_CSV_COLUMNS)
    for row in TEMPLATE_SAMPLE_ROWS:
        writer.writerow([row[column] for column in LANE_CSV_COLUMNS])
    return buffer.getvalue()


def _decode_upload(content: bytes) -> str:
    """
    Decodes an uploaded CSV (UTF-8, optional BOM from Excel).

    Raises:
        HTTPException(413/400): too large or not UTF-8.
    """
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=FILE_TOO_LARGE_DETAIL)
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=FILE_NOT_UTF8_DETAIL) from exc


# ---- Service ------------------------------------------------------------------


class PrimeAdminService:
    """Staff list/edit/import/export of Prime zones and lanes."""

    def __init__(self, repository: PrimeRatesRepository) -> None:
        """
        Args:
            repository: Prime repository on the request session.
        """
        self.repository = repository

    @staticmethod
    def _assert_can_read(user: User) -> None:
        """403 unless the user is tenant staff."""
        if not is_tenant_staff(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=READ_FORBIDDEN_DETAIL)

    @staticmethod
    def _assert_can_write(user: User) -> None:
        """403 unless the user is a tenant owner/admin."""
        if not is_tenant_admin(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=WRITE_FORBIDDEN_DETAIL)

    async def list_zones(self, tenant_id: uuid.UUID, user: User) -> List[PrimeZoneRead]:
        """Zones with pincode counts (staff)."""
        self._assert_can_read(user)
        rows = await self.repository.list_zones_with_counts(tenant_id)
        return [PrimeZoneRead(id=row.zone.id, name=row.zone.name, pincode_count=row.pincode_count) for row in rows]

    async def list_lanes(self, tenant_id: uuid.UUID, user: User, *, active_only: bool) -> List[PrimeLaneRead]:
        """Lanes with zone names (staff)."""
        self._assert_can_read(user)
        rows = await self.repository.list_lanes(tenant_id, active_only=active_only)
        return [_lane_read(row.lane, row.origin_zone_name, row.dest_zone_name) for row in rows]

    async def export_csv(self, tenant_id: uuid.UUID, user: User) -> str:
        """All lanes as CSV in the import format (staff)."""
        self._assert_can_read(user)
        return lanes_to_csv(await self.repository.list_lanes(tenant_id))

    def template_csv(self, user: User) -> str:
        """Sample CSV template with exact import headers and 2 sample rows (staff)."""
        self._assert_can_read(user)
        return template_lanes_csv()

    async def patch_lane(
        self, tenant_id: uuid.UUID, user: User, lane_id: uuid.UUID, patch: PrimeLanePatch
    ) -> PrimeLaneRead:
        """
        Applies a partial edit (owner/admin). Activating a lane deactivates the route's other active lane.

        Raises:
            HTTPException(403/404/409): not admin, unknown lane, concurrent activation.
        """
        self._assert_can_write(user)
        lane = await self.repository.get_lane(tenant_id, lane_id)
        if lane is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=LANE_NOT_FOUND_DETAIL)
        changes = patch.model_dump(exclude_unset=True, exclude_none=True)
        activate = changes.pop("is_active", None)
        try:
            if activate is True and not lane.is_active:
                await self.repository.deactivate_route(
                    tenant_id, lane.origin_zone_id, lane.dest_zone_id, PrimeLaneMode(lane.mode), except_lane_ids=[lane.id]
                )
                await self.repository.flush()
            self._apply_patch(lane, changes, activate, user.id)
            self.repository.add(lane)
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_CONFLICT_DETAIL) from exc
        await self.repository.refresh(lane)
        names = await self.repository.get_zone_names(tenant_id, [lane.origin_zone_id, lane.dest_zone_id])
        return _lane_read(lane, names.get(lane.origin_zone_id, ""), names.get(lane.dest_zone_id, ""))

    @staticmethod
    def _apply_patch(lane: PrimeLane, changes: Mapping[str, object], activate: Optional[bool], user_id: uuid.UUID) -> None:
        """Copies patched numbers (rounded to the paisa) and the active flag onto the lane."""
        for column, value in changes.items():
            setattr(lane, column, int(value) if column == "tat_hours" else to_money(value))  # type: ignore[arg-type]
        if activate is not None:
            lane.is_active = activate
        lane.updated_by = user_id
        lane.updated_at = _utc_now_naive()

    async def import_csv(
        self, tenant_id: uuid.UUID, user: User, content: bytes, *, dry_run: bool
    ) -> PrimeImportReport:
        """
        Imports lanes from a CSV in the export format (owner/admin).

        All-or-nothing: any error → nothing written. `dry_run` → report only.

        Raises:
            HTTPException(403/413/400): not admin, file too large, not UTF-8.
        """
        self._assert_can_write(user)
        inputs, plan = parse_lanes_csv(_decode_upload(content))
        zones = await self.repository.list_zones(tenant_id)
        zone_ids = {zone.name: zone.id for zone in zones}
        existing = await self.repository.list_lanes(tenant_id)
        plan = plan_lane_import(inputs, existing, set(zone_ids), plan)
        if dry_run or plan.errors:
            return plan.report()
        try:
            await apply_lane_plan(self.repository, tenant_id, plan, zone_ids, user.id)
            await self.repository.commit()
        except IntegrityError as exc:
            await self.repository.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=ACTIVE_CONFLICT_DETAIL) from exc
        return plan.report()


def get_prime_admin_service(session: AsyncSession = Depends(get_session)) -> PrimeAdminService:
    """FastAPI factory wiring the repository on the request session."""
    return PrimeAdminService(PrimeRatesRepository(session))
