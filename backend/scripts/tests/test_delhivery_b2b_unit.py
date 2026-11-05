"""
Unit + HTTP wire-contract tests for the Delhivery B2B (Cargo / LTL) option
(contract: llm_resources/.agents/pricing/delhivery_b2b_api.md).

Covers:
- `delhivery_b2b_client.LiveDelhiveryB2BApi` over `httpx.MockTransport`: `POST /ums/login`
  body + JWT reuse, Bearer auth, 401 → one re-login, refused-login back-off, 5xx / 429 /
  timeout → unavailable, business refusals, "pricing file" → unavailable, the estimate rate
  limiter, pincode serviceability + TAT parsing and their 24 h cache, credential binding.
- Request body mapping (whole cm rounded up, grouped boxes, grams, string pins, prepaid /
  fop, invoice value, `rov_insurance`), RTO = swapped pins, cache keys.
- The defensive estimate reader (explicit pre-GST, total − GST, total ÷ (1 + GST %), refusal).
- `FakeDelhiveryB2BApi` (formula, never serves live) and `DelhiveryB2BProvider` (cache
  freshness, 24 h fallback, not connected, no boxes, unserviceable, refusals, RTO leg).
- QuoteService cards for B2B, booking (409 / COD / 503), drift-neutral re-pricing, the
  PERCENT / FLAT option markups, and the B2B classifiers.

No database: the price cache is an in-memory stand-in and tenants are SimpleNamespaces.
"""

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.models.manifests import ServiceFlow
from app.models.pickups import (
    DimensionUnit,
    ProductCategory,
    ServiceOption,
    ServiceType,
)
from app.repositories.shipments import B2B_SERVICE_OPTIONS
from app.schemas.v1.pickups import PackageCreate, PickupCreate, carrier_display_name
from app.schemas.v1.pricing import PricingPolicy, QuoteRequest
from app.schemas.v1.tenant_settings import (
    MarkupMode,
    OptionMarkup,
    PricingPolicySettings,
)
from app.services.pricing import delhivery_b2b, delhivery_b2b_client, fake_delhivery_b2b
from app.services.pricing.booking import (
    PRICE_CHANGED_CODE,
    price_booking,
    service_type_for,
)
from app.services.pricing.delhivery import (
    PriceFreshness,
    _Fetched,
    leg_from_response,
    return_only_leg,
)
from app.services.pricing.delhivery_b2b import (
    NO_BOXES_REASON,
    NOT_CONNECTED_REASON,
    B2CFallbackDelhiveryB2BApi,
    DelhiveryB2BProvider,
    cache_key,
    delhivery_b2b_api_for,
    dimensions_payload,
    estimate_amounts,
    estimate_body,
    leg_from_estimate,
    weight_grams,
)
from app.services.pricing.delhivery_b2b_client import (
    ESTIMATE_PATH,
    LOGIN_BACKOFF_SECONDS,
    LOGIN_PATH,
    LiveDelhiveryB2BApi,
    error_text,
    live_b2b_api_if_configured,
)
from app.services.pricing.delhivery_client import (
    DelhiveryRefusedError,
    DelhiveryUnavailableError,
)
from app.services.pricing.fake_delhivery import FakeDelhiveryApi
from app.services.pricing.policy import (
    COD_DISABLED_DETAIL,
    delhivery_b2b_configured,
    policy_of,
    to_read,
)
from app.services.pricing.prime import PrimeProvider
from app.services.pricing.quote_service import (
    B2B_OPTIONS,
    PRIME_COD_REASON,
    QuoteService,
    RequoteRequest,
    SellInputs,
    flow_of_option,
    options_for_flow,
    price_option,
)
from app.services.pricing.sell_price import SellTerms, terms_for
from app.services.pricing.types import (
    CarrierLegKind,
    CarrierQuote,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)
from app.services.repricing import _option_for_service_type

BASE_URL = "https://ltl.example.test"
B2B = ServiceOption.DELHIVERY_B2B_SURFACE
TEST_TENANT = SimpleNamespace(id=uuid.uuid4(), slug="logismart-test", settings={})
LIVE_TENANT = SimpleNamespace(id=uuid.uuid4(), slug="logismart", settings={})
JWT = "header.payload.signature"


def _box(weight: float = 30.0, length: float = 50, width: float = 40, height: float = 30, count: int = 1) -> PackageCreate:
    """A cargo box in cm / kg."""
    return PackageCreate(length=length, breadth=width, height=height, weight=weight, box_count=count)


def _spec(*boxes: PackageCreate, invoice: str = "10000", carriers_risk: bool = False) -> ParcelSpec:
    """The calibration lane 122001 → 110001 (default: one 50×40×30 cm, 30 kg box)."""
    return ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="110001",
        packages=tuple(boxes or (_box(),)),
        invoice_value=Decimal(invoice),
        carriers_risk=carriers_risk,
    )


class _MemoryCache:
    """In-memory stand-in for DelhiveryPriceCacheRepository."""

    def __init__(self) -> None:
        self.rows: Dict[str, Any] = {}

    async def get(self, tenant_id: uuid.UUID, key: str) -> Optional[Any]:
        return self.rows.get(key)

    async def upsert(self, *, tenant_id, cache_key, request_params, response, fetched_at) -> None:
        self.rows[cache_key] = SimpleNamespace(response=response, fetched_at=fetched_at)


