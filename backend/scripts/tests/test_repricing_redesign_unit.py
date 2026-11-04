"""
Unit tests for D4 (DESIGN.md v4):
- `RepricingService._quote` -> `QuoteService.requote`
- No-op re-price delta == ₹0.00
- COD / declared-value edit makes 0 Delhivery calls (uses frozen `carrier_cost`)
- Drift-neutral re-weigh (`new = booked + (API(new) - API(booked))`)
- Delhivery down during re-weigh refuses with H-7 (`ZeroQuoteError`)
- Provisional RTO when RTO leg is missing (`rto.provisional = True`)
- `service_option` edit before pickup (Surface <-> Express), locked after pickup (H-8),
  refused across B2C <-> B2B flows (Q4)
- `TO_PAY` edit refused with 400 (`mvp_scope.TO_PAY_DISABLED_DETAIL`)
- Ops carrier billing (`get_carrier_billing` / `update_carrier_billing`):
  `CARRIER` measurement, invoice-gap verdict (`has_gap`, `gap_amount`, `gap_message`),
  409 duplicate AWB per tenant, and 403 for customer / read_only_user / support_user.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.models.delhivery_modules import InvoiceNoteType
from app.models.pickups import (
    Address,
    DimensionUnit,
    FreightPaymentMode,
    PackageDetails,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ProductCategory,
    ServiceOption,
    ServiceType,
    ShipmentType,
    WeightUnit,
)
from app.models.repricing import (
    ChargeAdjustmentReason,
    MeasurementSource,
)
from app.models.tenants import Tenant, User, UserRole
from app.models.wallet import (
    WalletServiceCategory,
    WalletTxnDirection,
    WalletTxnStatus,
    WalletTxnType,
)
from app.schemas.v1.pickups import PackageCreate, PaymentDetailsCreate, PickupUpdate
from app.schemas.v1.pricing import AdminShipmentChargeCreate, CarrierBillingUpdate
from app.schemas.v1.wallet import AdminOfflineCreditRequest
from app.services import mvp_scope
from app.services.delhivery_modules import shipment_effective_gst_rate
from app.services.pricing import fake_delhivery
from app.services.pricing.carrier_billing import (
    _build_carrier_billing_read,
    apply_admin_shipment_charge,
    get_carrier_billing,
    shipment_transporter_name,
    update_carrier_billing,
)
from app.services.pricing.quote_service import (
    QuoteService,
    RequoteRequest,
    SellInputs,
    build_carrier_cost,
)
from app.services.pricing.sell_price import SellTerms
from app.services.pricing.types import (
    CarrierLeg,
    CarrierLegKind,
    CarrierQuote,
    CostLine,
    ParcelSpec,
    PriceSource,
)
from app.services.repricing import (
    EditField,
    EditNotAllowedError,
    RepriceChange,
    RepricingService,
    ServiceTypeLockedError,
    assert_edit_allowed,
    edit_fields_from_update,
)
from app.services.shipment import POST_PICKUP_CANCEL_RTO_DETAIL, ShipmentService
from app.services.wallet import WalletService


def _tenant() -> Tenant:
    return Tenant(
        id=uuid.uuid4(),
        name="LogiSmart Test",
        slug="logismart-test",
        settings={
            "pricing_policy": {
                "delhivery_markup_percent": 0.0,
                "prime_default_markup_percent": 20.0,
                "cod_fee_percent": 2.0,
                "cod_fee_min": 1.0,
                "enabled_options": [
                    "DELHIVERY_SURFACE",
                    "DELHIVERY_EXPRESS",
                    "PRIME_SURFACE",
                ],
            }
        },
    )


def _booked_record(
    *,
    forward_cost: Decimal = Decimal("55.00"),
    rto_cost: Decimal | None = Decimal("25.00"),
    slab_grams: int = 500,
    markup_percent: Decimal = Decimal("0.00"),
    cod_fee_percent: Decimal = Decimal("2.00"),
    cod_fee_min: Decimal = Decimal("1.00"),
) -> dict:
    spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="400001",
        packages=(
            PackageCreate(
                length=10.0,
                breadth=10.0,
                height=10.0,
                dimension_unit=DimensionUnit.CM,
                weight=0.5,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
        shipment_type=ShipmentType.FORWARD,
    )
    fwd = CarrierLeg(
        kind=CarrierLegKind.FORWARD,
        cost=forward_cost,
        lines=(CostLine(code="charge_DL", label="Delivery charge", amount=forward_cost),),
        charged_weight_kg=Decimal(slab_grams) / Decimal(1000),
        transit_days=4,
        source=PriceSource.LIVE,
        fetched_at=datetime(2026, 10, 30, 0, 0, 0),
        details={"zone": "D", "slab_grams": slab_grams},
    )
    rto = (
        CarrierLeg(
            kind=CarrierLegKind.RTO,
            cost=rto_cost,
            lines=(CostLine(code="charge_RTO", label="RTO charge", amount=rto_cost),),
            charged_weight_kg=Decimal(slab_grams) / Decimal(1000),
            transit_days=None,
            source=PriceSource.LIVE,
            fetched_at=datetime(2026, 10, 30, 0, 0, 0),
            details={"zone": "D", "slab_grams": slab_grams},
        )
        if rto_cost is not None
        else None
    )
    quote = CarrierQuote(
        option=ServiceOption.DELHIVERY_SURFACE,
        serviceable=True,
        forward=fwd,
        rto=rto,
    )
    terms = SellTerms(
        markup_percent=markup_percent,
        cod_fee_percent=cod_fee_percent,
        cod_fee_min=cod_fee_min,
        gst_percent=Decimal("18.00"),
    )
    return build_carrier_cost(quote, spec, terms)


@pytest.mark.asyncio
async def test_noop_reprice_delta_is_zero_and_makes_no_carrier_calls() -> None:
    """Re-quoting with identical inputs returns the exact booked price without calling Delhivery."""
    tenant = _tenant()
    record = _booked_record()
    spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="400001",
        packages=(
            PackageCreate(
                length=10.0,
                breadth=10.0,
                height=10.0,
                dimension_unit=DimensionUnit.CM,
                weight=0.5,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
    )
    sell = SellInputs(
        mode=FreightPaymentMode.PREPAID,
        is_cod=False,
        cod_goods=Decimal("0.00"),
        add_shipping_to_cod=False,
        include_rto=False,
        charge_cod_fee=False,
    )
    fake_delhivery.FAKE_DELHIVERY_DOWN = True
    try:
        res = await QuoteService(AsyncMock()).requote(
            tenant,
            record,
            RequoteRequest(option=ServiceOption.DELHIVERY_SURFACE, spec=spec, sell=sell),
        )
    finally:
        fake_delhivery.FAKE_DELHIVERY_DOWN = False

    assert res.serviceable is True
    assert Decimal(str(res.base_charge)) == Decimal("55.00")
    assert Decimal(str(res.total_amount)) == Decimal("64.90")


@pytest.mark.asyncio
async def test_cod_edit_uses_frozen_terms_with_zero_delhivery_calls() -> None:
    """Editing COD while Delhivery is down succeeds and uses the booking-time COD fee."""
    tenant = _tenant()
    record = _booked_record(cod_fee_percent=Decimal("2.00"), cod_fee_min=Decimal("1.00"))
    spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="400001",
        packages=(
            PackageCreate(
                length=10.0,
                breadth=10.0,
                height=10.0,
                dimension_unit=DimensionUnit.CM,
                weight=0.5,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
    )
    sell = SellInputs(
        mode=FreightPaymentMode.PREPAID,
        is_cod=True,
        cod_goods=Decimal("1000.00"),
        add_shipping_to_cod=False,
        include_rto=False,
        charge_cod_fee=True,
    )
    fake_delhivery.FAKE_DELHIVERY_DOWN = True
    try:
        res = await QuoteService(AsyncMock()).requote(
            tenant,
            record,
            RequoteRequest(option=ServiceOption.DELHIVERY_SURFACE, spec=spec, sell=sell),
        )
    finally:
        fake_delhivery.FAKE_DELHIVERY_DOWN = False

    assert res.serviceable is True
    # Freight 55.00 + COD fee 20.00 (2% of 1000) = 75.00 pre-GST, * 1.18 = 88.50
    assert res.pricing_breakdown["cod_fee"] == 20.0
    assert Decimal(str(res.total_amount)) == Decimal("88.50")


@pytest.mark.asyncio
async def test_provisional_rto_when_rto_leg_was_not_recorded_at_booking() -> None:
    """When `rto` was skipped at booking, RTO uses 100% of forward cost and marks `provisional=True`."""
    tenant = _tenant()
    record = _booked_record(forward_cost=Decimal("55.00"), rto_cost=None)
    spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="400001",
        packages=(
            PackageCreate(
                length=10.0,
                breadth=10.0,
                height=10.0,
                dimension_unit=DimensionUnit.CM,
                weight=0.5,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
    )
    sell = SellInputs(
        mode=FreightPaymentMode.PREPAID,
        is_cod=False,
        cod_goods=Decimal("0.00"),
        add_shipping_to_cod=False,
        include_rto=True,
        charge_cod_fee=False,
    )
    fake_delhivery.FAKE_DELHIVERY_DOWN = True
    try:
        res = await QuoteService(AsyncMock()).requote(
            tenant,
            record,
            RequoteRequest(option=ServiceOption.DELHIVERY_SURFACE, spec=spec, sell=sell),
        )
    finally:
        fake_delhivery.FAKE_DELHIVERY_DOWN = False

    assert res.serviceable is True
    assert res.pricing_breakdown["rto_surcharge"] == 55.0
    assert res.carrier_cost is not None
    assert res.carrier_cost["rto"]["source"] == PriceSource.PROVISIONAL.value
    assert res.carrier_cost["rto"]["details"]["provisional"] is True


@pytest.mark.asyncio
async def test_drift_neutral_reweigh_and_refusal_when_delhivery_down() -> None:
    """
    Re-weighing from 0.5 kg to 1.0 kg computes `new = booked + (API(new) - API(booked))`,
    and refuses with `serviceable=False` when Delhivery is down (H-7).
    """
    tenant = _tenant()
    record = _booked_record(forward_cost=Decimal("55.00"), slab_grams=500)
    heavier_spec = ParcelSpec(
        pickup_pincode="122001",
        delivery_pincode="400001",
        packages=(
            PackageCreate(
                length=10.0,
                breadth=10.0,
                height=10.0,
                dimension_unit=DimensionUnit.CM,
                weight=1.0,
                weight_unit=WeightUnit.KG,
                box_count=1,
            ),
        ),
    )
    sell = SellInputs(
        mode=FreightPaymentMode.PREPAID,
        is_cod=False,
        cod_goods=Decimal("0.00"),
        add_shipping_to_cod=False,
        include_rto=False,
        charge_cod_fee=False,
    )
    session = AsyncMock()
    session.exec = AsyncMock(return_value=SimpleNamespace(first=lambda: None))
    res = await QuoteService(session).requote(
        tenant,
        record,
        RequoteRequest(option=ServiceOption.DELHIVERY_SURFACE, spec=heavier_spec, sell=sell),
    )
    assert res.serviceable is True
    # 1.0 kg on FakeDelhiveryApi = 80.00; 0.5 kg on FakeDelhiveryApi = 52.50;
    # drift-neutral: booked (55.00) + (80.00 - 52.50) = 82.50
    assert Decimal(str(res.base_charge)) == Decimal("82.50")

    fake_delhivery.FAKE_DELHIVERY_DOWN = True
    try:
        down_res = await QuoteService(session).requote(
            tenant,
            record,
            RequoteRequest(option=ServiceOption.DELHIVERY_SURFACE, spec=heavier_spec, sell=sell),
        )
    finally:
        fake_delhivery.FAKE_DELHIVERY_DOWN = False
    assert down_res.serviceable is False


@pytest.mark.asyncio
async def test_service_option_edit_rules_and_to_pay_edit_blocked() -> None:
    """
    - `service_option` counts as `EditField.SERVICE_TYPE` (locked after pickup, H-8).
    - Switching between B2C (`DELHIVERY_SURFACE`) and B2B (`PRIME_SURFACE`) raises 400 (Q4).
    - Switching `freight_payment_mode` to `TO_PAY` raises 400 (`TO_PAY_DISABLED_DETAIL`).
    """
    shipment = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        requested_pickup_date=date(2026, 10, 30),
        product_category=ProductCategory.ELECTRONICS,
        status=PickupStatus.IN_TRANSIT,
        service_type=ServiceType.SURFACE_ROAD,
        service_option=ServiceOption.DELHIVERY_SURFACE,
    )
    shipment.payment_details = PaymentDetails(
        pickup_id=shipment.id,
        freight_payment_mode=FreightPaymentMode.PREPAID,
    )
    patch_after_pickup = PickupUpdate(service_option=ServiceOption.DELHIVERY_EXPRESS)
    fields = edit_fields_from_update(patch_after_pickup, shipment)
    assert EditField.SERVICE_TYPE in fields
    with pytest.raises(ServiceTypeLockedError):
        assert_edit_allowed(shipment, fields, None)

    shipment.status = PickupStatus.OPEN
    svc = RepricingService(AsyncMock())
    with pytest.raises(EditNotAllowedError) as exc_flow:
        await svc.change_from_update(
            shipment,
            PickupUpdate(service_option=ServiceOption.PRIME_SURFACE),
            shipment.tenant_id,
            None,
        )
    assert exc_flow.value.field == "service_option"

    with pytest.raises(EditNotAllowedError) as exc_topay:
        await svc.change_from_update(
            shipment,
            PickupUpdate(
                payment_details=PaymentDetailsCreate(
                    freight_payment_mode=FreightPaymentMode.TO_PAY
                )
            ),
            shipment.tenant_id,
            None,
        )
    assert exc_topay.value.detail == mvp_scope.TO_PAY_DISABLED_DETAIL


@pytest.mark.asyncio
async def test_carrier_billing_permissions_duplicate_awb_and_gap_verdict(monkeypatch) -> None:
    """
    Verifies `get_carrier_billing` and `update_carrier_billing`:
    - Customers get 403 on GET and PUT; `read_only_user` and `support_user` get 403 on PUT.
    - Duplicate `carrier_awb` in the same tenant raises 409.
    - A carrier charge above the seller price (pre-GST) sets `has_gap=True` with the shortfall,
      the message and the margin view (80.00 incl. GST = 67.80 taxable vs 55.00 billed).
    """
    tenant = _tenant()
    shipment_id = uuid.uuid4()
    shipment = PickupRequest(
        id=shipment_id,
        tenant_id=tenant.id,
        created_by_user_id=uuid.uuid4(),
        tracking_id="LOGI-TEST-001",
        requested_pickup_date=date(2026, 10, 30),
        product_category=ProductCategory.ELECTRONICS,
        status=PickupStatus.OPEN,
        service_type=ServiceType.SURFACE_ROAD,
        service_option=ServiceOption.DELHIVERY_SURFACE,
    )
    shipment.payment_details = PaymentDetails(
        pickup_id=shipment_id,
        total_logistics_cost=64.90,
        tax_amount=9.90,
        carrier_cost=_booked_record(),
    )

    customer = User(id=uuid.uuid4(), tenant_id=tenant.id, email="c@t.in", role=UserRole.customer)
    readonly = User(id=uuid.uuid4(), tenant_id=tenant.id, email="r@t.in", role=UserRole.read_only_user)
    support = User(id=uuid.uuid4(), tenant_id=tenant.id, email="s@t.in", role=UserRole.support_user)
    ops = User(id=uuid.uuid4(), tenant_id=tenant.id, email="o@t.in", role=UserRole.operations_user)

    session = AsyncMock()
    with pytest.raises(HTTPException) as exc_cust:
        await get_carrier_billing(session, shipment_id, tenant.id, customer)
    assert exc_cust.value.status_code == 403

    for blocked_user in (customer, readonly, support):
        with pytest.raises(HTTPException) as exc_put:
            await update_carrier_billing(
                session,
                shipment_id,
                tenant,
                CarrierBillingUpdate(carrier_awb="DLV123456"),
                blocked_user,
            )
        assert exc_put.value.status_code == 403

    conflict_row = SimpleNamespace(id=uuid.uuid4(), tracking_id="LOGI-OTHER-999")
    monkeypatch.setattr(
        RepricingService,
        "load_shipment",
        AsyncMock(return_value=shipment),
    )
    monkeypatch.setattr(
        "app.repositories.repricing.RepricingRepository.find_shipment_by_carrier_awb",
        AsyncMock(return_value=conflict_row),
    )
    with pytest.raises(HTTPException) as exc_dup:
        await update_carrier_billing(
            session,
            shipment_id,
            tenant,
            CarrierBillingUpdate(carrier_awb="DLV123456"),
            ops,
        )
    assert exc_dup.value.status_code == 409
    assert "LOGI-OTHER-999" in exc_dup.value.detail

    monkeypatch.setattr(
        "app.repositories.repricing.RepricingRepository.find_shipment_by_carrier_awb",
        AsyncMock(return_value=None),
    )
    record_meas_mock = AsyncMock(
        return_value=SimpleNamespace(
            changed=True,
            replayed=False,
            delta=Decimal("23.60"),
            old_total=Decimal("64.90"),
            new_total=Decimal("88.50"),
            old_chargeable_weight=Decimal("0.500"),
            new_chargeable_weight=Decimal("1.000"),
        )
    )
    record_dispute_mock = AsyncMock()
    monkeypatch.setattr(RepricingService, "get_active_measurement", AsyncMock(return_value=None))
    monkeypatch.setattr(RepricingService, "record_measurement", record_meas_mock)
    monkeypatch.setattr(
        "app.services.pricing.carrier_billing.DelhiveryModulesService.record_weight_audit_dispute",
        record_dispute_mock,
    )

    saved = await update_carrier_billing(
        session,
        shipment_id,
        tenant,
        CarrierBillingUpdate(
            carrier_awb="DLV123456",
            charged_weight_kg=1.0,
            charged_amount=80.00,
        ),
        ops,
    )
    assert record_meas_mock.await_count == 1
    assert record_dispute_mock.await_count == 1
    meas_arg = record_meas_mock.await_args.args[2]
    assert meas_arg.source == MeasurementSource.CARRIER
    assert meas_arg.weight_only_kg == Decimal("1.000")
    assert saved.carrier_awb == "DLV123456"
    assert saved.has_gap is True
    assert saved.gap_amount == pytest.approx(12.80)
    assert saved.gap_gross_amount == pytest.approx(15.10)
    assert saved.seller_billed_amount == pytest.approx(64.90)
    assert saved.seller_billed_taxable == pytest.approx(55.00)
    assert saved.carrier_charged_taxable == pytest.approx(67.80)
    assert saved.margin_amount == pytest.approx(-12.80)
    assert saved.gap_message is not None


def _billed_shipment(total: float, tax: float, charged: Optional[float]) -> PickupRequest:
    """Shipment whose ops-entered carrier charge (incl. GST) is `charged`."""
    shipment_id = uuid.uuid4()
    shipment = PickupRequest(
        id=shipment_id,
        tenant_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        tracking_id="LOGI-TEST-002",
        requested_pickup_date=date(2026, 10, 30),
        product_category=ProductCategory.ELECTRONICS,
        status=PickupStatus.IN_TRANSIT,
        service_type=ServiceType.SURFACE_ROAD,
        service_option=ServiceOption.PRIME_SURFACE,
        carrier_awb="DLV999",
    )
    carrier_cost = _booked_record()
    if charged is not None:
        carrier_cost["carrier_billed"] = {"awb": "DLV999", "charged_weight_kg": None, "charged_amount": charged}
    shipment.payment_details = PaymentDetails(
        pickup_id=shipment_id, total_logistics_cost=total, tax_amount=tax, carrier_cost=carrier_cost
    )
    return shipment


def test_carrier_margin_positive_is_not_a_gap() -> None:
    """A Prime-style margin (seller 120 + GST vs carrier 100 + GST) is shown, never flagged."""
    read = _build_carrier_billing_read(_billed_shipment(141.60, 21.60, 118.00))
    assert read.has_gap is False
    assert read.gap_amount == 0.0
    assert read.gap_message is None
    assert read.seller_billed_taxable == pytest.approx(120.00)
    assert read.carrier_charged_taxable == pytest.approx(100.00)
    assert read.margin_amount == pytest.approx(20.00)


def test_carrier_margin_zero_markup_matches_exactly() -> None:
    """Delhivery at 0 % markup: same pre-GST amount on both sides -> margin 0, no gap."""
    read = _build_carrier_billing_read(_billed_shipment(118.00, 18.00, 118.00))
    assert read.has_gap is False
    assert read.margin_amount == pytest.approx(0.0)


def test_carrier_margin_absent_before_charge_is_entered() -> None:
    """Before ops enter a carrier charge only the seller price is known."""
    read = _build_carrier_billing_read(_billed_shipment(118.00, 18.00, None))
    assert read.has_gap is False
    assert read.gap_amount is None
    assert read.seller_billed_amount == pytest.approx(118.00)
    assert read.margin_amount is None
    assert read.carrier_charged_taxable is None


def test_carrier_margin_after_override_and_recovery_surcharge_does_not_double_subtract_gst() -> None:
    """
    BUG-15: when `ADMIN_PRICE_OVERRIDE` is present in `bill_adjustments`, `RepricingService`
    already updates `payment.tax_amount` across the entire `total_logistics_cost` (including
    a subsequent `Recover Difference from Customer` surcharge). `_seller_taxable_amount` must
    return `seller_billed - tax_amount` directly (`354.00 - 54.00 = 300.00`) instead of
    subtracting `54.00` from `177.00` and adding `150.00` (`273.00`, false `-27.00` margin).
    """
    shipment = _billed_shipment(354.00, 54.00, 354.00)
    shipment.payment_details.pricing_breakdown = {
        "bill_adjustments": [
            {
                "kind": "ADMIN_PRICE_OVERRIDE",
                "label": "Admin price override",
                "amount": 18.70,
                "txn_type": "SPEND",
            },
            {
                "label": "Carrier bill shortfall recovery",
                "amount": 177.00,
                "txn_type": "ADMIN_SURCHARGE",
            },
        ]
    }
    read = _build_carrier_billing_read(shipment)
    assert read.has_gap is False
    assert read.gap_amount == pytest.approx(0.0)
    assert read.seller_billed_amount == pytest.approx(354.00)
    assert read.seller_billed_taxable == pytest.approx(300.00)
    assert read.carrier_charged_taxable == pytest.approx(300.00)
    assert read.margin_amount == pytest.approx(0.0)


def test_transporter_name_visible_to_staff_only() -> None:
    """#540 (3): Prime `transporter_name` is returned to staff and hidden from customers."""
    shipment_staff = _billed_shipment(141.60, 21.60, 118.00)
    shipment_staff.payment_details.carrier_cost["snapshot"] = {"transporter_name": "VRL Logistics"}
    assert shipment_transporter_name(shipment_staff) == "VRL Logistics"
    ops_user = User(id=uuid.uuid4(), tenant_id=shipment_staff.tenant_id, email="ops@t.in", role=UserRole.operations_user)
    ShipmentService._attach_staff_transporter(shipment_staff, ops_user)
    assert getattr(shipment_staff, "transporter_name", None) == "VRL Logistics"

    shipment_cust = _billed_shipment(141.60, 21.60, 118.00)
    shipment_cust.payment_details.carrier_cost["snapshot"] = {"transporter_name": "VRL Logistics"}
    customer_user = User(id=uuid.uuid4(), tenant_id=shipment_cust.tenant_id, email="cust@t.in", role=UserRole.customer)
    ShipmentService._attach_staff_transporter(shipment_cust, customer_user)
    assert getattr(shipment_cust, "transporter_name", None) is None


