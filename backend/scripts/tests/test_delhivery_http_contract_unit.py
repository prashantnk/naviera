"""
Exhaustive HTTP wire & contract tests for the live Delhivery B2C integration
(`app/services/pricing/delhivery_client.py`, `app/services/pricing/delhivery.py`).

Covers:
(a) Pincode serviceability (`delivery_codes[].postal_code`, `pre_paid`, `cod`, `is_oda`,
    embargo `REMARK`/`remarks`, empty list = unserviceable, 24h lookup cache).
(b) `kinko/v1/invoice/charges/.json` (`md=S|E`, `ss=Delivered|RTO|DTO`, `pt=Pre-paid|COD`,
    `charge_*` breakup, `gross_amount`/`total_amount`, `charge_COD` stripping).
(c) 50 req / 5 min (`PRICE_CALLS_PER_WINDOW = 45`) sliding-window rate limiter.
(d) 3s HTTP timeout & 5xx/429/403 fallback to `delhivery_price_cache`
    (≤30m fresh cache hit, ≤24h fallback with `PriceSource.CACHED`, >24h -> 503).
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException

from app.models.pickups import (
    DimensionUnit,
    FreightPaymentMode,
    ProductCategory,
    ServiceOption,
    ShipmentType,
    WeightUnit,
)
from app.models.tenants import Tenant
from app.schemas.v1.pickups import (
    AddressCreate,
    PackageCreate,
    PaymentDetailsCreate,
    PickupCreate,
)
from app.services.pricing import delhivery_client
from app.services.pricing.booking import price_booking
from app.services.pricing.delhivery import (
    DelhiveryProvider,
    PriceFreshness,
    _Fetched,
    leg_from_response,
)
from app.services.pricing.delhivery_client import (
    PRICE_CALLS_PER_WINDOW,
    PRICE_WINDOW_SECONDS,
    REQUEST_TIMEOUT_SECONDS,
    DelhiveryRefusedError,
    DelhiveryUnavailableError,
    LiveDelhiveryApi,
    _SlidingWindowLimiter,
    flag,
    is_embargoed,
)
from app.services.pricing.types import (
    CarrierLegKind,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)


def _recorded_kinko_row(
    *,
    gross: float = 145.0,
    total: float = 171.1,
    charge_dl: float = 110.0,
    charge_dph: float = 15.0,
    charge_fsc: float = 20.0,
    charge_rto: float = 0.0,
    charge_dto: float = 0.0,
    charge_cod: float = 0.0,
    charged_weight: int = 500,
    zone: str = "D",
) -> Dict[str, Any]:
    """Recorded `one.delhivery.com` `/api/kinko/v1/invoice/charges/.json` element shape."""
    return {
        "gross_amount": gross,
        "total_amount": total,
        "charged_weight": charged_weight,
        "zone": zone,
        "status": "Delivered",
        "charge_DL": charge_dl,
        "charge_DPH": charge_dph,
        "charge_FSC": charge_fsc,
        "charge_FOV": 0.0,
        "charge_RTO": charge_rto,
        "charge_DTO": charge_dto,
        "charge_COD": charge_cod,
        "charge_WOD": 0.0,
        "charge_DOCUMENT": 0.0,
        "charge_AWB": 0.0,
        "tax_data": {"CGST": 0.0, "SGST": 0.0, "IGST": round(total - gross, 2)},
    }


def _recorded_pincode_payload(
    *,
    pin: int = 400001,
    pre_paid: str = "Y",
    cod: str = "Y",
    pickup: str = "Y",
    repl: str = "Y",
    is_oda: str = "N",
    remarks: str = "",
    upper_remark: str | None = None,
) -> Dict[str, Any]:
    """Recorded `/c/api/pin-codes/json/` response shape."""
    postal: Dict[str, Any] = {
        "pin": pin,
        "city": "Mumbai",
        "district": "Mumbai",
        "state_code": "MH",
        "pre_paid": pre_paid,
        "cod": cod,
        "pickup": pickup,
        "repl": repl,
        "is_oda": is_oda,
        "remarks": remarks,
    }
    if upper_remark is not None:
        postal["REMARK"] = upper_remark
    return {"delivery_codes": [{"postal_code": postal}]}


def _spec(
    *,
    pickup_pin: str = "110037",
    delivery_pin: str = "400001",
    shipment_type: ShipmentType = ShipmentType.FORWARD,
    weight_kg: float = 0.5,
) -> ParcelSpec:
    return ParcelSpec(
        pickup_pincode=pickup_pin,
        delivery_pincode=delivery_pin,
        packages=(
            PackageCreate(
                length=10.0,
                breadth=10.0,
                height=10.0,
                dimension_unit=DimensionUnit.CM,
                weight=weight_kg,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
        shipment_type=shipment_type,
    )


def _live_tenant() -> Tenant:
    return Tenant(
        id=uuid.uuid4(),
        name="Logismart Live",
        slug="logismart",
        settings={
            "pricing_policy": {
                "delhivery_markup_percent": 0.0,
                "prime_default_markup_percent": 20.0,
                "cod_fee_percent": 2.0,
                "cod_fee_min": 40.0,
                "enabled_options": [
                    "DELHIVERY_SURFACE",
                    "DELHIVERY_EXPRESS",
                    "PRIME_SURFACE",
                ],
            }
        },
    )


# =============================================================================
# (a) Pincode serviceability wire contract
# =============================================================================


@pytest.mark.asyncio
async def test_pincode_wire_serviceability_oda_embargo_and_empty_list() -> None:
    """
    Tests `LiveDelhiveryApi.pincode` + `flag`/`is_embargoed` + `DelhiveryProvider` on:
    - Authorization header (`Token <token>`, never Bearer)
    - Serviceable pin (`pre_paid=Y`, `cod=Y`, `is_oda=N`)
    - ODA pin (`is_oda=Y`)
    - Embargo remark (`remarks="Embargo"` and uppercase `REMARK="Temporary Embargo"`)
    - Empty `delivery_codes: []` -> `None` -> `NOT_SERVICEABLE`
    - `cod="N"` with `is_cod=True` -> `COD_NOT_AVAILABLE`
    - 24h in-process lookup cache reuse
    """
    delhivery_client._LOOKUP_CACHE.clear()
    seen_headers: List[Dict[str, str]] = []
    pin_calls: List[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        code = request.url.params.get("filter_codes", "")
        pin_calls.append(code)
        if code == "400001":
            return httpx.Response(200, json=_recorded_pincode_payload(pin=400001))
        if code == "400009":
            return httpx.Response(200, json=_recorded_pincode_payload(pin=400009, is_oda="Y"))
        if code == "799001":
            return httpx.Response(
                200,
                json=_recorded_pincode_payload(
                    pin=799001, remarks="", upper_remark="Temporary Embargo"
                ),
            )
        if code == "500001":
            return httpx.Response(200, json=_recorded_pincode_payload(pin=500001, cod="N"))
        return httpx.Response(200, json={"delivery_codes": []})

    api = LiveDelhiveryApi(
        token="dlv-secret-token",
        base_url="https://track.delhivery.com",
        transport=httpx.MockTransport(handler),
    )

    rec_ok = await api.pincode("400001")
    assert rec_ok is not None
    assert seen_headers[0]["authorization"] == "Token dlv-secret-token"
    assert flag(rec_ok, "pre_paid") is True
    assert flag(rec_ok, "cod") is True
    assert flag(rec_ok, "is_oda") is False
    assert is_embargoed(rec_ok) is False

    # Second call for 400001 hits the 24h in-process cache (no second HTTP call)
    rec_cached = await api.pincode("400001")
    assert rec_cached == rec_ok
    assert pin_calls.count("400001") == 1

    rec_oda = await api.pincode("400009")
    assert rec_oda is not None and flag(rec_oda, "is_oda") is True

    rec_embargo = await api.pincode("799001")
    assert rec_embargo is not None and is_embargoed(rec_embargo) is True

    rec_unserv = await api.pincode("000000")
    assert rec_unserv is None

    # Provider-level mapping of embargo, unserviceable, and COD-disabled pins
    tenant = _live_tenant()
    provider = DelhiveryProvider(AsyncMock(), tenant, api=api)

    q_embargo = await provider.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(pickup_pin="400001", delivery_pin="799001"),
        freshness=PriceFreshness.QUOTE,
        include_rto=False,
        is_cod=False,
    )
    assert q_embargo.serviceable is False
    assert q_embargo.unavailable_code == QuoteUnavailableCode.EMBARGO

    q_unserv = await provider.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(pickup_pin="400001", delivery_pin="999998"),
        freshness=PriceFreshness.QUOTE,
        include_rto=False,
        is_cod=False,
    )
    assert q_unserv.serviceable is False
    assert q_unserv.unavailable_code == QuoteUnavailableCode.NOT_SERVICEABLE

    q_no_cod = await provider.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(pickup_pin="400001", delivery_pin="500001"),
        freshness=PriceFreshness.QUOTE,
        include_rto=False,
        is_cod=True,
    )
    assert q_no_cod.serviceable is False
    assert q_no_cod.unavailable_code == QuoteUnavailableCode.COD_NOT_AVAILABLE


# =============================================================================
# (b) `kinko/v1/invoice/charges/.json` wire contract (`md`, `ss`, `pt`, breakup)
# =============================================================================


@pytest.mark.asyncio
async def test_kinko_invoice_charges_modes_statuses_and_cod_stripping() -> None:
    """
    Tests `LiveDelhiveryApi.invoice_charges` and `DelhiveryProvider` across:
    - `md=S` (Surface) and `md=E` (Express)
    - `ss=Delivered` (forward), `ss=RTO` (return leg), and `ss=DTO` (reverse pickup)
    - `pt=Pre-paid` vs `pt=COD` (`charge_COD` stripped from `gross_amount` by `leg_from_response`)
    - Non-zero `charge_*` keys preserved in `details["charges"]`
    - Business refusal (`{"error": "..."}` -> `DelhiveryRefusedError`)
    """
    delhivery_client._LOOKUP_CACHE.clear()
    delhivery_client._PRICE_LIMITER._calls.clear()
    kinko_queries: List[Dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pin-codes/json/"):
            pin = int(request.url.params.get("filter_codes", "400001"))
            return httpx.Response(200, json=_recorded_pincode_payload(pin=pin))
        if path.endswith("/expected_tat"):
            mot = request.url.params.get("mot", "S")
            return httpx.Response(
                200, json={"success": True, "data": {"tat": 2 if mot == "E" else 5}}
            )
        if path.endswith("/invoice/charges/.json"):
            params = dict(request.url.params)
            kinko_queries.append(params)
            if params.get("d_pin") == "888888":
                return httpx.Response(200, json={"error": "Lane not supported"})
            md = params.get("md")
            ss = params.get("ss")
            if ss == "RTO":
                # Real Delhivery `ss=RTO` is cumulative (forward 110 + return 40), prod check 2026-11-01.
                return httpx.Response(
                    200,
                    json=[
                        _recorded_kinko_row(
                            gross=150.0,
                            total=177.0,
                            charge_dl=110.0,
                            charge_dph=0.0,
                            charge_fsc=0.0,
                            charge_rto=40.0,
                        )
                    ],
                )
            if ss == "DTO":
                return httpx.Response(
                    200,
                    json=[
                        _recorded_kinko_row(
                            gross=160.0,
                            total=188.8,
                            charge_dl=100.0,
                            charge_dph=0.0,
                            charge_fsc=20.0,
                            charge_dto=40.0,
                        )
                    ],
                )
            gross = 210.0 if md == "E" else 145.0
            dl = 175.0 if md == "E" else 110.0
            return httpx.Response(
                200,
                json=[
                    _recorded_kinko_row(
                        gross=gross,
                        total=round(gross * 1.18, 2),
                        charge_dl=dl,
                        charge_dph=15.0,
                        charge_fsc=20.0,
                        charge_cod=35.0,  # Even if returned by Delhivery, must be stripped!
                    )
                ],
            )
        return httpx.Response(404)

    api = LiveDelhiveryApi(
        token="dlv-token",
        base_url="https://track.delhivery.com",
        transport=httpx.MockTransport(handler),
    )
    tenant = _live_tenant()
    provider = DelhiveryProvider(AsyncMock(), tenant, api=api)
    provider.cache.get = AsyncMock(return_value=None)
    provider.cache.upsert = AsyncMock()

    # 1. Surface forward + RTO leg (`include_rto=True`)
    q_surface = await provider.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(),
        freshness=PriceFreshness.BOOK,
        include_rto=True,
        is_cod=False,
    )
    assert q_surface.serviceable is True
    assert q_surface.forward is not None
    # gross 145.0 minus charge_COD 35.0 = 110.00 pre-GST freight!
    assert q_surface.forward.cost == Decimal("110.00")
    assert q_surface.forward.transit_days == 5
    assert set(q_surface.forward.details["charges"].keys()) == {
        "charge_DL",
        "charge_DPH",
        "charge_FSC",
        "charge_COD",
    }
    assert q_surface.rto is not None
    assert q_surface.rto.cost == Decimal("40.00")

    # 2. Express forward (`md=E`)
    q_express = await provider.quote(
        ServiceOption.DELHIVERY_EXPRESS,
        _spec(),
        freshness=PriceFreshness.QUOTE,
        include_rto=False,
        is_cod=False,
    )
    assert q_express.serviceable is True
    assert q_express.forward is not None
    assert q_express.forward.cost == Decimal("175.00")  # 210.0 - 35.0 charge_COD
    assert q_express.forward.transit_days == 2

    # 3. Reverse (`ss=DTO`)
    q_reverse = await provider.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(shipment_type=ShipmentType.REVERSE),
        freshness=PriceFreshness.QUOTE,
        include_rto=False,
        is_cod=False,
    )
    assert q_reverse.serviceable is True
    assert q_reverse.forward is not None
    assert q_reverse.forward.cost == Decimal("160.00")
    assert any(q.get("ss") == "DTO" for q in kinko_queries)

    # 4. Business refusal (`{"error": "Lane not supported"}`)
    with pytest.raises(DelhiveryRefusedError):
        await api.invoice_charges(
            {"md": "S", "cgm": 500, "o_pin": "110037", "d_pin": "888888", "ss": "Delivered", "pt": "Pre-paid"}
        )

    # Direct check on leg_from_response stripping charge_COD
    leg = leg_from_response(
        CarrierLegKind.FORWARD,
        _Fetched(
            response={"gross_amount": 150.0, "charge_COD": 40.0, "charged_weight": 500},
            fetched_at=datetime(2026, 10, 30, 0, 0, 0),
            source=PriceSource.LIVE,
        ),
        3,
    )
    assert leg.cost == Decimal("110.00")


# =============================================================================
# (c) 50 req / 5 min (`PRICE_CALLS_PER_WINDOW = 45`) rate limiter
# =============================================================================


@pytest.mark.asyncio
async def test_sliding_window_rate_limiter_enforces_45_per_5_min(monkeypatch) -> None:
    """
    Verifies `_SlidingWindowLimiter(45, 300.0)` allows 45 calls in a 5-min window,
    immediately raises `DelhiveryUnavailableError` on call #46 without sleeping,
    and admits calls again after 300.1s.
    """
    assert PRICE_CALLS_PER_WINDOW == 45
    assert PRICE_WINDOW_SECONDS == 300.0

    clock = [1000.0]
    monkeypatch.setattr(delhivery_client.time, "monotonic", lambda: clock[0])
    limiter = _SlidingWindowLimiter(PRICE_CALLS_PER_WINDOW, PRICE_WINDOW_SECONDS)

    for _ in range(PRICE_CALLS_PER_WINDOW):
        await limiter.acquire()

    with pytest.raises(DelhiveryUnavailableError, match="limit reached"):
        await limiter.acquire()

    # Advance clock past the 5-minute window
    clock[0] += PRICE_WINDOW_SECONDS + 0.1
    await limiter.acquire()


# =============================================================================
# (d) 3s timeout & 5xx/429 fallback to `delhivery_price_cache` (30m / 24h / >24h)
# =============================================================================


@pytest.mark.asyncio
async def test_timeout_and_5xx_429_cache_fallback_30m_24h_and_expired_503(monkeypatch) -> None:
    """
    Verifies:
    - `REQUEST_TIMEOUT_SECONDS == 3.0`
    - `httpx.ReadTimeout` and HTTP 429 / 503 raise `DelhiveryUnavailableError`
    - ≤ 30 min cached row: `PriceFreshness.QUOTE` returns without hitting Delhivery
    - ≤ 24 h cached row (e.g. 3 hours old) when Delhivery times out / 503s: falls back to cache
      (`source == PriceSource.CACHED`)
    - > 24 h cached row (e.g. 26 hours old) when Delhivery is down: returns
      `QuoteUnavailableCode.PRICE_UNAVAILABLE`, and `price_booking` raises HTTP 503.
    """
    assert REQUEST_TIMEOUT_SECONDS == 3.0
    delhivery_client._LOOKUP_CACHE.clear()
    delhivery_client._PRICE_LIMITER._calls.clear()

    # 1. Timeout & 429/503 on LiveDelhiveryApi raise DelhiveryUnavailableError
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("3s timeout exceeded", request=request)

    timeout_api = LiveDelhiveryApi(
        token="dlv-token",
        base_url="https://track.delhivery.com",
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(DelhiveryUnavailableError, match="did not answer in time"):
        await timeout_api.invoice_charges({"md": "S", "cgm": 500})

    for status_code in (401, 403, 429, 500, 502, 503, 504):
        err_api = LiveDelhiveryApi(
            token="dlv-token",
            base_url="https://track.delhivery.com",
            transport=httpx.MockTransport(lambda req, sc=status_code: httpx.Response(sc)),
        )
        delhivery_client._PRICE_LIMITER._calls.clear()
        with pytest.raises(DelhiveryUnavailableError):
            await err_api.invoice_charges({"md": "S", "cgm": 500})

    # Pre-seed pincode cache so pincode serviceability succeeds while price endpoint is down
    delhivery_client._store_lookup(
        ("pin", "110037"), _recorded_pincode_payload(pin=110037)["delivery_codes"][0]["postal_code"]
    )
    delhivery_client._store_lookup(
        ("pin", "400001"), _recorded_pincode_payload(pin=400001)["delivery_codes"][0]["postal_code"]
    )
    delhivery_client._store_lookup(("tat", "110037", "400001", "S"), 4)

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    tenant = _live_tenant()

    # 2. ≤ 30 min cache hit (10 minutes old): 0 HTTP calls made to Delhivery
    fresh_row = SimpleNamespace(
        response=_recorded_kinko_row(gross=120.0, total=141.6, charge_dl=85.0),
        fetched_at=now - timedelta(minutes=10),
    )
    provider_30m = DelhiveryProvider(AsyncMock(), tenant, api=timeout_api)
    provider_30m.cache.get = AsyncMock(return_value=fresh_row)
    q_30m = await provider_30m.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(),
        freshness=PriceFreshness.QUOTE,
        include_rto=False,
        is_cod=False,
    )
    assert q_30m.serviceable is True
    assert q_30m.forward is not None
    assert q_30m.forward.cost == Decimal("120.00")

    # 3. ≤ 24 h fallback (180 minutes old) when Delhivery times out on BOOK
    fallback_row = SimpleNamespace(
        response=_recorded_kinko_row(gross=120.0, total=141.6, charge_dl=85.0),
        fetched_at=now - timedelta(minutes=180),
    )
    provider_24h = DelhiveryProvider(AsyncMock(), tenant, api=timeout_api)
    provider_24h.cache.get = AsyncMock(return_value=fallback_row)
    q_24h = await provider_24h.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(),
        freshness=PriceFreshness.BOOK,
        include_rto=False,
        is_cod=False,
    )
    assert q_24h.serviceable is True
    assert q_24h.forward is not None
    assert q_24h.forward.source == PriceSource.CACHED
    assert q_24h.forward.cost == Decimal("120.00")

    # 4. > 24 h expired row (26 hours old) when Delhivery is down -> PRICE_UNAVAILABLE / HTTP 503
    expired_row = SimpleNamespace(
        response=_recorded_kinko_row(gross=120.0, total=141.6, charge_dl=85.0),
        fetched_at=now - timedelta(hours=26),
    )
    provider_expired = DelhiveryProvider(AsyncMock(), tenant, api=timeout_api)
    provider_expired.cache.get = AsyncMock(return_value=expired_row)
    q_expired = await provider_expired.quote(
        ServiceOption.DELHIVERY_SURFACE,
        _spec(),
        freshness=PriceFreshness.BOOK,
        include_rto=False,
        is_cod=False,
    )
    assert q_expired.serviceable is False
    assert q_expired.unavailable_code == QuoteUnavailableCode.PRICE_UNAVAILABLE

    # Verify price_booking maps PRICE_UNAVAILABLE to HTTP 503
    monkeypatch.setattr(
        "app.services.pricing.quote_service.DelhiveryProvider",
        lambda session, t: provider_expired,
    )
    addr = AddressCreate(
        name="Sender",
        phone="9876543210",
        address_line1="12 MG Road",
        city="Delhi",
        state="DL",
        pincode="110037",
    )
    payload = PickupCreate(
        requested_pickup_date=now.date(),
        product_category=ProductCategory.ELECTRONICS,
        new_pickup_address=addr,
        new_delivery_address=addr.model_copy(update={"pincode": "400001"}),
        packages=list(_spec().packages),
        payment_details=PaymentDetailsCreate(
            freight_payment_mode=FreightPaymentMode.PREPAID,
            shipment_value=500.0,
        ),
        service_option=ServiceOption.DELHIVERY_SURFACE,
    )
    with pytest.raises(HTTPException) as exc_503:
        await price_booking(
            AsyncMock(),
            tenant,
            payload,
            pickup_pincode="110037",
            delivery_pincode="400001",
        )
    assert exc_503.value.status_code == 503
    assert "unavailable" in str(exc_503.value.detail).lower()
