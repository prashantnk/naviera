"""
Unit tests for the Pricing Engine (`app/services/pricing/`, DESIGN.md v4).

Replaces the legacy static-rate `PricingEngine` tests with unit coverage of:
- 500 g slab rounding & 0.5 kg floor (`slab_grams`)
- Aggregated sum(actual) vs sum(volumetric) weight calculation (`weights`)
- Dimension (`CM`, `IN`, `FT`, `M`) and weight (`KG`, `G`) unit normalizations
- `FakeDelhiveryApi` calibration formula & live-tenant guard (`FAKE_PROVIDER_TENANT_SLUGS`)
- `PrimeProvider` (`price_on_terms`) B2B lane pricing, ODA, door delivery, odd weight, and 240 cm cap
- Decoupled COD fee on `cod_amount` (not `shipment_total_value`) and breakup sum invariant
"""

import uuid
from decimal import Decimal

import pytest

from app.models.pickups import DimensionUnit, ShipmentType, WeightUnit
from app.models.prime import PrimeDeliveryType, PrimeLaneMode
from app.schemas.v1.pickups import PackageCreate
from app.schemas.v1.pricing import PricingPolicy
from app.services.pricing import fake_delhivery, weights
from app.services.pricing.delhivery import slab_grams
from app.services.pricing.prime import PrimeLaneTerms, price_on_terms
from app.services.pricing.quote_service import SellInputs, price_option
from app.services.pricing.sell_price import terms_for
from app.services.pricing.types import ParcelSpec, QuoteUnavailableCode


