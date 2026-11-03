"""
Pure unit tests for the pricing redesign core (DESIGN.md v4 D2): weights, the fake
Delhivery provider, the Delhivery provider's cache / fallback rules, sell prices, the
customer breakdown, policy parsing and the WP0 / A-26 / D-06 guards.

No database: the price cache is an in-memory stand-in and the tenant is a SimpleNamespace.
Expected numbers mirror the pre-redesign engine (board #348): 2 kg surface 122001 → 110001
= ₹135.00 + 18 % = ₹159.30; COD 2 % of ₹1,000 → ₹182.90; RTO leg ₹25/kg → ₹218.30.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, Optional

import pytest
from fastapi import HTTPException

from app.models.manifests import ServiceFlow
from app.models.pickups import (
    DimensionUnit,
    FreightPaymentMode,
    ServiceOption,
    ShipmentType,
    WeightUnit,
)
from app.schemas.v1.pickups import PackageCreate
from app.schemas.v1.pricing import PricingPolicy
from app.services import mvp_scope
from app.services.pricing import delhivery as delhivery_module
from app.services.pricing import fake_delhivery, weights
from app.services.pricing.delhivery import (
    DelhiveryProvider,
    PriceFreshness,
    cache_key,
    price_params,
    slab_grams,
)
from app.services.pricing.policy import policy_of
from app.services.pricing.quote_service import (
    SellInputs,
    assert_mvp_scope,
    assert_weight_limits,
    build_carrier_cost,
    leg_from_json,
    leg_to_json,
    price_option,
    valuation,
)
from app.services.pricing.sell_price import SellTerms, cod_fee_for, marked_up, terms_for
from app.services.pricing.types import (
    CarrierLegKind,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)

TEST_TENANT = SimpleNamespace(id=uuid.uuid4(), slug="logismart-test", settings={})
LIVE_TENANT = SimpleNamespace(id=uuid.uuid4(), slug="logismart", settings={})
COD_POLICY = PricingPolicy(cod_fee_percent=2, cod_fee_min=1)


def _box(weight: float, side: float = 10.0, count: int = 1) -> PackageCreate:
    """A cube box in cm / kg."""
    return PackageCreate(length=side, breadth=side, height=side, weight=weight, box_count=count)


def _spec(*boxes: PackageCreate, reverse: bool = False) -> ParcelSpec:
    """The calibration lane 122001 → 110001."""
    return ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="110001",
        packages=tuple(boxes),
        shipment_type=ShipmentType.REVERSE if reverse else ShipmentType.FORWARD,
    )


class _MemoryCache:
    """In-memory stand-in for DelhiveryPriceCacheRepository."""

    def __init__(self) -> None:
        self.rows: Dict[str, Any] = {}

    async def get(self, tenant_id: uuid.UUID, key: str) -> Optional[Any]:
        return self.rows.get(key)

    async def upsert(self, *, tenant_id, cache_key, request_params, response, fetched_at) -> None:
        self.rows[cache_key] = SimpleNamespace(response=response, fetched_at=fetched_at)


def _provider(tenant: Any = TEST_TENANT) -> DelhiveryProvider:
    """A provider on the fake API with an in-memory cache."""
    provider = DelhiveryProvider.__new__(DelhiveryProvider)
    provider.tenant = tenant
    provider.cache = _MemoryCache()
    provider.api = delhivery_module.delhivery_api_for(tenant)
    return provider


@pytest.fixture(autouse=True)
def _reset_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts with the fake 'up' and no price override."""
    monkeypatch.setattr(fake_delhivery, "FAKE_DELHIVERY_DOWN", False)
    monkeypatch.setattr(fake_delhivery, "FAKE_GROSS_OVERRIDE", None)


# --- weights ------------------------------------------------------------------------


def test_delhivery_chargeable_grams_uses_5000_divisor_and_box_count() -> None:
    # 30 cm cube = 27 000 cm³ / 5000 = 5.4 kg > 2 kg dead, × 2 boxes.
    assert weights.delhivery_chargeable_grams([_box(2, side=30, count=2)]) == 10800


