"""
Logismart Prime carrier-cost provider (DESIGN.md v4 §A "Prime", §C.3 "Prime cost").

The Prime rate table is Logismart's transporter COST. This provider turns one active
lane + a parcel into a `CarrierQuote` (pre-GST cost lines, forward + RTO legs, lane
markup, frozen lane snapshot). The sell price (markup, GST) is applied later by
`app.services.pricing.sell_price`, never here.

Cost of one leg (all money via `app.core.money`, half-up to the paisa):
    chargeable kg = max(actual kg, Σ L×B×H / lane.volumetric_divisor, lane.min_chargeable_kg)
                    (blind pickup: lane.min_chargeable_kg)
    FREIGHT        rate_per_kg × chargeable kg
    DOCKET         docket_charge
    PICKUP         max(pickup_per_kg × kg, pickup_min)                (always: pickup is DOOR)
    ODA            max(oda_per_kg × kg, oda_min)                      if the delivery pin is ODA
    ODD_WEIGHT     max(odd_weight_per_kg × kg, odd_weight_min)        if any box > 200 kg
    DOOR_DELIVERY  max(door_delivery_per_kg × kg, door_delivery_min)  if asked on a GODOWN lane
    MIN_LR_TOPUP   min_lr_charge − subtotal                           if subtotal < min_lr_charge
    RTO leg        = 100 % of the forward leg (Q10)
Not serviceable: any box side > lane.max_dimension_cm (TOO_LARGE), no zone / no active
lane (NO_PRIME_LANE), reverse shipments (Prime is one-way, Q11).

Spring analogy: a `@Component` strategy implementing the carrier-quote interface; the
pure pricing core (`requote`) is a static method so re-pricing from the lane copy frozen
at booking needs no database (DESIGN §C.4 "lane edited after booking").
"""

import math
import uuid
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.money import ZERO_MONEY, to_money, to_weight
from app.models.pickups import DimensionUnit, ServiceOption, ShipmentType, WeightUnit
from app.models.prime import PrimeDeliveryType, PrimeLane, PrimeLaneMode
from app.repositories.prime_rates import PincodeZone, PrimeRatesRepository
from app.schemas.v1.pickups import PackageCreate
from app.services.pricing.types import (
    CarrierLeg,
    CarrierLegKind,
    CarrierQuote,
    CostLine,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)

PRIME_OPTION = ServiceOption.PRIME_SURFACE
"""The service option this provider prices."""

OPTION_LANE_MODE: Mapping[ServiceOption, PrimeLaneMode] = {ServiceOption.PRIME_SURFACE: PrimeLaneMode.SURFACE}
"""Which lane mode each Prime option books on."""

ODD_WEIGHT_BOX_THRESHOLD_KG = Decimal("200")
"""Sheet1 "ODD WEIGHT - MORE THAN 200 KG/BOX": a single box heavier than this adds ODD_WEIGHT."""

RTO_COST_SHARE = Decimal("1")
"""Q10: the RTO leg costs 100 % of the forward leg."""

HOURS_PER_DAY = 24
GRAMS_PER_KG = Decimal("1000")
DIMENSION_TO_CM: Mapping[DimensionUnit, Decimal] = {
    DimensionUnit.CM: Decimal("1"),
    DimensionUnit.M: Decimal("100"),
    DimensionUnit.IN: Decimal("2.54"),
    DimensionUnit.FT: Decimal("30.48"),
}
"""Centimetres per dimension unit."""

LINE_FREIGHT = "FREIGHT"
LINE_DOCKET = "DOCKET"
LINE_PICKUP = "PICKUP"
LINE_ODA = "ODA"
LINE_ODD_WEIGHT = "ODD_WEIGHT"
LINE_DOOR_DELIVERY = "DOOR_DELIVERY"
LINE_MIN_LR_TOPUP = "MIN_LR_TOPUP"
LINE_LABELS: Mapping[str, str] = {
    LINE_FREIGHT: "Freight",
    LINE_DOCKET: "Docket charge",
    LINE_PICKUP: "Pickup charge",
    LINE_ODA: "Out-of-delivery-area (ODA) charge",
    LINE_ODD_WEIGHT: "Heavy box handling (over 200 kg per box)",
    LINE_DOOR_DELIVERY: "Door delivery",
    LINE_MIN_LR_TOPUP: "Minimum LR charge top-up",
}
"""Plain-English labels for the seller's breakup (codes are stable machine keys)."""

REVERSE_NOT_SUPPORTED_REASON = "Logismart Prime carries forward shipments only."


