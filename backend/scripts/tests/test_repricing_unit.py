"""
Unit tests for the re-pricing core (services/repricing.py, models/repricing.py,
core/idempotency.py helpers, pricing labels). Pure: no DB, no FastAPI app.

The service runs against in-memory fakes (session, repository, wallet repository,
GST notes service) and the B7 collectible contract published by reprice-integration
(#104/#108), so the expected ₹ figures are the live-rate-card numbers from
repricing.md (base ₹50/kg, fuel 10 %, network ₹25, COD 2 %, GST 18 %).
"""

import contextlib
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

from app.core import idempotency as idem
from app.models.pickups import (
    DimensionUnit,
    FreightPaymentMode,
    PaymentDetails,
    PickupStatus,
    ProductCategory,
    ServiceOption,
    ServiceType,
    ShipmentType,
    WeightUnit,
)
from app.models.prime import PrimeDeliveryType, PrimeLaneMode
from app.models.repricing import (
    BILLING_CHANNEL_KEY,
    BillingChannel,
    ChargeAdjustmentReason,
    IdempotencyKey,
    MeasurementSource,
    ShipmentMeasurement,
    billing_channel_for_booking,
    billing_channel_of,
    is_wallet_billed,
    net_debited,
    stamp_billing_channel,
)
from app.models.tenants import UserRole
from app.models.wallet import WalletTransaction, WalletTxnStatus, WalletTxnType
from app.schemas.v1.pickups import PackageCreate, PickupUpdate
from app.schemas.v1.pricing import PricingPolicy
from app.services import cod_payout
from app.services import delhivery_modules as delhivery_modules_service
from app.services import repricing as rp
from app.services.pricing import delhivery as delhivery_module
from app.services.pricing.delhivery import (
    OPTION_MODE,
    SS_FORWARD,
    SS_REVERSE,
    SS_RTO,
    _Fetched,
    leg_from_response,
    price_params,
)
from app.services.pricing.fake_delhivery import _formula_gross, _slab_grams
from app.services.pricing.policy import policy_of
from app.services.pricing.prime import PrimeLaneTerms, price_on_terms
from app.services.pricing.quote_service import PriceResult, SellInputs, price_option
from app.services.pricing.sell_price import terms_for
from app.services.pricing.types import (
    CarrierLegKind,
    CarrierQuote,
    ParcelSpec,
    PriceSource,
)

LIVE_PRICING_POLICY = PricingPolicy(cod_fee_percent=2.0, cod_fee_min=1.0).model_dump(mode="json")
TENANT = SimpleNamespace(
    id=uuid.uuid4(),
    slug="logismart-test",
    settings={"pricing_policy": LIVE_PRICING_POLICY},
)
CUSTOMER = SimpleNamespace(id=uuid.uuid4(), role=UserRole.customer)
ADMIN = SimpleNamespace(id=uuid.uuid4(), role=UserRole.admin)

