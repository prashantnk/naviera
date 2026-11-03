"""
Pure unit tests for Logismart Prime pricing and the lanes admin (DESIGN.md v4 §C.3, API_CONTRACT §7).

No database: the provider runs on in-memory lane terms or a fake repository, the admin
service on a fake repository, and the HTTP layer on a local FastAPI app with overridden
dependencies.

Reference lane (Sheet1 terms, also the `logismart-test` fixture): rate ₹10/kg, min LR ₹500,
docket ₹100, min 50 kg, L×B×H/4500, max side 240 cm, GODOWN, ODA ₹2/kg min ₹800, odd
weight ₹2/kg min ₹800, pickup ₹1/kg min ₹600, door delivery ₹1/kg min ₹600, TAT 30 h,
markup 20 %.
"""

import json
import uuid
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.v1.endpoints import pricing_prime
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.pickups import DimensionUnit, ServiceOption, ShipmentType, WeightUnit
from app.models.prime import PrimeDeliveryType, PrimeLane, PrimeLaneMode, PrimeZone
from app.models.tenants import UserRole
from app.repositories.prime_rates import LaneWithZones, PincodeZone, ZoneWithCount
from app.schemas.v1.pickups import PackageCreate
from app.schemas.v1.prime import PrimeLanePatch
from app.services.pricing.prime import PrimeLaneTerms, PrimeProvider, price_on_terms
from app.services.pricing.types import (
    CarrierLegKind,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)
from app.services.prime_admin import (
    LANE_CSV_COLUMNS,
    PrimeAdminService,
    get_prime_admin_service,
    lanes_to_csv,
    parse_lanes_csv,
    plan_lane_import,
)
from scripts.import_prime_lanes import choose_active_lanes, read_sheet1
from scripts.seed_prime_zones import (
    ALIAS_INDEX,
    PincodeRecord,
    match_pincodes,
    zone_for_place,
)

TENANT_ID = uuid.uuid4()
DELHI = "Delhi NCR"
MUMBAI = "Mumbai"
PUNE = "Pune"


def _terms(**overrides: Any) -> PrimeLaneTerms:
    """The reference lane terms, optionally changed."""
    base = PrimeLaneTerms(
        lane_id=str(uuid.uuid4()),
        origin_zone=DELHI,
        dest_zone=MUMBAI,
        mode=PrimeLaneMode.SURFACE,
        delivery_type=PrimeDeliveryType.GODOWN,
        transporter_name="SAMEER TRANSPORT",
        tat_hours=30,
        is_oda=False,
        rate_per_kg=Decimal("10.00"),
        min_lr_charge=Decimal("500.00"),
        docket_charge=Decimal("100.00"),
        min_chargeable_kg=Decimal("50.00"),
        volumetric_divisor=Decimal("4500.00"),
        max_dimension_cm=Decimal("240.00"),
        oda_per_kg=Decimal("2.00"),
        oda_min=Decimal("800.00"),
        odd_weight_per_kg=Decimal("2.00"),
        odd_weight_min=Decimal("800.00"),
        pickup_per_kg=Decimal("1.00"),
        pickup_min=Decimal("600.00"),
        door_delivery_per_kg=Decimal("1.00"),
        door_delivery_min=Decimal("600.00"),
        markup_percent=Decimal("20.00"),
    )
    return replace(base, **overrides)


def _box(
    weight: float, length: float = 40, breadth: float = 30, height: float = 30, count: int = 1, **kw: Any
) -> PackageCreate:
    """One package line (cm / kg unless overridden)."""
    return PackageCreate(length=length, breadth=breadth, height=height, weight=weight, box_count=count, **kw)


def _spec(*packages: PackageCreate, **overrides: Any) -> ParcelSpec:
    """A forward Delhi → Mumbai parcel."""
    values: Dict[str, Any] = {"pickup_pincode": "122001", "delivery_pincode": "400001", "packages": tuple(packages)}
    values.update(overrides)
    return ParcelSpec(**values)


def _lines(quote: Any) -> Dict[str, Decimal]:
    """Forward cost lines by code."""
    return {line.code: line.amount for line in quote.forward.lines}


# ---- Formula -----------------------------------------------------------------


