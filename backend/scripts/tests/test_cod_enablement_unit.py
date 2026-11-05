"""
Pure unit tests for Release 8 COD Enablement (`rel8:cod`):
1. Standard COD policy defaults (`DEFAULT_COD_FEE_PERCENT = 2.0`, `DEFAULT_COD_FEE_MIN = 20.0`)
   matching Delhivery One (`rate-card`, `create-forward-order`, `cod-remittance`:
   "fixed ₹ amount or % of COD value, whichever is higher").
2. Quote with and without COD across B2C Express (`DELHIVERY_SURFACE`, `DELHIVERY_EXPRESS`)
   and B2B Cargo (`DELHIVERY_B2B_SURFACE` supports COD; `PRIME_SURFACE` stays Prepaid-only).
3. Minimum fee branch (`cod_amount = ₹500` -> `max(₹20, 2% = ₹10) = ₹20.00`) vs
   percentage branch (`cod_amount = ₹2,500` -> `max(₹20, 2% = ₹50) = ₹50.00`).
4. 18% GST applied on `(forward_freight + cod_fee)` and standalone `COD_FEE` ("COD fee")
   line in `sell_lines` and `pricing_breakdown`.
5. No double-charging on Delhivery options (`pt="Pre-paid"` + `charge_COD` stripped from
   carrier `gross_amount`).
6. Booking freeze (`price_booking`) + `cod_payout.compute_collectibles` door collectible
   and COD remittance accuracy.
7. Cancellation refund of COD fee + freight + GST via `RepricingService.refund_all`
   (`CREDIT_NOTE`) and post-booking `RepricingService` COD edits (`PREPAID <-> COD`,
   min-to-percent `cod_amount` increase, RTO COD fee reversal).
"""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import AsyncMock

import pytest

import scripts.tests.test_repricing_unit as repricing_unit_mod
from app.models.manifests import ServiceFlow
from app.models.pickups import (
    FreightPaymentMode,
    PickupStatus,
    ProductCategory,
    ServiceOption,
)
from app.models.repricing import ChargeAdjustmentReason
from app.models.wallet import WalletTxnType
from app.schemas.v1.pickups import PackageCreate, PickupCreate
from app.schemas.v1.pricing import (
    DEFAULT_COD_FEE_MIN,
    DEFAULT_COD_FEE_PERCENT,
    PricingPolicy,
    QuoteRequest,
)
from app.services import cod_payout
from app.services import delhivery_modules as delhivery_modules_service
from app.services import repricing as rp
from app.services.pricing import delhivery as delhivery_module
from app.services.pricing import delhivery_b2b as delhivery_b2b_module
from app.services.pricing.booking import price_booking
from app.services.pricing.delhivery import (
    PT_PREPAID,
    DelhiveryProvider,
    _Fetched,
    leg_from_response,
    price_params,
)
from app.services.pricing.delhivery_b2b import (
    COD_NOT_SERVED,
    PAYMENT_MODE_PREPAID,
    B2CFallbackDelhiveryB2BApi,
    DelhiveryB2BProvider,
    estimate_body,
)
from app.services.pricing.policy import policy_of
from app.services.pricing.prime import PrimeProvider
from app.services.pricing.quote_service import (
    PRIME_COD_REASON,
    QuoteService,
)
from app.services.pricing.sell_price import (
    COD_LINE_LABEL,
    LINE_COD_FEE,
    LINE_GST,
)
from app.services.pricing.types import (
    CarrierLegKind,
    CarrierQuote,
    ParcelSpec,
    PriceSource,
    QuoteUnavailableCode,
)
from scripts.tests.test_repricing_unit import (
    CUSTOMER,
    FakeNotes,
    FakeRepo,
    FakeWalletRepo,
    box,
    make_shipment,
    service,
    txn,
)