def test_units_are_normalised() -> None:
    box = PackageCreate(length=1, breadth=1, height=1, dimension_unit=DimensionUnit.FT, weight=500, weight_unit=WeightUnit.G)
    assert weights.box_weight_kg(box) == Decimal("0.500")
    assert weights.box_dimensions_cm(box)[0] == Decimal("30.48")


def test_slab_rounding() -> None:
    assert slab_grams(1) == 500
    assert slab_grams(2000) == 2000
    assert slab_grams(2001) == 2500


# --- fake provider --------------------------------------------------------------------


@pytest.mark.parametrize(
    "md,ss,cgm,gross",
    [
        ("S", "Delivered", 1000, 80.00),
        ("S", "Delivered", 2000, 135.00),
        ("S", "Delivered", 3500, 217.50),
        ("E", "Delivered", 2000, 201.00),
        ("S", "RTO", 2000, 185.00),  # cumulative like real Delhivery: 135 forward + 50 return
        ("S", "DTO", 2000, 185.00),
    ],
)
async def test_fake_formula_reproduces_old_engine(md: str, ss: str, cgm: int, gross: float) -> None:
    api = fake_delhivery.FakeDelhiveryApi("logismart-test")
    answer = await api.invoice_charges({"md": md, "ss": ss, "o_pin": "122001", "d_pin": "110001", "cgm": cgm, "pt": "Pre-paid"})
    assert answer["gross_amount"] == gross
    assert answer["total_amount"] == float((Decimal(str(gross)) * Decimal("1.18")).quantize(Decimal("0.01")))


def test_fake_refuses_live_tenant() -> None:
    with pytest.raises(PermissionError):
        fake_delhivery.FakeDelhiveryApi("logismart")


def test_live_tenant_without_token_is_not_connected() -> None:
    assert delhivery_module.delhivery_api_for(LIVE_TENANT) is None


# --- Delhivery provider --------------------------------------------------------------


async def test_quote_prices_forward_with_transit_and_no_rto_by_default() -> None:
    quote = await _provider().quote(
        ServiceOption.DELHIVERY_SURFACE, _spec(_box(2)), freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False
    )
    assert quote.serviceable and quote.forward is not None
    assert quote.forward.cost == Decimal("135.00")
    assert quote.forward.charged_weight_kg == Decimal("2.000")
    assert quote.forward.transit_days == fake_delhivery.FAKE_TRANSIT_DAYS["S"]
    assert quote.rto is None


async def test_booking_quote_includes_rto_leg() -> None:
    quote = await _provider().quote(
        ServiceOption.DELHIVERY_SURFACE, _spec(_box(2)), freshness=PriceFreshness.BOOK, include_rto=True, is_cod=False
    )
    assert quote.rto is not None and quote.rto.cost == Decimal("50.00")
    assert quote.rto.kind == CarrierLegKind.RTO


async def test_reverse_uses_dto_leg() -> None:
    quote = await _provider().quote(
        ServiceOption.DELHIVERY_SURFACE, _spec(_box(2), reverse=True), freshness=PriceFreshness.QUOTE, include_rto=True, is_cod=False
    )
    assert quote.forward.kind == CarrierLegKind.REVERSE
    assert quote.forward.cost == Decimal("185.00")
    assert quote.rto is None