def test_light_parcel_is_billed_on_minimum_weight_and_minimum_pickup() -> None:
    quote = price_on_terms(_terms(), _spec(_box(10)))
    assert quote.serviceable and quote.option == ServiceOption.PRIME_SURFACE
    assert _lines(quote) == {"FREIGHT": Decimal("500.00"), "DOCKET": Decimal("100.00"), "PICKUP": Decimal("600.00")}
    assert quote.forward.cost == Decimal("1200.00")
    assert quote.forward.charged_weight_kg == Decimal("50.000")
    assert quote.forward.transit_days == 2
    assert quote.forward.source == PriceSource.TABLE
    assert quote.markup_percent == Decimal("20.00")
    assert quote.cod_supported is False


def test_rto_leg_is_100_percent_of_forward() -> None:
    quote = price_on_terms(_terms(), _spec(_box(10)))
    assert quote.rto.kind == CarrierLegKind.RTO
    assert quote.rto.cost == quote.forward.cost
    assert [line.code for line in quote.rto.lines] == [line.code for line in quote.forward.lines]


def test_oda_destination_adds_oda_minimum() -> None:
    quote = price_on_terms(_terms(is_oda=True), _spec(_box(10)))
    assert _lines(quote)["ODA"] == Decimal("800.00")
    assert quote.forward.cost == Decimal("2000.00")


def test_oda_per_kg_beats_minimum_on_heavy_parcel() -> None:
    quote = price_on_terms(_terms(is_oda=True), _spec(_box(150, count=3)))
    assert quote.forward.charged_weight_kg == Decimal("450.000")
    assert _lines(quote)["ODA"] == Decimal("900.00")


def test_door_delivery_only_charged_on_godown_lane() -> None:
    godown = price_on_terms(_terms(), _spec(_box(10), door_delivery=True))
    door = price_on_terms(_terms(delivery_type=PrimeDeliveryType.DOOR), _spec(_box(10), door_delivery=True))
    assert _lines(godown)["DOOR_DELIVERY"] == Decimal("600.00")
    assert godown.forward.cost == Decimal("1800.00")
    assert "DOOR_DELIVERY" not in _lines(door)
    assert door.forward.cost == Decimal("1200.00")


def test_odd_weight_box_over_200_kg() -> None:
    quote = price_on_terms(_terms(), _spec(_box(250, 100, 100, 100)))
    assert quote.forward.charged_weight_kg == Decimal("250.000")
    assert _lines(quote) == {
        "FREIGHT": Decimal("2500.00"),
        "DOCKET": Decimal("100.00"),
        "PICKUP": Decimal("600.00"),
        "ODD_WEIGHT": Decimal("800.00"),
    }
    assert quote.forward.cost == Decimal("4000.00")


def test_exactly_200_kg_box_is_not_odd_weight() -> None:
    assert "ODD_WEIGHT" not in _lines(price_on_terms(_terms(), _spec(_box(200))))


def test_heavy_shipment_per_kg_charges_beat_minimums() -> None:
    quote = price_on_terms(_terms(), _spec(_box(250, count=4)))
    assert _lines(quote) == {
        "FREIGHT": Decimal("10000.00"),
        "DOCKET": Decimal("100.00"),
        "PICKUP": Decimal("1000.00"),
        "ODD_WEIGHT": Decimal("2000.00"),
    }
    assert quote.forward.cost == Decimal("13100.00")


def test_volumetric_weight_wins_when_larger() -> None:
    quote = price_on_terms(_terms(), _spec(_box(50, 120, 100, 90, count=2)))
    assert quote.forward.charged_weight_kg == Decimal("480.000")
    assert quote.forward.cost == Decimal("5500.00")


def test_grams_are_converted_to_kg() -> None:
    quote = price_on_terms(_terms(), _spec(_box(60000, weight_unit=WeightUnit.G)))
    assert quote.forward.charged_weight_kg == Decimal("60.000")
    assert quote.forward.cost == Decimal("1300.00")


def test_fractional_weight_is_rounded_to_the_paisa() -> None:
    quote = price_on_terms(_terms(rate_per_kg=Decimal("10.55")), _spec(_box(70.333)))
    assert _lines(quote)["FREIGHT"] == Decimal("742.01")