TEST_TENANT = SimpleNamespace(
    id=uuid.uuid4(),
    slug="logismart-test",
    settings={
        "pricing_policy": {
            "delhivery_markup_percent": 0.0,
            "prime_default_markup_percent": 20.0,
            "cod_fee_percent": 2.0,
            "cod_fee_min": 20.0,
            "enabled_options": [
                "DELHIVERY_SURFACE",
                "DELHIVERY_EXPRESS",
                "DELHIVERY_B2B_SURFACE",
                "PRIME_SURFACE",
            ],
        }
    },
)

ADDRESS = {
    "name": "Asha Logistics",
    "phone": "9876543210",
    "address_line1": "Plot 14, Sector 18",
    "city": "Gurugram",
    "state": "Haryana",
    "pincode": "122001",
}


class _MemoryCache:
    """In-memory stand-in for DelhiveryPriceCacheRepository."""

    def __init__(self) -> None:
        self.rows: Dict[str, Any] = {}

    async def get(self, tenant_id: uuid.UUID, key: str) -> Any:
        return self.rows.get(key)

    async def upsert(self, *, tenant_id, cache_key, request_params, response, fetched_at) -> None:
        self.rows[cache_key] = SimpleNamespace(response=response, fetched_at=fetched_at)


@pytest.fixture(autouse=True)
def _offline_providers(monkeypatch: pytest.MonkeyPatch) -> _MemoryCache:
    """Routes both B2C and B2B Delhivery providers through the in-memory cache and fake APIs."""
    cache = _MemoryCache()

    def _b2c_init(self, session, tenant, *, api=None) -> None:
        self.tenant = tenant
        self.cache = cache
        self.api = api if api is not None else delhivery_module.delhivery_api_for(tenant)

    def _b2b_init(self, session, tenant, *, api=None) -> None:
        self.tenant = tenant
        self.cache = cache
        self.api = api if api is not None else delhivery_b2b_module.delhivery_b2b_api_for(tenant)

    async def _prime_quote(self, tenant_id, spec):
        return CarrierQuote.unavailable(ServiceOption.PRIME_SURFACE, QuoteUnavailableCode.NO_PRIME_LANE, "no lane")

    monkeypatch.setattr(DelhiveryProvider, "__init__", _b2c_init)
    monkeypatch.setattr(DelhiveryB2BProvider, "__init__", _b2b_init)
    monkeypatch.setattr(PrimeProvider, "quote", _prime_quote)
    return cache


def test_standard_cod_policy_defaults_and_admin_toggle() -> None:
    """Default policy has COD open with max(₹20, 2%); admin can clear or customize."""
    assert DEFAULT_COD_FEE_PERCENT == 2.0
    assert DEFAULT_COD_FEE_MIN == 20.0

    default_policy = PricingPolicy()
    assert default_policy.cod_enabled is True
    assert default_policy.cod_fee_percent == 2.0
    assert default_policy.cod_fee_min == 20.0

    tenant_unset = SimpleNamespace(id=uuid.uuid4(), slug="logismart", settings={})
    resolved = policy_of(tenant_unset)  # type: ignore[arg-type]
    assert resolved is not None and resolved.cod_enabled is True
    assert resolved.cod_fee_percent == 2.0 and resolved.cod_fee_min == 20.0

    # Admin explicitly disables COD by setting both fields to null
    tenant_off = SimpleNamespace(
        id=uuid.uuid4(),
        slug="logismart",
        settings={"pricing_policy": {"cod_fee_percent": None, "cod_fee_min": None}},
    )
    resolved_off = policy_of(tenant_off)  # type: ignore[arg-type]
    assert resolved_off is not None and resolved_off.cod_enabled is False