@pytest.mark.asyncio
async def test_post_pickup_cancel_rto_blocked_for_operations_user() -> None:
    """#540 (2): `operations_user` cannot force RTO-with-charge via Cancel Order after pickup."""
    tenant_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    shipment = PickupRequest(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        created_by_user_id=customer_id,
        status=PickupStatus.IN_TRANSIT,
        requested_pickup_date=date(2026, 10, 30),
        product_category=ProductCategory.ELECTRONICS,
    )
    ops_user = User(id=uuid.uuid4(), tenant_id=tenant_id, email="ops@t.in", role=UserRole.operations_user)
    admin_user = User(id=uuid.uuid4(), tenant_id=tenant_id, email="adm@t.in", role=UserRole.admin)
    customer_user = User(id=customer_id, tenant_id=tenant_id, email="cust@t.in", role=UserRole.customer)

    with pytest.raises(HTTPException) as exc:
        ShipmentService._assert_status_change_role(
            ops_user, PickupStatus.RTO_INITIATED, PickupStatus.IN_TRANSIT, cancel_converted=True
        )
    assert exc.value.status_code == 403
    assert exc.value.detail == POST_PICKUP_CANCEL_RTO_DETAIL

    svc = ShipmentService(AsyncMock())
    with pytest.raises(HTTPException) as exc2:
        await svc._cancel_after_pickup_as_rto(shipment, ops_user, tenant_id)
    assert exc2.value.status_code == 403
    assert exc2.value.detail == POST_PICKUP_CANCEL_RTO_DETAIL

    ShipmentService._assert_status_change_role(
        admin_user, PickupStatus.RTO_INITIATED, PickupStatus.IN_TRANSIT, cancel_converted=True
    )
    ShipmentService._assert_status_change_role(
        customer_user, PickupStatus.RTO_INITIATED, PickupStatus.IN_TRANSIT, cancel_converted=True
    )