PRIME_FIXTURE_TERMS = PrimeLaneTerms(
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


class FakePriceCacheRepo:
    """In-memory DelhiveryPriceCacheRepository for pure unit tests."""

    rows: dict = {}

    def __init__(self, session: Any) -> None:
        self.session = session

    async def get(self, tenant_id: Any, cache_key: str) -> Any:
        return FakePriceCacheRepo.rows.get((tenant_id, cache_key))

    async def upsert(
        self,
        *,
        tenant_id: Any,
        cache_key: str,
        request_params: dict,
        response: dict,
        fetched_at: Any,
    ) -> Any:
        row = SimpleNamespace(
            tenant_id=tenant_id,
            cache_key=cache_key,
            request_params=request_params,
            response=response,
            fetched_at=fetched_at,
        )
        FakePriceCacheRepo.rows[(tenant_id, cache_key)] = row
        return row


# --------------------------------------------------------------------- fakes


class FakeSession:
    """Just enough AsyncSession for the service: add/flush/get + no_autoflush."""

    def __init__(self) -> None:
        self.added: List[Any] = []
        self.objects: dict = {}

    @property
    def no_autoflush(self):
        return contextlib.nullcontext()

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        return None

    async def get(self, model: Any, key: Any) -> Any:
        return self.objects.get(key)


class FakeRepo:
    """In-memory RepricingRepository."""

    def __init__(self, txns: Optional[List[WalletTransaction]] = None, active=None) -> None:
        self.txns = list(txns or [])
        self.active = active
        self.measurements: List[ShipmentMeasurement] = []
        self.adjustments: List[Any] = []
        self.deactivated = 0
        self.by_key: dict = {}
        self.pincodes: dict = {}

    async def get_active_measurement(self, pickup_id, tenant_id):
        return self.active

    async def list_shipment_wallet_txns(self, pickup_id, tenant_id):
        return list(self.txns)

    async def deactivate_measurements(self, pickup_id, tenant_id):
        self.deactivated += 1

    async def add_measurement(self, measurement):
        self.measurements.append(measurement)
        self.active = measurement
        return measurement

    async def add_adjustment(self, adjustment):
        self.adjustments.append(adjustment)
        return adjustment

    async def get_adjustment_by_idempotency_key(self, tenant_id, key):
        return self.by_key.get(key)

    async def has_wallet_txn_type(self, pickup_id, tenant_id, txn_type):
        return any(rp.wallet_txn_type(t) == txn_type for t in self.txns)

    async def has_shipment_invoice(self, pickup_id, tenant_id):
        """Fake shipments are booked PREPAID (or are TO_PAY with no money moved yet)."""
        return any(rp.wallet_txn_type(t) == WalletTxnType.SPEND for t in self.txns)

    async def add_wallet_txn(self, txn):
        self.txns.append(txn)
        return txn

    async def get_address_pincode(self, address_id, tenant_id):
        return self.pincodes.get(address_id)


class FakeWalletRepo:
    wallet = SimpleNamespace(id=uuid.uuid4(), balance=0.0, updated_at=None)

    def __init__(self, session: Any) -> None:
        pass

    async def get_or_create_wallet(self, user_id, tenant_id, for_update=False):
        return FakeWalletRepo.wallet


class FakeNotes:
    issued: List[dict] = []

    def __init__(self, repo: Any) -> None:
        pass

    async def record_shipment_billing_note(self, *, shipment, note_type, amount_override=None, is_b2b=False):
        note = SimpleNamespace(
            id=uuid.uuid4(), invoice_number=f"LTST2627{note_type[0]}{len(FakeNotes.issued) + 1:06d}",
            note_type=note_type, amount=amount_override,
        )
        FakeNotes.issued.append({"note_type": note_type, "amount": amount_override, "id": note.id})
        return note


def _cod_goods_amount(payment):
    """B7 contract (#104): stored cod_amount minus freight only on non-TO_PAY add-shipping rows."""
    freight = (
        Decimal(str(payment.total_logistics_cost or 0))
        if payment.add_shipping_to_cod and payment.freight_payment_mode != FreightPaymentMode.TO_PAY
        else Decimal(0)
    )
    return Decimal(str(payment.cod_amount or 0)) - freight


def _collectible_amounts(*, is_cod, goods, total, mode, add_shipping_to_cod, merchant_paid):
    """B7 contract (#104/#108)."""
    if mode == FreightPaymentMode.TO_PAY:
        return (goods if is_cod else Decimal(0)), max(Decimal(0), total - merchant_paid)
    cod = (goods + (total if add_shipping_to_cod else Decimal(0))) if is_cod else Decimal(0)
    return cod, Decimal(0)


@pytest.fixture(autouse=True)
def _fakes(monkeypatch):
    monkeypatch.setattr(cod_payout, "cod_goods_amount", _cod_goods_amount, raising=False)
    monkeypatch.setattr(cod_payout, "collectible_amounts", _collectible_amounts, raising=False)
    monkeypatch.setattr(
        cod_payout, "is_collectible_frozen",
        lambda shipment: shipment.status == PickupStatus.COMPLETED, raising=False,
    )
    monkeypatch.setattr(rp, "WalletRepository", FakeWalletRepo)
    monkeypatch.setattr(delhivery_modules_service, "DelhiveryModulesService", FakeNotes)
    monkeypatch.setattr(delhivery_module, "DelhiveryPriceCacheRepository", FakePriceCacheRepo)
    FakePriceCacheRepo.rows = {}
    FakeNotes.issued = []
    FakeWalletRepo.wallet = SimpleNamespace(id=uuid.uuid4(), balance=0.0, updated_at=None)
    yield


# ------------------------------------------------------------------ builders


def box(length, breadth, height, weight, count=1, unit=DimensionUnit.CM):
    return PackageCreate(length=length, breadth=breadth, height=height, weight=weight,
                         box_count=count, dimension_unit=unit)


def package_row(pkg: PackageCreate):
    return SimpleNamespace(**pkg.model_dump())


def quote(
    packages,
    *,
    pickup_pincode="122001",
    delivery_pincode="110001",
    service_type=ServiceType.SURFACE_ROAD,
    is_cod=False,
    cod_amount=0.0,
    shipment_total_value=0.0,
    freight_payment_mode=FreightPaymentMode.PREPAID,
    add_shipping_to_cod=False,
    is_b2b=False,
    shipment_type=ShipmentType.FORWARD,
):
    option = (
        ServiceOption.PRIME_SURFACE
        if is_b2b
        else (
            ServiceOption.DELHIVERY_EXPRESS
            if service_type == ServiceType.AIR
            else ServiceOption.DELHIVERY_SURFACE
        )
    )
    spec = ParcelSpec(
        pickup_pincode=pickup_pincode,
        delivery_pincode=delivery_pincode,
        packages=tuple(packages),
        shipment_type=shipment_type,
        is_blind_pickup=is_b2b and not packages,
    )
    if is_b2b:
        carrier = price_on_terms(PRIME_FIXTURE_TERMS, spec)
    else:
        md = OPTION_MODE[option]
        ss = SS_REVERSE if shipment_type == ShipmentType.REVERSE else SS_FORWARD
        params = price_params(option, spec, ss)
        slab = _slab_grams(int(params["cgm"]))
        slab_kg = Decimal(slab) / Decimal(1000)
        fwd_gross = float(_formula_gross(md, ss, slab_kg))
        # The stored RTO leg is return-only (Delhivery's `ss=RTO` is cumulative; see return_only_leg).
        rto_gross = float(_formula_gross(md, SS_RTO, slab_kg) - _formula_gross(md, SS_FORWARD, slab_kg))
        now = delhivery_module._utc_now_naive()
        fwd_leg = leg_from_response(
            CarrierLegKind.REVERSE if shipment_type == ShipmentType.REVERSE else CarrierLegKind.FORWARD,
            _Fetched(
                {"gross_amount": fwd_gross, "charged_weight": slab, "zone": "C", "charge_COD": 0.0},
                now,
                PriceSource.LIVE,
            ),
            5 if md == "S" else 2,
        )
        rto_leg = (
            None
            if shipment_type == ShipmentType.REVERSE
            else leg_from_response(
                CarrierLegKind.RTO,
                _Fetched(
                    {"gross_amount": rto_gross, "charged_weight": slab, "zone": "C", "charge_COD": 0.0},
                    now,
                    PriceSource.LIVE,
                ),
                None,
            )
        )
        carrier = CarrierQuote(
            option=option,
            serviceable=True,
            forward=fwd_leg,
            rto=rto_leg,
            cod_supported=True,
            snapshot={"request": params},
        )
    policy = policy_of(TENANT)
    terms = terms_for(carrier, policy)
    sell_inputs = SellInputs(
        mode=freight_payment_mode,
        is_cod=is_cod,
        cod_goods=Decimal(str(cod_amount or 0)),
        add_shipping_to_cod=add_shipping_to_cod,
        include_rto=False,
        charge_cod_fee=is_cod,
    )
    priced = price_option(carrier, terms, spec, sell_inputs)
    return PriceResult.of(priced, spec, terms, None)


def make_shipment(
    packages,
    *,
    mode=FreightPaymentMode.PREPAID,
    is_cod=False,
    goods=0.0,
    total_value=0.0,
    add_shipping=False,
    status=PickupStatus.OPEN,
    service=ServiceType.SURFACE_ROAD,
    channel: Optional[BillingChannel] = None,
    blind=False,
    shipment_type=ShipmentType.FORWARD,
    manifest_id=None,
):
    """A booked shipment priced exactly as booking does (COD fee on goods)."""
    booked = quote(packages, service_type=service, is_cod=is_cod, cod_amount=goods,
                   shipment_total_value=total_value, freight_payment_mode=mode,
                   add_shipping_to_cod=add_shipping, is_b2b=blind,
                   shipment_type=shipment_type)
    total = booked.total_amount
    cod_amount = goods
    freight_collectible = Decimal("0.00")
    if mode == FreightPaymentMode.TO_PAY:
        freight_collectible = Decimal(str(total))
    elif is_cod and add_shipping:
        cod_amount = round(goods + total, 2)
    breakdown = dict(booked.pricing_breakdown)
    if channel is not None:
        breakdown = stamp_billing_channel(breakdown, channel)
    payment = PaymentDetails(
        pickup_id=uuid.uuid4(), freight_payment_mode=mode, is_cod=is_cod, cod_amount=cod_amount,
        add_shipping_to_cod=add_shipping, shipment_total_value=total_value,
        base_freight=booked.base_charge, tax_amount=booked.tax_amount, total_logistics_cost=total,
        pricing_breakdown=breakdown, chargeable_weight=booked.chargeable_weight,
        freight_collectible=freight_collectible, carrier_cost=booked.carrier_cost,
    )
    option = ServiceOption(booked.carrier_cost["option"])
    return SimpleNamespace(
        id=uuid.uuid4(), tenant_id=TENANT.id, created_by_user_id=CUSTOMER.id, tracking_id="LTST-0001",
        status=status, service_type=service, service_option=option, shipment_type=shipment_type,
        is_blind_pickup=blind, estimated_box_count=None, is_carriers_risk=False, po_number=None,
        product_category=ProductCategory.HOUSEHOLD_PERSONAL, appointment_id=None, pickup_strategy=None,
        manifest_id=manifest_id,
        pickup_address=SimpleNamespace(pincode="122001"),
        delivery_address=SimpleNamespace(pincode="110001", name="Priya", phone="9810011102",
                                         address_line1="Tower 9", address_line2=None, landmark=None,
                                         city="New Delhi", state="Delhi", pincode_dummy=None),
        packages=[package_row(p) for p in packages],
        payment_details=payment,
    )


def txn(txn_type: WalletTxnType, amount: float, status=WalletTxnStatus.COMPLETED):
    return WalletTransaction(
        wallet_id=uuid.uuid4(), tenant_id=TENANT.id, user_id=CUSTOMER.id, txn_type=txn_type,
        service_category="B2C", opening_balance=0.0, amount=amount, closing_balance=0.0,
        receipt_number="X", status=status,
    )


def service(repo: FakeRepo) -> rp.RepricingService:
    svc = rp.RepricingService(FakeSession())  # type: ignore[arg-type]
    svc.repo = repo  # type: ignore[assignment]
    return svc


THREE_BOXES = [box(30, 30, 30, 10.0 / 3, 3)]
FOUR_BOXES = [box(30, 30, 30, 3.5, 4)]


# ------------------------------------------------------- money definitions


def test_net_debited_counts_only_bill_rows_that_completed():
    rows = [
        txn(WalletTxnType.SPEND, 182.90),
        txn(WalletTxnType.WEIGHT_AUDIT_DEBIT, 10.0),
        txn(WalletTxnType.RTO_FREIGHT, 59.0),
        txn(WalletTxnType.FREIGHT_COLLECTION, 5.0),
        txn(WalletTxnType.REFUND, 20.0),
        txn(WalletTxnType.ADDITIONAL_CHARGE, 590.0),
        txn(WalletTxnType.RECHARGE, 1000.0),
        txn(WalletTxnType.SPEND, 999.0, status=WalletTxnStatus.PENDING),
    ]
    assert net_debited(rows) == Decimal("236.90")


@pytest.mark.parametrize(
    ("mode", "staff", "expected"),
    [
        (FreightPaymentMode.PREPAID, False, BillingChannel.WALLET),
        (FreightPaymentMode.PREPAID, True, BillingChannel.WALLET),
        (FreightPaymentMode.POSTPAID, False, BillingChannel.WALLET),
        (FreightPaymentMode.POSTPAID, True, BillingChannel.WALLET),
        (FreightPaymentMode.TO_PAY, False, BillingChannel.NONE),
    ],
)
def test_billing_channel_for_booking(mode, staff, expected):
    assert billing_channel_for_booking(mode, booked_by_staff=staff) == expected


def test_billing_channel_flag_wins_and_legacy_falls_back_to_mode():
    payment = PaymentDetails(pickup_id=uuid.uuid4(), freight_payment_mode=FreightPaymentMode.POSTPAID,
                             pricing_breakdown={})
    assert billing_channel_of(payment) == BillingChannel.NONE
    payment.pricing_breakdown = stamp_billing_channel({}, BillingChannel.WALLET)
    assert payment.pricing_breakdown[BILLING_CHANNEL_KEY] == "WALLET"
    assert is_wallet_billed(payment) is True
    legacy = PaymentDetails(pickup_id=uuid.uuid4(), freight_payment_mode=FreightPaymentMode.PREPAID,
                            pricing_breakdown={})
    assert is_wallet_billed(SimpleNamespace(payment_details=legacy)) is True
    assert is_wallet_billed(None) is False


def test_stamp_billing_channel_returns_a_new_dict():
    original = {"a": 1}
    stamped = stamp_billing_channel(original, BillingChannel.NONE)
    assert original == {"a": 1} and stamped == {"a": 1, BILLING_CHANNEL_KEY: "NONE"}


# ---------------------------------------------------------------- movements


def test_plan_movements_refund_never_exceeds_net_debited():
    moves = rp._plan_movements(
        reason=ChargeAdjustmentReason.ADMIN_EDIT, channel=BillingChannel.WALLET,
        new_total=Decimal("0.00"), paid_towards_bill=Decimal("100.00"),
        merchant_paid_after=Decimal("0"), extra=None,
    )
    assert [(m.txn_type, m.amount) for m in moves] == [(WalletTxnType.REFUND, Decimal("-100.00"))]


def test_plan_movements_upward_measurement_uses_weight_audit_debit():
    moves = rp._plan_movements(
        reason=ChargeAdjustmentReason.PICKUP_MEASUREMENT, channel=BillingChannel.WALLET,
        new_total=Decimal("1587.10"), paid_towards_bill=Decimal("1197.70"),
        merchant_paid_after=Decimal("0"), extra=None,
    )
    assert [(m.txn_type, m.amount) for m in moves] == [(WalletTxnType.WEIGHT_AUDIT_DEBIT, Decimal("389.40"))]


def test_plan_movements_ignores_sub_paisa_noise():
    moves = rp._plan_movements(
        reason=ChargeAdjustmentReason.ADMIN_EDIT, channel=BillingChannel.WALLET,
        new_total=Decimal("182.90"), paid_towards_bill=Decimal("182.90"),
        merchant_paid_after=Decimal("0"), extra=None,
    )
    assert moves == []


# -------------------------------------------------------------- measurements


def test_weight_only_scales_declared_boxes_and_keeps_dimensions():
    declared = [box(130, 40, 40, 20.0)]
    measured = rp._measurement_packages(
        rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("22")), declared
    )
    assert measured[0].length == 130 and measured[0].weight == 22.0
    two = [box(30, 30, 30, 2.0, 2), box(20, 20, 20, 500, 1)]
    two[1] = PackageCreate(length=20, breadth=20, height=20, weight=500, weight_unit=WeightUnit.G)
    scaled = rp._measurement_packages(
        rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("9")), two
    )
    total = sum(Decimal(str(p.weight)) * p.box_count for p in scaled)
    assert total == Decimal("9.000")
    assert all(p.weight_unit == WeightUnit.KG for p in scaled)


