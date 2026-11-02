import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, List, Optional

import sqlalchemy as sa
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


def _utc_now_naive() -> datetime:
    """Return current UTC timestamp as a naive datetime for PostgreSQL TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TicketCategoryGroup(str, Enum):
    SHIPMENT_ISSUE = "SHIPMENT_ISSUE"
    OTHER_ISSUE = "OTHER_ISSUE"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RemittanceState(str, Enum):
    COMPLETED = "Completed"
    PENDING = "Pending"


class InvoiceNoteType(str, Enum):
    INVOICE = "INVOICE"
    CREDIT_NOTE = "CREDIT_NOTE"
    DEBIT_NOTE = "DEBIT_NOTE"


class InvoiceServiceType(str, Enum):
    DOMESTIC = "Domestic"
    COMMUNICATION_VAS = "Communication VAS"
    B2B_CARGO = "B2B Cargo"


class InvoiceStatus(str, Enum):
    PAID = "Paid"
    OVERDUE = "Overdue"
    ISSUED = "Issued"


class BillToType(str, Enum):
    """
    Who a GST document is billed to (`billing_invoices.bill_to_type`, VARCHAR + CHECK, migration M-B4).
    At most one INVOICE per shipment per bill-to party (DB partial unique index).
    """

    MERCHANT = "MERCHANT"
    CONSIGNEE = "CONSIGNEE"


class WeightDisputeClaimStatus(str, Enum):
    NONE = "NONE"
    CLAIM_RAISED = "CLAIM_RAISED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


DEFAULT_LOGISMART_GSTIN = "06AAECL2138H1ZQ"
DEFAULT_LOGISMART_BILLING_ADDRESS = (
    "H. NO-632/5, GALI NO-3, PATEL NAGAR, JYOTI HOSPITAL, Gurgaon, Haryana, 122001"
)
DEFAULT_MANIFESTED_DIMS = "39 x 30 x 6 cm"
DEFAULT_CHARGED_DIMS = "23.8 x 31.8 x 7.3 cm"


class SupportTicket(SQLModel, table=True):
    """
    Delhivery One Support Ticket ('Support -> Raise a ticket').
    Supports SHIPMENT_ISSUE and OTHER_ISSUE categories with Open, Resolved, and Closed states.
    """

    __tablename__ = "support_tickets"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
    )
    ticket_number: str = Field(index=True, max_length=64)
    shipment_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("pickups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    tracking_id: Optional[str] = Field(default=None, index=True, max_length=100)
    category_group: str = Field(default=TicketCategoryGroup.SHIPMENT_ISSUE.value, max_length=64)
    sub_category: str = Field(max_length=255)
    subject: str = Field(max_length=255)
    description: str = Field(sa_column=Column(sa.Text, nullable=False))
    status: str = Field(default=TicketStatus.OPEN.value, index=True, max_length=32)
    cc_emails: List[str] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    email_notifications: bool = Field(default=True)
    raised_by_email: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=_utc_now_naive)
    updated_at: datetime = Field(default_factory=_utc_now_naive)


class SupportTicketMessage(SQLModel, table=True):
    """
    Thread message within a SupportTicket.
    """

    __tablename__ = "support_ticket_messages"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ticket_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("support_tickets.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
    )
    sender_user_id: uuid.UUID = Field(nullable=False)
    sender_email: str = Field(max_length=255)
    sender_role: str = Field(max_length=64)
    message: str = Field(sa_column=Column(sa.Text, nullable=False))
    attachment_url: Optional[str] = Field(default=None, max_length=512)
    created_at: datetime = Field(default_factory=_utc_now_naive)


class CodRemittance(SQLModel, table=True):
    """
    Delhivery One COD Remittance batch ('Finances -> Remittances').
    Records UTR settlement batches for delivered COD shipments.
    """

    __tablename__ = "cod_remittances"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    merchant_user_id: uuid.UUID = Field(index=True, nullable=False)
    remittance_number: str = Field(index=True, max_length=64)
    processed_date: date = Field(nullable=False)
    bank_utr: str = Field(max_length=64)
    state: str = Field(default=RemittanceState.COMPLETED.value, max_length=32)
    total_remittance: float = Field(default=0.0)
    total_orders: int = Field(default=0)
    shipment_breakdown: List[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    created_at: datetime = Field(default_factory=_utc_now_naive)


class BillingInvoice(SQLModel, table=True):
    """
    Delhivery One GST Invoice / Credit Note / Debit Note ('Finances -> Invoices').
    """

    __tablename__ = "billing_invoices"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    merchant_user_id: uuid.UUID = Field(index=True, nullable=False)
    invoice_number: str = Field(index=True, max_length=64)
    note_type: str = Field(default=InvoiceNoteType.INVOICE.value, max_length=32)
    service_type: str = Field(default=InvoiceServiceType.DOMESTIC.value, max_length=64)
    invoice_date: date = Field(nullable=False)
    due_date: date = Field(nullable=False)
    status: str = Field(default=InvoiceStatus.PAID.value, max_length=32)
    gst_number: str = Field(default=DEFAULT_LOGISMART_GSTIN, max_length=32)
    billing_address: str = Field(
        default=DEFAULT_LOGISMART_BILLING_ADDRESS,
        sa_column=Column(sa.Text, nullable=False),
    )
    freight_amount: float = Field(default=0.0)
    cgst_amount: float = Field(default=0.0)
    sgst_amount: float = Field(default=0.0)
    igst_amount: float = Field(default=0.0)
    total_amount: float = Field(default=0.0)
    line_items: List[Any] = Field(
        default_factory=list,
        sa_column=Column(JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    created_at: datetime = Field(default_factory=_utc_now_naive)
    # Migration M-B4 (6c4dae5fb004): structured GST links (CGST Rule 53) + bill-to party.
    shipment_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("pickups.id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        ),
    )
    original_invoice_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("billing_invoices.id"),
            index=True,
            nullable=True,
        ),
        description="The INVOICE a CREDIT_NOTE / DEBIT_NOTE corrects; always NULL on an INVOICE (DB CHECK).",
    )
    bill_to_type: BillToType = Field(
        default=BillToType.MERCHANT,
        sa_column=Column(
            sa.String(16), nullable=False, server_default=sa.text("'MERCHANT'")
        ),
    )


class WeightDispute(SQLModel, table=True):
    """
    Delhivery One Weight Mismatch & Dispute Claim ('Information Center -> Weight Mismatch').
    """

    __tablename__ = "weight_disputes"  # type: ignore

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(index=True, nullable=False)
    merchant_user_id: uuid.UUID = Field(index=True, nullable=False)
    shipment_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("pickups.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    tracking_id: str = Field(index=True, max_length=100)
    order_reference_id: Optional[str] = Field(default=None, max_length=100)
    shipment_status: str = Field(default="Delivered", max_length=64)
    manifested_weight_g: float = Field(default=0.0)
    charged_weight_g: float = Field(default=0.0)
    claimed_weight_g: Optional[float] = Field(default=None)
    manifested_dims: str = Field(default=DEFAULT_MANIFESTED_DIMS, max_length=120)
    charged_dims: str = Field(default=DEFAULT_CHARGED_DIMS, max_length=120)
    shipping_cost_inr: float = Field(default=0.0)
    shipment_value_inr: float = Field(default=0.0)
    cost_diff_inr: float = Field(default=0.0)
    sorter_image_url: Optional[str] = Field(default=None, max_length=512)
    claim_status: str = Field(default=WeightDisputeClaimStatus.NONE.value, max_length=32)
    claim_remarks: Optional[str] = Field(default=None, sa_column=Column(sa.Text, nullable=True))
    raised_at: datetime = Field(default_factory=_utc_now_naive)
    updated_at: datetime = Field(default_factory=_utc_now_naive)
