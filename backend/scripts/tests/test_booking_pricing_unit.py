"""
Pure unit tests for booking-time pricing rules (DESIGN.md v4 D3; WP0 + WP1 A-01/A-02/A-17/A-26).

No database: `price_booking` runs on the fake Delhivery provider with an in-memory price cache.
"""

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict

import pytest
from fastapi import HTTPException

from app.models.manifests import ServiceFlow
from app.models.pickups import FreightPaymentMode, PickupStrategy, ProductCategory, ServiceOption, ServiceType, ShipmentType
from app.schemas.v1.pickups import PickupCreate
from app.services import mvp_scope
from app.services.pricing import booking, delhivery as delhivery_module, fake_delhivery
from app.services.pricing.booking import (
    COMMERCIAL_IS_B2B_DETAIL,
    PRICE_CHANGED_CODE,
    assert_flow_fields,
    booking_flow,
    booking_option,
    price_booking,
    service_type_for,
)
from app.services.pricing.policy import COD_DISABLED_DETAIL

ADDRESS = {
    "name": "Asha",
    "phone": "9876543210",
    "address_line1": "1 MG Road",
    "city": "Gurugram",
    "state": "Haryana",
    "pincode": "122001",
}
TEST_TENANT = SimpleNamespace(
    id=uuid.uuid4(),
    slug="logismart-test",
    settings={"pricing_policy": {"cod_fee_percent": 2, "cod_fee_min": 1}},
)


def _payload(**overrides: Any) -> PickupCreate:
    """A valid B2C forward booking body (2 kg, 10 cm cube)."""
    body: Dict[str, Any] = {
        "requested_pickup_date": date.today().isoformat(),
        "product_category": ProductCategory.APPAREL.value,
        "new_pickup_address": ADDRESS,
        "new_delivery_address": {**ADDRESS, "pincode": "110001", "city": "Delhi", "state": "Delhi"},
        "packages": [{"length": 10, "breadth": 10, "height": 10, "weight": 2}],
        "payment_details": {"shipment_value": 1000},
        "service_flow": ServiceFlow.B2C.value,
    }
    body.update(overrides)
    return PickupCreate.model_validate(body)


class _MemoryCache:
    """In-memory price cache."""

    def __init__(self) -> None:
        self.rows: Dict[str, Any] = {}

    async def get(self, tenant_id, key):
        return self.rows.get(key)

    async def upsert(self, *, tenant_id, cache_key, request_params, response, fetched_at):
        self.rows[cache_key] = SimpleNamespace(response=response, fetched_at=fetched_at)


@pytest.fixture(autouse=True)
def _offline_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """DelhiveryProvider on the fake API + memory cache; the fake starts 'up'."""
    cache = _MemoryCache()

    def _init(self, session, tenant) -> None:
        self.tenant = tenant
        self.cache = cache
        self.api = delhivery_module.delhivery_api_for(tenant)

    monkeypatch.setattr(delhivery_module.DelhiveryProvider, "__init__", _init)
    monkeypatch.setattr(fake_delhivery, "FAKE_DELHIVERY_DOWN", False)
    monkeypatch.setattr(fake_delhivery, "FAKE_GROSS_OVERRIDE", None)


async def _book(payload: PickupCreate):
    return await price_booking(None, TEST_TENANT, payload, pickup_pincode="122001", delivery_pincode="110001")


# --- flow / option (A-02) ---------------------------------------------------------------


def test_flow_comes_from_route_not_category() -> None:
    assert booking_flow(_payload()) == ServiceFlow.B2C
    legacy = _payload(service_flow=None, pickup_strategy=PickupStrategy.DEFAULT.value)
    assert booking_flow(legacy) == ServiceFlow.B2B
    assert booking_flow(_payload(service_flow=None, service_option=ServiceOption.PRIME_SURFACE.value)) == ServiceFlow.B2B


def test_b2c_commercial_is_refused_not_flipped() -> None:
    with pytest.raises(HTTPException) as err:
        assert_flow_fields(_payload(product_category=ProductCategory.COMMERCIAL.value), ServiceFlow.B2C)
    assert err.value.detail == COMMERCIAL_IS_B2B_DETAIL


def test_b2c_with_b2b_fields_is_refused() -> None:
    with pytest.raises(HTTPException) as err:
        assert_flow_fields(_payload(po_number="PO-1"), ServiceFlow.B2C)
    assert "PO number" in err.value.detail