def test_weight_only_without_declared_boxes_uses_probe():
    measured = rp._measurement_packages(
        rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("600")), []
    )
    assert (measured[0].length, measured[0].weight, measured[0].box_count) == (10.0, 600.0, 1)


@pytest.mark.parametrize(
    "measurement",
    [
        rp.MeasurementInput(source=MeasurementSource.HUB),
        rp.MeasurementInput(source=MeasurementSource.HUB, packages=[box(1, 1, 1, 1)], weight_only_kg=Decimal("1")),
        rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("0")),
        rp.MeasurementInput(source=MeasurementSource.PICKUP, packages=[box(1, 1, 1, 1)],
                            evidence_urls=["a", "b", "c", "d"]),
    ],
)
def test_invalid_measurements_are_rejected(measurement):
    with pytest.raises(rp.InvalidMeasurementError):
        rp._measurement_packages(measurement, [box(10, 10, 10, 1)])


# ------------------------------------------------------- service: preview


async def test_r1_noop_edit_on_cod_add_shipping_does_not_drift():
    shipment = make_shipment([box(20, 15, 10, 2.0)], is_cod=True, goods=1000.0, total_value=1000.0,
                             add_shipping=True)
    assert shipment.payment_details.total_logistics_cost == 182.90
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 182.90)])
    preview = await service(repo).preview(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.ADMIN_EDIT, delivery_pincode="110002"),
        ADMIN,
    )
    assert preview.new_total == Decimal("182.90")
    assert preview.delta == Decimal("0.00")
    assert preview.wallet_delta == Decimal("0.00")
    assert preview.settlement == rp.SettlementKind.NONE
    assert preview.new_cod_amount == Decimal("1182.90")
    assert preview.new_breakdown["cod_fee"] == 20.0
    assert repo.adjustments == [] and FakeNotes.issued == []