def _provider(tenant: Any = TEST_TENANT, api: Any = None) -> DelhiveryB2BProvider:
    """A provider with an in-memory cache (fake API by default)."""
    provider = DelhiveryB2BProvider.__new__(DelhiveryB2BProvider)
    provider.tenant = tenant
    provider.cache = _MemoryCache()
    provider.api = api if api is not None else delhivery_b2b.delhivery_b2b_api_for(tenant)
    return provider


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh client state; the fake starts 'up' with no override."""
    delhivery_b2b_client.reset_state()
    monkeypatch.setattr(fake_delhivery_b2b, "FAKE_B2B_DOWN", False)
    monkeypatch.setattr(fake_delhivery_b2b, "FAKE_B2B_PRE_TAX_OVERRIDE", None)


@pytest.fixture
def offline_b2b(monkeypatch: pytest.MonkeyPatch) -> _MemoryCache:
    """Every DelhiveryB2BProvider built by services uses the fake + one shared memory cache."""
    cache = _MemoryCache()

    def _init(self, session, tenant, *, api=None) -> None:
        self.tenant = tenant
        self.cache = cache
        self.api = api if api is not None else delhivery_b2b.delhivery_b2b_api_for(tenant)

    monkeypatch.setattr(DelhiveryB2BProvider, "__init__", _init)
    return cache


# --- wire contract (httpx.MockTransport) ------------------------------------------------


class _Recorder:
    """A MockTransport handler that answers from a route table and records every request."""

    def __init__(self, routes: Dict[str, List[Any]]) -> None:
        self.routes = {path: list(answers) for path, answers in routes.items()}
        self.requests: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        answers = self.routes[request.url.path]
        answer = answers.pop(0) if len(answers) > 1 else answers[0]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        return httpx.Response(status, json=body) if not isinstance(body, str) else httpx.Response(status, text=body)

    def paths(self) -> List[str]:
        return [request.url.path for request in self.requests]


LOGIN_OK = (200, {"data": {"jwt": JWT}})
ESTIMATE_OK = (200, {"success": True, "data": {"total": 472.0, "price_breakup": {"pre_tax_freight_charges": 400.0, "gst": 72.0}}})


def _api(recorder: _Recorder) -> LiveDelhiveryB2BApi:
    """A live client on the mock transport."""
    return LiveDelhiveryB2BApi("LOGISMARTB2BC", "s3cret", BASE_URL + "/", transport=httpx.MockTransport(recorder))


async def test_login_body_then_bearer_estimate_and_jwt_reuse() -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], ESTIMATE_PATH: [ESTIMATE_OK]})
    api = _api(recorder)
    body = estimate_body(_spec())
    first = await api.estimate(body)
    await api.estimate(body)
    assert first["data"]["total"] == 472.0
    assert recorder.paths() == [LOGIN_PATH, ESTIMATE_PATH, ESTIMATE_PATH]  # one login, token reused
    login = recorder.requests[0]
    assert login.method == "POST" and str(login.url) == f"{BASE_URL}{LOGIN_PATH}"
    assert json.loads(login.content) == {"username": "LOGISMARTB2BC", "password": "s3cret"}
    assert "authorization" not in login.headers
    estimate = recorder.requests[1]
    assert estimate.method == "POST"
    assert estimate.headers["authorization"] == f"Bearer {JWT}"
    assert estimate.headers["content-type"] == "application/json"
    assert json.loads(estimate.content) == body


async def test_401_triggers_one_relogin_then_succeeds() -> None:
    recorder = _Recorder(
        {LOGIN_PATH: [LOGIN_OK, (200, {"data": {"jwt": "new.jwt.token"}})], ESTIMATE_PATH: [(401, {"error": "expired"}), ESTIMATE_OK]}
    )
    await _api(recorder).estimate(estimate_body(_spec()))
    assert recorder.paths() == [LOGIN_PATH, ESTIMATE_PATH, LOGIN_PATH, ESTIMATE_PATH]
    assert recorder.requests[-1].headers["authorization"] == "Bearer new.jwt.token"


async def test_persistent_401_is_unavailable() -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], ESTIMATE_PATH: [(401, {"error": "Unauthorized"})]})
    with pytest.raises(DelhiveryUnavailableError):
        await _api(recorder).estimate(estimate_body(_spec()))
    assert recorder.paths().count(ESTIMATE_PATH) == 2


async def test_refused_login_arms_backoff_and_never_retries_within_10_minutes() -> None:
    recorder = _Recorder({LOGIN_PATH: [(401, {"error": "User not authenticated"})], ESTIMATE_PATH: [ESTIMATE_OK]})
    api = _api(recorder)
    with pytest.raises(DelhiveryUnavailableError):
        await api.estimate(estimate_body(_spec()))
    with pytest.raises(DelhiveryUnavailableError, match="paused"):
        await api.estimate(estimate_body(_spec()))
    assert recorder.paths() == [LOGIN_PATH]  # the second call never hit Delhivery
    assert LOGIN_BACKOFF_SECONDS == 600


async def test_login_5xx_does_not_arm_backoff() -> None:
    recorder = _Recorder({LOGIN_PATH: [(503, "down"), LOGIN_OK], ESTIMATE_PATH: [ESTIMATE_OK]})
    api = _api(recorder)
    with pytest.raises(DelhiveryUnavailableError):
        await api.estimate(estimate_body(_spec()))
    await api.estimate(estimate_body(_spec()))
    assert recorder.paths() == [LOGIN_PATH, LOGIN_PATH, ESTIMATE_PATH]


async def test_login_timeout_is_unavailable() -> None:
    recorder = _Recorder({LOGIN_PATH: [httpx.ConnectTimeout("slow")]})
    with pytest.raises(DelhiveryUnavailableError):
        await _api(recorder).estimate(estimate_body(_spec()))


@pytest.mark.parametrize("answer", [(429, {"error": "slow down"}), (503, "oops"), (403, {"detail": "blocked"}), httpx.ReadTimeout("t")])
async def test_estimate_transport_failures_are_unavailable(answer: Any) -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], ESTIMATE_PATH: [answer]})
    with pytest.raises(DelhiveryUnavailableError):
        await _api(recorder).estimate(estimate_body(_spec()))


@pytest.mark.parametrize(
    "answer,detail",
    [
        ((400, {"error": "pin : 4000690 not found in DataBase"}), "not found in DataBase"),
        ((200, {"success": False, "data": "payment_mode: Permitted values: ['prepaid', 'cod']"}), "Permitted"),
        ((422, {"message": "Validation Error: ['weight_g: field required']"}), "weight_g"),
    ],
)
async def test_estimate_business_refusals(answer: Any, detail: str) -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], ESTIMATE_PATH: [answer]})
    with pytest.raises(DelhiveryRefusedError, match=detail):
        await _api(recorder).estimate(estimate_body(_spec()))


async def test_missing_pricing_file_is_unavailable_not_a_route_refusal() -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], ESTIMATE_PATH: [(400, {"error": "Pricing File Not exist"})]})
    with pytest.raises(DelhiveryUnavailableError, match="rate card"):
        await _api(recorder).estimate(estimate_body(_spec()))


async def test_unreadable_estimate_is_unavailable() -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], ESTIMATE_PATH: [(200, "<html>")]})
    with pytest.raises(DelhiveryUnavailableError):
        await _api(recorder).estimate(estimate_body(_spec()))


async def test_estimate_limiter_refuses_locally(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(delhivery_b2b_client, "_ESTIMATE_LIMITER", delhivery_b2b_client._SlidingWindowLimiter(1, 300.0))
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], ESTIMATE_PATH: [ESTIMATE_OK]})
    api = _api(recorder)
    await api.estimate(estimate_body(_spec()))
    with pytest.raises(DelhiveryUnavailableError, match="limit"):
        await api.estimate(estimate_body(_spec()))
    assert recorder.paths().count(ESTIMATE_PATH) == 1


async def test_pincode_serviceability_parsing_and_cache() -> None:
    recorder = _Recorder(
        {
            LOGIN_PATH: [LOGIN_OK],
            "/pincode-service/122001": [(200, {"data": {"pincode": "122001"}})],
            "/pincode-service/100001": [(400, {"error": "pin: 100001 is not serviceable."})],
            "/pincode-service/560001": [(200, {"data": {"serviceable": False}})],
            "/pincode-service/799001": [(200, {"data": {"serviceable": True, "cod": False}})],
        }
    )
    api = _api(recorder)
    assert await api.pincode_serviceable("122001", 30000) is True
    assert await api.pincode_serviceable("100001", 30000) is False
    assert await api.pincode_serviceable("560001", 30000) is False
    assert await api.pincode_serviceable("122001", 30000) is True  # cached
    assert await api.pincode_serviceable("799001", 30000, is_cod=False) is True
    assert await api.pincode_serviceable("799001", 30000, is_cod=True) is False
    assert recorder.paths().count("/pincode-service/799001") == 1  # raw response reused across modes
    assert recorder.paths().count("/pincode-service/122001") == 1
    assert recorder.requests[1].url.params["weight"] == "30000"
    assert recorder.requests[1].headers["authorization"] == f"Bearer {JWT}"


async def test_pincode_other_refusal_propagates() -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], "/pincode-service/122001": [(404, {"error": "No Such Resource"})]})
    with pytest.raises(DelhiveryRefusedError):
        await _api(recorder).pincode_serviceable("122001", 1)


async def test_tat_parsing_refusal_and_cache() -> None:
    recorder = _Recorder({LOGIN_PATH: [LOGIN_OK], "/tat/estimate": [(200, {"data": {"tat": 3}}), (400, {"error": "Origin pin not serviceable."})]})
    api = _api(recorder)
    assert await api.tat_days("122001", "110001") == 3
    assert await api.tat_days("122001", "110001") == 3  # cached
    assert await api.tat_days("999999", "110001") is None
    tat_request = recorder.requests[1]
    assert dict(tat_request.url.params) == {"origin_pin": "122001", "destination_pin": "110001"}


def test_error_text_shapes() -> None:
    assert error_text({"error": "x"}) == "x"
    assert error_text({"success": False}) == "Delhivery refused the request."
    assert error_text({"success": True, "data": {}}) is None
    assert error_text([1, 2]) is None


def test_live_client_needs_credentials_and_the_bound_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = str(uuid.uuid4())
    monkeypatch.setattr(settings, "DELHIVERY_TENANT_ID", tenant_id)
    monkeypatch.setattr(settings, "DELHIVERY_B2B_USERNAME", "")
    monkeypatch.setattr(settings, "DELHIVERY_B2B_PASSWORD", "pw")
    assert live_b2b_api_if_configured(tenant_id) is None
    monkeypatch.setattr(settings, "DELHIVERY_B2B_USERNAME", "LOGISMARTB2BC")
    assert isinstance(live_b2b_api_if_configured(tenant_id), LiveDelhiveryB2BApi)
    assert live_b2b_api_if_configured(str(uuid.uuid4())) is None
    live = SimpleNamespace(id=uuid.UUID(tenant_id), slug="logismart", settings={})
    assert delhivery_b2b_configured(live) is True
    assert to_read(live, PricingPolicy()).delhivery_b2b_configured is True


# --- request body ---------------------------------------------------------------------------


def test_body_maps_every_estimate_field() -> None:
    body = estimate_body(_spec(invoice="60000", carriers_risk=True))
    assert body == {
        "dimensions": [{"length_cm": 50, "width_cm": 40, "height_cm": 30, "box_count": 1}],
        "weight_g": 30000,
        "source_pin": "122001",
        "consignee_pin": "110001",
        "payment_mode": "prepaid",
        "freight_mode": "fop",
        "inv_amount": 60000.0,
        "rov_insurance": True,
        "cheque_payment": False,
    }
    assert isinstance(body["source_pin"], str)


def test_dimensions_round_up_group_and_convert_units() -> None:
    inches = PackageCreate(length=10, breadth=10, height=10, dimension_unit=DimensionUnit.IN, weight=1, box_count=2)
    boxes = [_box(length=10.2, width=10, height=10), _box(length=11, width=10, height=10, count=2), inches]
    assert dimensions_payload(boxes) == [
        {"length_cm": 11, "width_cm": 10, "height_cm": 10, "box_count": 3},
        {"length_cm": 26, "width_cm": 26, "height_cm": 26, "box_count": 2},
    ]
    assert weight_grams([_box(weight=0.0001)]) == 1
    assert weight_grams([_box(weight=2.5, count=3)]) == 7500


def test_rto_body_swaps_pins_and_cache_keys_are_exact() -> None:
    forward, rto = estimate_body(_spec()), estimate_body(_spec(), CarrierLegKind.RTO)
    assert (rto["source_pin"], rto["consignee_pin"]) == ("110001", "122001")
    assert cache_key(forward).startswith("B2B|122001|110001|")
    assert cache_key(forward) == cache_key(dict(reversed(list(forward.items()))))
    assert cache_key(forward) != cache_key(estimate_body(_spec(invoice="10001")))
    assert len(cache_key(forward)) <= 200


# --- estimate reader -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "response,pre_tax",
    [
        ({"data": {"total": 472, "price_breakup": {"pre_tax_freight_charges": 400, "gst": 72}}}, "400.00"),
        ({"data": {"total": 472.0, "gst": 72.0}}, "400.00"),
        ({"data": {"grand_total": 590, "gst_percent": 18}}, "500.00"),
        ({"data": [{"total_amount": 118, "tax_amount": 18}]}, "100.00"),
        ({"total": 236, "tax": 36}, "200.00"),
    ],
)
def test_estimate_reader_variants(response: Dict[str, Any], pre_tax: str) -> None:
    amounts = estimate_amounts(response)
    assert amounts is not None and amounts.pre_tax == Decimal(pre_tax)


@pytest.mark.parametrize(
    "response",
    [{"data": {"total": 472}}, {"data": {"pre_tax_amount": 0}}, {"data": "x"}, {}, {"data": {"total": "abc", "gst": True}}],
)
def test_estimate_reader_never_guesses(response: Dict[str, Any]) -> None:
    assert estimate_amounts(response) is None


def test_leg_details_are_server_side_and_weight_falls_back() -> None:
    fetched = _Fetched({"data": {"total": 118, "gst": 18, "breakup": {"fuel": 10, "label": "x"}}}, datetime(2026, 11, 1), PriceSource.LIVE)
    leg = leg_from_estimate(CarrierLegKind.FORWARD, fetched, 4, _spec())
    assert leg is not None and leg.cost == Decimal("100.00") and leg.transit_days == 4
    assert leg.charged_weight_kg == Decimal("30.000")  # max(30 kg dead, 60 000 cm³ / 5000)
    assert leg.details["charges"] == {"fuel": 10.0} and leg.details["gross"] == 118.0
    unreadable = _Fetched({"data": {"total": 5}}, datetime(2026, 11, 1), PriceSource.LIVE)
    assert leg_from_estimate(CarrierLegKind.FORWARD, unreadable, None, _spec()) is None


# --- fake ------------------------------------------------------------------------------------


def test_fake_refuses_live_tenant() -> None:
    with pytest.raises(PermissionError):
        fake_delhivery_b2b.FakeDelhiveryB2BApi("logismart")


@pytest.mark.parametrize(
    "spec,pre_tax,gst",
    [
        (_spec(), "400.00", "72.00"),  # 270 + 27 + 100 = 397 → ₹400 minimum LR
        (_spec(invoice="60000", carriers_risk=True), "497.00", "89.46"),  # + ROV max(₹60, ₹100)
        (_spec(_box(weight=50, length=100, width=100, height=100, count=2)), "4500.00", "810.00"),  # 444.444 kg vol
    ],
)
async def test_fake_formula(spec: ParcelSpec, pre_tax: str, gst: str) -> None:
    answer = await fake_delhivery_b2b.FakeDelhiveryB2BApi("logismart-test").estimate(estimate_body(spec))
    amounts = estimate_amounts(answer)
    assert amounts is not None
    assert (amounts.pre_tax, amounts.gst) == (Decimal(pre_tax), Decimal(gst))
    assert amounts.total == Decimal(pre_tax) + Decimal(gst)


async def test_fake_knobs() -> None:
    api = fake_delhivery_b2b.FakeDelhiveryB2BApi("logismart-test")
    with pytest.raises(DelhiveryRefusedError):
        await api.estimate({**estimate_body(_spec()), "consignee_pin": "999999"})
    assert await api.pincode_serviceable("999999", 1) is False
    assert await api.tat_days("122001", "110001") == 4
    fake_delhivery_b2b.FAKE_B2B_PRE_TAX_OVERRIDE = Decimal("1234.5")
    assert estimate_amounts(await api.estimate(estimate_body(_spec()))).pre_tax == Decimal("1234.50")  # type: ignore[union-attr]
    fake_delhivery_b2b.FAKE_B2B_DOWN = True
    with pytest.raises(DelhiveryUnavailableError):
        await api.tat_days("1", "2")


# --- provider ----------------------------------------------------------------------------------


async def test_provider_quote_on_fake() -> None:
    quote = await _provider().quote(B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False)
    assert quote.serviceable and quote.cod_supported is True and quote.rto is None
    assert quote.forward is not None and quote.forward.cost == Decimal("400.00")
    assert quote.forward.transit_days == 4 and quote.forward.charged_weight_kg == Decimal("30.000")
    assert quote.snapshot["request"] == estimate_body(_spec())


async def test_provider_quote_reuses_fresh_cache_even_when_down() -> None:
    provider = _provider()
    await provider.quote(B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False)
    fake_delhivery_b2b.FAKE_B2B_DOWN = True
    again = await provider.quote(B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False)
    assert again.serviceable and again.forward.source == PriceSource.LIVE  # type: ignore[union-attr]


async def test_book_falls_back_to_24h_cache_then_unavailable() -> None:
    provider = _provider()
    await provider.quote(B2B, _spec(), freshness=PriceFreshness.BOOK, include_rto=False)
    fake_delhivery_b2b.FAKE_B2B_DOWN = True
    cached = await provider.quote(B2B, _spec(), freshness=PriceFreshness.BOOK, include_rto=False)
    assert cached.serviceable and cached.forward.source == PriceSource.CACHED  # type: ignore[union-attr]
    for row in provider.cache.rows.values():
        row.fetched_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
    stale = await provider.quote(B2B, _spec(), freshness=PriceFreshness.BOOK, include_rto=False)
    assert stale.unavailable_code == QuoteUnavailableCode.PRICE_UNAVAILABLE


async def test_provider_unavailable_reasons() -> None:
    not_connected = await _provider(LIVE_TENANT).quote(B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False)
    assert not_connected.unavailable_reason == NOT_CONNECTED_REASON
    blind = ParcelSpec(pickup_pincode="122001", delivery_pincode="110001", packages=(), is_blind_pickup=True)
    no_boxes = await _provider().quote(B2B, blind, freshness=PriceFreshness.QUOTE, include_rto=False)
    assert no_boxes.unavailable_reason == NO_BOXES_REASON
    pin_spec = ParcelSpec(pickup_pincode="122001", delivery_pincode="999999", packages=(_box(),))
    unserved = await _provider().quote(B2B, pin_spec, freshness=PriceFreshness.QUOTE, include_rto=False)
    assert unserved.unavailable_code == QuoteUnavailableCode.NOT_SERVICEABLE and "999999" in unserved.unavailable_reason  # type: ignore[operator]
    no_cod_spec = ParcelSpec(pickup_pincode="122001", delivery_pincode="799001", packages=(_box(),))
    prepaid_ok = await _provider().quote(
        B2B, no_cod_spec, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False
    )
    assert prepaid_ok.serviceable is True
    cod_refused = await _provider().quote(
        B2B, no_cod_spec, freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=True
    )
    assert (
        cod_refused.serviceable is False
        and cod_refused.unavailable_code == QuoteUnavailableCode.COD_NOT_AVAILABLE
        and "799001" in cod_refused.unavailable_reason  # type: ignore[operator]
    )


class _StubApi:
    """A B2B API stub whose estimate answer is set per test."""

    def __init__(self, estimate: Callable[[], Any], served: Any = True) -> None:
        self._estimate, self._served = estimate, served

    async def estimate(self, body):
        return self._estimate()

    async def pincode_serviceable(self, pin, grams, *, is_cod: bool = False, is_origin: bool = False):
        if isinstance(self._served, Exception):
            raise self._served
        return self._served

    async def tat_days(self, origin, destination):
        raise DelhiveryUnavailableError("no tat")


async def test_estimate_refusal_and_unreadable_answer_and_lookup_outage() -> None:
    def _refuse() -> Any:
        raise DelhiveryRefusedError("pin : 4000690 not found in DataBase")

    refused = await _provider(api=_StubApi(_refuse)).quote(B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False)
    assert refused.unavailable_code == QuoteUnavailableCode.NOT_SERVICEABLE and "DataBase" in refused.unavailable_reason  # type: ignore[operator]
    unreadable = await _provider(api=_StubApi(lambda: {"data": {"total": 9}})).quote(
        B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False
    )
    assert unreadable.unavailable_code == QuoteUnavailableCode.PRICE_UNAVAILABLE
    lookup_down = _StubApi(lambda: {"data": {"pre_tax_amount": 321}}, served=DelhiveryUnavailableError("down"))
    priced = await _provider(api=lookup_down).quote(B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False)
    assert priced.serviceable and priced.forward.cost == Decimal("321.00") and priced.forward.transit_days is None  # type: ignore[union-attr]


async def test_rto_leg_prices_the_return_lane_and_reuses_cache() -> None:
    provider = _provider()
    quote = await provider.quote(B2B, _spec(), freshness=PriceFreshness.BOOK, include_rto=True)
    assert quote.rto is not None and quote.rto.kind == CarrierLegKind.RTO and quote.rto.cost == Decimal("400.00")
    assert cache_key(estimate_body(_spec(), CarrierLegKind.RTO)) in provider.cache.rows
    fake_delhivery_b2b.FAKE_B2B_DOWN = True
    again = await provider._rto_leg(_spec())
    assert again is not None and again.source == PriceSource.CACHED


async def test_leg_for_refusal_is_none() -> None:
    def _refuse() -> Any:
        raise DelhiveryRefusedError("no")

    assert await _provider(api=_StubApi(_refuse)).leg_for(B2B, _spec(), CarrierLegKind.FORWARD) is None
    assert await _provider(LIVE_TENANT).leg_for(B2B, _spec(), CarrierLegKind.FORWARD) is None


# --- options, sell price, markups ---------------------------------------------------------------


def test_b2b_flow_offers_prime_and_delhivery_b2b() -> None:
    assert options_for_flow(ServiceFlow.B2B) == (ServiceOption.PRIME_SURFACE, B2B) == B2B_OPTIONS
    assert flow_of_option(B2B) == ServiceFlow.B2B
    assert B2B in B2B_SERVICE_OPTIONS
    assert service_type_for(B2B) == ServiceType.SURFACE_ROAD
    assert carrier_display_name(B2B) == "Delhivery"
    assert _option_for_service_type(B2B, ServiceType.AIR) == B2B
    assert _option_for_service_type(ServiceOption.PRIME_SURFACE, ServiceType.AIR) == ServiceOption.PRIME_SURFACE
    assert _option_for_service_type(ServiceOption.DELHIVERY_SURFACE, ServiceType.AIR) == ServiceOption.DELHIVERY_EXPRESS


async def _priced_quote(policy: PricingPolicy, include_rto: bool = False):
    quote = await _provider().quote(B2B, _spec(), freshness=PriceFreshness.BOOK, include_rto=True)
    terms = terms_for(quote, policy)
    return price_option(quote, terms, _spec(), SellInputs(include_rto=include_rto)), terms


async def test_default_policy_is_delhivery_pre_gst_plus_18_percent() -> None:
    priced, terms = await _priced_quote(PricingPolicy())
    assert terms.markup_percent == Decimal("0") and terms.markup_flat == Decimal("0.00")
    assert terms.cod_fee_percent == Decimal("2.0") and terms.cod_fee_min == Decimal("20.0")
    assert (priced.sell.forward_freight, priced.sell.gst, priced.sell.total) == (Decimal("400.00"), Decimal("72.00"), Decimal("472.00"))
    assert priced.breakdown["sell_lines"][0]["label"] == "Freight (Delhivery B2B Cargo)"
    assert priced.breakdown["service_option"] == B2B.value


async def test_percent_and_flat_option_markups() -> None:
    percent = PricingPolicy(option_markups={B2B: OptionMarkup(mode=MarkupMode.PERCENT, value=10)})
    priced, _ = await _priced_quote(percent)
    assert priced.sell.total == Decimal("519.20")  # 440 + 18 %
    flat = PricingPolicy(option_markups={B2B: {"mode": "FLAT", "value": 50}})
    priced, terms = await _priced_quote(flat, include_rto=True)
    assert terms.markup_flat == Decimal("50.00") and terms.markup_percent == Decimal("0")
    assert priced.sell.forward_freight == Decimal("450.00") and priced.sell.rto_freight == Decimal("450.00")
    assert priced.sell.total == Decimal("1062.00")
    assert SellTerms.from_json(terms.to_json()) == terms


def test_option_markup_overrides_prime_lane_and_old_terms_default_flat_zero() -> None:
    prime_quote = CarrierQuote(option=ServiceOption.PRIME_SURFACE, serviceable=True, markup_percent=Decimal("20"))
    assert terms_for(prime_quote, PricingPolicy()).markup_percent == Decimal("20")
    overridden = PricingPolicy(option_markups={ServiceOption.PRIME_SURFACE: {"mode": "PERCENT", "value": 5}})
    assert terms_for(prime_quote, overridden).markup_percent == Decimal("5")
    legacy = SellTerms.from_json({"markup_percent": "20", "cod_fee_percent": None, "cod_fee_min": None, "gst_percent": "18"})
    assert legacy.markup_flat == Decimal("0")


def test_option_markup_validation_and_storage_shape() -> None:
    with pytest.raises(ValidationError):
        OptionMarkup(mode=MarkupMode.PERCENT, value=201)
    with pytest.raises(ValidationError):
        OptionMarkup(mode=MarkupMode.FLAT, value=100_001)
    with pytest.raises(ValidationError):
        OptionMarkup(mode=MarkupMode.FLAT, value=-1)
    assert OptionMarkup(mode=MarkupMode.FLAT, value=100_000).value == 100_000
    policy = PricingPolicy(option_markups={B2B: {"mode": "FLAT", "value": 25}})
    stored = policy.model_dump(mode="json")
    assert stored["option_markups"] == {B2B.value: {"mode": "FLAT", "value": 25.0}}
    assert policy_of(SimpleNamespace(id=uuid.uuid4(), slug="x", settings={"pricing_policy": stored})) == policy
    assert PricingPolicy().option_markups == {} and B2B in PricingPolicy().enabled_options
    assert PricingPolicySettings(option_markups={B2B.value: {"mode": "PERCENT", "value": 3}}).option_markups[B2B].value == 3


# --- QuoteService / booking / re-pricing -------------------------------------------------------------


@pytest.fixture
def no_prime_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prime has no lane on the calibration route (only Delhivery B2B is serviceable)."""

    async def _quote(self, tenant_id, spec):
        return CarrierQuote.unavailable(ServiceOption.PRIME_SURFACE, QuoteUnavailableCode.NO_PRIME_LANE, "no lane")

    monkeypatch.setattr(PrimeProvider, "quote", _quote)