async def test_down_falls_back_to_stored_price_under_24h(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    spec = _spec(_box(2))
    await provider.quote(ServiceOption.DELHIVERY_SURFACE, spec, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False)
    key = cache_key(price_params(ServiceOption.DELHIVERY_SURFACE, spec, "Delivered"))
    provider.cache.rows[key].fetched_at -= timedelta(hours=5)
    monkeypatch.setattr(fake_delhivery, "FAKE_DELHIVERY_DOWN", True)
    quote = await provider.quote(ServiceOption.DELHIVERY_SURFACE, spec, freshness=PriceFreshness.BOOK, include_rto=False, is_cod=False)
    assert quote.serviceable and quote.forward.source == PriceSource.CACHED


async def test_down_with_old_price_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    spec = _spec(_box(2))
    await provider.quote(ServiceOption.DELHIVERY_SURFACE, spec, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False)
    key = cache_key(price_params(ServiceOption.DELHIVERY_SURFACE, spec, "Delivered"))
    provider.cache.rows[key].fetched_at -= timedelta(hours=25)
    monkeypatch.setattr(fake_delhivery, "FAKE_DELHIVERY_DOWN", True)
    quote = await provider.quote(ServiceOption.DELHIVERY_SURFACE, spec, freshness=PriceFreshness.BOOK, include_rto=False, is_cod=False)
    assert not quote.serviceable
    assert quote.unavailable_code == QuoteUnavailableCode.PRICE_UNAVAILABLE


async def test_quote_reuses_fresh_price_but_book_asks_again(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    spec = _spec(_box(2))
    await provider.quote(ServiceOption.DELHIVERY_SURFACE, spec, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False)
    monkeypatch.setattr(fake_delhivery, "FAKE_GROSS_OVERRIDE", Decimal("150"))
    reused = await provider.quote(ServiceOption.DELHIVERY_SURFACE, spec, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False)
    fresh = await provider.quote(ServiceOption.DELHIVERY_SURFACE, spec, freshness=PriceFreshness.BOOK, include_rto=False, is_cod=False)
    assert reused.forward.cost == Decimal("135.00")
    assert fresh.forward.cost == Decimal("150.00")


async def test_unserviceable_and_embargo_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = _provider()
    bad = ParcelSpec(pickup_pincode="122001", delivery_pincode="999999", packages=(_box(1),))
    quote = await provider.quote(ServiceOption.DELHIVERY_SURFACE, bad, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False)
    assert quote.unavailable_code == QuoteUnavailableCode.NOT_SERVICEABLE
    monkeypatch.setattr(fake_delhivery, "FAKE_EMBARGO_PINS", frozenset({"110001"}))
    quote = await provider.quote(ServiceOption.DELHIVERY_SURFACE, _spec(_box(1)), freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False)
    assert quote.unavailable_code == QuoteUnavailableCode.EMBARGO


async def test_not_connected_tenant_is_unavailable() -> None:
    quote = await _provider(LIVE_TENANT).quote(
        ServiceOption.DELHIVERY_SURFACE, _spec(_box(1)), freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False
    )
    assert quote.unavailable_code == QuoteUnavailableCode.PRICE_UNAVAILABLE


# --- sell price + breakdown ----------------------------------------------------------


async def _priced(policy: PricingPolicy, inputs: SellInputs, *boxes: PackageCreate):
    quote = await _provider().quote(
        ServiceOption.DELHIVERY_SURFACE, _spec(*boxes), freshness=PriceFreshness.BOOK, include_rto=True, is_cod=inputs.is_cod
    )
    return price_option(quote, terms_for(quote, policy), _spec(*boxes), inputs)


async def test_delhivery_sell_equals_delhivery_total_with_zero_markup() -> None:
    priced = await _priced(PricingPolicy(), SellInputs(), _box(2))
    assert priced.sell.total == Decimal("159.30")
    b = priced.breakdown
    assert Decimal(str(b["base_charge"])) + Decimal(str(b["cod_fee"])) + Decimal(str(b["rto_surcharge"])) + Decimal(str(b["gst_total"])) == priced.sell.total


async def test_cod_fee_and_door_amount_use_typed_goods() -> None:
    inputs = SellInputs(is_cod=True, cod_goods=Decimal("1000"), add_shipping_to_cod=True)
    priced = await _priced(COD_POLICY, inputs, _box(2))
    assert priced.sell.cod_fee == Decimal("20.00")
    assert priced.sell.total == Decimal("182.90")
    assert priced.door_collectible == Decimal("1182.90")  # A-01: goods typed + shipping
    assert priced.cod_remittance == Decimal("1000.00")


async def test_rto_billing_adds_rto_leg_and_drops_cod_fee() -> None:
    inputs = SellInputs(include_rto=True, charge_cod_fee=False, is_cod=True, cod_goods=Decimal("1000"))
    priced = await _priced(COD_POLICY, inputs, _box(2))
    assert priced.sell.rto_freight == Decimal("50.00")
    assert priced.sell.total == Decimal("218.30")


def test_cod_fee_minimum_and_off_switch() -> None:
    terms = SellTerms(markup_percent=Decimal("0"), cod_fee_percent=Decimal("2"), cod_fee_min=Decimal("30"))
    assert cod_fee_for(Decimal("1000"), terms) == Decimal("30.00")
    off = SellTerms(markup_percent=Decimal("0"), cod_fee_percent=None, cod_fee_min=Decimal("30"))
    assert cod_fee_for(Decimal("1000"), off) == Decimal("0.00")


def test_markup_rounding() -> None:
    assert marked_up(Decimal("100.00"), Decimal("20")) == Decimal("120.00")
    assert marked_up(Decimal("10.01"), Decimal("12.5")) == Decimal("11.26")


async def test_breakdown_never_leaks_carrier_fields() -> None:
    priced = await _priced(COD_POLICY, SellInputs(), _box(2))
    flat = repr(priced.breakdown)
    for forbidden in ("carrier_cost", "gross", "markup_percent", "transporter"):
        assert forbidden not in flat


async def test_carrier_cost_round_trips() -> None:
    priced = await _priced(COD_POLICY, SellInputs(), _box(2))
    record = build_carrier_cost(priced.quote, _spec(_box(2)), priced.terms)
    assert leg_from_json(record["forward"]) == priced.quote.forward
    assert SellTerms.from_json(record["terms"]) == priced.terms
    assert leg_to_json(None) is None


# --- policy + guards -------------------------------------------------------------------


def test_policy_defaults_and_invalid() -> None:
    assert policy_of(SimpleNamespace(id=uuid.uuid4(), settings={})).cod_enabled is False
    assert policy_of(SimpleNamespace(id=uuid.uuid4(), settings={"pricing_policy": {"cod_fee_percent": -1}})) is None
    enabled = policy_of(SimpleNamespace(id=uuid.uuid4(), settings={"pricing_policy": {"cod_fee_percent": 2, "cod_fee_min": 30}}))
    assert enabled.cod_enabled is True


def test_valuation_is_value_plus_tax() -> None:
    result = valuation(50000.10, 9000.20)
    assert result.shipment_total_value == 59000.30
    assert result.eway_bill_required is True


def test_weight_caps_per_flow() -> None:
    with pytest.raises(HTTPException):
        assert_weight_limits(ServiceFlow.B2C, [_box(500)])
    assert_weight_limits(ServiceFlow.B2B, [_box(500)])
    with pytest.raises(HTTPException):
        assert_weight_limits(ServiceFlow.B2B, [_box(1000, count=25)])


def test_mvp_scope_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(HTTPException) as to_pay:
        assert_mvp_scope(FreightPaymentMode.TO_PAY, ShipmentType.FORWARD, ServiceFlow.B2C)
    assert to_pay.value.detail == mvp_scope.TO_PAY_DISABLED_DETAIL
    with pytest.raises(HTTPException) as reverse:
        assert_mvp_scope(FreightPaymentMode.PREPAID, ShipmentType.REVERSE, ServiceFlow.B2B)
    assert reverse.value.detail == mvp_scope.B2B_REVERSE_DISABLED_DETAIL
    assert_mvp_scope(FreightPaymentMode.PREPAID, ShipmentType.REVERSE, ServiceFlow.B2C)
    monkeypatch.setattr(mvp_scope, "TO_PAY_BOOKINGS_ENABLED", True)
    assert_mvp_scope(FreightPaymentMode.TO_PAY, ShipmentType.FORWARD, ServiceFlow.B2C)


def test_utc_helpers_are_naive() -> None:
    assert delhivery_module._utc_now_naive().tzinfo is None
    assert datetime.now(timezone.utc).tzinfo is not None