def test_box_side_over_maximum_is_too_large() -> None:
    quote = price_on_terms(_terms(), _spec(_box(10, 241, 30, 30)))
    assert not quote.serviceable
    assert quote.unavailable_code == QuoteUnavailableCode.TOO_LARGE
    assert "240.00 cm" in quote.unavailable_reason


def test_box_side_in_feet_is_converted_before_the_size_check() -> None:
    too_long = price_on_terms(_terms(), _spec(_box(10, 8, 1, 1, dimension_unit=DimensionUnit.FT)))
    fits = price_on_terms(_terms(), _spec(_box(10, 7.5, 1, 1, dimension_unit=DimensionUnit.FT)))
    assert too_long.unavailable_code == QuoteUnavailableCode.TOO_LARGE
    assert fits.serviceable


def test_box_side_exactly_at_maximum_is_allowed() -> None:
    assert price_on_terms(_terms(), _spec(_box(10, 240, 30, 30))).serviceable


def test_min_lr_top_up_reaches_the_minimum() -> None:
    cheap = _terms(rate_per_kg=Decimal("1.00"), docket_charge=Decimal("0"), pickup_min=Decimal("0"),
                   pickup_per_kg=Decimal("0"))
    quote = price_on_terms(cheap, _spec(_box(10)))
    assert _lines(quote)["MIN_LR_TOPUP"] == Decimal("450.00")
    assert quote.forward.cost == Decimal("500.00")


def test_no_top_up_when_above_minimum() -> None:
    assert "MIN_LR_TOPUP" not in _lines(price_on_terms(_terms(), _spec(_box(10))))


def test_blind_pickup_is_billed_on_minimum_weight() -> None:
    quote = price_on_terms(_terms(), _spec(is_blind_pickup=True, estimated_box_count=5))
    assert quote.forward.charged_weight_kg == Decimal("50.000")
    assert quote.forward.cost == Decimal("1200.00")


def test_reverse_shipment_is_not_serviceable() -> None:
    quote = price_on_terms(_terms(), _spec(_box(10), shipment_type=ShipmentType.REVERSE))
    assert quote.unavailable_code == QuoteUnavailableCode.NOT_SERVICEABLE


def test_snapshot_and_details_are_json_safe_and_requote_matches() -> None:
    spec = _spec(_box(250, 100, 100, 100), door_delivery=True)
    quote = price_on_terms(_terms(is_oda=True), spec)
    json.dumps(quote.snapshot)
    json.dumps(dict(quote.forward.details))
    snapshot = json.loads(json.dumps(quote.snapshot))
    again = PrimeProvider.requote(snapshot, spec)
    assert again.forward.lines == quote.forward.lines
    assert again.rto.cost == quote.rto.cost
    assert again.snapshot == quote.snapshot
    assert snapshot["rate_per_kg"] == "10.00" and snapshot["is_oda"] is True


def test_requote_reprices_changed_parcel_on_frozen_terms() -> None:
    quote = price_on_terms(_terms(), _spec(_box(10)))
    heavier = PrimeProvider.requote(quote.snapshot, _spec(_box(100)))
    assert heavier.forward.cost == Decimal("1700.00")


def test_requote_rejects_malformed_snapshot() -> None:
    with pytest.raises(ValueError):
        PrimeProvider.requote({"lane_id": "x"}, _spec(_box(10)))


# ---- Provider with a fake repository -------------------------------------------


class _FakeQuoteRepository:
    """Zone + lane lookups from dicts."""

    def __init__(self, pins: Dict[str, PincodeZone], lane: Optional[PrimeLane]) -> None:
        self.pins = pins
        self.lane = lane

    async def get_pincode_zone(self, tenant_id: uuid.UUID, pincode: str) -> Optional[PincodeZone]:
        return self.pins.get(pincode)

    async def get_active_lane(self, tenant_id, origin_zone_id, dest_zone_id, mode) -> Optional[PrimeLane]:
        assert mode == PrimeLaneMode.SURFACE
        return self.lane


def _zone(name: str) -> PrimeZone:
    return PrimeZone(id=uuid.uuid4(), tenant_id=TENANT_ID, name=name)


