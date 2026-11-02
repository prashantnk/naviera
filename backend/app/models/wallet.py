import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import sqlalchemy as sa
from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utc_now_naive() -> datetime:
    """Return current UTC timestamp as a naive datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class WalletTxnType(str, Enum):
    """
    Ledger transaction categories matching Delhivery One's Unified Wallet Passbook:
    - RECHARGE: Shipper tops up wallet balance via NPCI UPI QR ('upi://pay' + 12-digit UTR).
    - SPEND: Immediate freight deduction when booking a Prepaid B2C parcel or B2B LR.
    - REFUND: Automatic freight reversal when an OPEN/SCHEDULED shipment is cancelled before dispatch.
    - COD_SETTLEMENT: 1-Click conversion of collected doorstep Cash-on-Delivery (COD) into usable wallet balance.
    - WEIGHT_AUDIT_DEBIT: Automated differential debit when the Hub DWS laser scale measures higher weight than declared.
    - FREIGHT_COLLECTION: Pending freight cleared by the merchant on a "Freight Collection" exception.
    - ADDITIONAL_CHARGE: Acknowledged on-hold charges (e.g. Mathadi / union charges) on an "Additional Charges" exception.
    - RTO_FREIGHT: The return (RTO) leg billed once per shipment (DB partial unique, migration M-B4).
    - CHARGE_REVERSAL: Reversal of a separate charge (e.g. an Additional Charge waived by ops); own GST note.
    The column is a plain VARCHAR(50) with no CHECK constraint, so new members need no migration.
    """

    RECHARGE = "RECHARGE"
    SPEND = "SPEND"
    REFUND = "REFUND"
    COD_SETTLEMENT = "COD_SETTLEMENT"
    WEIGHT_AUDIT_DEBIT = "WEIGHT_AUDIT_DEBIT"
    FREIGHT_COLLECTION = "FREIGHT_COLLECTION"
    ADDITIONAL_CHARGE = "ADDITIONAL_CHARGE"
    RTO_FREIGHT = "RTO_FREIGHT"
    CHARGE_REVERSAL = "CHARGE_REVERSAL"


class WalletTxnDirection(str, Enum):
    """Whether a ledger row adds to (CREDIT) or takes from (DEBIT) the wallet balance."""

    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


WALLET_CREDIT_TXN_TYPES = frozenset(
    {
        WalletTxnType.RECHARGE,
        WalletTxnType.REFUND,
        WalletTxnType.COD_SETTLEMENT,
        WalletTxnType.CHARGE_REVERSAL,
    }
)
"""A-16: the single list of ledger types that credit the wallet; every other type debits it."""

WALLET_COD_UTR_PREFIX = "WALLET-COD-"
"""`bank_utr` prefix of the CodRemittance row written by a self-service COD-to-wallet settle."""


def wallet_txn_direction(txn_type: WalletTxnType) -> WalletTxnDirection:
    """CREDIT for the credit types above, DEBIT for every other ledger type."""
    return (
        WalletTxnDirection.CREDIT
        if txn_type in WALLET_CREDIT_TXN_TYPES
        else WalletTxnDirection.DEBIT
    )


class WalletServiceCategory(str, Enum):
    """
    Tags which logistics vertical or funding stream generated the wallet ledger entry:
    - B2C: Express parcel shipments (< 20 kg standard courier).
    - B2B: Heavy Cargo LTL/PTL consignments (multi-box Lorry Receipts).
    - RECHARGE: Direct wallet funding / COD remittance credit.
    """

    B2C = "B2C"
    B2B = "B2B"
    RECHARGE = "RECHARGE"


class WalletTxnStatus(str, Enum):
    """Lifecycle status of a wallet ledger transaction."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class UserWallet(SQLModel, table=True):
    """
    Per-user Unified Prepaid Wallet scoped to a specific 3PL Tenant (e.g., Logismart vs Naviera).
    
    Real-World FinTech Use Case:
    - Every shipper account starts strictly at ₹0.00 ('balance = 0.0') with zero artificial credit.
    - Enforces composite uniqueness ('uq_user_wallet_tenant' on user_id + tenant_id) at the PostgreSQL
      storage layer so concurrent requests from multiple browser tabs can never create duplicate wallets.
    - Spring Boot / JPA Equivalent: '@Entity @Table(name = "user_wallets", uniqueConstraints = @UniqueConstraint(columnNames = {"user_id", "tenant_id"}))'
    """

    __tablename__ = "user_wallets"  # type: ignore
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", name="uq_user_wallet_tenant"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        description="Multi-tenant isolation key linking the wallet to a specific 3PL brand (e.g. Logismart)",
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        description="Owner shipper user ID; each customer maintains an independent wallet balance",
    )
    balance: float = Field(
        default=0.0,
        description="Current spendable wallet balance in INR (₹). Always initialized strictly to ₹0.00",
    )
    updated_at: datetime = Field(
        default_factory=_utc_now_naive,
        description="UTC timestamp of the last wallet balance mutation",
    )