def test_option_defaults_and_mismatch() -> None:
    assert booking_option(_payload(), ServiceFlow.B2C) == ServiceOption.DELHIVERY_SURFACE
    assert booking_option(_payload(service_type=ServiceType.AIR.value), ServiceFlow.B2C) == ServiceOption.DELHIVERY_EXPRESS
    assert booking_option(_payload(), ServiceFlow.B2B) == ServiceOption.PRIME_SURFACE
    with pytest.raises(HTTPException):
        booking_option(_payload(service_option=ServiceOption.PRIME_SURFACE.value), ServiceFlow.B2C)
    assert service_type_for(ServiceOption.DELHIVERY_EXPRESS) == ServiceType.AIR


# --- price_booking ------------------------------------------------------------------------


async def test_booking_price_matches_quote_and_stores_carrier_cost() -> None:
    result = await _book(_payload(expected_total=159.30))
    assert result.priced.sell.total == Decimal("159.30")
    assert result.carrier_cost["option"] == ServiceOption.DELHIVERY_SURFACE.value
    assert result.carrier_cost["rto"]["cost"] == "50.00"
    assert result.carrier_cost["terms"]["cod_fee_percent"] == "2.0"


async def test_price_changed_is_409_with_new_total() -> None:
    with pytest.raises(HTTPException) as err:
        await _book(_payload(expected_total=150.00))
    assert err.value.status_code == 409
    assert err.value.detail["code"] == PRICE_CHANGED_CODE
    assert err.value.detail["new_total"] == 159.30


async def test_delhivery_down_without_stored_price_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fake_delhivery, "FAKE_DELHIVERY_DOWN", True)
    with pytest.raises(HTTPException) as err:
        await _book(_payload())
    assert err.value.status_code == 503


async def test_cod_goods_is_typed_amount_a01() -> None:
    body = _payload(payment_details={"shipment_value": 2000, "is_cod": True, "cod_amount": 1000, "add_shipping_to_cod": True})
    result = await _book(body)
    assert result.priced.sell.cod_fee == Decimal("20.00")  # 2 % of the typed ₹1,000, not ₹2,000
    assert result.priced.door_collectible == result.priced.sell.total + Decimal("1000.00")


async def test_cod_off_is_refused_with_plain_message() -> None:
    tenant = SimpleNamespace(id=uuid.uuid4(), slug="logismart-test", settings={})
    body = _payload(payment_details={"shipment_value": 2000, "is_cod": True, "cod_amount": 1000})
    with pytest.raises(HTTPException) as err:
        await price_booking(None, tenant, body, pickup_pincode="122001", delivery_pincode="110001")
    assert err.value.detail == COD_DISABLED_DETAIL


async def test_to_pay_and_b2b_reverse_are_refused() -> None:
    with pytest.raises(HTTPException) as to_pay:
        await _book(_payload(payment_details={"shipment_value": 1000, "freight_payment_mode": FreightPaymentMode.TO_PAY.value}))
    assert to_pay.value.detail == mvp_scope.TO_PAY_DISABLED_DETAIL
    reverse = _payload(
        service_flow=ServiceFlow.B2B.value,
        shipment_type=ShipmentType.REVERSE.value,
        reason_for_return="damaged",
        pickup_strategy=PickupStrategy.DEFAULT.value,
    )
    with pytest.raises(HTTPException) as b2b_reverse:
        await _book(reverse)
    assert b2b_reverse.value.detail == mvp_scope.B2B_REVERSE_DISABLED_DETAIL


async def test_b2c_box_weight_cap_a26() -> None:
    body = _payload(packages=[{"length": 10, "breadth": 10, "height": 10, "weight": 500}])
    with pytest.raises(HTTPException) as err:
        await _book(body)
    assert err.value.status_code == 400


def test_zero_dimensions_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        _payload(packages=[{"length": 0, "breadth": 0, "height": 0, "weight": 1}])


def test_bad_pincode_and_phone_rejected_by_schema() -> None:
    with pytest.raises(ValueError):
        _payload(new_delivery_address={**ADDRESS, "pincode": "ABCDEF"})
    with pytest.raises(ValueError):
        _payload(new_delivery_address={**ADDRESS, "pincode": "012345"})
    with pytest.raises(ValueError):
        _payload(new_delivery_address={**ADDRESS, "phone": "12345"})
    assert _payload(new_delivery_address={**ADDRESS, "phone": "+91 98765-43210"})


def test_declared_total_is_server_computed_d06() -> None:
    body = _payload(payment_details={"shipment_value": 50000, "shipment_tax_value": 9000, "shipment_total_value": 1, "eway_bill_numbers": ["123456789012"]})
    assert body.payment_details.shipment_total_value == 59000.0


def test_module_constants_exist_for_tests() -> None:
    assert booking.PRICE_CHANGED_CODE == "PRICE_CHANGED"