def test_delhivery_no_double_charge_on_b2c_and_b2b() -> None:
    """
    Delhivery kinko is always queried with pt='Pre-paid' and any echoed `charge_COD` is
    subtracted from `gross_amount`; Delhivery B2B is queried with payment_mode='prepaid'.
    """
    spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="110001",
        packages=(PackageCreate(length=20, breadth=15, height=10, weight=2.0),),
        invoice_value=Decimal("1500"),
    )
    b2c_params = price_params(ServiceOption.DELHIVERY_SURFACE, spec, "Delivered")
    assert b2c_params["pt"] == PT_PREPAID

    # Even if Delhivery echoes a non-zero charge_COD inside gross_amount, leg_from_response strips it
    fetched = _Fetched(
        response={"gross_amount": 155.00, "charge_DL": 135.00, "charge_COD": 20.00, "charged_weight": 2000},
        fetched_at=datetime.now(timezone.utc).replace(tzinfo=None),
        source=PriceSource.LIVE,
    )
    leg = leg_from_response(CarrierLegKind.FORWARD, fetched, transit_days=3)
    assert leg.cost == Decimal("135.00")
    assert all(line.code != "charge_COD" for line in leg.lines)

    b2b_body = estimate_body(spec)
    assert b2b_body["payment_mode"] == PAYMENT_MODE_PREPAID


async def test_b2c_quotes_without_cod_and_with_cod_min_vs_percent_branch() -> None:
    """Quotes B2C Surface & Express without COD, with COD min branch (₹500), and % branch (₹2,500)."""
    svc = QuoteService(AsyncMock())
    pkg = PackageCreate(length=20, breadth=15, height=10, weight=2.0)

    # 1. Prepaid (no COD)
    prepaid_res = await svc.quote_options(
        TEST_TENANT,  # type: ignore[arg-type]
        QuoteRequest(
            service_flow=ServiceFlow.B2C,
            pickup_pincode="122001",
            delivery_pincode="110001",
            packages=[pkg],
            is_cod=False,
            shipment_value=500.0,
        ),
        None,
    )
    assert prepaid_res.cod_available is True
    surf_prepaid = next(o for o in prepaid_res.options if o.service_option == ServiceOption.DELHIVERY_SURFACE)
    assert surf_prepaid.serviceable is True
    assert surf_prepaid.freight_amount == 135.0
    assert surf_prepaid.cod_fee == 0.0
    assert surf_prepaid.tax_amount == 24.30  # 18% of 135
    assert surf_prepaid.total_amount == 159.30
    assert surf_prepaid.door_collectible_amount == 0.0
    assert surf_prepaid.cod_remittance_amount == 0.0
    assert all(line.code != LINE_COD_FEE for line in surf_prepaid.sell_lines)

    # 2. COD Minimum Branch: cod_amount = ₹500 -> 2% is ₹10 < ₹20 min -> cod_fee = ₹20.00
    min_res = await svc.quote_options(
        TEST_TENANT,  # type: ignore[arg-type]
        QuoteRequest(
            service_flow=ServiceFlow.B2C,
            pickup_pincode="122001",
            delivery_pincode="110001",
            packages=[pkg],
            is_cod=True,
            cod_amount=500.0,
            add_shipping_to_cod=False,
            shipment_value=500.0,
        ),
        None,
    )
    surf_min = next(o for o in min_res.options if o.service_option == ServiceOption.DELHIVERY_SURFACE)
    assert surf_min.freight_amount == 135.0
    assert surf_min.cod_fee == 20.0
    assert surf_min.tax_amount == 27.90  # 18% of (135 + 20) = 27.90
    assert surf_min.total_amount == 182.90
    assert surf_min.door_collectible_amount == 500.0
    assert surf_min.cod_remittance_amount == 500.0
    cod_lines = [line for line in surf_min.sell_lines if line.code == LINE_COD_FEE]
    assert len(cod_lines) == 1 and cod_lines[0].label == COD_LINE_LABEL and cod_lines[0].amount == 20.0
    gst_lines = [line for line in surf_min.sell_lines if line.code == LINE_GST]
    assert len(gst_lines) == 1 and gst_lines[0].amount == 27.90

    # 3. COD Percentage Branch: cod_amount = ₹2,500 -> 2% is ₹50 > ₹20 min -> cod_fee = ₹50.00
    pct_res = await svc.quote_options(
        TEST_TENANT,  # type: ignore[arg-type]
        QuoteRequest(
            service_flow=ServiceFlow.B2C,
            pickup_pincode="122001",
            delivery_pincode="110001",
            packages=[pkg],
            is_cod=True,
            cod_amount=2500.0,
            add_shipping_to_cod=True,
            shipment_value=2500.0,
        ),
        None,
    )
    surf_pct = next(o for o in pct_res.options if o.service_option == ServiceOption.DELHIVERY_SURFACE)
    assert surf_pct.freight_amount == 135.0
    assert surf_pct.cod_fee == 50.0
    assert surf_pct.tax_amount == 33.30  # 18% of (135 + 50) = 33.30
    assert surf_pct.total_amount == 218.30
    assert surf_pct.door_collectible_amount == 2718.30  # 2500 + 218.30 shipping
    assert surf_pct.cod_remittance_amount == 2500.0


