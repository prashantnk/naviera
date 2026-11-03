"""
RepricingService: the ONE writer of a shipment's price columns after booking (plan Phase B, B1/B2).

Every post-booking price change (admin or customer edit, pickup/hub measurement,
Payment Dispute, COD change, Freight Collection, RTO, accepted weight claim,
cancellation refund) flows through `RepricingService.apply()`:

1. canonical inputs: billing basis = active measurement, else the declared boxes;
   COD fee on the goods value only; freight mode and `is_rto` always passed;
   B2B class worked out after the change;
2. H-7 guard: a ₹0 / unserviceable quote is refused and the old price stays;
3. the bill is saved, then settled by billing channel (wallet delta + DEBIT/CREDIT
   note for exactly the delta, never blocked by balance; TO_PAY moves the freight
   still to be collected at the door; staff-booked POSTPAID is record-only);
4. one `shipment_charge_adjustments` row is written as the audit trail.

Money arithmetic is Decimal through `app.core.money`. The service flushes but never
commits: the caller owns the unit of work (Spring analogy: a `@Service` method with
`@Transactional(propagation = MANDATORY)`).

Cross-service collaborators (`cod_payout`, `delhivery_modules`) are imported as
modules and resolved at call time, so services that import this module back
(booking, wallet, GST notes) never hit a circular-import error.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from types import SimpleNamespace
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)

from fastapi import Depends, HTTPException, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.money import (
    ZERO_MONEY,
    is_billable_delta,
    money_to_float,
    to_money,
    to_weight,
)
from app.core.permissions import is_tenant_staff
from app.models.delhivery_modules import BillingInvoice, InvoiceNoteType
from app.models.manifests import ServiceFlow
from app.models.pickups import (
    FreightPaymentMode,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ServiceOption,
    ServiceType,
    ShipmentType,
    WeightUnit,
)
from app.models.repricing import (  # noqa: F401  (money definitions are re-exported)
    BILL_CREDIT_TYPES,
    BILL_DEBIT_TYPES,
    BILLING_CHANNEL_KEY,
    OUTSIDE_BILL_TYPES,
    SEPARATE_CHARGE_TYPES,
    BillingChannel,
    ChargeAdjustmentReason,
    MeasurementSource,
    ShipmentChargeAdjustment,
    ShipmentMeasurement,
    billing_channel_for_booking,
    billing_channel_of,
    is_wallet_billed,
    net_debited,
    stamp_billing_channel,
    wallet_txn_status,
    wallet_txn_type,
)
from app.models.tenants import Tenant, User, UserRole
from app.models.wallet import (
    WalletServiceCategory,
    WalletTransaction,
    WalletTxnStatus,
    WalletTxnType,
)
from app.repositories import delhivery_modules as delhivery_modules_repository
from app.repositories.repricing import RepricingRepository
from app.repositories.shipments import is_b2b_shipment
from app.repositories.wallet import WalletRepository
from app.schemas.v1.pickups import PackageCreate, PickupUpdate
from app.services import cod_payout, mvp_scope
from app.services import delhivery_modules as delhivery_modules_service
from app.services.pricing import weights
from app.services.pricing.booking import OPTION_SERVICE_TYPES
from app.services.pricing.quote_service import (
    PriceResult,
    QuoteService,
    RequoteRequest,
    SellInputs,
    flow_of_option,
)
from app.services.pricing.types import ParcelSpec
from app.services.shipment_lifecycle import ShipmentLifecycleMachine

BILL_ADJUSTMENTS_KEY = "bill_adjustments"
"""`pricing_breakdown` key: GST-inclusive extras added to the bill (Freight Collection, manual weight charge)."""

BILLING_BASIS_KEY = "billing_basis"
MEASUREMENT_ID_KEY = "measurement_id"
RTO_SURCHARGE_KEY = "rto_surcharge"
RTO_BILLING_KEY = "rto_billing"
"""`pricing_breakdown` marker written when the RTO leg is billed (plan C2)."""

PRE_PICKUP_STATUSES: FrozenSet[PickupStatus] = frozenset(
    {PickupStatus.DRAFT, PickupStatus.OPEN, PickupStatus.ASSIGNED}
)
"""Before the parcel is physically picked up (service type editable, H-8)."""

READY_TO_SHIP_STATUSES: FrozenSet[PickupStatus] = frozenset({PickupStatus.DRAFT, PickupStatus.OPEN})
"""DO1 "Ready to ship": a customer may still change declared boxes / payment mode."""

CONSIGNEE_EDIT_STATUSES: FrozenSet[PickupStatus] = PRE_PICKUP_STATUSES | frozenset(
    {PickupStatus.IN_TRANSIT, PickupStatus.EXCEPTION}
)
"""COD amount and consignee address editable up to and including In Transit (H-12, DO1)."""

TERMINAL_STATUSES = frozenset(ShipmentLifecycleMachine.TERMINAL_STATUSES)
"""No edits at all once a shipment is terminal (wave 2 adds RTO_DELIVERED)."""

RTO_STATUSES = frozenset(ShipmentLifecycleMachine.RTO_STATUSES)
"""Statuses whose bill carries the RTO leg."""

WEIGHT_PROBE_CM = 10.0
"""Neutral box used when a weight-only entry has no declared boxes to scale (blind LR)."""

GRAMS_PER_KG = Decimal("1000")
IST = timezone(timedelta(hours=5, minutes=30))

UPWARD_TXN_BY_REASON: Mapping[ChargeAdjustmentReason, WalletTxnType] = {
    ChargeAdjustmentReason.PICKUP_MEASUREMENT: WalletTxnType.WEIGHT_AUDIT_DEBIT,
    ChargeAdjustmentReason.HUB_MEASUREMENT: WalletTxnType.WEIGHT_AUDIT_DEBIT,
    ChargeAdjustmentReason.MANUAL_WEIGHT_CHARGE: WalletTxnType.WEIGHT_AUDIT_DEBIT,
    ChargeAdjustmentReason.CLAIM_ACCEPTED: WalletTxnType.WEIGHT_AUDIT_DEBIT,
    ChargeAdjustmentReason.RTO: WalletTxnType.RTO_FREIGHT,
    ChargeAdjustmentReason.FREIGHT_COLLECTION: WalletTxnType.FREIGHT_COLLECTION,
}
"""Txn type of an upward wallet delta; anything not listed is SPEND."""

ONCE_PER_SHIPMENT_TXN_TYPES: FrozenSet[WalletTxnType] = frozenset({WalletTxnType.RTO_FREIGHT})
"""Unique per shipment in the DB (M-B4); a second delta of that kind falls back to SPEND."""

RECEIPT_PREFIX_BY_TXN: Mapping[WalletTxnType, str] = {
    WalletTxnType.SPEND: "INV",
    WalletTxnType.REFUND: "CN",
    WalletTxnType.WEIGHT_AUDIT_DEBIT: "WAD",
    WalletTxnType.RTO_FREIGHT: "RTO",
    WalletTxnType.FREIGHT_COLLECTION: "FRC",
}
DEFAULT_RECEIPT_PREFIX = "ADJ"

MEASUREMENT_REASON_BY_SOURCE: Mapping[MeasurementSource, ChargeAdjustmentReason] = {
    MeasurementSource.PICKUP: ChargeAdjustmentReason.PICKUP_MEASUREMENT,
    MeasurementSource.HUB: ChargeAdjustmentReason.HUB_MEASUREMENT,
    MeasurementSource.ADMIN: ChargeAdjustmentReason.HUB_MEASUREMENT,
    MeasurementSource.CLAIM: ChargeAdjustmentReason.CLAIM_ACCEPTED,
    MeasurementSource.CARRIER: ChargeAdjustmentReason.HUB_MEASUREMENT,
}

B2B_MARKER_FIELDS: Sequence[str] = (
    "po_number",
    "is_blind_pickup",
    "is_carriers_risk",
    "product_category",
    "appointment_id",
    "pickup_strategy",
    "service_option",
)
"""Header fields read by `is_b2b_shipment()`; overridable in a preview via `header_overrides`."""

PACKAGE_COMPARE_FIELDS: Sequence[str] = (
    "length",
    "breadth",
    "height",
    "dimension_unit",
    "weight",
    "weight_unit",
    "box_count",
)
MAX_EVIDENCE_URLS = 3

RULE_ZERO_QUOTE = "H-7"
RULE_SERVICE_LOCKED = "H-8"
RULE_COLLECTIBLE_FROZEN = "H-9"
RULE_STATUS_WINDOW = "H-12"
RULE_CUSTOMER_FIELD = "B9"
RULE_MEASUREMENT = "MEASUREMENT"
RULE_STATE = "STATE"


# =============================================================================
# Exceptions
# =============================================================================


class RepricingError(HTTPException):
    """
    Base error of the re-pricing domain. Carries the hard-block `rule` and the
    refused `field` so the preview endpoint can report them per field.
    """

    def __init__(
        self, status_code: int, detail: str, *, rule: str, field: Optional[str] = None
    ) -> None:
        super().__init__(status_code=status_code, detail=detail)
        self.rule = rule
        self.field = field


class ZeroQuoteError(RepricingError):
    """H-7: the change would price the shipment at ₹0 (unserviceable lane / no boxes)."""

    def __init__(self, detail: str, *, field: Optional[str] = None) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, detail, rule=RULE_ZERO_QUOTE, field=field)


class ServiceTypeLockedError(RepricingError):
    """H-8: the service type cannot change after pickup."""

    def __init__(self, detail: str = "Service type cannot change after pickup.") -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, detail, rule=RULE_SERVICE_LOCKED, field="service_type")


class CollectibleFrozenError(RepricingError):
    """H-9: COD / door collectible cannot change once delivered."""

    def __init__(self, detail: str = "The COD amount cannot change after delivery.") -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, detail, rule=RULE_COLLECTIBLE_FROZEN, field="cod_amount")


class EditNotAllowedError(RepricingError):
    """B9 / H-12: the field is not editable by this actor or not in this status."""


class InvalidMeasurementError(RepricingError):
    """The measurement payload is inconsistent (422)."""

    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_422_UNPROCESSABLE_CONTENT, detail, rule=RULE_MEASUREMENT, field="measurement")


class NotRepriceableError(RepricingError):
    """The shipment has no payment details or is cancelled (400)."""

    def __init__(self, detail: str) -> None:
        super().__init__(status.HTTP_400_BAD_REQUEST, detail, rule=RULE_STATE)


# =============================================================================
# Inputs and outputs
# =============================================================================


@dataclass(frozen=True)
class MeasurementInput:
    """A measured parcel. Exactly one of `packages` / `weight_only_kg`."""

    source: MeasurementSource
    packages: Sequence[PackageCreate] = ()
    weight_only_kg: Optional[Decimal] = None
    evidence_urls: Sequence[str] = ()
    remark: Optional[str] = None
    override_total_price: Optional[Decimal] = None


@dataclass(frozen=True)
class ExtraBillCharge:
    """A GST-inclusive amount the merchant pays from the wallet on top of the engine price."""

    amount: Decimal
    txn_type: WalletTxnType
    label: str


@dataclass(frozen=True)
class RepriceChange:
    """What changes. Every None field keeps the persisted value."""

    reason: ChargeAdjustmentReason
    packages: Optional[Sequence[PackageCreate]] = None
    measurement: Optional[MeasurementInput] = None
    service_type: Optional[ServiceType] = None
    service_option: Optional[ServiceOption] = None
    """Switch Delhivery Surface ↔ Express before pickup (same flow only); `service_type` follows."""
    pickup_pincode: Optional[str] = None
    delivery_pincode: Optional[str] = None
    is_cod: Optional[bool] = None
    cod_amount: Optional[Decimal] = None
    shipment_total_value: Optional[Decimal] = None
    add_shipping_to_cod: Optional[bool] = None
    freight_payment_mode: Optional[FreightPaymentMode] = None
    is_carriers_risk: Optional[bool] = None
    is_rto: Optional[bool] = None
    waive_rto_charge: bool = False
    waive_cod_fee: bool = False
    max_refund: Optional[Decimal] = None
    extra_charge: Optional[ExtraBillCharge] = None
    override_total_price: Optional[Decimal] = None
    header_overrides: Optional[Mapping[str, Any]] = None
    idempotency_key: Optional[str] = None
    remark: Optional[str] = None


class SettlementKind(str, Enum):
    """How a price change was (or would be) settled."""

    WALLET_DEBIT = "WALLET_DEBIT"
    WALLET_REFUND = "WALLET_REFUND"
    COLLECTIBLE_CHANGE = "COLLECTIBLE_CHANGE"
    RECORD_ONLY = "RECORD_ONLY"
    NONE = "NONE"


@dataclass(frozen=True)
class RepricePreview:
    """The outcome of a re-price, computed without writing anything."""

    shipment_id: uuid.UUID
    reason: ChargeAdjustmentReason
    old_total: Decimal
    new_total: Decimal
    delta: Decimal
    old_chargeable_weight: Decimal
    new_chargeable_weight: Decimal
    old_breakdown: Dict[str, Any]
    new_breakdown: Dict[str, Any]
    freight_payment_mode: FreightPaymentMode
    billing_channel: BillingChannel
    settlement: SettlementKind
    wallet_delta: Decimal
    note_type: Optional[str]
    old_cod_amount: Decimal
    new_cod_amount: Decimal
    old_freight_collectible: Decimal
    new_freight_collectible: Decimal
    collectible_frozen: bool
    changed: bool
    warnings: Sequence[str]


@dataclass(frozen=True)
class RepriceResult(RepricePreview):
    """A re-price that was applied (flushed, not committed)."""

    adjustment_id: Optional[uuid.UUID]
    wallet_txn_id: Optional[uuid.UUID]
    billing_invoice_id: Optional[uuid.UUID]
    note_number: Optional[str]
    measurement_id: Optional[uuid.UUID]
    replayed: bool

    def activity_diff(self) -> Dict[str, Any]:
        """Structured, JSON-safe diff for the ShipmentActivity of this change."""
        return {
            "repricing": {
                "reason": self.reason.value,
                "old_total": float(self.old_total),
                "new_total": float(self.new_total),
                "delta": float(self.delta),
                "old_weight": float(self.old_chargeable_weight),
                "new_weight": float(self.new_chargeable_weight),
                "wallet_delta": float(self.wallet_delta),
                "wallet_txn_id": str(self.wallet_txn_id) if self.wallet_txn_id else None,
                "note_type": self.note_type,
                "note_number": self.note_number,
                "measurement_id": str(self.measurement_id) if self.measurement_id else None,
                "adjustment_id": str(self.adjustment_id) if self.adjustment_id else None,
            }
        }


@dataclass(frozen=True)
class ChargeAdjustmentView:
    """One charges-history row: the adjustment columns plus note and actor details."""

    id: uuid.UUID
    created_at: datetime
    reason: ChargeAdjustmentReason
    old_total: Decimal
    new_total: Decimal
    delta: Decimal
    old_chargeable_weight: Optional[Decimal]
    new_chargeable_weight: Optional[Decimal]
    freight_payment_mode: FreightPaymentMode
    wallet_txn_id: Optional[uuid.UUID]
    billing_invoice_id: Optional[uuid.UUID]
    note_number: Optional[str]
    note_type: Optional[str]
    actor_email: Optional[str]


class EditField(str, Enum):
    """Groups of PickupUpdate fields, for the B9 / H-8 / H-12 edit policy."""

    PACKAGES = "PACKAGES"
    SERVICE_TYPE = "SERVICE_TYPE"
    COD = "COD"
    CONSIGNEE_CONTACT = "CONSIGNEE_CONTACT"
    CONSIGNEE_ADDRESS = "CONSIGNEE_ADDRESS"
    PICKUP_ADDRESS = "PICKUP_ADDRESS"
    DECLARED_VALUE = "DECLARED_VALUE"
    PAYMENT_MODE = "PAYMENT_MODE"
    CARRIERS_RISK = "CARRIERS_RISK"
    B2B_FLAGS = "B2B_FLAGS"
    OTHER = "OTHER"


# =============================================================================
# Module-level helpers (pure)
# =============================================================================


def edit_fields_from_update(
    payload: PickupUpdate, shipment: Optional[PickupRequest] = None
) -> FrozenSet[EditField]:
    """
    Classifies the fields set in a PATCH body into EditField groups.

    When `shipment` is passed, only fields whose values actually differ from the
    stored shipment / payment_details count, so always-sent form fields never
    trigger a false edit-window error. A new consignee address that keeps the
    same lines and pincode and only changes name / phone / email counts as
    CONSIGNEE_CONTACT.

    Args:
        payload: The PATCH body (only explicitly set fields count).
        shipment: The current shipment (used to filter unchanged fields and tell
            contact from address edits).

    Returns:
        The set of edited groups.
    """
    data = payload.model_dump(exclude_unset=True)
    fields: set = set()
    if _packages_edit_present(payload, data, shipment):
        fields.add(EditField.PACKAGES)
    if data.get("service_type") is not None and (
        shipment is None or data["service_type"] != getattr(shipment, "service_type", None)
    ):
        fields.add(EditField.SERVICE_TYPE)
    if data.get("service_option") is not None and (
        shipment is None or data["service_option"] != getattr(shipment, "service_option", None)
    ):
        fields.add(EditField.SERVICE_TYPE)
    payment = getattr(shipment, "payment_details", None) if shipment is not None else None
    fields |= _payment_edit_fields(payload, payment)
    fields |= _address_edit_fields(payload, shipment)
    if (
        "is_carriers_risk" in data
        and data["is_carriers_risk"] is not None
        and (shipment is None or bool(data["is_carriers_risk"]) != bool(getattr(shipment, "is_carriers_risk", False)))
    ):
        fields.add(EditField.CARRIERS_RISK)
    if any(
        key in data and (shipment is None or _scalar_differs(getattr(shipment, key, None), data[key]))
        for key in (
            "po_number", "po_date", "po_expiry_date", "appointment_id",
            "appointment_start", "appointment_end", "pickup_strategy",
            "product_category", "other_category_description",
        )
    ):
        fields.add(EditField.B2B_FLAGS)
    if any(
        key in data and (shipment is None or _scalar_differs(getattr(shipment, key, None), data[key]))
        for key in (
            "order_reference_id", "requested_pickup_date", "pickup_time_slot",
            "documents", "reason_for_return", "qc_required", "qc_notes",
        )
    ):
        fields.add(EditField.OTHER)
    return frozenset(fields)


def assert_edit_allowed(
    shipment: PickupRequest, fields: Iterable[EditField], actor: Optional[User]
) -> None:
    """
    Edit policy: hard blocks for everyone, plus the DO1 customer matrix (B9).

    Everyone: nothing on a terminal shipment (except nothing); service type only before
    pickup (H-8); COD frozen once delivered (H-9).
    Customers (DO1 `update-forward-order`): everything while Ready to ship and not in a
    pickup request; COD + consignee address + reference fields up to and including
    In Transit (H-12); consignee contact until terminal.

    Raises:
        ServiceTypeLockedError, CollectibleFrozenError, EditNotAllowedError.
    """
    requested = frozenset(fields)
    if not requested:
        return
    current = shipment.status
    if current in TERMINAL_STATUSES:
        if EditField.COD in requested and current == PickupStatus.COMPLETED:
            raise CollectibleFrozenError()
        raise EditNotAllowedError(
            status.HTTP_400_BAD_REQUEST,
            f"A {current.value} shipment can no longer be edited.",
            rule=RULE_STATE,
            field=sorted(f.value for f in requested)[0],
        )
    if EditField.SERVICE_TYPE in requested and current not in PRE_PICKUP_STATUSES:
        raise ServiceTypeLockedError()
    if EditField.COD in requested and current not in CONSIGNEE_EDIT_STATUSES:
        raise EditNotAllowedError(
            status.HTTP_400_BAD_REQUEST,
            f"COD amount cannot be changed once the shipment is in status {current.value} (H-12).",
            rule=RULE_STATUS_WINDOW,
            field=EditField.COD.value,
        )
    if actor is not None and is_tenant_staff(actor):
        if actor.role not in (UserRole.owner, UserRole.admin) and (
            EditField.COD in requested or EditField.PAYMENT_MODE in requested
        ):
            blocked_field = (
                EditField.COD.value if EditField.COD in requested else EditField.PAYMENT_MODE.value
            )
            raise EditNotAllowedError(
                status.HTTP_403_FORBIDDEN,
                "Only Tenant Owners or Admins can change payment mode or COD amount on behalf of a shipper.",
                rule=RULE_CUSTOMER_FIELD,
                field=blocked_field,
            )
        return
    _assert_customer_window(shipment, requested)


# =============================================================================
# Service
# =============================================================================


@dataclass
class _Movement:
    """One wallet ledger movement: positive amount = debit, negative = refund."""

    txn_type: WalletTxnType
    amount: Decimal


@dataclass
class _Plan:
    """Everything apply() needs, computed by _plan() without writing."""

    preview: RepricePreview
    quote: PriceResult
    movements: List[_Movement]
    measurement_draft: Optional[ShipmentMeasurement]
    payment_writes: Dict[str, Any]
    header_writes: Dict[str, Any]
    is_b2b: bool
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class _Inputs:
    """Canonical pricing inputs after applying the change to the persisted state."""

    packages: List[PackageCreate]
    billing_basis: str
    service_type: ServiceType
    service_option: ServiceOption
    pickup_pincode: str
    delivery_pincode: str
    is_cod: bool
    goods: Decimal
    shipment_total_value: Decimal
    add_shipping_to_cod: bool
    mode: FreightPaymentMode
    is_carriers_risk: bool
    is_rto: bool
    is_b2b: bool
    engine_is_cod: bool
    """COD fee charged? Never once the parcel is in an RTO status: no cash is collected (C2, D50)."""


class RepricingService:
    """The only transactional writer of a shipment's price columns after booking."""

    BASIS_MEASUREMENT = "MEASUREMENT"
    BASIS_DECLARED = "DECLARED"
    BASIS_BLIND_FLOOR = "BLIND_FLOOR"

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = RepricingRepository(session)

    # ----------------------------------------------------------- public reads

    async def load_shipment(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID, *, for_update: bool = False
    ) -> PickupRequest:
        """
        Loads a shipment (all price-relevant relations eager-loaded).

        Raises:
            HTTPException(404): not found in this tenant (H-5).
        """
        shipment = await self.repo.get_shipment(shipment_id, tenant_id, for_update=for_update)
        if shipment is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shipment not found")
        return shipment

    async def get_active_measurement(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Optional[ShipmentMeasurement]:
        """The measurement currently used as the billing basis, if any."""
        return await self.repo.get_active_measurement(shipment_id, tenant_id)

    async def list_adjustments(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[ShipmentChargeAdjustment]:
        """All charge adjustments of a shipment, newest first."""
        return await self.repo.list_adjustments(shipment_id, tenant_id, newest_first=True)

    async def list_adjustment_views(
        self, shipment_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> List[ChargeAdjustmentView]:
        """Charges history, oldest first, with GST note number/type and actor email."""
        rows = await self.repo.list_adjustments_joined(shipment_id, tenant_id)
        return [
            ChargeAdjustmentView(
                id=row.adjustment.id,
                created_at=row.adjustment.created_at,
                reason=ChargeAdjustmentReason(row.adjustment.reason),
                old_total=to_money(row.adjustment.old_total),
                new_total=to_money(row.adjustment.new_total),
                delta=to_money(row.adjustment.delta),
                old_chargeable_weight=_optional_weight(row.adjustment.old_chargeable_weight),
                new_chargeable_weight=_optional_weight(row.adjustment.new_chargeable_weight),
                freight_payment_mode=FreightPaymentMode(row.adjustment.freight_payment_mode),
                wallet_txn_id=row.adjustment.wallet_txn_id,
                billing_invoice_id=row.adjustment.billing_invoice_id,
                note_number=row.note_number,
                note_type=row.note_type,
                actor_email=row.actor_email,
            )
            for row in rows
        ]

    # ------------------------------------------------------- preview / apply

    async def preview(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        change: RepriceChange,
        actor: Optional[User],
    ) -> RepricePreview:
        """
        Computes the outcome of a change without adding or flushing anything.

        Raises:
            The RepricingError subclasses (H-7, H-8, H-9, measurement, state).
        """
        with self.session.no_autoflush:
            plan = await self._plan(shipment, tenant, change, actor)
        return plan.preview

    async def apply(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        change: RepriceChange,
        actor: Optional[User],
    ) -> RepriceResult:
        """
        Applies a change: writes the bill, settles it, records the audit row. Flushes, never commits.

        `shipment` must have been loaded with `load_shipment(for_update=True)` in this session.
        A change carrying an `idempotency_key` that was already applied returns the stored outcome
        (`replayed=True`) without moving money again.
        """
        if change.idempotency_key:
            existing = await self.repo.get_adjustment_by_idempotency_key(tenant.id, change.idempotency_key)
            if existing is not None:
                return await self._result_from_adjustment(shipment, existing)

        with self.session.no_autoflush:
            plan = await self._plan(shipment, tenant, change, actor)
        measurement = await self._persist_measurement(shipment, plan)
        self._write_shipment(shipment, plan, measurement)
        wallet_txn, note = await self._settle(shipment, tenant, plan, change)

        adjustment = await self._record_adjustment(shipment, plan, change, actor, wallet_txn, note, measurement)

        if change.reason == ChargeAdjustmentReason.RTO and change.is_rto and shipment.payment_details:
            self._stamp_rto_billing(shipment.payment_details, plan, note)

        await self.session.flush()
        return RepriceResult(
            **_preview_fields(plan.preview),
            adjustment_id=adjustment.id if adjustment else None,
            wallet_txn_id=wallet_txn.id if wallet_txn else None,
            billing_invoice_id=note.id if note else None,
            note_number=note.invoice_number if note else None,
            measurement_id=measurement.id if measurement else None,
            replayed=False,
        )

    @staticmethod
    def _stamp_rto_billing(payment: PaymentDetails, plan: "_Plan", note: Optional[Any]) -> None:
        """
        C2 / F17: records how the RTO leg was billed in `pricing_breakdown.rto_billing`, so no
        screen or check has to guess RTO from "any RTO surcharge". Re-assigns the JSONB dict so
        SQLAlchemy tracks the change.
        """
        breakdown = dict(payment.pricing_breakdown or {})
        breakdown[RTO_BILLING_KEY] = {
            "charged_at": datetime.now(IST).isoformat(),
            "rto_leg_amount": float(plan.preview.new_breakdown.get(RTO_SURCHARGE_KEY, 0)),
            "billed_to": plan.preview.new_breakdown.get(BILLING_CHANNEL_KEY, BillingChannel.WALLET.value),
            "document_id": str(note.id) if note else None,
        }
        payment.pricing_breakdown = breakdown

    async def record_measurement(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        measurement: MeasurementInput,
        actor: Optional[User],
        *,
        idempotency_key: Optional[str] = None,
    ) -> RepriceResult:
        """Records a measurement (it becomes the billing basis) and re-prices on it."""
        change = RepriceChange(
            reason=MEASUREMENT_REASON_BY_SOURCE[measurement.source],
            measurement=measurement,
            idempotency_key=idempotency_key,
            remark=measurement.remark,
        )
        return await self.apply(shipment, tenant, change, actor)

    async def refund_all(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        reason: ChargeAdjustmentReason,
        actor: Optional[User],
        *,
        idempotency_key: Optional[str] = None,
        remark: Optional[str] = None,
    ) -> RepriceResult:
        """
        Refunds everything paid towards the bill (cancellation, pickup rejection, LOST):
        one REFUND of the net debited amount + a CREDIT_NOTE of exactly that amount.
        Separate charges (Mathadi etc.) are never refunded. Price columns are left as
        booked; the adjustment row records the bill going to ₹0. Flushes, never commits.
        """
        if idempotency_key:
            existing = await self.repo.get_adjustment_by_idempotency_key(tenant.id, idempotency_key)
            if existing is not None:
                return await self._result_from_adjustment(shipment, existing)
        payment = _require_payment(shipment)
        txns = await self.repo.list_shipment_wallet_txns(shipment.id, tenant.id)
        paid = net_debited(txns)
        old_total = to_money(payment.total_logistics_cost)
        weight = to_weight(payment.chargeable_weight)
        movements = [_Movement(WalletTxnType.REFUND, -paid)] if is_billable_delta(paid) and paid > 0 else []
        preview = RepricePreview(
            shipment_id=shipment.id,
            reason=reason,
            old_total=old_total,
            new_total=ZERO_MONEY,
            delta=to_money(ZERO_MONEY - old_total),
            old_chargeable_weight=weight,
            new_chargeable_weight=weight,
            old_breakdown=dict(payment.pricing_breakdown or {}),
            new_breakdown=dict(payment.pricing_breakdown or {}),
            freight_payment_mode=payment.freight_payment_mode,
            billing_channel=billing_channel_of(payment),
            settlement=SettlementKind.WALLET_REFUND if movements else SettlementKind.NONE,
            wallet_delta=paid if movements else ZERO_MONEY,
            note_type=InvoiceNoteType.CREDIT_NOTE.value if movements else None,
            old_cod_amount=to_money(payment.cod_amount),
            new_cod_amount=to_money(payment.cod_amount),
            old_freight_collectible=to_money(payment.freight_collectible),
            new_freight_collectible=to_money(payment.freight_collectible),
            collectible_frozen=bool(cod_payout.is_collectible_frozen(shipment)),
            changed=True,
            warnings=(),
        )
        plan = _Plan(
            preview=preview,
            quote=PriceResult(
                serviceable=True,
                error_message=None,
                chargeable_weight=float(weight),
                base_charge=float(payment.base_freight or 0.0),
                tax_amount=float(payment.tax_amount or 0.0),
                total_amount=float(old_total),
                pricing_breakdown=dict(payment.pricing_breakdown or {}),
                carrier_cost=None,
            ),
            movements=movements,
            measurement_draft=None,
            payment_writes={},
            header_writes={},
            is_b2b=is_b2b_shipment(shipment),
        )
        change = RepriceChange(reason=reason, idempotency_key=idempotency_key, remark=remark)
        wallet_txn, note = await self._settle(shipment, tenant, plan, change)
        adjustment = await self._record_adjustment(shipment, plan, change, actor, wallet_txn, note, None)
        await self.session.flush()
        return RepriceResult(
            **_preview_fields(preview),
            adjustment_id=adjustment.id if adjustment else None,
            wallet_txn_id=wallet_txn.id if wallet_txn else None,
            billing_invoice_id=note.id if note else None,
            note_number=note.invoice_number if note else None,
            measurement_id=None,
            replayed=False,
        )

    async def change_from_update(
        self,
        shipment: PickupRequest,
        payload: PickupUpdate,
        tenant_id: uuid.UUID,
        actor: Optional[User],
    ) -> Optional[RepriceChange]:
        """
        Maps a PATCH body to a RepriceChange, keeping only price inputs that really change.

        Address ids are resolved to pincodes (tenant-scoped). Returns None when no price
        input changed, so a comment-only or address-line-only save never re-prices (R1, R6).
        Never adds or flushes.
        """
        payment = shipment.payment_details
        overrides: Dict[str, Any] = {}
        data = payload.model_dump(exclude_unset=True)

        packages = _changed_packages(shipment, payload)
        if "is_blind_pickup" in data and bool(data["is_blind_pickup"]) != bool(shipment.is_blind_pickup):
            overrides["header_overrides"] = {"is_blind_pickup": bool(data["is_blind_pickup"])}
        if packages is not None:
            overrides["packages"] = packages

        new_service = data.get("service_type")
        if new_service is not None and new_service != shipment.service_type:
            overrides["service_type"] = new_service
            implied = _option_for_service_type(shipment.service_option, new_service)
            if implied != shipment.service_option:
                overrides["service_option"] = implied
        new_option = data.get("service_option")
        if new_option is not None and new_option != shipment.service_option:
            _assert_same_flow(shipment.service_option, new_option)
            overrides["service_option"] = new_option

        with self.session.no_autoflush:
            pickup_pin = await self._resolve_pincode(payload, tenant_id, side="pickup")
            delivery_pin = await self._resolve_pincode(payload, tenant_id, side="delivery")
        if pickup_pin and shipment.pickup_address and pickup_pin != shipment.pickup_address.pincode:
            overrides["pickup_pincode"] = pickup_pin
        if delivery_pin and shipment.delivery_address and delivery_pin != shipment.delivery_address.pincode:
            overrides["delivery_pincode"] = delivery_pin

        overrides.update(_changed_payment_fields(payload, payment))
        if mvp_scope.is_to_pay_blocked(overrides.get("freight_payment_mode")):
            raise EditNotAllowedError(
                status.HTTP_400_BAD_REQUEST,
                mvp_scope.TO_PAY_DISABLED_DETAIL,
                rule=RULE_STATE,
                field="freight_payment_mode",
            )

        if "is_carriers_risk" in data and data["is_carriers_risk"] is not None:
            if bool(data["is_carriers_risk"]) != bool(shipment.is_carriers_risk):
                overrides["is_carriers_risk"] = bool(data["is_carriers_risk"])

        # A status move into RTO is NOT a price input here: ShipmentService.apply_rto_charges
        # bills the RTO leg once (RTO_FREIGHT + DN, after the COD-fee CN) after the save.
        marker_changes = {
            name: data[name]
            for name in B2B_MARKER_FIELDS
            if name in data and name not in ("is_blind_pickup", "is_carriers_risk")
            and data[name] != getattr(shipment, name)
        }
        if marker_changes:
            merged = dict(overrides.get("header_overrides") or {})
            merged.update(marker_changes)
            overrides["header_overrides"] = merged

        if not overrides:
            return None
        reason = (
            ChargeAdjustmentReason.ADMIN_EDIT
            if actor is not None and is_tenant_staff(actor)
            else ChargeAdjustmentReason.CUSTOMER_EDIT
        )
        return RepriceChange(reason=reason, **overrides)

    # ------------------------------------------------------------- planning

    async def _plan(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        change: RepriceChange,
        actor: Optional[User],
    ) -> _Plan:
        """Computes the new bill, settlement and writes for a change (reads only)."""
        payment = _require_payment(shipment)
        if shipment.status == PickupStatus.CANCELLED:
            raise NotRepriceableError("A cancelled shipment cannot be re-priced.")
        if (
            change.service_type is not None
            and change.service_type != shipment.service_type
            and shipment.status not in PRE_PICKUP_STATUSES
        ) or (
            change.service_option is not None
            and change.service_option != shipment.service_option
            and shipment.status not in PRE_PICKUP_STATUSES
        ):
            raise ServiceTypeLockedError()

        frozen = bool(cod_payout.is_collectible_frozen(shipment))
        if frozen and _touches_cod(change, payment):
            raise CollectibleFrozenError()

        warnings: List[str] = []
        active = await self.repo.get_active_measurement(shipment.id, tenant.id)
        packages, basis, measurement_draft = self._billing_packages(shipment, change, active, warnings)
        inputs = self._resolve_inputs(shipment, payment, change, packages, basis)
        if (
            not (payment.carrier_cost or {}).get("forward")
            and _has_direct_price_adjustment(change)
            and getattr(self._quote, "__func__", None) is RepricingService._quote
        ):
            quote = _stored_payment_as_quote(payment, packages)
        else:
            quote = await self._quote(inputs, shipment, payment, tenant)
        _assert_quote_bookable(quote, change)

        txns = await self.repo.list_shipment_wallet_txns(shipment.id, tenant.id)
        paid_towards_bill = net_debited(txns)
        merchant_paid_freight = _sum_txn_type(txns, WalletTxnType.FREIGHT_COLLECTION)

        old_channel = billing_channel_of(payment)
        new_channel = _channel_after_change(old_channel, payment.freight_payment_mode, inputs.mode, actor)
        old_breakdown = dict(payment.pricing_breakdown or {})
        adjustments = list(old_breakdown.get(BILL_ADJUSTMENTS_KEY) or [])
        if change.reason == ChargeAdjustmentReason.CLAIM_ACCEPTED:
            adjustments = [
                a
                for a in adjustments
                if a.get("txn_type") != WalletTxnType.WEIGHT_AUDIT_DEBIT.value
                and a.get("kind") != "ADMIN_PRICE_OVERRIDE"
            ]

        extra = change.extra_charge
        if extra is not None and to_money(extra.amount) <= ZERO_MONEY:
            raise InvalidMeasurementError("Extra charge amount must be greater than 0.")
        merchant_paid_after = merchant_paid_freight
        wallet_extra: Optional[ExtraBillCharge] = None
        if extra is not None:
            is_door_freight_payment = (
                new_channel != BillingChannel.WALLET and extra.txn_type == WalletTxnType.FREIGHT_COLLECTION
            )
            if is_door_freight_payment:
                # TO_PAY: the merchant pays freight the consignee would have paid; the bill stays.
                merchant_paid_after = to_money(merchant_paid_freight + to_money(extra.amount))
                wallet_extra = extra
            else:
                adjustments.append(
                    {"label": extra.label, "amount": float(to_money(extra.amount)), "txn_type": extra.txn_type.value}
                )
                if new_channel == BillingChannel.WALLET:
                    wallet_extra = extra

        engine_total = to_money(quote.total_amount)
        effective_override = (
            change.override_total_price
            if change.override_total_price is not None
            else (
                change.measurement.override_total_price
                if change.measurement is not None
                else None
            )
        )
        if effective_override is not None:
            override_money = to_money(effective_override)
            if override_money <= ZERO_MONEY:
                raise InvalidMeasurementError("Override final price must be greater than 0.")
            adjustments = [
                a for a in adjustments if a.get("kind") != "ADMIN_PRICE_OVERRIDE"
            ]
            base_total = to_money(
                engine_total
                + sum((to_money(a.get("amount")) for a in adjustments), ZERO_MONEY)
            )
            override_delta = to_money(override_money - base_total)
            if override_delta != ZERO_MONEY:
                adjustments.append(
                    {
                        "kind": "ADMIN_PRICE_OVERRIDE",
                        "label": (change.remark or "Admin price override")[:120],
                        "amount": float(override_delta),
                        "txn_type": (
                            WalletTxnType.SPEND.value
                            if override_delta > ZERO_MONEY
                            else WalletTxnType.REFUND.value
                        ),
                    }
                )
            new_total = override_money
        else:
            new_total = to_money(engine_total + sum((to_money(a.get("amount")) for a in adjustments), ZERO_MONEY))
        old_total = to_money(payment.total_logistics_cost)
        if change.reason == ChargeAdjustmentReason.CLAIM_ACCEPTED:
            # A-07: Accepting a weight discrepancy claim can never debit the seller and can
            # never refund more than the cumulative upward measurement delta (max_refund).
            new_total = min(new_total, old_total)
            if change.max_refund is not None:
                floor_total = max(ZERO_MONEY, to_money(old_total - to_money(change.max_refund)))
                new_total = max(new_total, floor_total)
        if _merchant_pays_returned_to_pay(shipment, inputs, new_channel):
            # C2: a refused TO_PAY parcel comes back, so nobody pays at the door; the merchant is
            # billed the whole bill (forward + RTO) less what they already paid.
            merchant_paid_after = new_total

        movements = _plan_movements(
            reason=change.reason,
            channel=new_channel,
            new_total=new_total,
            paid_towards_bill=paid_towards_bill,
            merchant_paid_after=merchant_paid_after,
            extra=wallet_extra,
        )

        old_cod = to_money(payment.cod_amount)
        old_fc = to_money(payment.freight_collectible)
        if frozen:
            new_cod, new_fc = old_cod, old_fc
        else:
            new_cod, new_fc = cod_payout.collectible_amounts(
                is_cod=inputs.is_cod,
                goods=inputs.goods,
                total=new_total,
                mode=inputs.mode,
                add_shipping_to_cod=inputs.add_shipping_to_cod,
                merchant_paid=merchant_paid_after,
            )
            new_cod, new_fc = to_money(new_cod), to_money(new_fc)

        new_breakdown = stamp_billing_channel(quote.pricing_breakdown, new_channel)
        new_breakdown[BILL_ADJUSTMENTS_KEY] = adjustments
        new_breakdown[BILLING_BASIS_KEY] = basis
        if active is not None and measurement_draft is None:
            new_breakdown[MEASUREMENT_ID_KEY] = str(active.id)

        payment_writes = _payment_writes(payment, inputs, quote, new_total, new_breakdown, new_cod, new_fc, frozen)
        header_writes = _header_writes(shipment, change)
        wallet_net = to_money(sum((m.amount for m in movements), ZERO_MONEY))
        settlement = _settlement_kind(new_channel, inputs.mode, wallet_net, old_fc, new_fc, old_total, new_total)
        new_weight = to_weight(quote.chargeable_weight)
        old_weight = to_weight(payment.chargeable_weight)
        changed = bool(
            old_total != new_total
            or old_weight != new_weight
            or movements
            or old_cod != new_cod
            or old_fc != new_fc
            or measurement_draft is not None
            or _has_real_writes(payment, payment_writes, ("freight_payment_mode", "is_cod",
                                                          "add_shipping_to_cod", "shipment_total_value"))
            or _has_real_writes(shipment, header_writes, tuple(header_writes))
        )
        if frozen:
            warnings.append("The COD collectible is frozen after delivery (H-9).")

        preview = RepricePreview(
            shipment_id=shipment.id,
            reason=change.reason,
            old_total=old_total,
            new_total=new_total,
            delta=to_money(new_total - old_total),
            old_chargeable_weight=old_weight,
            new_chargeable_weight=new_weight,
            old_breakdown=old_breakdown,
            new_breakdown=new_breakdown,
            freight_payment_mode=inputs.mode,
            billing_channel=new_channel,
            settlement=settlement,
            wallet_delta=to_money(-wallet_net),
            note_type=_note_type_for(wallet_net),
            old_cod_amount=old_cod,
            new_cod_amount=new_cod,
            old_freight_collectible=old_fc,
            new_freight_collectible=new_fc,
            collectible_frozen=frozen,
            changed=changed,
            warnings=tuple(warnings),
        )
        return _Plan(
            preview=preview,
            quote=quote,
            movements=movements,
            measurement_draft=measurement_draft,
            payment_writes=payment_writes,
            header_writes=header_writes,
            is_b2b=inputs.is_b2b,
            warnings=warnings,
        )

    def _billing_packages(
        self,
        shipment: PickupRequest,
        change: RepriceChange,
        active: Optional[ShipmentMeasurement],
        warnings: List[str],
    ) -> Tuple[List[PackageCreate], str, Optional[ShipmentMeasurement]]:
        """
        Picks the billing basis: a new measurement, else the active one, else the declared boxes.

        Returns:
            (packages to price, basis label, unsaved measurement row or None).
        """
        overrides = change.header_overrides or {}
        is_blind = bool(overrides.get("is_blind_pickup", shipment.is_blind_pickup))
        if change.packages is not None:
            declared = [_clone_package(p) for p in change.packages]
        elif is_blind:
            declared = []
        else:
            declared = [_package_from_row(p) for p in (shipment.packages or [])]

        if change.measurement is not None:
            measured = _measurement_packages(change.measurement, declared)
            draft = ShipmentMeasurement(
                tenant_id=shipment.tenant_id,
                pickup_id=shipment.id,
                source=change.measurement.source,
                packages=[_package_json(p) for p in measured],
                total_boxes=max(1, sum(int(p.box_count) for p in measured)),
                actual_weight_kg=Decimal("0"),
                volumetric_weight_kg=Decimal("0"),
                chargeable_weight_kg=Decimal("0"),
                evidence_urls=list(change.measurement.evidence_urls),
                remark=(change.measurement.remark or None),
            )
            return measured, self.BASIS_MEASUREMENT, draft
        if active is not None:
            if change.packages is not None:
                warnings.append(
                    "The parcel was measured; declared box edits do not change the bill."
                )
            return [PackageCreate(**p) for p in (active.packages or [])], self.BASIS_MEASUREMENT, None
        if not declared:
            if is_blind:
                return [], self.BASIS_BLIND_FLOOR, None
            raise ZeroQuoteError("A shipment needs at least one box to be priced.", field="packages")
        return declared, self.BASIS_DECLARED, None

    def _resolve_inputs(
        self,
        shipment: PickupRequest,
        payment: PaymentDetails,
        change: RepriceChange,
        packages: List[PackageCreate],
        basis: str,
    ) -> _Inputs:
        """Applies the change to the persisted values and returns canonical engine inputs."""
        mode = change.freight_payment_mode or payment.freight_payment_mode
        is_cod = payment.is_cod if change.is_cod is None else bool(change.is_cod)
        add_shipping = (
            bool(payment.add_shipping_to_cod) if change.add_shipping_to_cod is None else bool(change.add_shipping_to_cod)
        )
        total_value = (
            to_money(payment.shipment_total_value)
            if change.shipment_total_value is None
            else to_money(change.shipment_total_value)
        )
        goods = _goods_value(payment, change, is_cod, total_value)
        is_carriers_risk = (
            bool(shipment.is_carriers_risk) if change.is_carriers_risk is None else bool(change.is_carriers_risk)
        )
        if change.is_rto is not None:
            is_rto = bool(change.is_rto)
        else:
            breakdown = payment.pricing_breakdown or {}
            is_rto = shipment.status in RTO_STATUSES or to_money(breakdown.get(RTO_SURCHARGE_KEY)) > ZERO_MONEY
        if change.waive_rto_charge:
            is_rto = False
        is_b2b = _is_b2b_after(shipment, change, is_carriers_risk)
        service_type = change.service_type or shipment.service_type
        service_option = (
            change.service_option
            or (
                _option_for_service_type(shipment.service_option, change.service_type)
                if change.service_type is not None
                else None
            )
            or shipment.service_option
            or (
                ServiceOption.PRIME_SURFACE
                if is_b2b
                else (
                    ServiceOption.DELHIVERY_EXPRESS
                    if service_type == ServiceType.AIR
                    else ServiceOption.DELHIVERY_SURFACE
                )
            )
        )
        return _Inputs(
            packages=packages,
            billing_basis=basis,
            service_type=service_type,
            service_option=service_option,
            pickup_pincode=change.pickup_pincode or _pincode(shipment.pickup_address),
            delivery_pincode=change.delivery_pincode or _pincode(shipment.delivery_address),
            is_cod=is_cod,
            goods=goods,
            shipment_total_value=total_value,
            add_shipping_to_cod=add_shipping,
            mode=mode,
            is_carriers_risk=is_carriers_risk,
            is_rto=is_rto,
            is_b2b=is_b2b,
            engine_is_cod=is_cod and not change.waive_cod_fee and shipment.status not in RTO_STATUSES,
        )

    async def _quote(
        self, inputs: _Inputs, shipment: PickupRequest, payment: PaymentDetails, tenant: Tenant
    ) -> PriceResult:
        """
        The new bill from QuoteService (DESIGN.md v4 D4): frozen booking terms, no carrier
        call unless a carrier input changed (drift-neutral pair), provisional RTO when needed.
        """
        record = payment.carrier_cost
        booked_inputs = (record or {}).get("inputs") or {}
        spec = ParcelSpec(
            pickup_pincode=inputs.pickup_pincode,
            delivery_pincode=inputs.delivery_pincode,
            packages=tuple(inputs.packages),
            shipment_type=shipment.shipment_type or ShipmentType.FORWARD,
            is_blind_pickup=inputs.billing_basis == self.BASIS_BLIND_FLOOR,
            estimated_box_count=shipment.estimated_box_count,
            door_delivery=bool(booked_inputs.get("door_delivery")),
            invoice_value=inputs.shipment_total_value,
            carriers_risk=inputs.is_carriers_risk,
        )
        sell = SellInputs(
            mode=inputs.mode,
            is_cod=inputs.is_cod,
            cod_goods=inputs.goods,
            add_shipping_to_cod=inputs.add_shipping_to_cod,
            include_rto=inputs.is_rto,
            charge_cod_fee=inputs.engine_is_cod,
        )
        request = RequoteRequest(option=inputs.service_option, spec=spec, sell=sell)
        return await QuoteService(self.session).requote(tenant, record, request)

    # --------------------------------------------------------------- writes

    async def _persist_measurement(
        self, shipment: PickupRequest, plan: _Plan
    ) -> Optional[ShipmentMeasurement]:
        """Deactivates the old measurement and inserts the new one (weights from the quote)."""
        draft = plan.measurement_draft
        if draft is None:
            return None
        breakdown = plan.quote.pricing_breakdown or {}
        draft.actual_weight_kg = to_weight(breakdown.get("total_actual_weight"))
        draft.volumetric_weight_kg = to_weight(breakdown.get("total_volumetric_weight"))
        draft.chargeable_weight_kg = to_weight(plan.quote.chargeable_weight)
        await self.repo.deactivate_measurements(shipment.id, shipment.tenant_id)
        saved = await self.repo.add_measurement(draft)
        plan.preview.new_breakdown[MEASUREMENT_ID_KEY] = str(saved.id)
        return saved

    @staticmethod
    def _write_shipment(
        shipment: PickupRequest, plan: _Plan, measurement: Optional[ShipmentMeasurement]
    ) -> None:
        """Writes the header price inputs and every price column of payment_details."""
        payment = shipment.payment_details
        for name, value in plan.header_writes.items():
            setattr(shipment, name, value)
        for name, value in plan.payment_writes.items():
            setattr(payment, name, value)
        payment.pricing_breakdown = dict(plan.preview.new_breakdown)

    async def _settle(
        self,
        shipment: PickupRequest,
        tenant: Tenant,
        plan: _Plan,
        change: RepriceChange,
    ) -> Tuple[Optional[WalletTransaction], Optional[Any]]:
        """
        Posts the planned wallet movements, each with a GST note of exactly its amount.

        Returns:
            (main wallet txn, main GST note): the last movement's rows, or (None, None).
        """
        if not plan.movements:
            return None, None
        wallet = await WalletRepository(self.session).get_or_create_wallet(
            user_id=shipment.created_by_user_id, tenant_id=tenant.id, for_update=True
        )
        notes_service = delhivery_modules_service.DelhiveryModulesService(
            delhivery_modules_repository.DelhiveryModulesRepository(self.session)
        )
        main_txn: Optional[WalletTransaction] = None
        main_note: Optional[Any] = None
        for movement in plan.movements:
            txn_type = movement.txn_type
            if txn_type in ONCE_PER_SHIPMENT_TXN_TYPES and await self.repo.has_wallet_txn_type(
                shipment.id, tenant.id, txn_type
            ):
                txn_type = WalletTxnType.SPEND
            main_txn = await self._post_wallet_txn(wallet, shipment, tenant, txn_type, movement.amount, plan, change)
            note_type = await self._note_type_for_movement(shipment, tenant, movement)
            main_note = await notes_service.record_shipment_billing_note(
                shipment=shipment,
                note_type=note_type.value,
                amount_override=money_to_float(abs(movement.amount)),
                is_b2b=plan.is_b2b,
            )
        return main_txn, main_note

    async def _note_type_for_movement(
        self, shipment: PickupRequest, tenant: Tenant, movement: _Movement
    ) -> InvoiceNoteType:
        """
        GST document for one wallet movement: CREDIT_NOTE for a refund, DEBIT_NOTE for a debit
        against the shipment's INVOICE. A debit on a shipment that has no INVOICE yet (a TO_PAY
        parcel billed to the merchant on RTO, plan C2) is invoiced, because a DEBIT_NOTE must
        quote an original invoice (CGST Rule 53).
        """
        if movement.amount <= 0:
            return InvoiceNoteType.CREDIT_NOTE
        if movement.txn_type in ONCE_PER_SHIPMENT_TXN_TYPES and not await self.repo.has_shipment_invoice(
            shipment.id, tenant.id
        ):
            return InvoiceNoteType.INVOICE
        return InvoiceNoteType.DEBIT_NOTE

    async def _post_wallet_txn(
        self,
        wallet: Any,
        shipment: PickupRequest,
        tenant: Tenant,
        txn_type: WalletTxnType,
        signed_amount: Decimal,
        plan: _Plan,
        change: RepriceChange,
    ) -> WalletTransaction:
        """Writes one wallet ledger row (debit when positive). Never blocked by balance (D18)."""
        amount = to_money(abs(signed_amount))
        opening = to_money(wallet.balance)
        closing = to_money(opening - amount) if signed_amount > 0 else to_money(opening + amount)
        wallet.balance = money_to_float(closing)
        wallet.updated_at = _utc_now_naive()
        self.session.add(wallet)
        txn_id = uuid.uuid4()
        txn = WalletTransaction(
            id=txn_id,
            wallet_id=wallet.id,
            tenant_id=tenant.id,
            user_id=shipment.created_by_user_id,
            shipment_id=shipment.id,
            tracking_id=shipment.tracking_id,
            txn_type=txn_type,
            service_category=WalletServiceCategory.B2B if plan.is_b2b else WalletServiceCategory.B2C,
            opening_balance=money_to_float(opening),
            amount=money_to_float(amount),
            closing_balance=money_to_float(closing),
            receipt_number=_receipt_number(txn_type, txn_id),
            status=WalletTxnStatus.COMPLETED,
            remarks=_wallet_remark(change, plan, shipment, signed_amount),
            created_at=_utc_now_naive(),
        )
        return await self.repo.add_wallet_txn(txn)

    async def _record_adjustment(
        self,
        shipment: PickupRequest,
        plan: _Plan,
        change: RepriceChange,
        actor: Optional[User],
        wallet_txn: Optional[WalletTransaction],
        note: Optional[Any],
        measurement: Optional[ShipmentMeasurement],
    ) -> Optional[ShipmentChargeAdjustment]:
        """Writes the audit row when anything changed."""
        preview = plan.preview
        if not preview.changed:
            return None
        adjustment = ShipmentChargeAdjustment(
            tenant_id=shipment.tenant_id,
            pickup_id=shipment.id,
            reason=change.reason,
            old_total=preview.old_total,
            new_total=preview.new_total,
            delta=to_money(preview.new_total - preview.old_total),
            old_chargeable_weight=preview.old_chargeable_weight,
            new_chargeable_weight=preview.new_chargeable_weight,
            freight_payment_mode=preview.freight_payment_mode,
            old_breakdown=preview.old_breakdown,
            new_breakdown=preview.new_breakdown,
            wallet_txn_id=wallet_txn.id if wallet_txn else None,
            billing_invoice_id=getattr(note, "id", None),
            actor_user_id=actor.id if actor else None,
            idempotency_key=change.idempotency_key,
        )
        return await self.repo.add_adjustment(adjustment)

    # -------------------------------------------------------------- helpers

    async def _resolve_pincode(
        self, payload: PickupUpdate, tenant_id: uuid.UUID, *, side: str
    ) -> Optional[str]:
        """Pincode of the new pickup/delivery address in a PATCH body (None when unchanged)."""
        new_address = getattr(payload, f"new_{side}_address")
        if new_address is not None:
            return new_address.pincode
        address_id = getattr(payload, f"{side}_address_id")
        if address_id is not None:
            return await self.repo.get_address_pincode(address_id, tenant_id)
        return None

    async def _result_from_adjustment(
        self, shipment: PickupRequest, adjustment: ShipmentChargeAdjustment
    ) -> RepriceResult:
        """Rebuilds the outcome of an already-applied idempotent change (no money moves)."""
        payment = shipment.payment_details
        wallet_delta = ZERO_MONEY
        note_type: Optional[str] = None
        if adjustment.wallet_txn_id is not None:
            txn = await self.session.get(WalletTransaction, adjustment.wallet_txn_id)
            if txn is not None:
                is_credit = wallet_txn_type(txn) in BILL_CREDIT_TYPES
                wallet_delta = to_money(txn.amount) if is_credit else to_money(-to_money(txn.amount))
                note_type = (InvoiceNoteType.CREDIT_NOTE if is_credit else InvoiceNoteType.DEBIT_NOTE).value
        note_number: Optional[str] = None
        if adjustment.billing_invoice_id is not None:
            note = await self.session.get(BillingInvoice, adjustment.billing_invoice_id)
            note_number = note.invoice_number if note is not None else None
        settlement = (
            SettlementKind.WALLET_REFUND if wallet_delta > 0
            else SettlementKind.WALLET_DEBIT if wallet_delta < 0
            else SettlementKind.NONE
        )
        new_breakdown = dict(adjustment.new_breakdown or {})
        return RepriceResult(
            shipment_id=shipment.id,
            reason=ChargeAdjustmentReason(adjustment.reason),
            old_total=to_money(adjustment.old_total),
            new_total=to_money(adjustment.new_total),
            delta=to_money(adjustment.delta),
            old_chargeable_weight=to_weight(adjustment.old_chargeable_weight),
            new_chargeable_weight=to_weight(adjustment.new_chargeable_weight),
            old_breakdown=dict(adjustment.old_breakdown or {}),
            new_breakdown=new_breakdown,
            freight_payment_mode=FreightPaymentMode(adjustment.freight_payment_mode),
            billing_channel=billing_channel_of(payment),
            settlement=settlement,
            wallet_delta=wallet_delta,
            note_type=note_type,
            old_cod_amount=to_money(payment.cod_amount) if payment else ZERO_MONEY,
            new_cod_amount=to_money(payment.cod_amount) if payment else ZERO_MONEY,
            old_freight_collectible=to_money(payment.freight_collectible) if payment else ZERO_MONEY,
            new_freight_collectible=to_money(payment.freight_collectible) if payment else ZERO_MONEY,
            collectible_frozen=bool(cod_payout.is_collectible_frozen(shipment)),
            changed=True,
            warnings=(),
            adjustment_id=adjustment.id,
            wallet_txn_id=adjustment.wallet_txn_id,
            billing_invoice_id=adjustment.billing_invoice_id,
            note_number=note_number,
            measurement_id=_uuid_or_none(new_breakdown.get(MEASUREMENT_ID_KEY)),
            replayed=True,
        )


def get_repricing_service(session: AsyncSession = Depends(get_session)) -> RepricingService:
    """FastAPI dependency factory (Spring: constructor injection of the session)."""
    return RepricingService(session)


# =============================================================================
# Private pure helpers
# =============================================================================


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sum_txn_type(txns: Iterable[WalletTransaction], txn_type: WalletTxnType) -> Decimal:
    """Σ amount of COMPLETED rows of one type."""
    return to_money(
        sum(
            (to_money(t.amount) for t in txns
             if wallet_txn_type(t) == txn_type and wallet_txn_status(t) == WalletTxnStatus.COMPLETED),
            ZERO_MONEY,
        )
    )


def _require_payment(shipment: PickupRequest) -> PaymentDetails:
    """Payment details or a 400."""
    payment = shipment.payment_details
    if payment is None:
        raise NotRepriceableError("This shipment has no payment details to re-price.")
    return payment


def _pincode(address: Any) -> str:
    """Pincode of a loaded address ('' when missing)."""
    return str(getattr(address, "pincode", "") or "")


def _optional_weight(value: Any) -> Optional[Decimal]:
    """to_weight() that keeps None."""
    return None if value is None else to_weight(value)


def _uuid_or_none(value: Any) -> Optional[uuid.UUID]:
    """Parses a UUID string, None when absent or invalid."""
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _clone_package(package: PackageCreate) -> PackageCreate:
    """A PackageCreate copy without any row id."""
    return PackageCreate(**package.model_dump(exclude={"id"}))


def _package_from_row(row: Any) -> PackageCreate:
    """A PackageCreate from a package_details row."""
    return PackageCreate(**{name: getattr(row, name) for name in PACKAGE_COMPARE_FIELDS + ("description", "is_fragile")})


def _package_json(package: PackageCreate) -> Dict[str, Any]:
    """JSONB form of a measured box."""
    return package.model_dump(mode="json", include=set(PACKAGE_COMPARE_FIELDS) | {"description", "is_fragile"})


def _weight_kg(package: PackageCreate) -> Decimal:
    """Per-box weight in kg."""
    weight = Decimal(str(package.weight))
    return weight / GRAMS_PER_KG if package.weight_unit == WeightUnit.G else weight


def _measurement_packages(measurement: MeasurementInput, declared: List[PackageCreate]) -> List[PackageCreate]:
    """
    The boxes a measurement bills on.

    Full measurement: its own boxes. Weight-only: the declared boxes with their
    weights scaled so the total actual weight equals the measured kg (keeps dims,
    volumetric and oversized); a probe box when nothing was declared (blind LR).

    Raises:
        InvalidMeasurementError: none or both inputs, non-positive weight, too many photos.
    """
    has_packages = bool(measurement.packages)
    has_weight = measurement.weight_only_kg is not None
    if has_packages == has_weight:
        raise InvalidMeasurementError("Send exactly one of packages or weight_only_kg.")
    if len(measurement.evidence_urls) > MAX_EVIDENCE_URLS:
        raise InvalidMeasurementError(f"At most {MAX_EVIDENCE_URLS} photos per measurement.")
    if has_packages:
        return [_clone_package(p) for p in measurement.packages]
    target_kg = to_weight(measurement.weight_only_kg)
    if target_kg <= 0:
        raise InvalidMeasurementError("Measured weight must be greater than 0 kg.")
    declared_kg = sum((_weight_kg(p) * p.box_count for p in declared), Decimal("0"))
    if not declared or declared_kg <= 0:
        return [
            PackageCreate(
                length=WEIGHT_PROBE_CM, breadth=WEIGHT_PROBE_CM, height=WEIGHT_PROBE_CM,
                weight=float(target_kg), weight_unit=WeightUnit.KG, box_count=1,
            )
        ]
    factor = target_kg / declared_kg
    scaled = []
    for package in declared:
        data = package.model_dump(exclude={"id"})
        data["weight"] = float(to_weight(_weight_kg(package) * factor))
        data["weight_unit"] = WeightUnit.KG
        scaled.append(PackageCreate(**data))
    return scaled


def _goods_value(
    payment: PaymentDetails,
    change: RepriceChange,
    is_cod: bool,
    total_value: Decimal,
) -> Decimal:
    """
    The goods part of the COD collectible: the COD-fee base (fixes the R1 drift).

    An explicit `change.cod_amount` sets the revised goods base (even when
    `add_shipping_to_cod` is True, e.g. Partial Delivery or Payment Dispute). Otherwise it
    is the stored goods part (computed BEFORE the total moves): A-01, the goods COD the
    seller typed is kept even with `add_shipping_to_cod` (never replaced by the declared
    value). Switching a prepaid shipment to COD without an amount uses the declared value.
    """
    if not is_cod:
        return ZERO_MONEY
    if change.cod_amount is not None:
        return to_money(change.cod_amount)
    if change.is_cod and not payment.is_cod:
        return total_value
    return to_money(cod_payout.cod_goods_amount(payment))


def _touches_cod(change: RepriceChange, payment: PaymentDetails) -> bool:
    """True when the change edits a COD field to a different value."""
    return bool(
        (change.is_cod is not None and bool(change.is_cod) != bool(payment.is_cod))
        or (change.cod_amount is not None and to_money(change.cod_amount) != to_money(payment.cod_amount))
        or (change.add_shipping_to_cod is not None
            and bool(change.add_shipping_to_cod) != bool(payment.add_shipping_to_cod))
    )


def _is_b2b_after(shipment: PickupRequest, change: RepriceChange, is_carriers_risk: bool) -> bool:
    """B2B class after the change, without mutating the shipment."""
    overrides = dict(change.header_overrides or {})
    view = SimpleNamespace(**{name: overrides.get(name, getattr(shipment, name)) for name in B2B_MARKER_FIELDS})
    view.is_carriers_risk = is_carriers_risk
    return is_b2b_shipment(view)  # type: ignore[arg-type]


def _has_direct_price_adjustment(change: RepriceChange) -> bool:
    """True when `change` specifies an explicit `override_total_price` or `extra_charge`."""
    if change.override_total_price is not None or change.extra_charge is not None:
        return True
    if change.measurement is not None and change.measurement.override_total_price is not None:
        return True
    return False


def _stored_payment_as_quote(
    payment: PaymentDetails, packages: Sequence[PackageCreate]
) -> PriceResult:
    """
    Builds a synthetic `PriceResult` from the already-persisted `PaymentDetails` when an
    admin price override or extra charge is applied to a legacy/seeded shipment that has
    no stored `carrier_cost.forward` record (avoiding an external carrier network call).
    """
    breakdown = dict(payment.pricing_breakdown or {})
    prior_adj = sum(
        (
            to_money(a.get("amount"))
            for a in (breakdown.get(BILL_ADJUSTMENTS_KEY) or [])
            if isinstance(a, dict)
        ),
        ZERO_MONEY,
    )
    stored_total = to_money(payment.total_logistics_cost)
    engine_total = max(Decimal("0.01"), to_money(stored_total - prior_adj))
    actual_kg = (
        weights.total_actual_kg(packages)
        if packages
        else to_weight(breakdown.get("total_actual_weight") or payment.chargeable_weight or 1)
    )
    vol_kg = (
        weights.volumetric_kg(packages, weights.DELHIVERY_VOLUMETRIC_DIVISOR)
        if packages
        else to_weight(breakdown.get("total_volumetric_weight") or 0)
    )
    chg_kg = max(actual_kg, vol_kg, to_weight(payment.chargeable_weight or Decimal("0.5")))
    breakdown["total_actual_weight"] = float(actual_kg)
    breakdown["volumetric_weight"] = float(vol_kg)
    breakdown["total_volumetric_weight"] = float(vol_kg)
    breakdown["raw_chargeable_weight"] = float(chg_kg)
    breakdown["chargeable_weight"] = float(chg_kg)
    return PriceResult(
        serviceable=True,
        error_message=None,
        total_amount=money_to_float(engine_total),
        base_charge=money_to_float(to_money(payment.base_freight)),
        tax_amount=money_to_float(to_money(payment.tax_amount)),
        chargeable_weight=float(chg_kg),
        pricing_breakdown=breakdown,
        carrier_cost=dict(payment.carrier_cost) if payment.carrier_cost else None,
        estimated_days=0,
    )


def _assert_quote_bookable(quote: PriceResult, change: RepriceChange) -> None:
    """H-7: refuse an unserviceable or ₹0 quote; report the most likely field."""
    if quote.serviceable and to_money(quote.total_amount) > ZERO_MONEY:
        return
    if change.delivery_pincode or change.pickup_pincode:
        field_name = "delivery_pincode" if change.delivery_pincode else "pickup_pincode"
    elif change.service_type is not None or change.service_option is not None:
        field_name = "service_option" if change.service_option is not None else "service_type"
    elif change.packages is not None or change.measurement is not None:
        field_name = "packages"
    else:
        field_name = None
    raise ZeroQuoteError(
        quote.error_message or "This change would price the shipment at ₹0; the old price is kept.",
        field=field_name,
    )


def _channel_after_change(
    old_channel: BillingChannel,
    old_mode: FreightPaymentMode,
    new_mode: FreightPaymentMode,
    actor: Optional[User],
) -> BillingChannel:
    """The billing channel after a freight-mode change (unchanged when the mode is unchanged)."""
    if new_mode == old_mode:
        return old_channel
    return billing_channel_for_booking(new_mode, booked_by_staff=actor is not None and is_tenant_staff(actor))


def _merchant_pays_returned_to_pay(
    shipment: PickupRequest, inputs: "_Inputs", channel: BillingChannel
) -> bool:
    """
    True for a TO_PAY shipment (not wallet-billed) whose RTO leg is billed: the consignee
    refused it, so the merchant owes the full bill (plan C2). A waived RTO (Logismart liable,
    B6) is not billed to the merchant.
    """
    return (
        channel != BillingChannel.WALLET
        and inputs.mode == FreightPaymentMode.TO_PAY
        and inputs.is_rto
        and shipment.status in RTO_STATUSES
    )


def _plan_movements(
    *,
    reason: ChargeAdjustmentReason,
    channel: BillingChannel,
    new_total: Decimal,
    paid_towards_bill: Decimal,
    merchant_paid_after: Decimal,
    extra: Optional[ExtraBillCharge],
) -> List[_Movement]:
    """
    Wallet movements that bring "net paid towards the bill" to its target.

    Target: the new bill for WALLET shipments; otherwise only what the merchant chose
    to pay through Freight Collection. Refunds never exceed what was paid (H-1).
    """
    target = new_total if channel == BillingChannel.WALLET else merchant_paid_after
    movements: List[_Movement] = []
    remaining = to_money(target - paid_towards_bill)
    if extra is not None:
        extra_amount = to_money(extra.amount)
        movements.append(_Movement(extra.txn_type, extra_amount))
        remaining = to_money(remaining - extra_amount)
    if is_billable_delta(remaining):
        if remaining > 0:
            movements.append(_Movement(UPWARD_TXN_BY_REASON.get(reason, WalletTxnType.SPEND), remaining))
        else:
            paid_after = paid_towards_bill + sum((m.amount for m in movements), ZERO_MONEY)
            refund = min(abs(remaining), max(paid_after, ZERO_MONEY))
            if is_billable_delta(refund):
                movements.append(_Movement(WalletTxnType.REFUND, to_money(-refund)))
    return movements


def _payment_writes(
    payment: PaymentDetails,
    inputs: _Inputs,
    quote: PriceResult,
    new_total: Decimal,
    new_breakdown: Dict[str, Any],
    new_cod: Decimal,
    new_fc: Decimal,
    frozen: bool,
) -> Dict[str, Any]:
    """Every payment_details column apply() writes."""
    adjustments = new_breakdown.get(BILL_ADJUSTMENTS_KEY) or []
    has_price_override = any(
        isinstance(a, dict) and a.get("kind") == "ADMIN_PRICE_OVERRIDE"
        for a in adjustments
    )
    if has_price_override:
        taxable = to_money(new_total / Decimal("1.18"))
        gst = to_money(new_total - taxable)
        base_freight_val = money_to_float(taxable)
        tax_amount_val = money_to_float(gst)
    else:
        base_freight_val = float(quote.base_charge)
        tax_amount_val = float(quote.tax_amount)
    writes: Dict[str, Any] = {
        "freight_payment_mode": inputs.mode,
        "is_cod": inputs.is_cod,
        "add_shipping_to_cod": inputs.add_shipping_to_cod,
        "shipment_total_value": money_to_float(inputs.shipment_total_value),
        "base_freight": base_freight_val,
        "tax_amount": tax_amount_val,
        "total_logistics_cost": money_to_float(new_total),
        "chargeable_weight": float(quote.chargeable_weight),
    }
    if quote.carrier_cost is not None:
        writes["carrier_cost"] = quote.carrier_cost
    if not frozen:
        writes["cod_amount"] = money_to_float(new_cod)
        writes["freight_collectible"] = new_fc
    return writes


def _option_for_service_type(
    current_option: Optional[ServiceOption], service_type: ServiceType
) -> ServiceOption:
    """Implied ServiceOption when a legacy caller changes `service_type` (B2B options never change)."""
    if current_option is not None and flow_of_option(current_option) == ServiceFlow.B2B:
        return current_option
    if service_type == ServiceType.AIR:
        return ServiceOption.DELHIVERY_EXPRESS
    return ServiceOption.DELHIVERY_SURFACE


def _assert_same_flow(
    old_option: Optional[ServiceOption], new_option: ServiceOption
) -> None:
    """Refuses switching a shipment between B2C and B2B service options."""
    if old_option is not None and flow_of_option(old_option) != flow_of_option(new_option):
        raise EditNotAllowedError(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot switch from {old_option.value} to {new_option.value}.",
            rule=RULE_STATE,
            field="service_option",
        )


def _header_writes(shipment: PickupRequest, change: RepriceChange) -> Dict[str, Any]:
    """Shipment header columns that are price inputs (service option/type, carrier's risk)."""
    writes: Dict[str, Any] = {}
    if change.service_type is not None:
        writes["service_type"] = change.service_type
    if change.service_option is not None:
        writes["service_option"] = change.service_option
        writes["service_type"] = OPTION_SERVICE_TYPES[change.service_option]
    if change.is_carriers_risk is not None:
        writes["is_carriers_risk"] = bool(change.is_carriers_risk)
    return writes


def _has_real_writes(target: Any, writes: Mapping[str, Any], names: Sequence[str]) -> bool:
    """True when any listed write differs from the current value."""
    for name in names:
        if name not in writes:
            continue
        current, new = getattr(target, name, None), writes[name]
        if isinstance(new, (int, float, Decimal)) and not isinstance(new, bool):
            if to_money(current) != to_money(new):
                return True
        elif current != new:
            return True
    return False


def _settlement_kind(
    channel: BillingChannel,
    mode: FreightPaymentMode,
    wallet_net: Decimal,
    old_fc: Decimal,
    new_fc: Decimal,
    old_total: Decimal,
    new_total: Decimal,
) -> SettlementKind:
    """Classifies the settlement for the UI."""
    if wallet_net > 0:
        return SettlementKind.WALLET_DEBIT
    if wallet_net < 0:
        return SettlementKind.WALLET_REFUND
    if old_fc != new_fc:
        return SettlementKind.COLLECTIBLE_CHANGE
    if channel == BillingChannel.NONE and mode == FreightPaymentMode.POSTPAID and old_total != new_total:
        return SettlementKind.RECORD_ONLY
    return SettlementKind.NONE


def _note_type_for(wallet_net: Decimal) -> Optional[str]:
    """DEBIT_NOTE for a net debit, CREDIT_NOTE for a net refund."""
    if wallet_net > 0:
        return InvoiceNoteType.DEBIT_NOTE.value
    if wallet_net < 0:
        return InvoiceNoteType.CREDIT_NOTE.value
    return None


def _receipt_number(txn_type: WalletTxnType, txn_id: uuid.UUID) -> str:
    """`<PFX>-<FY>-<8 hex>` wallet receipt number, FY label instead of a hard-coded year."""
    prefix = RECEIPT_PREFIX_BY_TXN.get(txn_type, DEFAULT_RECEIPT_PREFIX)
    fy = delhivery_modules_service.indian_financial_year_label(datetime.now(IST).date())
    return f"{prefix}-{fy}-{str(txn_id)[:8].upper()}"


def _fmt_weight_kg(weight: Decimal) -> str:
    """Formats weight in kg with at least 1 decimal place (e.g. 18.0, 24.0, 18.25)."""
    w = to_weight(weight)
    if w == w.quantize(Decimal("0.1")):
        return f"{w:.1f}"
    return str(w.normalize())


def _wallet_remark(
    change: RepriceChange, plan: _Plan, shipment: PickupRequest, signed_amount: Decimal
) -> str:
    """Passbook narration, e.g. "Charged weight 18.0 kg → 24.0 kg (4 boxes) at pickup for LOGI-1"."""
    preview = plan.preview
    awb = shipment.tracking_id or str(shipment.id)[:8].upper()
    old_w = _fmt_weight_kg(preview.old_chargeable_weight)
    new_w = _fmt_weight_kg(preview.new_chargeable_weight)
    if change.reason == ChargeAdjustmentReason.PICKUP_MEASUREMENT:
        boxes = (
            plan.measurement_draft.total_boxes
            if plan.measurement_draft is not None
            else max(1, sum(int(p.box_count) for p in (shipment.packages or [])))
        )
        return f"Charged weight {old_w} kg → {new_w} kg ({boxes} boxes) at pickup for {awb}"[:500]
    if change.reason == ChargeAdjustmentReason.HUB_MEASUREMENT:
        return f"Charged weight {old_w} kg → {new_w} kg at hub for {awb}"[:500]
    if change.remark:
        return change.remark[:500]
    direction = "deducted" if signed_amount > 0 else "refunded"
    if preview.old_chargeable_weight != preview.new_chargeable_weight:
        return (
            f"Charged weight {old_w} kg → {new_w} kg ({change.reason.value}): "
            f"freight {direction} for {awb}"
        )[:500]
    return f"Freight {direction} on {change.reason.value} for {awb}"[:500]


def _scalar_differs(current: Any, new: Any) -> bool:
    """True when `new` differs from `current` (treating empty string and None as equal)."""
    if isinstance(new, bool) or isinstance(current, bool):
        return bool(current) != bool(new)
    return (current or None) != (new or None)


def _packages_edit_present(
    payload: PickupUpdate, data: Mapping[str, Any], shipment: Optional[PickupRequest]
) -> bool:
    """True when the PATCH body edits packages, blind-pickup flag, or estimated box count."""
    if shipment is None:
        return any(key in data for key in ("packages", "is_blind_pickup", "estimated_box_count"))
    if _changed_packages(shipment, payload) is not None:
        return True
    if (
        "is_blind_pickup" in data
        and data["is_blind_pickup"] is not None
        and bool(data["is_blind_pickup"]) != bool(getattr(shipment, "is_blind_pickup", False))
    ):
        return True
    if "estimated_box_count" in data and _scalar_differs(
        getattr(shipment, "estimated_box_count", None), data["estimated_box_count"]
    ):
        return True
    return False


def _payment_edit_fields(
    payload: PickupUpdate, payment: Optional[PaymentDetails] = None
) -> FrozenSet[EditField]:
    """EditField groups touched inside payment_details (filtered against stored payment when provided)."""
    incoming = payload.payment_details
    if incoming is None:
        return frozenset()
    set_fields = incoming.model_fields_set
    if payment is None:
        fields = set()
        if set_fields & {"is_cod", "cod_amount", "add_shipping_to_cod"}:
            fields.add(EditField.COD)
        if "freight_payment_mode" in set_fields:
            fields.add(EditField.PAYMENT_MODE)
        if set_fields & {"shipment_value", "shipment_tax_value", "shipment_total_value"}:
            fields.add(EditField.DECLARED_VALUE)
        if set_fields - {
            "is_cod", "cod_amount", "add_shipping_to_cod", "freight_payment_mode",
            "shipment_value", "shipment_tax_value", "shipment_total_value",
        }:
            fields.add(EditField.OTHER)
        return frozenset(fields)

    changed = _changed_payment_fields(payload, payment)
    fields = set()
    if any(k in changed for k in ("is_cod", "cod_amount", "add_shipping_to_cod")):
        fields.add(EditField.COD)
    if "freight_payment_mode" in changed:
        fields.add(EditField.PAYMENT_MODE)
    if "shipment_total_value" in changed or (
        "shipment_total_value" not in set_fields
        and any(
            name in set_fields
            and getattr(incoming, name) is not None
            and to_money(getattr(incoming, name)) != to_money(getattr(payment, name, 0))
            for name in ("shipment_value", "shipment_tax_value")
        )
    ):
        fields.add(EditField.DECLARED_VALUE)
    other_keys = set_fields - {
        "is_cod", "cod_amount", "add_shipping_to_cod", "freight_payment_mode",
        "shipment_value", "shipment_tax_value", "shipment_total_value",
    }
    if any(_scalar_differs(getattr(payment, name, None), getattr(incoming, name, None)) for name in other_keys):
        fields.add(EditField.OTHER)
    return frozenset(fields)


CONTACT_FIELDS: Sequence[str] = ("name", "phone", "alternate_phone", "email", "company_name")
"""Address fields that are "contact" rather than "address" (editable until terminal)."""


def _address_edit_fields(payload: PickupUpdate, shipment: Optional[PickupRequest]) -> FrozenSet[EditField]:
    """CONSIGNEE_CONTACT / CONSIGNEE_ADDRESS / PICKUP_ADDRESS from the address parts of a PATCH."""
    is_reverse = shipment is not None and shipment.shipment_type == ShipmentType.REVERSE
    consignee_side, merchant_side = ("pickup", "delivery") if is_reverse else ("delivery", "pickup")
    fields = set()
    if getattr(payload, f"{merchant_side}_address_id") is not None or getattr(payload, f"new_{merchant_side}_address") is not None:
        fields.add(EditField.PICKUP_ADDRESS)
    if getattr(payload, f"{consignee_side}_address_id") is not None:
        fields.add(EditField.CONSIGNEE_ADDRESS)
    new_consignee = getattr(payload, f"new_{consignee_side}_address")
    if new_consignee is not None:
        current = getattr(shipment, f"{consignee_side}_address", None) if shipment is not None else None
        fields.add(_consignee_edit_kind(new_consignee, current))
    return frozenset(fields)


def _consignee_edit_kind(new_address: Any, current: Any) -> EditField:
    """CONSIGNEE_CONTACT when only contact fields differ from the current address."""
    if current is None:
        return EditField.CONSIGNEE_ADDRESS
    data = new_address.model_dump()
    for name, value in data.items():
        if name in CONTACT_FIELDS or name in ("is_saved", "scope", "category"):
            continue
        if hasattr(current, name) and (getattr(current, name) or None) != (value or None):
            return EditField.CONSIGNEE_ADDRESS
    return EditField.CONSIGNEE_CONTACT


CUSTOMER_IN_TRANSIT_FIELDS: FrozenSet[EditField] = frozenset(
    {EditField.COD, EditField.CONSIGNEE_ADDRESS, EditField.CONSIGNEE_CONTACT, EditField.OTHER}
)
CUSTOMER_ANYTIME_FIELDS: FrozenSet[EditField] = frozenset({EditField.CONSIGNEE_CONTACT})


def _assert_customer_window(shipment: PickupRequest, requested: FrozenSet[EditField]) -> None:
    """The DO1 `update-forward-order` matrix for customers (B9, H-12)."""
    current = shipment.status
    ready_to_ship = current in READY_TO_SHIP_STATUSES and shipment.manifest_id is None
    if ready_to_ship:
        return
    allowed = CUSTOMER_IN_TRANSIT_FIELDS if current in CONSIGNEE_EDIT_STATUSES else CUSTOMER_ANYTIME_FIELDS
    refused = sorted(f.value for f in requested - allowed)
    if not refused:
        return
    if current in PRE_PICKUP_STATUSES:
        detail = (
            "Boxes, payment mode, declared value and pickup address can only be changed while the "
            "order is Ready to ship (not yet in a pickup request)."
        )
        rule = RULE_CUSTOMER_FIELD
    else:
        detail = (
            f"In status {current.value} you can change only "
            + ", ".join(sorted(f.value for f in allowed)) + "."
        )
        rule = RULE_STATUS_WINDOW
    raise EditNotAllowedError(status.HTTP_400_BAD_REQUEST, detail, rule=rule, field=refused[0])


def _changed_packages(shipment: PickupRequest, payload: PickupUpdate) -> Optional[List[PackageCreate]]:
    """New declared boxes when the PATCH really changes them, else None."""
    if payload.packages is None:
        return None
    new = [PackageCreate(**p.model_dump(exclude={"id"})) for p in payload.packages]
    current = [_package_from_row(p) for p in (shipment.packages or [])]
    if _package_signature(new) == _package_signature(current):
        return None
    return new


def _package_signature(packages: Sequence[PackageCreate]) -> List[Sequence[Any]]:
    """Comparable, order-sensitive tuple list of the priced box fields."""
    return [
        tuple(
            to_weight(getattr(p, name)) if name in ("length", "breadth", "height", "weight") else getattr(p, name)
            for name in PACKAGE_COMPARE_FIELDS
        )
        for p in packages
    ]


def _changed_payment_fields(
    payload: PickupUpdate, payment: Optional[PaymentDetails]
) -> Dict[str, Any]:
    """RepriceChange kwargs for payment fields that really change."""
    incoming = payload.payment_details
    if incoming is None:
        return {}
    set_fields = incoming.model_fields_set
    changes: Dict[str, Any] = {}

    def _differs(name: str, value: Any) -> bool:
        current = getattr(payment, name, None) if payment is not None else None
        if isinstance(value, bool) or value is None or not isinstance(value, (int, float, Decimal)):
            return current != value
        return to_money(current) != to_money(value)

    for name in ("is_cod", "add_shipping_to_cod", "freight_payment_mode"):
        if name in set_fields and _differs(name, getattr(incoming, name)):
            changes[name] = getattr(incoming, name)
    if "shipment_total_value" in set_fields and _differs("shipment_total_value", incoming.shipment_total_value):
        changes["shipment_total_value"] = to_money(incoming.shipment_total_value)
    if "cod_amount" in set_fields:
        goods_now = to_money(cod_payout.cod_goods_amount(payment)) if payment is not None else ZERO_MONEY
        if to_money(incoming.cod_amount) != goods_now and _differs("cod_amount", incoming.cod_amount):
            changes["cod_amount"] = to_money(incoming.cod_amount)
    return changes


def _preview_fields(preview: RepricePreview) -> Dict[str, Any]:
    """The RepricePreview fields as kwargs (to build a RepriceResult)."""
    return {name: getattr(preview, name) for name in RepricePreview.__dataclass_fields__}


__all__ = [
    "BILL_CREDIT_TYPES",
    "BILL_DEBIT_TYPES",
    "BILLING_CHANNEL_KEY",
    "ChargeAdjustmentView",
    "CollectibleFrozenError",
    "EditField",
    "EditNotAllowedError",
    "ExtraBillCharge",
    "InvalidMeasurementError",
    "MeasurementInput",
    "NotRepriceableError",
    "OUTSIDE_BILL_TYPES",
    "RepriceChange",
    "RepricePreview",
    "RepriceResult",
    "RepricingError",
    "RepricingService",
    "SEPARATE_CHARGE_TYPES",
    "ServiceTypeLockedError",
    "SettlementKind",
    "ZeroQuoteError",
    "assert_edit_allowed",
    "billing_channel_for_booking",
    "billing_channel_of",
    "edit_fields_from_update",
    "get_repricing_service",
    "is_wallet_billed",
    "net_debited",
    "stamp_billing_channel",
]