async def test_quote_options_b2b_cards(offline_b2b: _MemoryCache, no_prime_lane: None) -> None:
    request = QuoteRequest(
        service_flow=ServiceFlow.B2B,
        pickup_pincode="122001",
        delivery_pincode="110001",
        packages=[_box()],
        shipment_value=50000,
        shipment_tax_value=10000,
        is_carriers_risk=True,
    )
    response = await QuoteService(AsyncMock()).quote_options(TEST_TENANT, request, None)
    cards = {card.service_option: card for card in response.options}
    assert set(cards) == {ServiceOption.PRIME_SURFACE, B2B}
    assert cards[ServiceOption.PRIME_SURFACE].serviceable is False
    b2b = cards[B2B]
    assert b2b.serviceable and b2b.total_amount == 586.46 and b2b.freight_amount == 497.0 and b2b.transit_days == 4
    assert response.cod_available is True and response.cod_unavailable_reason is None
    dumped = response.model_dump_json()
    assert "pre_tax" not in dumped and "gross" not in dumped and "carrier" not in dumped


async def test_disabled_option_and_cod_refusal(offline_b2b: _MemoryCache) -> None:
    service = QuoteService(AsyncMock())
    off = PricingPolicy(enabled_options=[ServiceOption.PRIME_SURFACE])
    disabled = await service.carrier_quote(TEST_TENANT, off, B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=False)
    assert disabled.unavailable_code == QuoteUnavailableCode.OPTION_DISABLED
    assert service._cod_availability(ServiceFlow.B2B, off) == (False, PRIME_COD_REASON)
    prime_cod = await service.carrier_quote(TEST_TENANT, PricingPolicy(), ServiceOption.PRIME_SURFACE, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=True)
    assert prime_cod.unavailable_code == QuoteUnavailableCode.COD_NOT_AVAILABLE and prime_cod.unavailable_reason == PRIME_COD_REASON
    b2b_cod = await service.carrier_quote(TEST_TENANT, PricingPolicy(), B2B, _spec(), freshness=PriceFreshness.QUOTE, include_rto=False, is_cod=True)
    assert b2b_cod.serviceable is True and b2b_cod.cod_supported is True