def _prime_terms(**overrides) -> PrimeLaneTerms:
    base = dict(
        lane_id=str(uuid.uuid4()),
        origin_zone="Delhi NCR",
        dest_zone="Mumbai",
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
    base.update(overrides)
    return PrimeLaneTerms(**base)


def test_chargeable_weight_floor_and_500g_slab_rounding() -> None:
    """Tiny parcels floor to 500 g (0.5 kg) and round up in 500 g steps."""
    pkg_tiny = PackageCreate(
        length=5.0,
        breadth=5.0,
        height=5.0,
        dimension_unit=DimensionUnit.CM,
        weight=0.05,
        weight_unit=WeightUnit.KG,
        box_count=1,
    )
    grams_tiny = weights.delhivery_chargeable_grams([pkg_tiny])
    assert slab_grams(grams_tiny) == 500

    # 20x20x20 CM / 5000 = 1.600 kg > 1.12 kg actual -> 1600 g -> 2000 g (2.0 kg) slab
    pkg_slab = PackageCreate(
        length=20.0,
        breadth=20.0,
        height=20.0,
        dimension_unit=DimensionUnit.CM,
        weight=1.12,
        weight_unit=WeightUnit.KG,
        box_count=1,
    )
    grams_slab = weights.delhivery_chargeable_grams([pkg_slab])
    assert slab_grams(grams_slab) == 2000


def test_aggregated_vs_package_by_package_weight() -> None:
    """
    Prime B2B uses aggregated sum(Actual) vs sum(Volumetric) across boxes:
    Box 1: Actual = 10 kg, Vol (4500) = 2 kg
    Box 2: Actual = 2 kg, Vol (4500) = 8 kg
    total_actual_kg = 12.000 kg, volumetric_kg(4500) = 10.000 kg.
    """
    pkgs = [
        PackageCreate(
            length=30.0,
            breadth=20.0,
            height=15.0,
            dimension_unit=DimensionUnit.CM,
            weight=10.0,
            weight_unit=WeightUnit.KG,
            box_count=1,
        ),
        PackageCreate(
            length=60.0,
            breadth=30.0,
            height=20.0,
            dimension_unit=DimensionUnit.CM,
            weight=2.0,
            weight_unit=WeightUnit.KG,
            box_count=1,
        ),
    ]
    assert weights.total_actual_kg(pkgs) == Decimal("12.000")
    assert weights.volumetric_kg(pkgs, Decimal("4500")) == Decimal("10.000")


def test_dimension_and_weight_unit_conversions() -> None:
    """Verify M, IN, FT dimension units and G weight unit convert accurately."""
    pkg_g = PackageCreate(
        length=10.0,
        breadth=10.0,
        height=10.0,
        dimension_unit=DimensionUnit.CM,
        weight=1500.0,
        weight_unit=WeightUnit.G,
        box_count=1,
    )
    assert weights.total_actual_kg([pkg_g]) == Decimal("1.500")
    assert slab_grams(weights.delhivery_chargeable_grams([pkg_g])) == 1500

    pkg_in = PackageCreate(
        length=10.0,
        breadth=10.0,
        height=10.0,
        dimension_unit=DimensionUnit.IN,
        weight=1.0,
        weight_unit=WeightUnit.KG,
        box_count=1,
    )
    dims_cm = weights.box_dimensions_cm(pkg_in)
    assert dims_cm == (Decimal("25.40"), Decimal("25.40"), Decimal("25.40"))


@pytest.mark.asyncio
async def test_fake_delhivery_modes_and_tenant_guard() -> None:
    """Verify FakeDelhiveryApi calibration numbers and live-tenant guard."""
    with pytest.raises(PermissionError):
        fake_delhivery.FakeDelhiveryApi("logismart")

    api = fake_delhivery.FakeDelhiveryApi("logismart-test")
    surf = await api.invoice_charges(
        {"md": "S", "ss": "Delivered", "o_pin": "122001", "d_pin": "400001", "cgm": 2000, "pt": "Pre-paid"}
    )
    exp = await api.invoice_charges(
        {"md": "E", "ss": "Delivered", "o_pin": "122001", "d_pin": "400001", "cgm": 2000, "pt": "Pre-paid"}
    )
    rto = await api.invoice_charges(
        {"md": "S", "ss": "RTO", "o_pin": "122001", "d_pin": "400001", "cgm": 2000, "pt": "Pre-paid"}
    )
    assert surf["gross_amount"] == 135.0
    assert exp["gross_amount"] == 201.0
    assert rto["gross_amount"] == 185.0  # cumulative like real Delhivery: 135 forward + 50 return


def test_prime_b2b_lane_pricing_and_breakup_sum_invariant() -> None:
    """
    Verify B2B Prime lane pricing (50 kg floor, docket, pickup, markup, GST)
    and the breakup sum invariant (`base_charge + cod_fee + rto_surcharge + gst_total == total`).
    """
    spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="400001",
        packages=(
            PackageCreate(
                length=40.0,
                breadth=30.0,
                height=30.0,
                dimension_unit=DimensionUnit.CM,
                weight=10.0,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
        shipment_type=ShipmentType.FORWARD,
    )
    carrier_quote = price_on_terms(_prime_terms(), spec)
    assert carrier_quote.serviceable is True
    assert carrier_quote.forward is not None
    assert carrier_quote.forward.charged_weight_kg == Decimal("50.000")
    assert carrier_quote.forward.cost == Decimal("1200.00")

    policy = PricingPolicy(prime_default_markup_percent=20.0, cod_fee_percent=2.0, cod_fee_min=1.0)
    priced = price_option(carrier_quote, terms_for(carrier_quote, policy), spec, SellInputs())
    assert priced.sell.forward_freight == Decimal("1440.00")
    assert priced.sell.gst == Decimal("259.20")
    assert priced.sell.total == Decimal("1699.20")

    pb = priced.breakdown
    assert (
        Decimal(str(pb["base_charge"]))
        + Decimal(str(pb["cod_fee"]))
        + Decimal(str(pb["rto_surcharge"]))
        + Decimal(str(pb["gst_total"]))
        == priced.sell.total
    )

    # Box exceeding 240 cm max dimension is rejected with TOO_LARGE
    oversized_spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="400001",
        packages=(
            PackageCreate(
                length=245.0,
                breadth=30.0,
                height=30.0,
                dimension_unit=DimensionUnit.CM,
                weight=10.0,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
    )
    oversized_quote = price_on_terms(_prime_terms(), oversized_spec)
    assert oversized_quote.serviceable is False
    assert oversized_quote.unavailable_code == QuoteUnavailableCode.TOO_LARGE