def _lane_row(origin: PrimeZone, dest: PrimeZone, transporter: str = "SAMEER TRANSPORT", **overrides: Any) -> PrimeLane:
    """A lane row with the reference numbers."""
    terms = _terms()
    numbers = {name: getattr(terms, name) for name in (
        "rate_per_kg", "min_lr_charge", "docket_charge", "min_chargeable_kg", "volumetric_divisor",
        "max_dimension_cm", "oda_per_kg", "oda_min", "odd_weight_per_kg", "odd_weight_min", "pickup_per_kg",
        "pickup_min", "door_delivery_per_kg", "door_delivery_min", "markup_percent")}
    values: Dict[str, Any] = dict(
        id=uuid.uuid4(), tenant_id=TENANT_ID, origin_zone_id=origin.id, dest_zone_id=dest.id,
        mode=PrimeLaneMode.SURFACE, transporter_name=transporter, tat_hours=30,
        delivery_type=PrimeDeliveryType.GODOWN, is_active=True, updated_at=datetime(2026, 10, 30), **numbers,
    )
    values.update(overrides)
    return PrimeLane(**values)


def _provider(repo: _FakeQuoteRepository) -> PrimeProvider:
    provider = PrimeProvider(session=None)  # type: ignore[arg-type]
    provider.repository = repo  # type: ignore[assignment]
    return provider


async def test_provider_prices_active_lane_with_destination_oda_flag() -> None:
    delhi, mumbai = _zone(DELHI), _zone(MUMBAI)
    lane = _lane_row(delhi, mumbai)
    repo = _FakeQuoteRepository(
        {"122001": PincodeZone(delhi, False), "400009": PincodeZone(mumbai, True)}, lane
    )
    quote = await _provider(repo).quote(TENANT_ID, _spec(_box(10), delivery_pincode="400009"))
    assert quote.forward.cost == Decimal("2000.00")
    assert quote.snapshot["lane_id"] == str(lane.id)
    assert quote.snapshot["origin_zone"] == DELHI and quote.snapshot["dest_zone"] == MUMBAI
    assert quote.forward.details["is_oda"] is True


async def test_provider_unknown_pickup_pincode_is_no_prime_lane() -> None:
    quote = await _provider(_FakeQuoteRepository({}, None)).quote(TENANT_ID, _spec(_box(10)))
    assert quote.unavailable_code == QuoteUnavailableCode.NO_PRIME_LANE
    assert "122001" in quote.unavailable_reason


async def test_provider_unknown_delivery_pincode_is_no_prime_lane() -> None:
    repo = _FakeQuoteRepository({"122001": PincodeZone(_zone(DELHI), False)}, None)
    quote = await _provider(repo).quote(TENANT_ID, _spec(_box(10)))
    assert quote.unavailable_code == QuoteUnavailableCode.NO_PRIME_LANE
    assert "400001" in quote.unavailable_reason


async def test_provider_no_active_lane_names_both_zones() -> None:
    repo = _FakeQuoteRepository(
        {"122001": PincodeZone(_zone(DELHI), False), "400001": PincodeZone(_zone(MUMBAI), False)}, None
    )
    quote = await _provider(repo).quote(TENANT_ID, _spec(_box(10)))
    assert quote.unavailable_code == QuoteUnavailableCode.NO_PRIME_LANE
    assert quote.unavailable_reason == "Logismart Prime has no rate from Delhi NCR to Mumbai yet."


# ---- CSV parse + import plan ----------------------------------------------------


def _csv_row(**overrides: str) -> Dict[str, str]:
    row = {
        "origin_zone": DELHI, "dest_zone": MUMBAI, "mode": "SURFACE", "transporter_name": "SAMEER TRANSPORT",
        "tat_hours": "30", "rate_per_kg": "10", "min_lr_charge": "500", "docket_charge": "100",
        "min_chargeable_kg": "50", "volumetric_divisor": "4500", "max_dimension_cm": "240",
        "delivery_type": "GODOWN", "oda_per_kg": "2", "oda_min": "800", "odd_weight_per_kg": "2",
        "odd_weight_min": "800", "pickup_per_kg": "1", "pickup_min": "600", "door_delivery_per_kg": "1",
        "door_delivery_min": "600", "markup_percent": "20", "is_active": "true",
    }
    row.update(overrides)
    return row


def _csv(rows: Sequence[Dict[str, str]], columns: Sequence[str] = LANE_CSV_COLUMNS) -> str:
    lines = [",".join(columns)] + [",".join(row.get(column, "") for column in columns) for row in rows]
    return "\n".join(lines) + "\n"