ADDRESS = {"name": "Asha", "phone": "9876543210", "address_line1": "1 MG Road", "city": "Gurugram", "state": "Haryana", "pincode": "122001"}


def _b2b_payload(**overrides: Any) -> PickupCreate:
    """A valid B2B forward LR on Delhivery B2B Cargo (one 50×40×30 cm, 30 kg box)."""
    body: Dict[str, Any] = {
        "requested_pickup_date": date.today().isoformat(),
        "product_category": ProductCategory.COMMERCIAL.value,
        "new_pickup_address": ADDRESS,
        "new_delivery_address": {**ADDRESS, "pincode": "110001", "city": "Delhi", "state": "Delhi"},
        "packages": [{"length": 50, "breadth": 40, "height": 30, "weight": 30}],
        "payment_details": {"shipment_value": 10000},
        "service_flow": ServiceFlow.B2B.value,
        "service_option": B2B.value,
    }
    body.update(overrides)
    return PickupCreate(**body)


async def _book(payload: PickupCreate):
    return await price_booking(None, TEST_TENANT, payload, pickup_pincode="122001", delivery_pincode="110001")  # type: ignore[arg-type]


async def test_booking_prices_fresh_with_rto_and_409_on_change(offline_b2b: _MemoryCache) -> None:
    booked = await _book(_b2b_payload(expected_total=472.0))
    assert booked.option == B2B and booked.priced.sell.total == Decimal("472.00")
    assert booked.carrier_cost["option"] == B2B.value and booked.carrier_cost["rto"]["cost"] == "400.00"
    assert booked.carrier_cost["inputs"]["invoice_value"] == "10000.00"
    with pytest.raises(HTTPException) as err:
        await _book(_b2b_payload(expected_total=400.0))
    assert err.value.status_code == 409 and err.value.detail["code"] == PRICE_CHANGED_CODE  # type: ignore[index]
    assert err.value.detail["new_total"] == 472.0  # type: ignore[index]