@dataclass(frozen=True)
class PrimeLaneTerms:
    """
    The rate terms of one lane as frozen at quote time (the `CarrierQuote.snapshot`).

    Money/kg/cm/percent fields are Decimal here and plain strings in the JSON snapshot
    so a re-price from the snapshot is exact.
    """

    lane_id: str
    origin_zone: str
    dest_zone: str
    mode: PrimeLaneMode
    delivery_type: PrimeDeliveryType
    transporter_name: str
    tat_hours: int
    is_oda: bool
    rate_per_kg: Decimal
    min_lr_charge: Decimal
    docket_charge: Decimal
    min_chargeable_kg: Decimal
    volumetric_divisor: Decimal
    max_dimension_cm: Decimal
    oda_per_kg: Decimal
    oda_min: Decimal
    odd_weight_per_kg: Decimal
    odd_weight_min: Decimal
    pickup_per_kg: Decimal
    pickup_min: Decimal
    door_delivery_per_kg: Decimal
    door_delivery_min: Decimal
    markup_percent: Decimal

    @classmethod
    def from_lane(cls, lane: PrimeLane, origin_zone: str, dest_zone: str, is_oda: bool) -> "PrimeLaneTerms":
        """
        Copies a lane row plus the resolved zone names and destination ODA flag.

        Args:
            lane: The active lane.
            origin_zone: Origin zone name.
            dest_zone: Destination zone name.
            is_oda: Whether the delivery pincode is ODA.
        """
        numbers = {name: Decimal(str(getattr(lane, name))) for name in _decimal_field_names()}
        return cls(
            lane_id=str(lane.id),
            origin_zone=origin_zone,
            dest_zone=dest_zone,
            mode=PrimeLaneMode(lane.mode),
            delivery_type=PrimeDeliveryType(lane.delivery_type),
            transporter_name=lane.transporter_name,
            tat_hours=int(lane.tat_hours),
            is_oda=is_oda,
            **numbers,
        )

    @classmethod
    def from_snapshot(cls, snapshot: Mapping[str, Any]) -> "PrimeLaneTerms":
        """
        Rebuilds the terms from a JSON snapshot written by `to_snapshot`.

        Raises:
            ValueError: a field is missing or malformed.
        """
        try:
            numbers = {name: Decimal(str(snapshot[name])) for name in _decimal_field_names()}
            return cls(
                lane_id=str(snapshot["lane_id"]),
                origin_zone=str(snapshot["origin_zone"]),
                dest_zone=str(snapshot["dest_zone"]),
                mode=PrimeLaneMode(snapshot["mode"]),
                delivery_type=PrimeDeliveryType(snapshot["delivery_type"]),
                transporter_name=str(snapshot["transporter_name"]),
                tat_hours=int(snapshot["tat_hours"]),
                is_oda=bool(snapshot["is_oda"]),
                **numbers,
            )
        except (KeyError, ArithmeticError, TypeError) as exc:
            raise ValueError(f"Malformed Prime lane snapshot: {exc!r}") from exc

    def to_snapshot(self) -> Dict[str, Any]:
        """JSON-safe copy (str/int/bool only; Decimals as exact strings)."""
        result: Dict[str, Any] = {}
        for item in fields(self):
            value = getattr(self, item.name)
            if isinstance(value, Decimal):
                result[item.name] = str(value)
            elif isinstance(value, (PrimeLaneMode, PrimeDeliveryType)):
                result[item.name] = value.value
            else:
                result[item.name] = value
        return result


def _decimal_field_names() -> Tuple[str, ...]:
    """Names of the Decimal rate fields of `PrimeLaneTerms` (same names as the lane columns)."""
    return tuple(item.name for item in fields(PrimeLaneTerms) if item.type in (Decimal, "Decimal"))


@dataclass(frozen=True)
class _Weights:
    """Weights of one parcel in kg (3 dp)."""

    actual_kg: Decimal
    volumetric_kg: Decimal
    chargeable_kg: Decimal


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (matches `CarrierLeg.fetched_at`)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _box_weight_kg(package: PackageCreate) -> Decimal:
    """Weight of ONE box of a package line in kg."""
    weight = Decimal(str(package.weight))
    return weight / GRAMS_PER_KG if package.weight_unit == WeightUnit.G else weight


def _box_sides_cm(package: PackageCreate) -> Tuple[Decimal, Decimal, Decimal]:
    """Length, breadth and height of one box in centimetres."""
    factor = DIMENSION_TO_CM[package.dimension_unit]
    return (
        Decimal(str(package.length)) * factor,
        Decimal(str(package.breadth)) * factor,
        Decimal(str(package.height)) * factor,
    )


def _oversized_reason(packages: Sequence[PackageCreate], max_side_cm: Decimal) -> Optional[str]:
    """
    Plain-English reason when any box side exceeds the lane's maximum, else None.

    Args:
        packages: Declared boxes.
        max_side_cm: The lane's `max_dimension_cm`.
    """
    for package in packages:
        longest = max(_box_sides_cm(package))
        if longest > max_side_cm:
            return (
                f"A box side of {to_money(longest)} cm is longer than the "
                f"{to_money(max_side_cm)} cm Logismart Prime can carry."
            )
    return None