def test_parse_valid_csv() -> None:
    inputs, plan = parse_lanes_csv(_csv([_csv_row()]))
    assert not plan.errors and len(inputs) == 1
    assert inputs[0].rates["rate_per_kg"] == Decimal("10.00")
    assert inputs[0].delivery_type == PrimeDeliveryType.GODOWN and inputs[0].is_active


def test_parse_reports_bad_cells_with_row_numbers() -> None:
    rows = [_csv_row(rate_per_kg="NA"), _csv_row(transporter_name="X", oda_min="-1"), _csv_row(transporter_name="Y", mode="AIR")]
    inputs, plan = parse_lanes_csv(_csv(rows))
    assert inputs == []
    assert [(issue.row, issue.message.split(" ")[0]) for issue in plan.errors] == [
        (2, "rate_per_kg"), (3, "oda_min"), (4, "mode")
    ]


def test_parse_missing_column_is_an_error() -> None:
    _, plan = parse_lanes_csv(_csv([_csv_row()], columns=LANE_CSV_COLUMNS[:-1]))
    assert plan.errors[0].row == 1 and "is_active" in plan.errors[0].message


def test_parse_blank_markup_uses_default_with_warning() -> None:
    inputs, plan = parse_lanes_csv(_csv([_csv_row(markup_percent="")]))
    assert inputs[0].markup_percent == Decimal("20.00")
    assert plan.warnings and plan.warnings[0].row == 2


def _existing(lane: PrimeLane, origin: str = DELHI, dest: str = MUMBAI) -> LaneWithZones:
    return LaneWithZones(lane=lane, origin_zone_name=origin, dest_zone_name=dest)


def test_plan_creates_updates_and_deactivates() -> None:
    delhi, mumbai, pune = _zone(DELHI), _zone(MUMBAI), _zone(PUNE)
    unchanged = _lane_row(delhi, mumbai)
    to_update = _lane_row(delhi, pune, transporter="SAI CARGO")
    rows = [
        _csv_row(),
        _csv_row(dest_zone=PUNE, transporter_name="SAI CARGO", rate_per_kg="12", is_active="false"),
        _csv_row(dest_zone=PUNE, transporter_name="NEW CO", rate_per_kg="9"),
    ]
    inputs, plan = parse_lanes_csv(_csv(rows))
    plan = plan_lane_import(inputs, [_existing(unchanged), _existing(to_update, dest=PUNE)], {DELHI, MUMBAI, PUNE}, plan)
    assert not plan.errors
    report = plan.report()
    assert (report.created, report.updated, report.deactivated) == (1, 1, 1)
    assert plan.deactivations == [to_update]


def test_plan_two_active_lanes_for_one_route_is_an_error() -> None:
    rows = [_csv_row(), _csv_row(transporter_name="SAI CARGO")]
    inputs, plan = parse_lanes_csv(_csv(rows))
    plan = plan_lane_import(inputs, [], {DELHI, MUMBAI}, plan)
    assert len(plan.errors) == 1 and "Only one lane per route" in plan.errors[0].message


def test_plan_active_row_displaces_unlisted_active_lane() -> None:
    old = _lane_row(_zone(DELHI), _zone(MUMBAI), transporter="OLD CO")
    inputs, plan = parse_lanes_csv(_csv([_csv_row()]))
    plan = plan_lane_import(inputs, [_existing(old)], {DELHI, MUMBAI}, plan)
    assert plan.deactivations == [old] and plan.warnings
    assert plan.report().created == 1


def test_plan_unknown_zone_and_duplicate_rows_are_errors() -> None:
    rows = [_csv_row(), _csv_row(), _csv_row(dest_zone="Atlantis")]
    inputs, plan = parse_lanes_csv(_csv(rows))
    plan = plan_lane_import(inputs, [], {DELHI, MUMBAI}, plan)
    messages = [issue.message for issue in plan.errors]
    assert any("Atlantis" in message for message in messages)
    assert any("Duplicate lane" in message for message in messages)


def test_export_round_trips_through_import_as_no_change() -> None:
    lane = _lane_row(_zone(DELHI), _zone(MUMBAI))
    text = lanes_to_csv([_existing(lane)])
    inputs, plan = parse_lanes_csv(text)
    plan = plan_lane_import(inputs, [_existing(lane)], {DELHI, MUMBAI}, plan)
    report = plan.report()
    assert not report.errors and (report.created, report.updated, report.deactivated) == (0, 0, 0)