async def test_b2b_quotes_delhivery_supports_cod_while_prime_refuses() -> None:
    """On B2B, Delhivery B2B Cargo prices COD with standard COD fee while Prime returns PRIME_COD_REASON."""
    svc = QuoteService(AsyncMock())
    pkg = PackageCreate(length=50, breadth=40, height=30, weight=30.0)

    b2b_res = await svc.quote_options(
        TEST_TENANT,  # type: ignore[arg-type]
        QuoteRequest(
            service_flow=ServiceFlow.B2B,
            pickup_pincode="122001",
            delivery_pincode="110001",
            packages=[pkg],
            is_cod=True,
            cod_amount=3000.0,
            add_shipping_to_cod=True,
            shipment_value=10000.0,
        ),
        None,
    )
    assert b2b_res.cod_available is True and b2b_res.cod_unavailable_reason is None
    cards = {c.service_option: c for c in b2b_res.options}

    prime_card = cards[ServiceOption.PRIME_SURFACE]
    assert prime_card.serviceable is False
    assert prime_card.unavailable_code == QuoteUnavailableCode.COD_NOT_AVAILABLE
    assert prime_card.unavailable_reason == PRIME_COD_REASON

    dlv_b2b = cards[ServiceOption.DELHIVERY_B2B_SURFACE]
    assert dlv_b2b.serviceable is True
    assert dlv_b2b.freight_amount == 400.0
    assert dlv_b2b.cod_fee == 60.0  # 2% of ₹3,000 = ₹60 > ₹20 min
    assert dlv_b2b.tax_amount == 82.80  # 18% of (400 + 60)
    assert dlv_b2b.total_amount == 542.80
    assert dlv_b2b.door_collectible_amount == 3542.80
    assert dlv_b2b.cod_remittance_amount == 3000.0
    assert any(line.code == LINE_COD_FEE and line.amount == 60.0 for line in dlv_b2b.sell_lines)

    # Non-COD destination PIN 799001: Prepaid is serviceable, COD returns COD_NOT_AVAILABLE
    b2b_no_cod_res = await svc.quote_options(
        TEST_TENANT,  # type: ignore[arg-type]
        QuoteRequest(
            service_flow=ServiceFlow.B2B,
            pickup_pincode="122001",
            delivery_pincode="799001",
            packages=[pkg],
            is_cod=True,
            cod_amount=3000.0,
            shipment_value=10000.0,
        ),
        None,
    )
    no_cod_dlv = {c.service_option: c for c in b2b_no_cod_res.options}[ServiceOption.DELHIVERY_B2B_SURFACE]
    assert no_cod_dlv.serviceable is False
    assert no_cod_dlv.unavailable_code == QuoteUnavailableCode.COD_NOT_AVAILABLE
    assert no_cod_dlv.unavailable_reason == COD_NOT_SERVED.format(pin="799001")