def _override_world(
    base_freight: float, tax_amount: float, total: float, breakdown: dict
) -> tuple[Tenant, PickupRequest, RepricingService]:
    """An IN_TRANSIT wallet-billed B2C parcel, fully paid, ready for an admin price override."""
    tenant = _tenant()
    shipment_id = uuid.uuid4()
    shipment = PickupRequest(
        id=shipment_id,
        tenant_id=tenant.id,
        created_by_user_id=uuid.uuid4(),
        tracking_id="LOGI-OVERRIDE-01",
        requested_pickup_date=date(2026, 10, 30),
        product_category=ProductCategory.ELECTRONICS,
        status=PickupStatus.IN_TRANSIT,
        service_type=ServiceType.SURFACE_ROAD,
        service_option=ServiceOption.DELHIVERY_SURFACE,
    )
    shipment.pickup_address = Address(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Origin",
        phone="9800000001",
        address_line1="Plot 1",
        city="Gurugram",
        state="Haryana",
        pincode="122001",
        country="IN",
    )
    shipment.delivery_address = Address(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Dest",
        phone="9800000002",
        address_line1="Plot 2",
        city="Mumbai",
        state="Maharashtra",
        pincode="400001",
        country="IN",
    )
    shipment.packages = [
        PackageDetails(
            pickup_id=shipment_id,
            length=10.0,
            breadth=10.0,
            height=10.0,
            dimension_unit=DimensionUnit.CM,
            weight=0.5,
            weight_unit=WeightUnit.KG,
            box_count=1,
        )
    ]
    shipment.payment_details = PaymentDetails(
        pickup_id=shipment_id,
        freight_payment_mode=FreightPaymentMode.PREPAID,
        base_freight=base_freight,
        tax_amount=tax_amount,
        total_logistics_cost=total,
        pricing_breakdown=breakdown,
        carrier_cost=_booked_record(forward_cost=Decimal(str(base_freight))),
    )
    svc = RepricingService(AsyncMock())
    svc.repo.get_active_measurement = AsyncMock(return_value=None)
    svc.repo.list_shipment_wallet_txns = AsyncMock(
        return_value=[
            SimpleNamespace(
                txn_type=WalletTxnType.SPEND,
                status=WalletTxnStatus.COMPLETED,
                amount=Decimal(str(total)),
            )
        ]
    )
    return tenant, shipment, svc