# ---- Admin service access + PATCH ----------------------------------------------


class _FakeAdminRepository:
    """In-memory admin repository."""

    def __init__(self, lanes: List[LaneWithZones]) -> None:
        self.lanes = lanes
        self.committed = False
        self.deactivated_routes: List[Any] = []

    async def list_zones_with_counts(self, tenant_id):
        return [ZoneWithCount(zone=_zone(DELHI), pincode_count=1)]

    async def list_zones(self, tenant_id):
        return [_zone(DELHI), _zone(MUMBAI)]

    async def list_lanes(self, tenant_id, *, active_only=False):
        return [item for item in self.lanes if item.lane.is_active or not active_only]

    async def get_lane(self, tenant_id, lane_id):
        return next((item.lane for item in self.lanes if item.lane.id == lane_id), None)

    async def deactivate_route(self, tenant_id, origin, dest, mode, *, except_lane_ids=()):
        self.deactivated_routes.append((origin, dest, mode, tuple(except_lane_ids)))
        for item in self.lanes:
            if item.lane.id not in except_lane_ids and item.lane.origin_zone_id == origin and item.lane.dest_zone_id == dest:
                item.lane.is_active = False
        return 1

    async def get_zone_names(self, tenant_id, zone_ids):
        return {item.lane.origin_zone_id: item.origin_zone_name for item in self.lanes} | {
            item.lane.dest_zone_id: item.dest_zone_name for item in self.lanes
        }

    def add(self, entity): ...

    async def flush(self): ...

    async def commit(self):
        self.committed = True

    async def rollback(self): ...

    async def refresh(self, entity): ...


def _user(role: UserRole) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), role=role)


async def test_customers_cannot_read_lanes() -> None:
    service = PrimeAdminService(_FakeAdminRepository([]))  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as caught:
        await service.list_lanes(TENANT_ID, _user(UserRole.customer), active_only=False)
    assert caught.value.status_code == 403


async def test_read_only_staff_can_read_but_not_write() -> None:
    lane = _lane_row(_zone(DELHI), _zone(MUMBAI))
    service = PrimeAdminService(_FakeAdminRepository([_existing(lane)]))  # type: ignore[arg-type]
    rows = await service.list_lanes(TENANT_ID, _user(UserRole.read_only_user), active_only=True)
    assert rows[0].origin_zone == DELHI and rows[0].rate_per_kg == 10.0
    with pytest.raises(HTTPException) as caught:
        await service.patch_lane(TENANT_ID, _user(UserRole.operations_user), lane.id, PrimeLanePatch(rate_per_kg=11))
    assert caught.value.status_code == 403


async def test_admin_activation_deactivates_the_route_first() -> None:
    delhi, mumbai = _zone(DELHI), _zone(MUMBAI)
    active = _lane_row(delhi, mumbai)
    standby = _lane_row(delhi, mumbai, transporter="SAI CARGO", is_active=False)
    repo = _FakeAdminRepository([_existing(active), _existing(standby)])
    service = PrimeAdminService(repo)  # type: ignore[arg-type]
    result = await service.patch_lane(
        TENANT_ID, _user(UserRole.admin), standby.id, PrimeLanePatch(is_active=True, rate_per_kg=9.555)
    )
    assert result.is_active and result.rate_per_kg == 9.56
    assert active.is_active is False and repo.committed
    assert repo.deactivated_routes[0][3] == (standby.id,)


async def test_patch_unknown_lane_is_404() -> None:
    service = PrimeAdminService(_FakeAdminRepository([]))  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as caught:
        await service.patch_lane(TENANT_ID, _user(UserRole.owner), uuid.uuid4(), PrimeLanePatch(tat_hours=24))
    assert caught.value.status_code == 404


async def test_import_with_errors_writes_nothing() -> None:
    repo = _FakeAdminRepository([])
    service = PrimeAdminService(repo)  # type: ignore[arg-type]
    report = await service.import_csv(
        TENANT_ID, _user(UserRole.admin), _csv([_csv_row(rate_per_kg="abc")]).encode(), dry_run=False
    )
    assert report.errors and not repo.committed