async def test_b2b_fallback_enforces_origin_pickup_and_destination_cod_or_prepaid() -> None:
    """B2CFallbackDelhiveryB2BApi enforces origin `pickup`, destination `pre_paid`, and destination `cod`."""

    class _FakeB2C:
        records = {
            "122001": {"pin": 122001, "pickup": "Y", "pre_paid": "Y", "cod": "Y", "remarks": ""},
            "799001": {"pin": 799001, "pickup": "Y", "pre_paid": "Y", "cod": "N", "remarks": ""},
            "800001": {"pin": 800001, "pickup": "Y", "pre_paid": "N", "cod": "N", "remarks": ""},
            "800002": {"pin": 800002, "pickup": "N", "pre_paid": "Y", "cod": "Y", "remarks": ""},
        }

        async def pincode(self, pin: str):
            return self.records.get(pin)

    fallback = B2CFallbackDelhiveryB2BApi(_FakeB2C())  # type: ignore[arg-type]
    # 799001: Prepaid serviceable, COD refused
    assert await fallback.pincode_serviceable("799001", 20000, is_cod=False, is_origin=False) is True
    assert await fallback.pincode_serviceable("799001", 20000, is_cod=True, is_origin=False) is False
    # 800001 (pickup-only PIN): destination Prepaid and COD both refused
    assert await fallback.pincode_serviceable("800001", 20000, is_cod=False, is_origin=False) is False
    assert await fallback.pincode_serviceable("800001", 20000, is_cod=True, is_origin=False) is False
    assert await fallback.pincode_serviceable("800001", 20000, is_cod=False, is_origin=True) is True
    # 800002 (delivery-only PIN, pickup='N'): origin refused, destination allowed
    assert await fallback.pincode_serviceable("800002", 20000, is_cod=False, is_origin=True) is False
    assert await fallback.pincode_serviceable("800002", 20000, is_cod=True, is_origin=False) is True


async def test_booking_freeze_matches_quote_and_cod_payout_collectibles() -> None:
    """Booking freeze matches quote to the paisa and aligns with `cod_payout.compute_collectibles`."""
    payload = PickupCreate(
        requested_pickup_date=date.today().isoformat(),
        product_category=ProductCategory.ELECTRONICS,
        new_pickup_address=ADDRESS,
        new_delivery_address={**ADDRESS, "pincode": "110001", "city": "Delhi", "state": "Delhi"},
        packages=[{"length": 20, "breadth": 15, "height": 10, "weight": 2.0}],
        payment_details={
            "shipment_value": 500,
            "is_cod": True,
            "cod_amount": 500,
            "add_shipping_to_cod": True,
        },
        service_flow=ServiceFlow.B2C,
        service_option=ServiceOption.DELHIVERY_SURFACE,
        expected_total=182.90,
    )
    booked = await price_booking(
        None,  # type: ignore[arg-type]
        TEST_TENANT,  # type: ignore[arg-type]
        payload,
        pickup_pincode="122001",
        delivery_pincode="110001",
    )
    assert booked.priced.sell.forward_freight == Decimal("135.00")
    assert booked.priced.sell.cod_fee == Decimal("20.00")
    assert booked.priced.sell.gst == Decimal("27.90")
    assert booked.priced.sell.total == Decimal("182.90")
    assert booked.priced.breakdown["cod_fee"] == 20.0

    # Verify cod_payout.py door collectible, goods base, & merchant payout match booking freeze
    cod_col, freight_col = cod_payout.collectible_amounts(
        is_cod=True,
        goods=Decimal("500.00"),
        total=booked.priced.sell.total,
        mode=FreightPaymentMode.PREPAID,
        add_shipping_to_cod=True,
        merchant_paid=Decimal("0.00"),
    )
    payment_ns = SimpleNamespace(
        freight_payment_mode=FreightPaymentMode.PREPAID,
        total_logistics_cost=float(booked.priced.sell.total),
        is_cod=True,
        cod_amount=float(cod_col),
        freight_collectible=float(freight_col),
        add_shipping_to_cod=True,
        pricing_breakdown=booked.priced.breakdown,
    )
    assert cod_payout.door_collectible(payment_ns) == booked.priced.door_collectible == Decimal("682.90")  # type: ignore[arg-type]
    assert cod_payout.cod_goods_amount(payment_ns) == booked.priced.cod_remittance == Decimal("500.00")  # type: ignore[arg-type]
    assert cod_payout.cod_payout_amount(payment_ns) == 682.90  # type: ignore[arg-type]


