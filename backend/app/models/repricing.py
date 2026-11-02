"""
Phase B (re-pricing on change) tables: charge adjustments, measurements and idempotency keys.

Each class maps a table created by an approved migration, column for column:
- `shipment_charge_adjustments` (M-B1, 3f9a1c2b7d01): append-only audit row per price change.
- `shipment_measurements` (M-B2, 4a2b8c3d9e02): the measured parcel that becomes the billing basis.
- `idempotency_keys` (M-B4, 6c4dae5fb004): one stored response per tenant + user + endpoint + key.

Status-like columns are VARCHAR + CHECK in the database and are backed here by Python
`str, Enum` classes (AGENTS §8): code always compares enum members, never raw strings.

Spring analogy: three `@Entity` classes with `@Enumerated(EnumType.STRING)` columns and
`@ManyToOne` foreign keys declared as plain UUID columns.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, FrozenSet, Iterable, List, Mapping, Optional, Union

import sqlalchemy as sa
from sqlalchemy import Column
from sqlalchemy import Enum as sa_Enum
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel

from app.core.money import ZERO_MONEY, to_money
from app.models.pickups import FreightPaymentMode, PaymentDetails, PickupRequest
from app.models.wallet import WalletTransaction, WalletTxnStatus, WalletTxnType

MONEY_PRECISION = 12
MONEY_SCALE = 2
WEIGHT_PRECISION = 10
WEIGHT_SCALE = 3
REASON_MAX_LENGTH = 32
SOURCE_MAX_LENGTH = 16
IDEMPOTENCY_KEY_MAX_LENGTH = 128
ENDPOINT_MAX_LENGTH = 128
REQUEST_HASH_LENGTH = 64
REMARK_MAX_LENGTH = 255


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (TIMESTAMP WITHOUT TIME ZONE columns)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _money_column(nullable: bool = False) -> Column:
    """A NUMERIC(12,2) money column."""
    return Column(sa.Numeric(MONEY_PRECISION, MONEY_SCALE), nullable=nullable)


def _weight_column(nullable: bool, server_default: Optional[str] = None) -> Column:
    """A NUMERIC(10,3) weight column in kilograms."""
    return Column(
        sa.Numeric(WEIGHT_PRECISION, WEIGHT_SCALE),
        nullable=nullable,
        server_default=sa.text(server_default) if server_default is not None else None,
    )


def _fk_column(target: str, *, nullable: bool, ondelete: str, index: bool = False) -> Column:
    """A UUID foreign-key column."""
    return Column(sa.Uuid, sa.ForeignKey(target, ondelete=ondelete), nullable=nullable, index=index)


class ChargeAdjustmentReason(str, Enum):
    """
    Why a shipment's bill changed. Mirrors the CHECK constraint of M-B1 exactly.
    Spring equivalent: an `@Enumerated(EnumType.STRING)` column.
    """

    CUSTOMER_EDIT = "CUSTOMER_EDIT"
    ADMIN_EDIT = "ADMIN_EDIT"
    PICKUP_MEASUREMENT = "PICKUP_MEASUREMENT"
    HUB_MEASUREMENT = "HUB_MEASUREMENT"
    MANUAL_WEIGHT_CHARGE = "MANUAL_WEIGHT_CHARGE"
    CLAIM_ACCEPTED = "CLAIM_ACCEPTED"
    PAYMENT_MODE_CHANGE = "PAYMENT_MODE_CHANGE"
    COD_CHANGE = "COD_CHANGE"
    SHORT_SHIPMENT = "SHORT_SHIPMENT"
    FREIGHT_COLLECTION = "FREIGHT_COLLECTION"
    EXCEPTION_CHARGE = "EXCEPTION_CHARGE"
    RTO = "RTO"
    COD_FEE_REVERSAL = "COD_FEE_REVERSAL"
    CANCELLATION = "CANCELLATION"
    PICKUP_REJECTION_REFUND = "PICKUP_REJECTION_REFUND"
    LOST = "LOST"
    LOST_FOUND = "LOST_FOUND"


class MeasurementSource(str, Enum):
    """Who measured the parcel. Mirrors the CHECK constraint of M-B2."""

    PICKUP = "PICKUP"
    HUB = "HUB"
    ADMIN = "ADMIN"
    CLAIM = "CLAIM"
    CARRIER = "CARRIER"
    """The carrier's own charged weight, pasted by ops from one.delhivery.com (M-P1)."""


class BillingChannel(str, Enum):
    """
    How a shipment's freight is settled, fixed once at booking and stored in
    `payment_details.pricing_breakdown["billing_channel"]` (JSONB, no column).
    WALLET = PREPAID or customer-booked POSTPAID; NONE = TO_PAY or staff-booked POSTPAID.
    """

    WALLET = "WALLET"
    NONE = "NONE"