def _weights(spec: ParcelSpec, terms: PrimeLaneTerms) -> _Weights:
    """
    Actual, volumetric and chargeable kg of the parcel on this lane.

    A blind pickup (or no boxes) is priced on the lane's minimum chargeable weight.
    """
    if spec.is_blind_pickup or not spec.packages:
        minimum = to_weight(terms.min_chargeable_kg)
        return _Weights(actual_kg=to_weight(0), volumetric_kg=to_weight(0), chargeable_kg=minimum)
    actual = Decimal("0")
    volume_cm3 = Decimal("0")
    for package in spec.packages:
        length, breadth, height = _box_sides_cm(package)
        actual += _box_weight_kg(package) * package.box_count
        volume_cm3 += length * breadth * height * package.box_count
    volumetric = volume_cm3 / terms.volumetric_divisor
    chargeable = max(actual, volumetric, terms.min_chargeable_kg)
    return _Weights(actual_kg=to_weight(actual), volumetric_kg=to_weight(volumetric), chargeable_kg=to_weight(chargeable))


def _has_odd_weight_box(spec: ParcelSpec) -> bool:
    """True when any single box is heavier than the odd-weight threshold."""
    return any(_box_weight_kg(package) > ODD_WEIGHT_BOX_THRESHOLD_KG for package in spec.packages)


def _per_kg_with_minimum(per_kg: Decimal, minimum: Decimal, kg: Decimal) -> Decimal:
    """`max(per_kg × kg, minimum)` rounded to the paisa."""
    return to_money(max(per_kg * kg, minimum))


def _line(code: str, amount: Decimal) -> CostLine:
    """A cost line with its plain-English label."""
    return CostLine(code=code, label=LINE_LABELS[code], amount=to_money(amount))


def _cost_lines(spec: ParcelSpec, terms: PrimeLaneTerms, kg: Decimal) -> List[CostLine]:
    """
    The forward leg's cost lines per DESIGN §C.3 (before the minimum-LR top-up).

    Args:
        spec: The parcel.
        terms: Lane terms.
        kg: Chargeable kg.
    """
    lines = [
        _line(LINE_FREIGHT, terms.rate_per_kg * kg),
        _line(LINE_DOCKET, terms.docket_charge),
        _line(LINE_PICKUP, _per_kg_with_minimum(terms.pickup_per_kg, terms.pickup_min, kg)),
    ]
    if terms.is_oda:
        lines.append(_line(LINE_ODA, _per_kg_with_minimum(terms.oda_per_kg, terms.oda_min, kg)))
    if _has_odd_weight_box(spec):
        lines.append(
            _line(LINE_ODD_WEIGHT, _per_kg_with_minimum(terms.odd_weight_per_kg, terms.odd_weight_min, kg))
        )
    if spec.door_delivery and terms.delivery_type == PrimeDeliveryType.GODOWN:
        lines.append(
            _line(
                LINE_DOOR_DELIVERY,
                _per_kg_with_minimum(terms.door_delivery_per_kg, terms.door_delivery_min, kg),
            )
        )
    return lines


def _with_min_lr_topup(lines: List[CostLine], min_lr_charge: Decimal) -> List[CostLine]:
    """Appends MIN_LR_TOPUP when the lines sum to less than the minimum LR charge."""
    subtotal = sum((line.amount for line in lines), ZERO_MONEY)
    shortfall = to_money(min_lr_charge) - subtotal
    if shortfall > ZERO_MONEY:
        return lines + [_line(LINE_MIN_LR_TOPUP, shortfall)]
    return lines


def _transit_days(tat_hours: int) -> int:
    """Lane TAT in whole days, rounded up (24 h → 1, 30 h → 2)."""
    return max(1, math.ceil(tat_hours / HOURS_PER_DAY))


def _leg_details(terms: PrimeLaneTerms, weights: _Weights) -> Dict[str, Any]:
    """Server-only, JSON-safe leg details (lane id, zones, ODA, weights)."""
    return {
        "lane_id": terms.lane_id,
        "origin_zone": terms.origin_zone,
        "dest_zone": terms.dest_zone,
        "is_oda": terms.is_oda,
        "actual_weight_kg": str(weights.actual_kg),
        "volumetric_weight_kg": str(weights.volumetric_kg),
        "chargeable_weight_kg": str(weights.chargeable_kg),
    }


def _rto_leg(forward: CarrierLeg) -> CarrierLeg:
    """The RTO leg: 100 % of the forward leg, same lines."""
    lines = tuple(
        CostLine(code=line.code, label=line.label, amount=to_money(line.amount * RTO_COST_SHARE))
        for line in forward.lines
    )
    return CarrierLeg(
        kind=CarrierLegKind.RTO,
        cost=sum((line.amount for line in lines), ZERO_MONEY),
        lines=lines,
        charged_weight_kg=forward.charged_weight_kg,
        transit_days=forward.transit_days,
        source=forward.source,
        fetched_at=forward.fetched_at,
        details=dict(forward.details),
    )