async def test_booking_b2b_cod_and_503_when_down_without_cache(offline_b2b: _MemoryCache) -> None:
    # Delhivery B2B Cargo supports COD: min branch (₹500 -> ₹20 COD fee) & % branch (₹2,500 -> ₹50 COD fee)
    cod_min = await _book(_b2b_payload(payment_details={"shipment_value": 10000, "is_cod": True, "cod_amount": 500}))
    assert cod_min.priced.sell.forward_freight == Decimal("400.00")
    assert cod_min.priced.sell.cod_fee == Decimal("20.00")
    assert cod_min.priced.sell.gst == Decimal("75.60")
    assert cod_min.priced.sell.total == Decimal("495.60")
    assert cod_min.priced.door_collectible == Decimal("500.00")

    cod_pct = await _book(
        _b2b_payload(
            payment_details={
                "shipment_value": 10000,
                "is_cod": True,
                "cod_amount": 2500,
                "add_shipping_to_cod": True,
            }
        )
    )
    assert cod_pct.priced.sell.cod_fee == Decimal("50.00")
    assert cod_pct.priced.sell.total == Decimal("531.00")
    assert cod_pct.priced.door_collectible == Decimal("3031.00")
    assert cod_pct.priced.cod_remittance == Decimal("2500.00")

    # Prime remains Prepaid-only
    with pytest.raises(HTTPException) as prime_err:
        await _book(
            _b2b_payload(
                service_option=ServiceOption.PRIME_SURFACE.value,
                payment_details={"shipment_value": 10000, "is_cod": True, "cod_amount": 500},
            )
        )
    assert prime_err.value.status_code == 400 and prime_err.value.detail == PRIME_COD_REASON

    # Policy COD off refuses B2B COD too
    cod_off_tenant = SimpleNamespace(
        id=uuid.uuid4(),
        slug="logismart-test",
        settings={"pricing_policy": {"cod_fee_percent": None, "cod_fee_min": None}},
    )
    with pytest.raises(HTTPException) as off_err:
        await price_booking(
            None,  # type: ignore[arg-type]
            cod_off_tenant,  # type: ignore[arg-type]
            _b2b_payload(payment_details={"shipment_value": 10000, "is_cod": True, "cod_amount": 500}),
            pickup_pincode="122001",
            delivery_pincode="110001",
        )
    assert off_err.value.status_code == 400 and off_err.value.detail == COD_DISABLED_DETAIL

    offline_b2b.rows.clear()
    fake_delhivery_b2b.FAKE_B2B_DOWN = True
    with pytest.raises(HTTPException) as down:
        await _book(_b2b_payload())
    assert down.value.status_code == 503