async def test_h7_unserviceable_pin_is_refused_and_nothing_written():
    shipment = make_shipment([box(20, 20, 20, 3.0)], service=ServiceType.AIR)
    before = shipment.payment_details.total_logistics_cost
    svc = service(FakeRepo(txns=[txn(WalletTxnType.SPEND, before)]))
    # Plan D8: unserviceable pin ("999999" in FakeDelhiveryApi) is refused (H-7).
    with pytest.raises(rp.ZeroQuoteError) as err:
        await svc.apply(
            shipment,
            TENANT,
            rp.RepriceChange(reason=ChargeAdjustmentReason.ADMIN_EDIT, delivery_pincode="999999"),
            ADMIN,
        )
    assert err.value.rule == "H-7" and err.value.field == "delivery_pincode"
    assert shipment.payment_details.total_logistics_cost == before == 341.02


async def test_h8_service_type_locked_after_pickup():
    shipment = make_shipment([box(20, 15, 10, 2.0)], status=PickupStatus.IN_TRANSIT)
    with pytest.raises(rp.ServiceTypeLockedError) as err:
        await service(FakeRepo()).preview(
            shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.ADMIN_EDIT,
                                               service_type=ServiceType.AIR), ADMIN)
    assert err.value.rule == "H-8"


async def test_service_upgrade_before_pickup_reprices():
    shipment = make_shipment([box(20, 15, 10, 2.0)])
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 159.30)])
    result = await service(repo).apply(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.CUSTOMER_EDIT,
                                           service_type=ServiceType.AIR), CUSTOMER)
    assert result.new_total == Decimal("237.18")
    assert result.wallet_delta == Decimal("-77.88")
    assert shipment.service_type == ServiceType.AIR


# --------------------------------------------------- service: measurements


