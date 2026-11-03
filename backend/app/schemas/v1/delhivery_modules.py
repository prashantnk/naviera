import uuid
from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import computed_field
from sqlmodel import Field, SQLModel

from app.models.delhivery_modules import (
    InvoiceNoteType,
    InvoiceServiceType,
    InvoiceStatus,
    RemittanceState,
    TicketCategoryGroup,
    TicketStatus,
    WeightDisputeClaimStatus,
)
from app.services.gst_documents import (
    document_display_name,
    first_line_item,
    invoice_bill_to,
    invoice_supplier_name,
    invoice_tax_rows,
    is_note_document,
    place_of_supply_label,
)


class CodRemittanceRead(SQLModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    merchant_user_id: uuid.UUID
    merchant_email: Optional[str] = Field(
        default=None,
        description="Merchant (customer) email, filled for tenant-wide staff views.",
    )
    remittance_number: str
    processed_date: date
    bank_utr: str
    state: str = RemittanceState.COMPLETED.value
    total_remittance: float = 0.0
    total_orders: int = 0
    shipment_breakdown: List[Any] = Field(default_factory=list)
    created_at: datetime


class CodRemittanceCreate(SQLModel):
    """
    One merchant's COD bank payout (A-06): finance first loads `GET /remittances/pending`,
    ticks the AWBs the bank transfer actually paid and sends them with the total it saw.
    The server recomputes the total and refuses a mismatch (409), so a UTR can never be
    stamped on orders the transfer did not cover.
    """

    merchant_user_id: Optional[uuid.UUID] = None
    remittance_number: Optional[str] = None
    processed_date: Optional[date] = None
    bank_utr: str
    state: str = RemittanceState.COMPLETED.value
    shipment_ids: Optional[List[uuid.UUID]] = None
    expected_total: Optional[float] = Field(
        default=None,
        ge=0,
        description="The payout total shown in the preview for the ticked AWBs (required).",
    )


class CodRemittancePreviewLine(SQLModel):
    """One AWB that can be paid in the next bank remittance."""

    shipment_id: uuid.UUID
    tracking_id: str
    order_reference_id: str
    amount: float


class CodRemittancePreview(SQLModel):
    """A-06 / A-05: what a bank payout to one merchant would cover right now."""

    merchant_user_id: uuid.UUID
    merchant_email: Optional[str] = None
    wallet_balance: float
    payout_blocked_reason: Optional[str] = None
    lines: List[CodRemittancePreviewLine]
    selected_count: int = 0
    total: float = Field(description="Payout total of the ticked AWBs (all AWBs when none sent).")


class GstTaxRowRead(SQLModel):
    """One printable GST row of a document, e.g. ("IGST @ 18%", 14.40)."""

    label: str
    amount: float


class GstPartyRead(SQLModel):
    """Recipient ("Bill To") of a GST document as frozen at issue."""

    name: str = ""
    address: str = ""
    gstin: Optional[str] = None
    state_code: Optional[str] = None


class BillingInvoiceRead(SQLModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    merchant_user_id: uuid.UUID
    merchant_email: Optional[str] = Field(
        default=None,
        description="Merchant (customer) email, filled for tenant-wide staff views.",
    )
    invoice_number: str
    note_type: str = InvoiceNoteType.INVOICE.value
    service_type: str = InvoiceServiceType.DOMESTIC.value
    invoice_date: date
    due_date: date
    status: str = InvoiceStatus.PAID.value
    gst_number: str
    billing_address: str
    freight_amount: float = 0.0
    cgst_amount: float = 0.0
    sgst_amount: float = 0.0
    igst_amount: float = 0.0
    total_amount: float = 0.0
    line_items: List[Any] = Field(default_factory=list)
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def document_title(self) -> str:
        """"Tax Invoice" / "Credit Note" / "Debit Note"."""
        return document_display_name(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_note(self) -> bool:
        """True for a credit / debit note (no due date; quotes `original_invoice_number`)."""
        return is_note_document(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tax_rows(self) -> List[GstTaxRowRead]:
        """CGST + SGST or IGST rows at the configured rate, e.g. "CGST @ 9%" (C-12)."""
        return [GstTaxRowRead(label=row.label, amount=row.amount) for row in invoice_tax_rows(self)]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def place_of_supply_label(self) -> Optional[str]:
        """"Haryana (06)" from the stored place-of-supply state code (C-02)."""
        return place_of_supply_label(first_line_item(self).get("place_of_supply"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def bill_to(self) -> Optional[GstPartyRead]:
        """Recipient frozen at issue: name, address, approved GSTIN (C-01)."""
        party = invoice_bill_to(self)
        if party is None:
            return None
        return GstPartyRead(
            name=party.name, address=party.address, gstin=party.gstin, state_code=party.state_code
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def supplier_name(self) -> Optional[str]:
        """Supplier legal name frozen at issue (None on documents issued before C-04)."""
        return invoice_supplier_name(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def original_invoice_number(self) -> Optional[str]:
        """The invoice a credit / debit note corrects (CGST Rule 53)."""
        return first_line_item(self).get("original_invoice_number") or None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def original_invoice_date(self) -> Optional[str]:
        """ISO date of the invoice a credit / debit note corrects."""
        return first_line_item(self).get("original_invoice_date") or None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def tracking_id(self) -> Optional[str]:
        """AWB the document was issued for, if any."""
        return first_line_item(self).get("tracking_id") or None


class BillingInvoiceCreate(SQLModel):
    """
    Manual GST document. `freight_amount` is the taxable value; GST (CGST+SGST or
    IGST by place of supply), totals, the supplier GSTIN / address and the
    sequential document number are always computed server-side.
    """

    merchant_user_id: Optional[uuid.UUID] = None
    note_type: str = InvoiceNoteType.INVOICE.value
    service_type: str = InvoiceServiceType.DOMESTIC.value
    invoice_date: Optional[date] = None
    due_date: Optional[date] = None
    status: str = InvoiceStatus.PAID.value
    freight_amount: float = 0.0
    reason: Optional[str] = Field(
        default=None,
        max_length=255,
        description="Why this manual GST document is issued (recorded on the document line)",
    )
    original_reference: Optional[str] = Field(
        default=None,
        max_length=64,
        description="Original invoice number / AWB / agreement this document refers to (Rule 53)",
    )


class SupportTicketMessageRead(SQLModel):
    id: uuid.UUID
    ticket_id: uuid.UUID
    sender_user_id: uuid.UUID
    sender_email: str
    sender_role: str
    message: str
    attachment_url: Optional[str] = None
    created_at: datetime


class SupportTicketSummary(SQLModel):
    """
    Home-dashboard Support card counters (Delhivery One parity).

    Customers read `resolved` + `need_your_input` (Logismart replied last on an
    open ticket); staff read `open` + `awaiting_support` (the shipper replied last).
    """

    open: int = 0
    resolved: int = 0
    closed: int = 0
    need_your_input: int = 0
    awaiting_support: int = 0


class SupportTicketRead(SQLModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    ticket_number: str
    shipment_id: Optional[uuid.UUID] = None
    tracking_id: Optional[str] = None
    category_group: str = TicketCategoryGroup.SHIPMENT_ISSUE.value
    sub_category: str
    subject: str
    description: str
    status: str = TicketStatus.OPEN.value
    cc_emails: List[str] = Field(default_factory=list)
    email_notifications: bool = True
    raised_by_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class SupportTicketDetailRead(SupportTicketRead):
    messages: List[SupportTicketMessageRead] = Field(default_factory=list)


class SupportTicketCreate(SQLModel):
    category_group: str = TicketCategoryGroup.SHIPMENT_ISSUE.value
    sub_category: str
    subject: Optional[str] = None
    description: str
    tracking_id: Optional[str] = None
    shipment_id: Optional[uuid.UUID] = None
    cc_emails: List[str] = Field(default_factory=list)
    email_notifications: bool = True
    attachment_url: Optional[str] = None


class SupportTicketMessageCreate(SQLModel):
    message: str
    attachment_url: Optional[str] = None


class SupportTicketStatusUpdate(SQLModel):
    status: str


class WeightDisputeRead(SQLModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    merchant_user_id: uuid.UUID
    merchant_email: Optional[str] = Field(
        default=None,
        description="Merchant (customer) email, filled for tenant-wide staff views.",
    )
    shipment_id: Optional[uuid.UUID] = None
    tracking_id: str
    order_reference_id: Optional[str] = None
    shipment_status: str = "Delivered"
    manifested_weight_g: float
    charged_weight_g: float
    claimed_weight_g: Optional[float] = None
    manifested_dims: str = ""
    charged_dims: str = ""
    shipping_cost_inr: float = 0.0
    shipment_value_inr: float = 0.0
    cost_diff_inr: float = 0.0
    sorter_image_url: Optional[str] = None
    claim_status: str = WeightDisputeClaimStatus.NONE.value
    claim_remarks: Optional[str] = None
    raised_at: datetime
    updated_at: datetime


class WeightDisputeClaimCreate(SQLModel):
    tracking_ids: List[str]
    claimed_weight_g: Optional[float] = None
    claim_remarks: Optional[str] = None


class WeightDisputeResolveRequest(SQLModel):
    claim_status: str
    claim_remarks: Optional[str] = None
    expected_claimed_weight_g: Optional[float] = None