@pytest.mark.asyncio
async def test_bidirectional_admin_price_override_plan_and_proportional_gst_split() -> None:
    """
    #568 (1-3): `override_total_price` on `RepriceChange` supports both:
    - Overpriced (`override_total_price < old_total`): credits wallet (`REFUND`) + `CREDIT_NOTE`.
    - Underpriced (`override_total_price > old_total`): debits wallet (`SPEND`) + `DEBIT_NOTE`.
    - Updates `base_freight`, `tax_amount`, and `total_logistics_cost` with proportional 18% GST.
    """
    tenant, shipment, svc = _override_world(100.00, 18.00, 118.00, {"billing_channel": "WALLET"})

    # 1. Overpriced: ₹118.00 -> ₹59.00 (refund ₹59.00 + CREDIT_NOTE)
    overpriced_change = RepriceChange(
        reason=ChargeAdjustmentReason.ADMIN_EDIT,
        override_total_price=Decimal("59.00"),
        remark="Overpriced lane correction",
    )
    plan_down = await svc._plan(shipment, tenant, overpriced_change, None)
    assert plan_down.preview.old_total == Decimal("118.00")
    assert plan_down.preview.new_total == Decimal("59.00")
    assert plan_down.preview.delta == Decimal("-59.00")
    assert plan_down.preview.reason == ChargeAdjustmentReason.ADMIN_EDIT
    assert plan_down.movements[0].txn_type == WalletTxnType.REFUND
    assert plan_down.movements[0].amount == Decimal("-59.00")
    assert plan_down.preview.note_type == InvoiceNoteType.CREDIT_NOTE
    assert plan_down.payment_writes["total_logistics_cost"] == pytest.approx(59.00)
    assert plan_down.payment_writes["base_freight"] == pytest.approx(50.00)
    assert plan_down.payment_writes["tax_amount"] == pytest.approx(9.00)

    # 2. Underpriced: ₹118.00 -> ₹177.00 (debit ₹59.00 + DEBIT_NOTE)
    underpriced_change = RepriceChange(
        reason=ChargeAdjustmentReason.ADMIN_EDIT,
        override_total_price=Decimal("177.00"),
        remark="Carrier bill shortfall recovery",
    )
    plan_up = await svc._plan(shipment, tenant, underpriced_change, None)
    assert plan_up.preview.old_total == Decimal("118.00")
    assert plan_up.preview.new_total == Decimal("177.00")
    assert plan_up.preview.delta == Decimal("59.00")
    assert plan_up.preview.reason == ChargeAdjustmentReason.ADMIN_EDIT
    assert plan_up.movements[0].txn_type == WalletTxnType.SPEND
    assert plan_up.movements[0].amount == Decimal("59.00")
    assert plan_up.preview.note_type == InvoiceNoteType.DEBIT_NOTE
    assert plan_up.payment_writes["total_logistics_cost"] == pytest.approx(177.00)
    assert plan_up.payment_writes["base_freight"] == pytest.approx(150.00)
    assert plan_up.payment_writes["tax_amount"] == pytest.approx(27.00)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("override", "subtotal", "gst", "cgst", "sgst"),
    [
        (Decimal("100.00"), 84.75, 15.25, 7.63, 7.62),  # J64 down: refund 59.30 + CREDIT_NOTE
        (Decimal("200.00"), 169.49, 30.51, 15.26, 15.25),  # up: debit 40.70 + DEBIT_NOTE
        (Decimal("106.88"), 90.58, 16.30, 8.15, 8.15),  # BUG-01b prod S3 total
    ],
)
async def test_override_rewrites_breakdown_taxable_so_notes_split_at_18_percent(
    override: Decimal, subtotal: float, gst: float, cgst: float, sgst: float
) -> None:
    """
    BUG-01: an override used to keep the quote's `subtotal` (135.00) next to the overridden
    `tax_amount`, so the order page showed 135.00 + 15.25 = 100.00 and every credit / debit
    note was split at 15.25 / 135 = 11.3 %. The breakdown now carries the overridden taxable.
    """
    quote_breakdown = {
        "billing_channel": "WALLET",
        "subtotal": 135.0,
        "gst_total": 24.3,
        "cgst_amount": 12.15,
        "sgst_amount": 12.15,
        "igst_amount": 24.3,
    }
    tenant, shipment, svc = _override_world(135.00, 24.30, 159.30, quote_breakdown)
    change = RepriceChange(reason=ChargeAdjustmentReason.ADMIN_EDIT, override_total_price=override)

    plan = await svc._plan(shipment, tenant, change, None)

    breakdown = plan.preview.new_breakdown
    assert (breakdown["subtotal"], breakdown["gst_total"]) == (subtotal, gst)
    assert (breakdown["cgst_amount"], breakdown["sgst_amount"], breakdown["igst_amount"]) == (cgst, sgst, gst)
    assert (plan.payment_writes["base_freight"], plan.payment_writes["tax_amount"]) == (subtotal, gst)
    assert Decimal(str(subtotal)) + Decimal(str(gst)) == override
    billed = SimpleNamespace(tax_amount=gst, total_logistics_cost=float(override), pricing_breakdown=breakdown)
    assert shipment_effective_gst_rate(billed) == 0.18