async def test_pickup_measurement_three_to_four_boxes_debits_and_issues_debit_note():
    shipment = make_shipment(THREE_BOXES)
    assert shipment.payment_details.total_logistics_cost == 1100.35
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 1100.35)])
    result = await service(repo).record_measurement(
        shipment, TENANT, rp.MeasurementInput(source=MeasurementSource.PICKUP, packages=FOUR_BOXES), ADMIN
    )
    assert result.new_total == Decimal("1457.30")
    assert result.new_chargeable_weight == Decimal("22.000")
    assert result.wallet_delta == Decimal("-356.95")
    assert result.settlement == rp.SettlementKind.WALLET_DEBIT
    assert result.note_type == "DEBIT_NOTE" and result.note_number
    assert FakeNotes.issued == [{"note_type": "DEBIT_NOTE", "amount": 356.95, "id": result.billing_invoice_id}]
    debit = repo.txns[-1]
    assert debit.txn_type == WalletTxnType.WEIGHT_AUDIT_DEBIT and debit.amount == 356.95
    assert FakeWalletRepo.wallet.balance == -356.95
    assert debit.receipt_number.startswith("WAD-")
    assert repo.measurements[0].chargeable_weight_kg == Decimal("22.000")
    assert repo.measurements[0].total_boxes == 4
    adjustment = repo.adjustments[0]
    assert adjustment.reason == ChargeAdjustmentReason.PICKUP_MEASUREMENT
    assert adjustment.delta == Decimal("356.95") and adjustment.wallet_txn_id == debit.id
    assert shipment.payment_details.total_logistics_cost == 1457.30
    assert shipment.payment_details.pricing_breakdown["billing_basis"] == "MEASUREMENT"
    assert shipment.payment_details.pricing_breakdown["measurement_id"] == str(result.measurement_id)
    assert result.activity_diff()["repricing"]["delta"] == 356.95


async def test_declared_edit_after_measurement_keeps_measured_bill():
    shipment = make_shipment(THREE_BOXES)
    active = ShipmentMeasurement(
        tenant_id=TENANT.id, pickup_id=shipment.id, source=MeasurementSource.PICKUP,
        packages=[rp._package_json(p) for p in FOUR_BOXES], total_boxes=4,
        actual_weight_kg=Decimal("14"), chargeable_weight_kg=Decimal("22"),
    )
    preview = await service(FakeRepo(txns=[txn(WalletTxnType.SPEND, 1457.30)], active=active)).preview(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.ADMIN_EDIT, packages=THREE_BOXES), ADMIN
    )
    assert preview.new_total == Decimal("1457.30")
    assert any("measured" in w for w in preview.warnings)


async def test_hub_weight_only_keeps_volumetric_and_oversized():
    shipment = make_shipment([box(130, 40, 40, 20.0)])
    assert shipment.payment_details.total_logistics_cost == 2755.30
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 2755.30)])
    preview = await service(repo).preview(
        shipment, TENANT,
        rp.RepriceChange(reason=ChargeAdjustmentReason.HUB_MEASUREMENT,
                         measurement=rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("22"))),
        ADMIN,
    )
    assert preview.new_total == Decimal("2755.30")
    assert preview.new_breakdown["total_volumetric_weight"] == 41.6


async def test_b2c_measured_lower_refunds_with_credit_note():
    shipment = make_shipment([box(130, 40, 40, 20.0)])
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 2755.30)])
    result = await service(repo).record_measurement(
        shipment, TENANT,
        rp.MeasurementInput(source=MeasurementSource.HUB, packages=[box(100, 40, 40, 22.0)]), ADMIN,
    )
    assert result.new_total == Decimal("2106.30")
    assert result.wallet_delta == Decimal("649.00")
    assert repo.txns[-1].txn_type == WalletTxnType.REFUND
    assert FakeNotes.issued[-1]["note_type"] == "CREDIT_NOTE" and FakeNotes.issued[-1]["amount"] == 649.00


async def test_blind_b2b_lr_billed_on_measured_cartons():
    shipment = make_shipment([], blind=True)
    assert shipment.payment_details.total_logistics_cost == 1699.20
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 1699.20)])
    result = await service(repo).record_measurement(
        shipment, TENANT,
        rp.MeasurementInput(source=MeasurementSource.PICKUP, packages=[box(60, 40, 40, 15.0, 40)]), ADMIN,
    )
    assert result.new_total == Decimal("13433.12")
    assert result.wallet_delta == Decimal("-11733.92")


# ------------------------------------------------- service: payment / modes


async def test_payment_dispute_prepaid_to_cod_charges_cod_fee():
    shipment = make_shipment([box(25, 20, 15, 1.5)], total_value=5000.0)
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 126.85)])
    result = await service(repo).apply(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.PAYMENT_MODE_CHANGE, is_cod=True), CUSTOMER
    )
    assert result.new_total == Decimal("244.85")
    assert result.wallet_delta == Decimal("-118.00")
    assert result.new_cod_amount == Decimal("5000.00")
    assert repo.txns[-1].txn_type == WalletTxnType.SPEND


async def test_to_pay_measurement_moves_freight_collectible_not_wallet():
    shipment = make_shipment([box(20, 15, 10, 2.0)], mode=FreightPaymentMode.TO_PAY)
    repo = FakeRepo()
    result = await service(repo).record_measurement(
        shipment, TENANT, rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("3.5")), ADMIN
    )
    assert result.new_total == Decimal("256.65")
    assert result.settlement == rp.SettlementKind.COLLECTIBLE_CHANGE
    assert result.new_freight_collectible == Decimal("256.65")
    assert result.wallet_delta == Decimal("0.00") and repo.txns == [] and FakeNotes.issued == []
    assert shipment.payment_details.freight_collectible == Decimal("256.65")
    assert repo.adjustments[0].freight_payment_mode == FreightPaymentMode.TO_PAY


async def test_to_pay_freight_collection_keeps_bill_and_lowers_collectible():
    shipment = make_shipment([box(20, 15, 10, 2.0)], mode=FreightPaymentMode.TO_PAY)
    repo = FakeRepo()
    extra = rp.ExtraBillCharge(amount=Decimal("159.30"), txn_type=WalletTxnType.FREIGHT_COLLECTION,
                               label="Freight Collection")
    result = await service(repo).apply(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.FREIGHT_COLLECTION, extra_charge=extra),
        CUSTOMER,
    )
    assert result.new_total == Decimal("159.30")
    assert result.new_freight_collectible == Decimal("0.00")
    assert result.wallet_delta == Decimal("-159.30")
    assert repo.txns[-1].txn_type == WalletTxnType.FREIGHT_COLLECTION
    assert FakeNotes.issued[-1]["amount"] == 159.30


