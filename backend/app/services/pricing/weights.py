"""
Unit normalisation and chargeable-weight rules per carrier (DESIGN.md v4 §C.3).

- Delhivery: chargeable = max(dead weight, L×B×H(cm) / 5000) per box, for Surface AND
  Express (delhivery_api.md §6.4). We send the total in grams (`cgm`); Delhivery applies
  its own slab and echoes `charged_weight`.
- Prime: max(actual, L×B×H / lane divisor, lane minimum) — computed by the Prime provider
  with `total_actual_kg` / `total_volume_cm3` from here.

All arithmetic is Decimal (core/money) so a re-price of unchanged boxes is exactly 0.00.
"""

from decimal import ROUND_CEILING, Decimal
from typing import Iterable, Tuple

from app.core.money import to_weight
from app.models.pickups import DimensionUnit, WeightUnit
from app.schemas.v1.pickups import PackageCreate

DELHIVERY_VOLUMETRIC_DIVISOR = Decimal("5000")
"""cm³ per kg for Delhivery Surface and Express."""

GRAMS_PER_KG = Decimal("1000")
CM_PER_UNIT = {
    DimensionUnit.CM: Decimal("1"),
    DimensionUnit.M: Decimal("100"),
    DimensionUnit.IN: Decimal("2.54"),
    DimensionUnit.FT: Decimal("30.48"),
}
"""Length conversion factors to centimetres."""

KG_PER_UNIT = {WeightUnit.KG: Decimal("1"), WeightUnit.G: Decimal("0.001")}
"""Weight conversion factors to kilograms."""

MIN_CHARGEABLE_GRAMS = 1
"""Delhivery rejects `cgm=0`; a priced parcel weighs at least one gram."""


def _dec(value: object) -> Decimal:
    """A float/int/str form value as an exact Decimal (floats go through `str`)."""
    return Decimal(str(value or 0))


def box_dimensions_cm(package: PackageCreate) -> Tuple[Decimal, Decimal, Decimal]:
    """
    One box's sides in centimetres.

    Args:
        package: The declared or measured box.

    Returns:
        (length, breadth, height) in cm.
    """
    factor = CM_PER_UNIT.get(package.dimension_unit, Decimal("1"))
    return (_dec(package.length) * factor, _dec(package.breadth) * factor, _dec(package.height) * factor)


def box_weight_kg(package: PackageCreate) -> Decimal:
    """One box's dead weight in kilograms."""
    return _dec(package.weight) * KG_PER_UNIT.get(package.weight_unit, Decimal("1"))


def box_volume_cm3(package: PackageCreate) -> Decimal:
    """One box's volume in cubic centimetres."""
    length, breadth, height = box_dimensions_cm(package)
    return length * breadth * height


def total_actual_kg(packages: Iterable[PackageCreate]) -> Decimal:
    """Dead weight of all boxes (weight × box_count), rounded to the gram."""
    return to_weight(sum((box_weight_kg(p) * p.box_count for p in packages), Decimal("0")))


def total_volume_cm3(packages: Iterable[PackageCreate]) -> Decimal:
    """Volume of all boxes (volume × box_count)."""
    return sum((box_volume_cm3(p) * p.box_count for p in packages), Decimal("0"))


def volumetric_kg(packages: Iterable[PackageCreate], divisor: Decimal) -> Decimal:
    """Volumetric weight of all boxes for a divisor, rounded to the gram."""
    return to_weight(total_volume_cm3(packages) / divisor)


def max_side_cm(packages: Iterable[PackageCreate]) -> Decimal:
    """The longest side of any box (0 when there are no boxes)."""
    sides = [side for p in packages for side in box_dimensions_cm(p)]
    return max(sides, default=Decimal("0"))


def max_box_weight_kg(packages: Iterable[PackageCreate]) -> Decimal:
    """The heaviest single box (0 when there are no boxes)."""
    return max((box_weight_kg(p) for p in packages), default=Decimal("0"))


def delhivery_chargeable_grams(packages: Iterable[PackageCreate]) -> int:
    """
    Delhivery `cgm`: Σ per box max(dead, volume / 5000) × box_count, in whole grams (rounded up).

    Args:
        packages: The boxes to price.

    Returns:
        Chargeable grams (≥ 1).
    """
    total_kg = sum(
        (
            max(box_weight_kg(p), box_volume_cm3(p) / DELHIVERY_VOLUMETRIC_DIVISOR) * p.box_count
            for p in packages
        ),
        Decimal("0"),
    )
    grams = int((total_kg * GRAMS_PER_KG).to_integral_value(rounding=ROUND_CEILING))
    return max(grams, MIN_CHARGEABLE_GRAMS)