async def test_requote_noop_makes_no_call_and_weight_change_is_drift_neutral(offline_b2b: _MemoryCache) -> None:
    booked = await _book(_b2b_payload())
    record = booked.carrier_cost
    same = ParcelSpec(pickup_pincode="122001", delivery_pincode="110001", packages=(_box(),), invoice_value=Decimal("10000"))
    fake_delhivery_b2b.FAKE_B2B_DOWN = True
    noop = await QuoteService(AsyncMock()).requote(TEST_TENANT, record, RequoteRequest(option=B2B, spec=same, sell=SellInputs()))
    assert noop.serviceable and noop.total_amount == 472.0
    heavier = ParcelSpec(pickup_pincode="122001", delivery_pincode="110001", packages=(_box(weight=40),), invoice_value=Decimal("10000"))
    refused = await QuoteService(AsyncMock()).requote(TEST_TENANT, record, RequoteRequest(option=B2B, spec=heavier, sell=SellInputs()))
    assert refused.serviceable is False  # Delhivery down → change refused, old price kept (H-7)
    fake_delhivery_b2b.FAKE_B2B_DOWN = False
    offline_b2b.rows.clear()
    reweighed = await QuoteService(AsyncMock()).requote(TEST_TENANT, record, RequoteRequest(option=B2B, spec=heavier, sell=SellInputs()))
    # booked 400 + (API(40 kg) 496 − API(30 kg) 400) = 496 → + 18 %
    assert reweighed.serviceable and reweighed.base_charge == 496.0 and reweighed.total_amount == 585.28
    assert reweighed.carrier_cost["forward"]["details"]["drift_neutral"]["api_new_inputs"] == "496.00"  # type: ignore[index]
    risk = ParcelSpec(pickup_pincode="122001", delivery_pincode="110001", packages=(_box(),), invoice_value=Decimal("60000"), carriers_risk=True)
    insured = await QuoteService(AsyncMock()).requote(TEST_TENANT, record, RequoteRequest(option=B2B, spec=risk, sell=SellInputs()))
    assert insured.base_charge == 497.0  # 400 + (497 − 400): the risk switch is a carrier input