@pytest.mark.asyncio
async def test_plan_without_override_keeps_the_quote_breakdown_taxable() -> None:
    """Only an override rewrites the taxable figures; a plain re-plan keeps the quote's subtotal."""
    quote_breakdown = {"billing_channel": "WALLET", "subtotal": 135.0, "gst_total": 24.3}
    tenant, shipment, svc = _override_world(135.00, 24.30, 159.30, quote_breakdown)
    change = RepriceChange(reason=ChargeAdjustmentReason.ADMIN_EDIT, override_total_price=Decimal("159.30"))

    plan = await svc._plan(shipment, tenant, change, None)

    assert plan.preview.new_breakdown["subtotal"] == 135.0
    assert plan.preview.new_breakdown["gst_total"] == 24.3


@pytest.mark.asyncio
async def test_apply_admin_shipment_charge_permissions_and_override(monkeypatch) -> None:
    """
    #558 (3c) & #568 (1-3): `apply_admin_shipment_charge` is restricted to Owner/Admin
    and delegates `override_total_price` to `RepricingService.apply`.
    """
    tenant = _tenant()
    shipment = _billed_shipment(118.00, 18.00, 177.00)
    shipment.tenant_id = tenant.id
    ops = User(id=uuid.uuid4(), tenant_id=tenant.id, email="o@t.in", role=UserRole.operations_user)
    admin = User(id=uuid.uuid4(), tenant_id=tenant.id, email="a@t.in", role=UserRole.admin)

    session = AsyncMock()
    with pytest.raises(HTTPException) as exc_ops:
        await apply_admin_shipment_charge(
            session,
            shipment.id,
            tenant,
            AdminShipmentChargeCreate(override_total_price=88.50, label="Discount"),
            ops,
        )
    assert exc_ops.value.status_code == 403

    apply_mock = AsyncMock(
        return_value=SimpleNamespace(
            old_total=Decimal("118.00"),
            new_total=Decimal("88.50"),
            delta=Decimal("-29.50"),
            note_number="CN-2627-0001",
        )
    )
    monkeypatch.setattr(RepricingService, "load_shipment", AsyncMock(return_value=shipment))
    monkeypatch.setattr(RepricingService, "apply", apply_mock)

    res = await apply_admin_shipment_charge(
        session,
        shipment.id,
        tenant,
        AdminShipmentChargeCreate(override_total_price=88.50, label="Special lane discount"),
        admin,
    )
    assert apply_mock.await_count == 1
    change_arg = apply_mock.await_args.args[2]
    assert change_arg.override_total_price == Decimal("88.50")
    assert res.seller_billed_amount == pytest.approx(118.00)