# ---- HTTP layer -------------------------------------------------------------------


def _client(service: PrimeAdminService, role: UserRole) -> TestClient:
    local = FastAPI()
    local.include_router(pricing_prime.router, prefix="/pricing")
    local.dependency_overrides[get_current_active_user] = lambda: _user(role)
    local.dependency_overrides[get_tenant_from_header] = lambda: SimpleNamespace(id=TENANT_ID)
    local.dependency_overrides[get_prime_admin_service] = lambda: service
    return TestClient(local)


def test_http_export_and_dry_run_import() -> None:
    lane = _lane_row(_zone(DELHI), _zone(MUMBAI))
    repo = _FakeAdminRepository([_existing(lane)])
    client = _client(PrimeAdminService(repo), UserRole.admin)  # type: ignore[arg-type]
    exported = client.get("/pricing/prime-lanes/export.csv")
    assert exported.status_code == 200 and exported.headers["content-type"].startswith("text/csv")
    response = client.post(
        "/pricing/prime-lanes/import", content=exported.content, headers={"Content-Type": "text/csv"}
    )
    assert response.status_code == 200
    assert response.json() == {"created": 0, "updated": 0, "deactivated": 0, "errors": [], "warnings": []}
    assert not repo.committed


def test_http_patch_rejects_unknown_fields_and_customers() -> None:
    lane = _lane_row(_zone(DELHI), _zone(MUMBAI))
    service = PrimeAdminService(_FakeAdminRepository([_existing(lane)]))  # type: ignore[arg-type]
    admin = _client(service, UserRole.admin)
    assert admin.patch(f"/pricing/prime-lanes/{lane.id}", json={"transporter_name": "X"}).status_code == 422
    assert admin.patch(f"/pricing/prime-lanes/{lane.id}", json={"rate_per_kg": -1}).status_code == 422
    customer = _client(service, UserRole.customer)
    assert customer.get("/pricing/prime-zones").status_code == 403


# ---- Sheet1 importer + zone seed (pure parts) ---------------------------------------

_SHEET_HEADER_1 = "\t".join([
    "FROM CITY", "FROM STATE", "TO CITY", "TO STATE", "MODE", "TRANSPORT NAME", "TAT", "RATE/KG", "MINIMUM LR",
    "PICKUP", "DELIVERY", "DOCKET", "MINIMUM WEIGHT", "ODD SIZE", "ODD WEIGHT- MORE THAN 200 KG/BOX",
    "ODA LOCATION- OUTSIDE FROM MAIN CITY", "PICKUP CHARGE", "DELIVERY CHARGE", "VOLUME WEIGHT",
])


def _sheet_header_2(tat_unit: str) -> str:
    return "\t".join([
        "FROM/TO", "", "TO/FROM", "", "TYPE", "PTL", tat_unit, "RS /KG", "IN RS", "GODOWN/DOOR", "GODOWN/DOOR",
        "IN RS", "IN KILOGRAM", "MORE THAN 7.9 FEET", "IN RS/KG OR MINIMUM RS 800", "IN RS/KG OR MINIMUM RS 800",
        "RS /KG OR MINIMUM RS 600", "RS /KG OR MINIMUM RS 600", "L*W*H/4500",
    ])


def _sheet_row(to_city: str, to_state: str, transporter: str, tat: str, rate: str, delivery: str = "GODOWN") -> str:
    return "\t".join([
        "RANGPURI", "NEW DELHI", to_city, to_state, "SURFACE", transporter, tat, rate, "500", "DOOR", delivery,
        "100", "50", "NOT ALLOWED", "2", "2", "1", "1", "L*W*H/4500",
    ])


_SHEET_TEXT = "\n".join([
    "--- Sheet1 ---",
    _SHEET_HEADER_1,
    _sheet_header_2("IN HRS"),
    _sheet_row("MUMBAI", "MAHARASHTRA", "SAMEER TRANSPORT", "30", "10"),
    _sheet_row("CHENNAI", "TELANGANA", "SAMEER TRANSPORT", "72", "15"),
    _sheet_header_2("IN DAYS"),
    _sheet_row("MUMBAI", "MAHARASHTRA", "SAI CARGO", "2", "9", delivery="DOOR"),
    _sheet_row("PUNE", "MAHARASHTRA", "VISION EXPRESS", "4", "NA"),
    _sheet_row("CHANDIGARGH", "PUNJAB", "ALL ROUNDER", "1", "5"),
    _sheet_row("CHANDIGARH- IXC", "PUNJAB", "AMIT/PATEL", "1", "5"),
    "--- Sheet2 ---",
    _sheet_row("SURAT", "GUJRAT", "SAMEER TRANSPORT", "30", "12"),
])