class WalletTransaction(SQLModel, table=True):
    """
    Immutable Double-Entry Passbook Ledger recording every rupee added or spent on a UserWallet.
    
    Real-World Banking & Accounting Use Case:
    - Stores 'opening_balance', signed 'amount', and 'closing_balance' on every row (just like an
      HDFC/ICICI Bank Passbook or Delhivery One Wallet Ledger) so customer support and auditors can
      verify exact balance math at any historical timestamp.
    - Enforces 'uq_wallet_txn_utr' ('UNIQUE (utr_number)') in PostgreSQL so a 12-digit NPCI UPI
      UTR reference from GPay/PhonePe can never be replayed twice to claim free wallet balance.
    - Uses 'ON DELETE SET NULL' on 'shipment_id' while persisting 'tracking_id' as a VARCHAR(100)
      snapshot so financial tax records (SAC 996812) survive permanently even if old shipments are purged.
    """

    __tablename__ = "wallet_transactions"  # type: ignore
    __table_args__ = (
        UniqueConstraint("utr_number", name="uq_wallet_txn_utr"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    wallet_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("user_wallets.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        description="Parent UserWallet ID that was credited or debited",
    )
    tenant_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        description="Tenant ID for strict multi-tenant financial ledger isolation",
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        ),
        description="Shipper user ID who initiated or owns this transaction",
    )
    shipment_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("pickups.id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        ),
        description="Linked shipment UUID for SPEND/REFUND/WEIGHT_AUDIT_DEBIT (SET NULL if shipment is archived)",
    )
    tracking_id: Optional[str] = Field(
        default=None,
        nullable=True,
        max_length=100,
        description="Immutable AWB / LR tracking number snapshot preserved for passbook & GST invoice display",
    )

    # Stored as VARCHAR(50) in Postgres backed by Python str Enum to prevent PostgreSQL ALTER TYPE locks
    txn_type: WalletTxnType = Field(
        sa_column=Column(sa.String(50), nullable=False),
        description="Transaction type (RECHARGE, SPEND, REFUND, COD_SETTLEMENT, WEIGHT_AUDIT_DEBIT)",
    )
    service_category: WalletServiceCategory = Field(
        sa_column=Column(sa.String(50), nullable=False),
        description="Logistics vertical (B2C, B2B, or RECHARGE)",
    )

    opening_balance: float = Field(
        default=0.0,
        description="Wallet balance in INR immediately BEFORE this transaction was applied",
    )
    amount: float = Field(
        default=0.0,
        description="Signed transaction delta in INR (+ve for RECHARGE/REFUND/COD_SETTLEMENT, -ve for SPEND/WEIGHT_AUDIT_DEBIT)",
    )
    closing_balance: float = Field(
        default=0.0,
        description="Wallet balance in INR immediately AFTER this transaction was applied (opening_balance + amount)",
    )

    utr_number: Optional[str] = Field(
        default=None,
        nullable=True,
        index=True,
        max_length=50,
        description="Unique 12-digit NPCI Bank UPI UTR number (enforces idempotency against replay attacks)",
    )
    receipt_number: str = Field(
        index=True,
        max_length=100,
        description="Human-readable voucher / GST receipt number (e.g., RCP-20260922-8F3A1B) for PDF downloads",
    )
    status: WalletTxnStatus = Field(
        default=WalletTxnStatus.COMPLETED,
        sa_column=Column(sa.String(50), nullable=False, default="COMPLETED"),
        description="Settlement status of the ledger entry (COMPLETED, PENDING, FAILED)",
    )
    remarks: Optional[str] = Field(
        default=None,
        nullable=True,
        max_length=500,
        description="Human-readable audit narration shown in the passbook table (e.g., weight discrepancy details)",
    )
    created_at: datetime = Field(
        default_factory=_utc_now_naive,
        description="UTC timestamp when the ledger entry was recorded",
    )