@pytest.mark.asyncio
async def test_admin_offline_wallet_credit_permissions_and_credit_flow() -> None:
    """
    #558 (3b) & #568 (4): `WalletService.record_admin_offline_credit` allows Owner/Admin to
    credit a customer's wallet from an offline NEFT/RTGS/Cash payment, rejects non-admins (403),
    and rejects duplicate UTR references (409).
    """
    tenant = _tenant()
    ops = User(id=uuid.uuid4(), tenant_id=tenant.id, email="ops@t.in", role=UserRole.operations_user)
    admin = User(id=uuid.uuid4(), tenant_id=tenant.id, email="adm@t.in", role=UserRole.admin)
    customer = User(id=uuid.uuid4(), tenant_id=tenant.id, email="b2c@t.in", role=UserRole.customer)

    repo = AsyncMock()
    svc = WalletService(repo)

    with pytest.raises(HTTPException) as exc_role:
        await svc.record_admin_offline_credit(
            admin_user=ops,
            tenant=tenant,
            payload=AdminOfflineCreditRequest(
                user_email="b2c@t.in",
                amount=1000.0,
                payment_method="NEFT",
                utr_number="NEFT20261101001",
            ),
        )
    assert exc_role.value.status_code == 403

    repo.get_tenant_user = AsyncMock(return_value=customer)
    repo.get_transaction_by_utr = AsyncMock(
        return_value=SimpleNamespace(receipt_number="REC-2026-0001")
    )
    with pytest.raises(HTTPException) as exc_dup:
        await svc.record_admin_offline_credit(
            admin_user=admin,
            tenant=tenant,
            payload=AdminOfflineCreditRequest(
                user_email="b2c@t.in",
                amount=1000.0,
                payment_method="NEFT",
                utr_number="NEFT20261101001",
            ),
        )
    assert exc_dup.value.status_code == 409

    repo.get_transaction_by_utr = AsyncMock(return_value=None)
    wallet_row = SimpleNamespace(id=uuid.uuid4(), balance=Decimal("500.00"))
    repo.get_or_create_wallet = AsyncMock(return_value=wallet_row)
    repo.create_transaction = AsyncMock(
        side_effect=lambda txn: SimpleNamespace(
            id=txn.id or uuid.uuid4(),
            tenant_id=txn.tenant_id,
            wallet_id=txn.wallet_id,
            user_id=txn.user_id,
            shipment_id=None,
            receipt_number=txn.receipt_number,
            utr_number=txn.utr_number,
            txn_type=WalletTxnType.RECHARGE,
            direction=WalletTxnDirection.CREDIT,
            service_category=WalletServiceCategory.WALLET,
            status=WalletTxnStatus.COMPLETED,
            amount=txn.amount,
            opening_balance=txn.opening_balance,
            closing_balance=txn.closing_balance,
            remarks=txn.remarks,
            created_at=datetime.utcnow(),
        )
    )

    res = await svc.record_admin_offline_credit(
        admin_user=admin,
        tenant=tenant,
        payload=AdminOfflineCreditRequest(
            user_email="b2c@t.in",
            amount=2500.0,
            payment_method="NEFT",
            utr_number="NEFT20261101002",
            remarks="HDFC NEFT verified",
        ),
    )
    assert res.balance == pytest.approx(3000.00)
    assert res.transaction.receipt_number.startswith("REC-")
    assert res.transaction.status == WalletTxnStatus.COMPLETED
    assert res.transaction.user_email == "b2c@t.in"