async def test_wallet_freight_collection_raises_the_bill():
    shipment = make_shipment([box(20, 15, 10, 2.0)])
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 159.30)])
    extra = rp.ExtraBillCharge(amount=Decimal("100"), txn_type=WalletTxnType.FREIGHT_COLLECTION, label="FC")
    result = await service(repo).apply(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.FREIGHT_COLLECTION, extra_charge=extra),
        CUSTOMER,
    )
    assert result.new_total == Decimal("259.30") and result.wallet_delta == Decimal("-100.00")
    assert shipment.payment_details.pricing_breakdown[rp.BILL_ADJUSTMENTS_KEY][0]["amount"] == 100.0
    later = await service(repo).preview(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.ADMIN_EDIT, delivery_pincode="110003"), ADMIN
    )
    assert later.new_total == Decimal("259.30") and later.wallet_delta == Decimal("0.00")


async def test_staff_postpaid_is_record_only():
    shipment = make_shipment([box(20, 15, 10, 2.0)], mode=FreightPaymentMode.POSTPAID, channel=BillingChannel.NONE)
    repo = FakeRepo()
    result = await service(repo).record_measurement(
        shipment, TENANT, rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("3.5")), ADMIN
    )
    assert result.settlement == rp.SettlementKind.RECORD_ONLY
    assert repo.txns == [] and len(repo.adjustments) == 1


async def test_customer_postpaid_is_wallet_billed():
    shipment = make_shipment([box(20, 15, 10, 2.0)], mode=FreightPaymentMode.POSTPAID,
                             channel=BillingChannel.WALLET)
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 159.30)])
    result = await service(repo).record_measurement(
        shipment, TENANT, rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("3.5")), ADMIN
    )
    assert result.wallet_delta == Decimal("-97.35") and result.note_type == "DEBIT_NOTE"


async def test_prepaid_to_to_pay_refunds_the_wallet():
    shipment = make_shipment([box(20, 15, 10, 2.0)])
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 159.30)])
    result = await service(repo).apply(
        shipment, TENANT,
        rp.RepriceChange(reason=ChargeAdjustmentReason.PAYMENT_MODE_CHANGE,
                         freight_payment_mode=FreightPaymentMode.TO_PAY), ADMIN,
    )
    assert result.billing_channel == BillingChannel.NONE
    assert result.wallet_delta == Decimal("159.30")
    assert result.new_freight_collectible == Decimal("159.30")


# ------------------------------------------------------ service: RTO / H-9


async def test_rto_reprice_uses_rto_freight_once_then_is_a_noop():
    shipment = make_shipment([box(20, 15, 10, 2.0)], status=PickupStatus.RTO_INITIATED)
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 159.30)])
    svc = service(repo)
    first = await svc.apply(shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.RTO, is_rto=True), ADMIN)
    assert first.new_total == Decimal("218.30")
    assert repo.txns[-1].txn_type == WalletTxnType.RTO_FREIGHT and repo.txns[-1].amount == 59.0
    again = await svc.apply(shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.RTO, is_rto=True), ADMIN)
    assert again.changed is False and again.adjustment_id is None and len(repo.txns) == 2


async def test_rto_of_cod_parcel_reverses_cod_fee_and_waiver_removes_rto_leg():
    shipment = make_shipment([box(20, 15, 10, 2.0)], is_cod=True, goods=1000.0, total_value=1000.0,
                             status=PickupStatus.RTO_INITIATED)
    preview = await service(FakeRepo(txns=[txn(WalletTxnType.SPEND, 182.90)])).preview(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.RTO, is_rto=True, waive_cod_fee=True), ADMIN
    )
    assert preview.new_total == Decimal("218.30")
    waived = await service(FakeRepo(txns=[txn(WalletTxnType.SPEND, 182.90)])).preview(
        shipment, TENANT, rp.RepriceChange(reason=ChargeAdjustmentReason.RTO, waive_rto_charge=True), ADMIN
    )
    assert waived.new_breakdown["rto_surcharge"] == 0.0


async def test_h9_cod_change_after_delivery_is_refused_but_measurement_keeps_collectible():
    shipment = make_shipment([box(20, 15, 10, 2.0)], is_cod=True, goods=1000.0, total_value=1000.0,
                             status=PickupStatus.COMPLETED)
    svc = service(FakeRepo(txns=[txn(WalletTxnType.SPEND, 182.90)]))
    with pytest.raises(rp.CollectibleFrozenError):
        await svc.preview(shipment, TENANT,
                          rp.RepriceChange(reason=ChargeAdjustmentReason.COD_CHANGE, cod_amount=Decimal("500")), ADMIN)
    result = await svc.record_measurement(
        shipment, TENANT, rp.MeasurementInput(source=MeasurementSource.HUB, weight_only_kg=Decimal("3.5")), ADMIN
    )
    assert result.collectible_frozen is True
    assert shipment.payment_details.cod_amount == 1000.0
    assert result.wallet_delta < 0


# ------------------------------------------------ idempotency and refunds


async def test_idempotent_apply_replays_without_moving_money():
    shipment = make_shipment(THREE_BOXES)
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 1100.35)])
    svc = service(repo)
    first = await svc.record_measurement(
        shipment, TENANT, rp.MeasurementInput(source=MeasurementSource.PICKUP, packages=FOUR_BOXES), ADMIN,
        idempotency_key="K1",
    )
    repo.by_key["K1"] = repo.adjustments[0]
    svc.session.objects[first.wallet_txn_id] = repo.txns[-1]
    replay = await svc.record_measurement(
        shipment, TENANT, rp.MeasurementInput(source=MeasurementSource.PICKUP, packages=FOUR_BOXES), ADMIN,
        idempotency_key="K1",
    )
    assert replay.replayed is True and replay.adjustment_id == first.adjustment_id
    assert replay.wallet_delta == Decimal("-356.95")
    assert len(repo.txns) == 2 and len(FakeNotes.issued) == 1