def price_on_terms(terms: PrimeLaneTerms, spec: ParcelSpec, option: ServiceOption = PRIME_OPTION) -> CarrierQuote:
    """
    Prices a parcel on frozen lane terms (pure: no DB, no clock other than `fetched_at`).

    Args:
        terms: Lane terms (from a lane row or a booking snapshot).
        spec: The parcel.
        option: The Prime option being priced.

    Returns:
        A serviceable quote with forward + RTO legs, or an unavailable one (reverse / too large).
    """
    if spec.shipment_type == ShipmentType.REVERSE:
        return CarrierQuote.unavailable(option, QuoteUnavailableCode.NOT_SERVICEABLE, REVERSE_NOT_SUPPORTED_REASON)
    oversized = None if spec.is_blind_pickup else _oversized_reason(spec.packages, terms.max_dimension_cm)
    if oversized:
        return CarrierQuote.unavailable(option, QuoteUnavailableCode.TOO_LARGE, oversized)
    weights = _weights(spec, terms)
    lines = _with_min_lr_topup(_cost_lines(spec, terms, weights.chargeable_kg), terms.min_lr_charge)
    forward = CarrierLeg(
        kind=CarrierLegKind.FORWARD,
        cost=sum((line.amount for line in lines), ZERO_MONEY),
        lines=tuple(lines),
        charged_weight_kg=weights.chargeable_kg,
        transit_days=_transit_days(terms.tat_hours),
        source=PriceSource.TABLE,
        fetched_at=_utc_now_naive(),
        details=_leg_details(terms, weights),
    )
    return CarrierQuote(
        option=option,
        serviceable=True,
        forward=forward,
        rto=_rto_leg(forward),
        markup_percent=terms.markup_percent,
        cod_supported=False,
        snapshot=terms.to_snapshot(),
    )


class PrimeProvider:
    """Quotes Logismart Prime from the tenant's zones and active lanes."""

    def __init__(self, session: AsyncSession) -> None:
        """
        Args:
            session: Request session (read-only use).
        """
        self.repository = PrimeRatesRepository(session)

    async def quote(self, tenant_id: uuid.UUID, spec: ParcelSpec) -> CarrierQuote:
        """
        Prices a parcel on the active lane between the pickup and delivery zones.

        Args:
            tenant_id: Tenant scope.
            spec: The parcel.

        Returns:
            A serviceable quote, or NO_PRIME_LANE / TOO_LARGE / NOT_SERVICEABLE with a plain reason.
        """
        origin = await self.repository.get_pincode_zone(tenant_id, spec.pickup_pincode)
        if origin is None:
            return self._no_lane(f"Logismart Prime does not pick up from pincode {spec.pickup_pincode} yet.")
        dest = await self.repository.get_pincode_zone(tenant_id, spec.delivery_pincode)
        if dest is None:
            return self._no_lane(f"Logismart Prime does not deliver to pincode {spec.delivery_pincode} yet.")
        lane = await self.repository.get_active_lane(
            tenant_id, origin.zone.id, dest.zone.id, OPTION_LANE_MODE[PRIME_OPTION]
        )
        if lane is None:
            return self._no_lane(
                f"Logismart Prime has no rate from {origin.zone.name} to {dest.zone.name} yet."
            )
        return price_on_terms(self._terms(lane, origin, dest), spec)

    @staticmethod
    def requote(snapshot: Mapping[str, Any], spec: ParcelSpec) -> CarrierQuote:
        """
        Re-prices from the lane copy frozen at booking (no DB; later lane edits are ignored).

        The snapshot fixes the lane and the destination ODA flag, so callers must use a
        fresh `quote()` when the pickup or delivery pincode changes.

        Args:
            snapshot: `CarrierQuote.snapshot` of the booking quote.
            spec: The (changed) parcel.

        Raises:
            ValueError: the snapshot is malformed.
        """
        return price_on_terms(PrimeLaneTerms.from_snapshot(snapshot), spec)

    @staticmethod
    def _terms(lane: PrimeLane, origin: PincodeZone, dest: PincodeZone) -> PrimeLaneTerms:
        """Lane terms with zone names and the delivery pincode's ODA flag."""
        return PrimeLaneTerms.from_lane(lane, origin.zone.name, dest.zone.name, dest.is_oda)

    @staticmethod
    def _no_lane(reason: str) -> CarrierQuote:
        """A greyed-out Prime card with a plain-English reason."""
        return CarrierQuote.unavailable(PRIME_OPTION, QuoteUnavailableCode.NO_PRIME_LANE, reason)