# --- B2C RTO is cumulative (prod check 2026-11-01) ---------------------------------------------


def test_b2c_rto_leg_is_return_only() -> None:
    now = datetime(2026, 11, 1)
    forward = leg_from_response(CarrierLegKind.FORWARD, _Fetched({"gross_amount": 35.69, "charged_weight": 500}, now, PriceSource.LIVE), 5)
    cumulative = leg_from_response(CarrierLegKind.RTO, _Fetched({"gross_amount": 69.39, "charged_weight": 500}, now, PriceSource.CACHED), None)
    rto = return_only_leg(cumulative, forward)
    assert rto is not None and rto.cost == Decimal("33.70") and rto.source == PriceSource.CACHED
    assert rto.details["cumulative_cost"] == "69.39" and rto.details["forward_cost"] == "35.69"
    assert return_only_leg(forward, forward) is None


# --- B2C token fallback when DELHIVERY_B2B_PASSWORD is unset (#558) -----------------------------


def test_b2c_fallback_selected_when_b2b_password_empty_and_b2c_token_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = str(uuid.uuid4())
    live = SimpleNamespace(id=uuid.UUID(tenant_id), slug="logismart", settings={})
    monkeypatch.setattr(settings, "DELHIVERY_TENANT_ID", tenant_id)
    monkeypatch.setattr(settings, "DELHIVERY_B2B_USERNAME", "LOGISMARTB2BC")
    monkeypatch.setattr(settings, "DELHIVERY_B2B_PASSWORD", "")
    monkeypatch.setattr(settings, "DELHIVERY_B2C_TOKEN", "")
    assert delhivery_b2b_configured(live) is False
    assert delhivery_b2b_api_for(live) is None

    monkeypatch.setattr(settings, "DELHIVERY_B2C_TOKEN", "b2c-token-xyz")
    assert delhivery_b2b_configured(live) is True
    assert isinstance(delhivery_b2b_api_for(live), B2CFallbackDelhiveryB2BApi)

    monkeypatch.setattr(settings, "DELHIVERY_B2B_PASSWORD", "ltl-secret")
    assert isinstance(delhivery_b2b_api_for(live), LiveDelhiveryB2BApi)