async def test_refund_all_refunds_net_debited_with_one_credit_note():
    shipment = make_shipment([box(20, 15, 10, 2.0)])
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 159.30), txn(WalletTxnType.SPEND, 40.70),
                          txn(WalletTxnType.REFUND, 20.0), txn(WalletTxnType.ADDITIONAL_CHARGE, 590.0)])
    result = await service(repo).refund_all(shipment, TENANT, ChargeAdjustmentReason.CANCELLATION, ADMIN)
    assert result.wallet_delta == Decimal("180.00")
    assert repo.txns[-1].txn_type == WalletTxnType.REFUND and repo.txns[-1].amount == 180.0
    assert FakeNotes.issued == [{"note_type": "CREDIT_NOTE", "amount": 180.0, "id": result.billing_invoice_id}]
    assert repo.adjustments[0].new_total == Decimal("0.00")
    assert shipment.payment_details.total_logistics_cost == 0.0
    assert shipment.payment_details.base_freight == 0.0
    assert shipment.payment_details.tax_amount == 0.0

    # Non-terminal LOST preserves booked price columns so LOST_FOUND can re-bill if found
    lost_ship = make_shipment([box(20, 15, 10, 2.0)])
    lost_repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 159.30)])
    await service(lost_repo).refund_all(lost_ship, TENANT, ChargeAdjustmentReason.LOST, ADMIN)
    assert lost_ship.payment_details.total_logistics_cost == 159.30


async def test_refund_all_with_nothing_paid_moves_no_money():
    shipment = make_shipment([box(20, 15, 10, 2.0)], mode=FreightPaymentMode.TO_PAY)
    repo = FakeRepo()
    result = await service(repo).refund_all(shipment, TENANT, ChargeAdjustmentReason.CANCELLATION, ADMIN)
    assert result.settlement == rp.SettlementKind.NONE and repo.txns == []


# ----------------------------------------------------- change_from_update


async def test_change_from_update_ignores_comment_and_same_values():
    shipment = make_shipment([box(20, 15, 10, 2.0)], is_cod=True, goods=1000.0, total_value=1000.0,
                             add_shipping=True)
    svc = service(FakeRepo())
    payload = PickupUpdate(comment="fix", payment_details={"cod_amount": 1000.0, "is_cod": True})
    assert await svc.change_from_update(shipment, payload, TENANT.id, ADMIN) is None
    same_box = PickupUpdate(packages=[{"length": 20, "breadth": 15, "height": 10, "weight": 2.0}])
    assert await svc.change_from_update(shipment, same_box, TENANT.id, ADMIN) is None


async def test_change_from_update_detects_price_inputs():
    shipment = make_shipment([box(20, 15, 10, 2.0)])
    repo = FakeRepo()
    addr_id = uuid.uuid4()
    repo.pincodes[addr_id] = "400001"
    payload = PickupUpdate(
        packages=[{"length": 20, "breadth": 15, "height": 10, "weight": 3.0}],
        delivery_address_id=addr_id, po_number="PO-1",
    )
    change = await service(repo).change_from_update(shipment, payload, TENANT.id, CUSTOMER)
    assert change.reason == ChargeAdjustmentReason.CUSTOMER_EDIT
    assert change.packages[0].weight == 3.0
    assert change.delivery_pincode == "400001"
    assert change.header_overrides == {"po_number": "PO-1"}
    preview = await service(repo).preview(shipment, TENANT, change, CUSTOMER)
    assert preview.new_total == Decimal("224.20")


# ------------------------------------------------------------ edit policy


@pytest.mark.parametrize(
    ("status", "manifest", "fields", "error"),
    [
        (PickupStatus.OPEN, None, {rp.EditField.PACKAGES, rp.EditField.PAYMENT_MODE}, None),
        (PickupStatus.ASSIGNED, uuid.uuid4(), {rp.EditField.PACKAGES}, "B9"),
        (PickupStatus.ASSIGNED, uuid.uuid4(), {rp.EditField.COD, rp.EditField.CONSIGNEE_ADDRESS}, None),
        (PickupStatus.IN_TRANSIT, None, {rp.EditField.COD}, None),
        (PickupStatus.IN_TRANSIT, None, {rp.EditField.DECLARED_VALUE}, "H-12"),
        (PickupStatus.RTO_INITIATED, None, {rp.EditField.COD}, "H-12"),
        (PickupStatus.RTO_INITIATED, None, {rp.EditField.CONSIGNEE_CONTACT}, None),
        (PickupStatus.COMPLETED, None, {rp.EditField.COD}, "H-9"),
        (PickupStatus.CANCELLED, None, {rp.EditField.OTHER}, "STATE"),
    ],
)
def test_customer_edit_matrix(status, manifest, fields, error):
    shipment = SimpleNamespace(status=status, manifest_id=manifest)
    if error is None:
        rp.assert_edit_allowed(shipment, fields, CUSTOMER)
        return
    with pytest.raises(rp.RepricingError) as err:
        rp.assert_edit_allowed(shipment, fields, CUSTOMER)
    assert err.value.rule == error


def test_staff_only_hit_hard_blocks():
    in_transit = SimpleNamespace(status=PickupStatus.IN_TRANSIT, manifest_id=uuid.uuid4())
    rp.assert_edit_allowed(in_transit, {rp.EditField.PACKAGES, rp.EditField.DECLARED_VALUE}, ADMIN)
    with pytest.raises(rp.ServiceTypeLockedError):
        rp.assert_edit_allowed(in_transit, {rp.EditField.SERVICE_TYPE}, ADMIN)


def test_edit_fields_from_update_classifies_groups():
    shipment = make_shipment([box(20, 15, 10, 2.0)])
    payload = PickupUpdate(
        service_type=ServiceType.AIR,
        is_carriers_risk=True,
        order_reference_id="R1",
        payment_details={"cod_amount": 10.0, "freight_payment_mode": "TO_PAY", "shipment_total_value": 5.0,
                         "hsn_code": "1234"},
        new_delivery_address={"name": "Priya V", "phone": "9999999999", "address_line1": "Tower 9",
                              "city": "New Delhi", "state": "Delhi", "pincode": "110001"},
    )
    assert rp.edit_fields_from_update(payload, shipment) == frozenset({
        rp.EditField.SERVICE_TYPE, rp.EditField.CARRIERS_RISK, rp.EditField.OTHER, rp.EditField.COD,
        rp.EditField.PAYMENT_MODE, rp.EditField.DECLARED_VALUE, rp.EditField.CONSIGNEE_CONTACT,
    })
    moved = PickupUpdate(new_delivery_address={"name": "Priya", "phone": "9810011102", "address_line1": "Tower 10",
                                               "city": "New Delhi", "state": "Delhi", "pincode": "110001"})
    assert rp.EditField.CONSIGNEE_ADDRESS in rp.edit_fields_from_update(moved, shipment)