class ShipmentChargeAdjustment(SQLModel, table=True):
    """
    One row per price change of a shipment (M-B1). Append-only.
    The DB CHECK enforces `delta = new_total - old_total` and non-negative totals.
    """

    __tablename__ = "shipment_charge_adjustments"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=_fk_column("tenant.id", nullable=False, ondelete="CASCADE", index=True)
    )
    pickup_id: uuid.UUID = Field(
        sa_column=_fk_column("pickups.id", nullable=False, ondelete="CASCADE")
    )
    reason: ChargeAdjustmentReason = Field(
        sa_column=Column(sa.String(REASON_MAX_LENGTH), nullable=False)
    )
    old_total: Decimal = Field(sa_column=_money_column())
    new_total: Decimal = Field(sa_column=_money_column())
    delta: Decimal = Field(sa_column=_money_column())
    old_chargeable_weight: Optional[Decimal] = Field(
        default=None, sa_column=_weight_column(nullable=True)
    )
    new_chargeable_weight: Optional[Decimal] = Field(
        default=None, sa_column=_weight_column(nullable=True)
    )
    freight_payment_mode: FreightPaymentMode = Field(
        sa_column=Column(
            sa_Enum(FreightPaymentMode, name="freightpaymentmode", create_type=False),
            nullable=False,
        )
    )
    old_breakdown: Optional[dict] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    new_breakdown: Optional[dict] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    wallet_txn_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=_fk_column("wallet_transactions.id", nullable=True, ondelete="SET NULL", index=True),
    )
    billing_invoice_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=_fk_column("billing_invoices.id", nullable=True, ondelete="SET NULL", index=True),
    )
    actor_user_id: Optional[uuid.UUID] = Field(
        default=None, sa_column=_fk_column("user.id", nullable=True, ondelete="SET NULL")
    )
    idempotency_key: Optional[str] = Field(
        default=None, sa_column=Column(sa.String(IDEMPOTENCY_KEY_MAX_LENGTH), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=_utc_now_naive,
        sa_column=Column(sa.DateTime, nullable=False, server_default=sa.text("now()")),
    )


class ShipmentMeasurement(SQLModel, table=True):
    """
    A measured parcel (rider at pickup, hub scale, admin or accepted claim) (M-B2).
    At most one row per shipment is active (partial unique index); the active row is
    the billing basis, so a later declared-box edit cannot undo it.
    `packages` holds a list of {length, breadth, height, dimension_unit, weight, weight_unit, box_count}.
    """

    __tablename__ = "shipment_measurements"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=_fk_column("tenant.id", nullable=False, ondelete="CASCADE", index=True)
    )
    pickup_id: uuid.UUID = Field(
        sa_column=_fk_column("pickups.id", nullable=False, ondelete="CASCADE")
    )
    source: MeasurementSource = Field(
        sa_column=Column(sa.String(SOURCE_MAX_LENGTH), nullable=False)
    )
    packages: List[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    total_boxes: int = Field(sa_column=Column(sa.Integer, nullable=False))
    actual_weight_kg: Decimal = Field(sa_column=_weight_column(nullable=False))
    volumetric_weight_kg: Decimal = Field(
        default=Decimal("0"), sa_column=_weight_column(nullable=False, server_default="0")
    )
    chargeable_weight_kg: Decimal = Field(sa_column=_weight_column(nullable=False))
    evidence_urls: List[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    remark: Optional[str] = Field(
        default=None, sa_column=Column(sa.String(REMARK_MAX_LENGTH), nullable=True)
    )
    is_active: bool = Field(
        default=True, sa_column=Column(sa.Boolean, nullable=False, server_default=sa.text("true"))
    )
    measured_by_user_id: Optional[uuid.UUID] = Field(
        default=None, sa_column=_fk_column("user.id", nullable=True, ondelete="SET NULL")
    )
    measured_at: datetime = Field(
        default_factory=_utc_now_naive,
        sa_column=Column(sa.DateTime, nullable=False, server_default=sa.text("now()")),
    )


class IdempotencyKey(SQLModel, table=True):
    """
    One claimed / completed money request (M-B4, H-4).
    Unique (tenant_id, user_id, endpoint, key); `response` is NULL while the request is in flight.
    """

    __tablename__ = "idempotency_keys"  # type: ignore
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", "user_id", "endpoint", "key", name="uq_idempotency_keys_scope"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=_fk_column("tenant.id", nullable=False, ondelete="CASCADE", index=True)
    )
    user_id: uuid.UUID = Field(
        sa_column=_fk_column("user.id", nullable=False, ondelete="CASCADE")
    )
    endpoint: str = Field(sa_column=Column(sa.String(ENDPOINT_MAX_LENGTH), nullable=False))
    key: str = Field(sa_column=Column(sa.String(IDEMPOTENCY_KEY_MAX_LENGTH), nullable=False))
    request_hash: str = Field(sa_column=Column(sa.String(REQUEST_HASH_LENGTH), nullable=False))
    response: Optional[dict] = Field(default=None, sa_column=Column(JSONB, nullable=True))
    created_at: datetime = Field(
        default_factory=_utc_now_naive,
        sa_column=Column(sa.DateTime, nullable=False, server_default=sa.text("now()"), index=True),
    )


# =============================================================================
# Money definitions (plan §2.0 "What the bill is"): the single source of truth.
# They live in the model layer (they depend only on models) so wallet, booking,
# GST and integrity code can import them without an import cycle; they are
# re-exported unchanged by `app.services.repricing`.
# =============================================================================

BILL_DEBIT_TYPES: FrozenSet[WalletTxnType] = frozenset(
    {
        WalletTxnType.SPEND,
        WalletTxnType.WEIGHT_AUDIT_DEBIT,
        WalletTxnType.RTO_FREIGHT,
        WalletTxnType.FREIGHT_COLLECTION,
    }
)
"""Wallet debits that pay the bill (forward freight + RTO leg)."""

BILL_CREDIT_TYPES: FrozenSet[WalletTxnType] = frozenset({WalletTxnType.REFUND})
"""Wallet credits that reduce what was paid towards the bill."""

SEPARATE_CHARGE_TYPES: FrozenSet[WalletTxnType] = frozenset(
    {WalletTxnType.ADDITIONAL_CHARGE, WalletTxnType.CHARGE_REVERSAL}
)
"""Charges outside the bill: own DEBIT_NOTE, never refunded by a cancellation."""

OUTSIDE_BILL_TYPES: FrozenSet[WalletTxnType] = frozenset(
    {WalletTxnType.RECHARGE, WalletTxnType.COD_SETTLEMENT}
)
"""Ledger rows unrelated to freight."""

BILLING_CHANNEL_KEY = "billing_channel"
"""`pricing_breakdown` key holding the BillingChannel fixed at booking."""


def wallet_txn_type(txn: WalletTransaction) -> Optional[WalletTxnType]:
    """The txn type as an enum member (rows may load the VARCHAR as a plain str)."""
    raw = txn.txn_type
    if isinstance(raw, WalletTxnType):
        return raw
    try:
        return WalletTxnType(raw)
    except ValueError:
        return None


def wallet_txn_status(txn: WalletTransaction) -> Optional[WalletTxnStatus]:
    """The txn status as an enum member."""
    raw = txn.status
    if isinstance(raw, WalletTxnStatus):
        return raw
    try:
        return WalletTxnStatus(raw)
    except ValueError:
        return None


def net_debited(txns: Iterable[WalletTransaction]) -> Decimal:
    """
    Net amount paid towards the bill: Σ BILL_DEBIT − Σ BILL_CREDIT (COMPLETED rows only).

    Args:
        txns: Wallet ledger rows of one shipment.

    Returns:
        The signed net amount, rounded to the paisa (normally >= 0).
    """
    total = ZERO_MONEY
    for txn in txns:
        if wallet_txn_status(txn) != WalletTxnStatus.COMPLETED:
            continue
        txn_type = wallet_txn_type(txn)
        if txn_type in BILL_DEBIT_TYPES:
            total += to_money(txn.amount)
        elif txn_type in BILL_CREDIT_TYPES:
            total -= to_money(txn.amount)
    return to_money(total)


def billing_channel_for_booking(
    mode: FreightPaymentMode, *, booked_by_staff: bool = False
) -> BillingChannel:
    """
    The billing channel fixed once at booking (B2/B16; #558 3a: walk-in on-behalf is not in MVP,
    so both PREPAID and POSTPAID are wallet-billed to the booking user and issue a GST invoice).

    Args:
        mode: The booked freight payment mode.
        booked_by_staff: True when tenant staff booked it (both customer and staff use WALLET).

    Returns:
        WALLET for PREPAID and POSTPAID, NONE for TO_PAY.
    """
    if mode in (FreightPaymentMode.PREPAID, FreightPaymentMode.POSTPAID):
        return BillingChannel.WALLET
    return BillingChannel.NONE


def stamp_billing_channel(
    breakdown: Optional[Mapping[str, Any]], channel: BillingChannel
) -> dict:
    """Returns a NEW breakdown dict carrying the billing channel (JSONB-safe value)."""
    stamped = dict(breakdown or {})
    stamped[BILLING_CHANNEL_KEY] = channel.value
    return stamped


def _payment_of(target: Union[PickupRequest, PaymentDetails, None]) -> Optional[PaymentDetails]:
    """The payment row of a shipment, or the row itself."""
    if target is None:
        return None
    if isinstance(target, PaymentDetails):
        return target
    return getattr(target, "payment_details", None)


def billing_channel_of(target: Union[PickupRequest, PaymentDetails, None]) -> BillingChannel:
    """
    The billing channel of a shipment / payment row. It is never recomputed from the
    creator's current role (D34). Legacy rows without the flag count as WALLET when
    PREPAID, NONE otherwise.
    """
    payment = _payment_of(target)
    if payment is None:
        return BillingChannel.NONE
    raw = (payment.pricing_breakdown or {}).get(BILLING_CHANNEL_KEY)
    if raw in (BillingChannel.WALLET.value, BillingChannel.NONE.value):
        return BillingChannel(raw)
    return (
        BillingChannel.WALLET
        if payment.freight_payment_mode == FreightPaymentMode.PREPAID
        else BillingChannel.NONE
    )


def is_wallet_billed(target: Union[PickupRequest, PaymentDetails, None]) -> bool:
    """True when the shipment's freight is settled through the creator's wallet."""
    return billing_channel_of(target) == BillingChannel.WALLET
