from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import computed_field
from sqlmodel import Field, SQLModel

from app.models.wallet import (
    WalletServiceCategory,
    WalletTxnDirection,
    WalletTxnStatus,
    WalletTxnType,
    wallet_txn_direction,
)

RECHARGE_REJECT_REASON_MAX_LENGTH = 200


class UpiIntentRequest(SQLModel):
    amount: float = Field(..., ge=1.0, description="Recharge amount in INR (minimum ₹1)")


class UpiIntentResponse(SQLModel):
    transaction_id: UUID
    upi_uri: str
    qr_svg_data_url: str
    merchant_vpa: str
    merchant_name: str
    amount: float


class VerifyUtrRequest(SQLModel):
    transaction_id: Optional[UUID] = None
    amount: Optional[float] = Field(default=None, ge=1.0)
    utr_number: str = Field(..., min_length=12, max_length=12)


class WalletTransactionRead(SQLModel):
    id: UUID
    wallet_id: UUID
    tenant_id: UUID
    user_id: UUID
    user_email: Optional[str] = None
    shipment_id: Optional[UUID] = None
    tracking_id: Optional[str] = None
    txn_type: WalletTxnType
    service_category: WalletServiceCategory
    opening_balance: float
    amount: float
    closing_balance: float
    utr_number: Optional[str] = None
    receipt_number: str
    status: WalletTxnStatus
    remarks: Optional[str] = None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def direction(self) -> WalletTxnDirection:
        """A-16: CREDIT or DEBIT from the one backend list, so the UI never guesses a sign."""
        return wallet_txn_direction(self.txn_type)


class RechargeRejectRequest(SQLModel):
    """A-15: why the admin rejected a recharge (shown to the merchant in the passbook)."""

    reason: Optional[str] = Field(default=None, max_length=RECHARGE_REJECT_REASON_MAX_LENGTH)


class AdminOfflineCreditRequest(SQLModel):
    """
    Owner/Admin manual wallet credit when a customer sends money offline
    (NEFT / IMPS / RTGS / Direct UPI / Cash / Cheque; #558 3b).
    """

    user_id: Optional[UUID] = Field(
        default=None,
        description="Target user UUID in the tenant (optional if user_email is provided).",
    )
    user_email: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Target user email in the tenant (optional if user_id is provided).",
    )
    amount: float = Field(
        ...,
        ge=1.0,
        le=10_000_000.0,
        description="Offline credit amount in INR (minimum ₹1).",
    )
    utr_number: str = Field(
        ...,
        min_length=4,
        max_length=64,
        description="Bank UTR, NEFT/IMPS/RTGS reference, cheque number, or cash receipt reference.",
    )
    payment_method: str = Field(
        default="NEFT / IMPS / RTGS",
        min_length=2,
        max_length=64,
        description="Offline payment instrument (e.g. NEFT / IMPS / RTGS, Direct UPI, Cash / Cheque).",
    )
    notes: Optional[str] = Field(
        default=None,
        max_length=200,
        description="Optional finance remark recorded in the passbook and receipt voucher.",
    )


class VerifyUtrResponse(SQLModel):
    balance: float
    transaction: WalletTransactionRead


class UpiConfirmRequest(SQLModel):
    utr_number: Optional[str] = Field(
        default=None,
        description="Required 12-digit numeric UPI / bank reference (UTR) of the payment (A-14)",
    )


class UpiRechargeStatusResponse(SQLModel):
    transaction_id: UUID
    status: WalletTxnStatus
    balance: float
    transaction: WalletTransactionRead
    auto_detected: bool = False


class WalletSummary(SQLModel):
    total_recharged: float = 0.0
    pending_recharge: float = 0.0
    total_spent: float = 0.0
    total_refunded: float = 0.0
    collectible_cod: float = 0.0


class WalletOverviewResponse(SQLModel):
    balance: float
    currency: str = "INR"
    wallet_config: dict = {}
    summary: WalletSummary


class CodSettlementResponse(SQLModel):
    settled_count: int
    settled_amount: float
    new_balance: float
    transactions: List[WalletTransactionRead] = []


class WeightAuditRequest(SQLModel):
    audited_weight_kg: float = Field(..., gt=0.0, description="Audited chargeable weight in KG")
    override_total_price: Optional[float] = Field(
        default=None,
        gt=0.0,
        le=10_000_000.0,
        description="Optional Admin final price override in INR (incl. GST; #568)",
    )


class WalletAuditDiscrepancy(SQLModel):
    category: str
    entity_id: str
    reference: str
    detail: str


class WalletIntegrityAuditResponse(SQLModel):
    passed: bool
    checked_at: datetime
    wallets_checked: int
    transactions_checked: int
    shipments_checked: int
    invoices_checked: int
    remittances_checked: int
    discrepancy_count: int
    discrepancies: List[WalletAuditDiscrepancy] = []
    warnings: List[WalletAuditDiscrepancy] = []
    """Non-failing findings (e.g. a blind LR still awaiting measurement, plan B5)."""