# ------------------------------------------------------------- idempotency


def test_request_hash_covers_method_path_query_and_canonical_body():
    a = idem.compute_request_hash("post", "/api/v1/wallet/recharge/A/approve", "", b"")
    b = idem.compute_request_hash("POST", "/api/v1/wallet/recharge/B/approve", "", b"")
    assert a != b and len(a) == 64
    body1 = json.dumps({"x": 1, "y": [1, 2]}).encode()
    body2 = b'{ "y": [1,2], "x": 1 }'
    assert idem.compute_request_hash("POST", "/p", "", body1) == idem.compute_request_hash("POST", "/p", "", body2)
    assert idem.compute_request_hash("POST", "/p", "q=1", body1) != idem.compute_request_hash("POST", "/p", "", body1)


def test_validate_key_rules():
    assert idem._validate_key(None, False) is None
    assert idem._validate_key("  k  ", False) == "k"
    with pytest.raises(idem.HTTPException) as missing:
        idem._validate_key("", True)
    assert missing.value.status_code == 400
    with pytest.raises(idem.HTTPException) as too_long:
        idem._validate_key("k" * 129, False)
    assert too_long.value.status_code == 422


def test_existing_key_mismatch_is_422_and_in_flight_is_409():
    context = idem.IdempotencyContext(endpoint="e", key="k", request_hash="h1")
    with pytest.raises(idem.HTTPException) as mismatch:
        idem._check_existing(IdempotencyKey(request_hash="h2", response={"status_code": 200, "body": {}}), context)
    assert mismatch.value.status_code == 422
    with pytest.raises(idem.HTTPException) as in_flight:
        idem._check_existing(IdempotencyKey(request_hash="h1", response=None), context)
    assert in_flight.value.status_code == 409
    idem._check_existing(IdempotencyKey(request_hash="h1", response={"status_code": 201, "body": {"a": 1}}), context)
    replay = idem._replay_response(IdempotencyKey(request_hash="h1", response={"status_code": 201, "body": {"a": 1}}))
    assert replay.status_code == 201 and replay.headers[idem.REPLAY_HEADER] == "true"
    assert json.loads(replay.body) == {"a": 1}


async def test_store_without_claim_is_a_noop():
    context = idem.IdempotencyContext(endpoint="e", key=None, request_hash="h")
    await context.store({"a": 1})
    await context.release()
    assert context.stored is False


# ------------------------------------------------------------ pricing labels


def test_postpaid_who_pays_label_and_gst_total_key():
    postpaid = quote([box(20, 15, 10, 2.0)], freight_payment_mode=FreightPaymentMode.POSTPAID)
    assert postpaid.pricing_breakdown["shipping_paid_by"] == "Sender, billed to wallet"
    assert postpaid.total_amount == quote([box(20, 15, 10, 2.0)]).total_amount
    assert postpaid.pricing_breakdown["gst_total"] == postpaid.tax_amount
    assert postpaid.pricing_breakdown["gst_split_mode"] == "CGST_SGST_OR_IGST"


async def test_explicit_cod_amount_with_add_shipping_updates_goods_base():
    shipment = make_shipment([box(20, 15, 10, 2.0)], is_cod=True, goods=2000.0, total_value=2000.0, add_shipping=True)
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, shipment.payment_details.total_logistics_cost)])
    result = await service(repo).apply(
        shipment,
        TENANT,
        rp.RepriceChange(reason=ChargeAdjustmentReason.SHORT_SHIPMENT, cod_amount=Decimal("1000.00")),
        CUSTOMER,
    )
    assert result.new_total == Decimal("182.90")
    assert result.new_cod_amount == Decimal("1182.90")


def test_edit_fields_from_update_ignores_unchanged_b2b_and_payment_fields():
    shipment = make_shipment([box(20, 15, 10, 2.0)], total_value=1000.0)
    payload = PickupUpdate(
        is_blind_pickup=False,
        is_carriers_risk=False,
        product_category=ProductCategory.HOUSEHOLD_PERSONAL,
        payment_details={
            "freight_payment_mode": "PREPAID",
            "is_cod": True,
            "cod_amount": 1000.0,
            "shipment_value": 1000.0,
            "shipment_tax_value": 0.0,
            "shipment_total_value": 1000.0,
        },
    )
    assert rp.edit_fields_from_update(payload, shipment) == frozenset({rp.EditField.COD})


async def test_measurement_wallet_remark_always_contains_weight_transition_and_boxes():
    shipment = make_shipment(THREE_BOXES)
    repo = FakeRepo(txns=[txn(WalletTxnType.SPEND, 1100.35)])
    await service(repo).record_measurement(
        shipment,
        TENANT,
        rp.MeasurementInput(source=MeasurementSource.PICKUP, packages=FOUR_BOXES, remark="Rider found 4 boxes"),
        ADMIN,
    )
    debit = repo.txns[-1]
    assert "16.5 kg" in debit.remarks and "22.0 kg" in debit.remarks and "(4 boxes)" in debit.remarks
    assert repo.measurements[0].remark == "Rider found 4 boxes"


async def test_to_pay_manual_weight_charge_raises_bill_and_collectible_not_wallet():
    shipment = make_shipment([box(20, 15, 10, 2.0)], mode=FreightPaymentMode.TO_PAY)
    repo = FakeRepo()
    extra = rp.ExtraBillCharge(
        amount=Decimal("59.00"),
        txn_type=WalletTxnType.WEIGHT_AUDIT_DEBIT,
        label="Weight discrepancy charge",
    )
    result = await service(repo).apply(
        shipment,
        TENANT,
        rp.RepriceChange(reason=ChargeAdjustmentReason.MANUAL_WEIGHT_CHARGE, extra_charge=extra),
        CUSTOMER,
    )
    assert result.new_total == Decimal("218.30")
    assert result.new_freight_collectible == Decimal("218.30")
    assert result.wallet_delta == Decimal("0.00") and repo.txns == []