def test_sheet1_rows_become_lanes_with_hours_and_header_minimums() -> None:
    report = read_sheet1(_SHEET_TEXT)
    by_key = {(lane.dest_zone, lane.transporter_name): lane for lane in report.lanes}
    assert set(by_key) == {
        ("Mumbai", "SAMEER TRANSPORT"), ("Chennai", "SAMEER TRANSPORT"), ("Mumbai", "SAI CARGO"),
        ("Chandigarh", "ALL ROUNDER"), ("Chandigarh", "AMIT/PATEL"),
    }
    sameer = by_key[("Mumbai", "SAMEER TRANSPORT")]
    assert sameer.origin_zone == "Delhi NCR" and sameer.tat_hours == 30
    assert sameer.rates["oda_min"] == Decimal("800.00") and sameer.rates["pickup_min"] == Decimal("600.00")
    assert sameer.rates["volumetric_divisor"] == Decimal("4500.00")
    assert sameer.rates["max_dimension_cm"] == Decimal("240.00")
    assert sameer.markup_percent == Decimal("20.00")
    assert by_key[("Mumbai", "SAI CARGO")].tat_hours == 48
    assert [issue.message for issue in report.errors] == ["PUNE / VISION EXPRESS: rate/kg 'NA' is not a number."]
    messages = " | ".join(issue.message for issue in report.warnings)
    assert "state 'TELANGANA' for 'CHENNAI' is not Tamil Nadu." in messages
    assert "'CHANDIGARGH' mapped to zone Chandigarh." in messages


def test_cheapest_transporter_is_activated_and_ties_are_reported() -> None:
    report = read_sheet1(_SHEET_TEXT)
    lanes = choose_active_lanes(report)
    active = {lane.dest_zone: lane.transporter_name for lane in lanes if lane.is_active}
    assert active == {"Mumbai": "SAI CARGO", "Chennai": "SAMEER TRANSPORT", "Chandigarh": "ALL ROUNDER"}
    assert any("tie at ₹5.00/kg" in issue.message for issue in report.warnings)


def test_unknown_sheet_city_is_an_error() -> None:
    text = "\n".join([_SHEET_HEADER_1, _sheet_header_2("IN HRS"), _sheet_row("ATLANTIS", "OCEAN", "X", "24", "5")])
    report = read_sheet1(text)
    assert not report.lanes and "ATLANTIS" in report.errors[0].message


def test_alias_table_has_no_ambiguous_spellings() -> None:
    assert all(len(zones) == 1 for zones in ALIAS_INDEX.values())
    assert zone_for_place("Yamuna Nagar").name == "Yamunanagar"
    assert zone_for_place("JAMMU VIA LUDHIANA").name == "Jammu"


def test_pincodes_match_city_then_district_then_whole_state() -> None:
    records = [
        PincodeRecord(line=2, pin="124507", city="Bahadurgarh", district="Jhajjar", state="Haryana", is_oda=False),
        PincodeRecord(line=3, pin="124103", city="Beri", district="Jhajjar", state="Haryana", is_oda=True),
        PincodeRecord(line=4, pin="110037", city="South West Delhi", district="South West Delhi", state="Delhi", is_oda=False),
        PincodeRecord(line=5, pin="560001", city="Bangalore", district="Bengaluru Urban", state="Karnataka", is_oda=False),
        PincodeRecord(line=6, pin="682001", city="Kochi", district="Ernakulam", state="Kerala", is_oda=False),
    ]
    report = match_pincodes(records)
    assert report.matched["Bahadurgarh"] == {"124507": False}
    assert report.matched["Jhajjar"] == {"124103": True}
    assert report.matched["Delhi NCR"] == {"110037": False}
    assert report.matched["Bengaluru"] == {"560001": False}
    assert [record.pin for record in report.unmatched] == ["682001"]