async def test_cod_cancellation_refunds_cod_fee_via_credit_note_and_repricing_handles_cod_edits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    - Pre-pickup cancellation refunds full freight + COD fee + 18% GST via CREDIT_NOTE.
    - RepricingService handles PREPAID <-> COD, min-to-% COD amount increase, and RTO COD fee reversal.
    """
    monkeypatch.setattr(repricing_unit_mod, "TENANT", TEST_TENANT)
    monkeypatch.setattr(rp, "WalletRepository", FakeWalletRepo)
    monkeypatch.setattr(delhivery_modules_service, "DelhiveryModulesService", FakeNotes)
    FakeWalletRepo.wallet = SimpleNamespace(id=uuid.uuid4(), balance=0.0, updated_at=None)
    # 1. Book a COD shipment (₹500 goods -> ₹20 COD fee -> ₹182.90 total) and cancel it
    shipment = make_shipment(
        [box(20, 15, 10, 2.0)],
        is_cod=True,
        goods=500.0,
        total_value=500.0,
        status=PickupStatus.OPEN,
    )
    assert shipment.payment_details.total_logistics_cost == 182.90
    assert shipment.payment_details.pricing_breakdown["cod_fee"] == 20.0

    cancel_repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 182.90)])
    FakeNotes.issued.clear()
    refund_res = await service(cancel_repo).refund_all(
        shipment,
        TEST_TENANT,
        ChargeAdjustmentReason.CANCELLATION,
        CUSTOMER,
    )
    assert refund_res.wallet_delta == Decimal("182.90")
    assert cancel_repo.txns[-1].txn_type == WalletTxnType.REFUND
    assert cancel_repo.txns[-1].amount == 182.90
    assert FakeNotes.issued == [
        {"note_type": "CREDIT_NOTE", "amount": 182.90, "id": refund_res.billing_invoice_id}
    ]
    assert shipment.payment_details.total_logistics_cost == 0.0

    # 2. Repricing: increase cod_amount on an active COD shipment from ₹500 (₹20 fee) to ₹2,500 (₹50 fee)
    active_cod = make_shipment(
        [box(20, 15, 10, 2.0)],
        is_cod=True,
        goods=500.0,
        total_value=3000.0,
        status=PickupStatus.OPEN,
    )
    edit_repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 182.90)])
    FakeNotes.issued.clear()
    up_res = await service(edit_repo).apply(
        active_cod,
        TEST_TENANT,
        rp.RepriceChange(
            reason=ChargeAdjustmentReason.COD_CHANGE,
            is_cod=True,
            cod_amount=Decimal("2500.00"),
        ),
        CUSTOMER,
    )
    # COD fee rises by ₹30 (₹20 -> ₹50) + 18% GST (₹5.40) = ₹35.40 debit
    assert up_res.new_total == Decimal("218.30")
    assert up_res.wallet_delta == Decimal("-35.40")
    assert up_res.note_type == "DEBIT_NOTE"
    assert active_cod.payment_details.pricing_breakdown["cod_fee"] == 50.0

    # 3. Repricing: switch COD -> PREPAID refunds the ₹50 COD fee + ₹9.00 GST = ₹59.00 via CREDIT_NOTE
    down_res = await service(edit_repo).apply(
        active_cod,
        TEST_TENANT,
        rp.RepriceChange(
            reason=ChargeAdjustmentReason.COD_CHANGE,
            is_cod=False,
            cod_amount=Decimal("0.00"),
        ),
        CUSTOMER,
    )
    assert down_res.new_total == Decimal("159.30")
    assert down_res.wallet_delta == Decimal("59.00")
    assert down_res.note_type == "CREDIT_NOTE"
    assert active_cod.payment_details.pricing_breakdown["cod_fee"] == 0.0