async def test_b2c_fallback_prices_b2b_quote_with_volumetric_and_rov() -> None:
    fallback = B2CFallbackDelhiveryB2BApi(FakeDelhiveryApi("logismart-test"))
    provider = _provider(LIVE_TENANT, api=fallback)

    owners = await provider.quote(B2B, _spec(invoice="200000", carriers_risk=False), freshness=PriceFreshness.QUOTE, include_rto=True)
    assert owners.serviceable is True
    assert owners.forward is not None and owners.forward.charged_weight_kg == Decimal("30.000")
    assert owners.forward.transit_days == 5
    base_cost = owners.forward.cost
    assert base_cost > Decimal("0")

    carriers = await provider.quote(B2B, _spec(invoice="200000", carriers_risk=True), freshness=PriceFreshness.QUOTE, include_rto=False)
    assert carriers.serviceable is True and carriers.forward is not None
    # 0.1% of 200,000 = ₹200.00 ROV added to pre-tax carrier cost
    assert carriers.forward.cost == base_cost + Decimal("200.00")
    assert carriers.forward.details["charges"]["rov_charges"] == 200.0

    # Volumetric box: 80x60x50 cm = 240,000 cm3 -> 48 kg volumetric > 10 kg dead weight
    vol_spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="110001",
        packages=(_box(length=80, width=60, height=50, weight=10),),
    )
    vol_quote = await provider.quote(B2B, vol_spec, freshness=PriceFreshness.QUOTE, include_rto=False)
    assert vol_quote.serviceable is True and vol_quote.forward is not None
    assert vol_quote.forward.charged_weight_kg == Decimal("48.000")

    unserved = await provider.quote(
        B2B,
        ParcelSpec(pickup_pincode="122001", delivery_pincode="999999", packages=(_box(),)),
        freshness=PriceFreshness.QUOTE,
        include_rto=False,
    )
    assert unserved.serviceable is False and unserved.unavailable_code == QuoteUnavailableCode.NOT_SERVICEABLE
