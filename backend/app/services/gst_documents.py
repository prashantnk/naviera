"""
GST tax documents (TAX INVOICE / CREDIT NOTE / DEBIT NOTE): the issue-time snapshot
shape, the printable view built from a stored `BillingInvoice` row, and the ONE PDF
renderer used by both `/finances/invoices/{id}/pdf` and `/shipments/{id}/invoice-pdf`.

Rules (prelaunch audit C-01, C-02, C-04, C-12, C-14; CGST Rules 46 and 53):
- An issued document is rendered ONLY from its stored row (`line_items[0]` snapshot),
  never from the live shipment, so re-downloading it never changes it.
- "Bill To" carries the recipient's name, address and (approved) GSTIN.
- Credit / debit notes quote the original invoice number and date.
- Tax rows print the configured rate: CGST + SGST (intra-state) OR IGST (inter-state).
- Test tenants get a "SPECIMEN" watermark.

This module imports no other service, so `delhivery_modules`, `receipt_pdf` and the
API schemas can all import it without an import cycle.
"""

import io
import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

from app.models.delhivery_modules import BillingInvoice, InvoiceNoteType

# --- Snapshot keys stored on `billing_invoices.line_items[0]` -----------------
SNAPSHOT_VERSION = 1
"""Bump when the snapshot shape changes; rows without it are legacy (pre-C-04)."""
SNAPSHOT_VERSION_KEY = "snapshot_version"
SUPPLIER_KEY = "supplier"
BILL_TO_KEY = "bill_to"
CHARGE_LINES_KEY = "charge_lines"
REVERSE_CHARGE_KEY = "reverse_charge"
CHARGEABLE_WEIGHT_KEY = "chargeable_weight_kg"
ORIGIN_KEY = "origin"
DESTINATION_KEY = "destination"

# --- GST constants -------------------------------------------------------------
SAC_CODE_COURIER = "996812"
SAC_DESCRIPTION = "Courier services"
STANDARD_GST_RATES: Tuple[float, ...] = (0.0, 5.0, 12.0, 18.0, 28.0)
"""Legacy rows stored a derived rate (e.g. 18.06); it prints as the nearest slab."""
RATE_DECIMALS = 2
MONEY_DECIMALS = 2
GSTIN_LENGTH = 15
GSTIN_PAN_SLICE = slice(2, 12)
GSTIN_STATE_CODE_LENGTH = 2
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GSTIN_CHECKSUM_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
UNREGISTERED_GSTIN_TEXT = "Unregistered"
KYC_REQUESTS_SETTINGS_KEY = "b2b_access_requests"
"""`tenant.settings` key holding each merchant's KYC / company details, keyed by user id."""
KYC_APPROVED_STATUS = "APPROVED"
"""`b2b_access_requests[uid].status` / `.gstin_status` value that makes a GSTIN printable."""
KYC_STATUS_KEY = "status"
GSTIN_STATUS_KEY = "gstin_status"
"""Set to APPROVED when a D2C seller's self-submitted GSTIN passed the checksum checks."""
VERIFIED_GSTIN_KEY = "verified_gstin"
"""The exact GSTIN that was verified; a later, unreviewed `gstin` (e.g. a new B2B request) never inherits it."""
BILLING_ADDRESS_KEY = "billing_address"
COMPANY_DETAILS_SUBMITTED_AT_KEY = "company_details_submitted_at"
"""ISO timestamp of the one-time company-details submission; its presence locks them."""
SLAB_SNAP_TOLERANCE = 0.5
"""A derived rate within this many percentage points of a GST slab prints as that slab."""

GST_STATE_NAMES: Dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
}
"""GST state code (first two digits of a GSTIN) -> state / UT name, as printed on documents."""

DOCUMENT_TITLES: Dict[str, str] = {
    InvoiceNoteType.INVOICE.value: "TAX INVOICE",
    InvoiceNoteType.CREDIT_NOTE.value: "CREDIT NOTE",
    InvoiceNoteType.DEBIT_NOTE.value: "DEBIT NOTE",
}
DOCUMENT_DISPLAY_NAMES: Dict[str, str] = {
    InvoiceNoteType.INVOICE.value: "Tax Invoice",
    InvoiceNoteType.CREDIT_NOTE.value: "Credit Note",
    InvoiceNoteType.DEBIT_NOTE.value: "Debit Note",
}
"""Screen name of each document type (the API sends it so the UI never branches on note_type)."""
LEGACY_CHARGE_LABEL = "Freight Charges"
OTHER_CHARGES_LABEL = "Other Charges"
VAS_CHARGE_LABEL = "Communication VAS Charges"
VAS_SERVICE_MARKER = "vas"
SHIPMENT_CHARGE_LABELS: Tuple[Tuple[str, str], ...] = (
    ("base_charge", "Base Freight"),
    ("service_surcharge", "Service Speed Surcharge"),
    ("fuel_surcharge", "Fuel Surcharge"),
    ("network_surcharge", "Network Surcharge"),
    ("oversized_surcharge", "Oversize Surcharge"),
    ("rto_surcharge", "RTO Charges"),
    ("docket_charge", "Docket Charge"),
    ("fov_charge", "FOV / Carrier Risk Charge"),
    ("cod_fee", "COD Collection Fee"),
)
"""`payment_details.pricing_breakdown` keys (pre-GST) -> printed charge-line label."""
NOTE_DEFAULT_DESCRIPTIONS: Dict[str, str] = {
    InvoiceNoteType.INVOICE.value: LEGACY_CHARGE_LABEL,
    InvoiceNoteType.CREDIT_NOTE.value: "Freight Adjustment (Credit)",
    InvoiceNoteType.DEBIT_NOTE.value: "Additional Freight Charges",
}
"""Charge-line label of a partial-amount document when the caller gives no description."""
SEPARATE_CHARGE_DESCRIPTION = "Freight Collection / Mathadi Charges"

# --- Test tenants (C-14) --------------------------------------------------------
SPECIMEN_TENANT_SLUGS = frozenset({"logismart-test"})
"""Mirrors `scripts.tenant_data_core.ALLOWED_TEST_SLUGS` (a test pins the two together)."""
TEST_ENVIRONMENT_VALUE = "test"
SPECIMEN_TEXT = "SPECIMEN"
SPECIMEN_SUBTEXT = "Test account - not a valid tax document"

# --- PDF layout -----------------------------------------------------------------
PAGE_MARGIN = 0.75 * inch
LINE_GAP = 0.18 * inch
SECTION_GAP = 0.3 * inch
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"
TITLE_FONT_SIZE = 14
NAME_FONT_SIZE = 13
BODY_FONT_SIZE = 9
SMALL_FONT_SIZE = 8
TOTAL_FONT_SIZE = 11
WATERMARK_FONT_SIZE = 96
WATERMARK_SUBTEXT_SIZE = 16
WATERMARK_ANGLE = 45
WATERMARK_COLOR = Color(0.8, 0.1, 0.1, alpha=0.18)
COLUMN_SPLIT_RATIO = 0.55
SAC_COLUMN_OFFSET = 1.6 * inch
SIGNATURE_BLOCK_WIDTH = 2.6 * inch
FOOTER_Y = 0.75 * inch
SIGNATURE_Y = 1.45 * inch
COMPUTER_GENERATED_TEXT = (
    "This is a computer-generated document and does not require a physical signature."
)
AUTHORISED_SIGNATORY_TEXT = "Authorised Signatory"


# ----------------------------------------------------------------------------
# Value objects
# ----------------------------------------------------------------------------


class GstDocumentRow(Protocol):
    """The stored GST document fields the read side needs (`BillingInvoice` or its Read schema)."""

    note_type: str
    freight_amount: float
    cgst_amount: float
    sgst_amount: float
    igst_amount: float
    total_amount: float
    line_items: List[Any]


@dataclass(frozen=True)
class GstParty:
    """Supplier or recipient as printed on a GST document."""

    name: str
    address: str
    gstin: Optional[str]
    state_code: Optional[str]

    def to_snapshot(self) -> Dict[str, Any]:
        """JSON-safe dict stored inside `line_items[0]`."""
        return {
            "name": self.name,
            "address": self.address,
            "gstin": self.gstin,
            "state_code": self.state_code,
        }

    @classmethod
    def from_snapshot(cls, raw: Any) -> Optional["GstParty"]:
        """Rebuilds a party from its stored dict; None when nothing was stored."""
        if not isinstance(raw, Mapping):
            return None
        return cls(
            name=str(raw.get("name") or ""),
            address=str(raw.get("address") or ""),
            gstin=raw.get("gstin") or None,
            state_code=raw.get("state_code") or None,
        )


@dataclass(frozen=True)
class ChargeLine:
    """One pre-GST charge (taxable) printed in the document's charge table."""

    label: str
    amount: float


@dataclass(frozen=True)
class GstTaxRow:
    """One printable tax row, e.g. ("CGST @ 9%", 7.20)."""

    label: str
    amount: float


@dataclass(frozen=True)
class GstDocumentView:
    """Everything the PDF prints, read from one stored `BillingInvoice` row."""

    title: str
    note_type: str
    number: str
    document_date: date
    due_date: Optional[date]
    service_type: str
    supplier: GstParty
    bill_to: Optional[GstParty]
    place_of_supply_label: Optional[str]
    reverse_charge: bool
    tracking_id: Optional[str]
    original_invoice_number: Optional[str]
    original_invoice_date: Optional[str]
    detail_line: Optional[str]
    charge_lines: Tuple[ChargeLine, ...]
    taxable_value: float
    tax_rows: Tuple[GstTaxRow, ...]
    total: float
    warning: Optional[str]
    is_specimen: bool

    @property
    def is_note(self) -> bool:
        """True for a credit / debit note (no due date; quotes the original invoice)."""
        return self.note_type != InvoiceNoteType.INVOICE.value


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------


def _round_money(value: float) -> float:
    """Rounds an INR amount to paise."""
    return round(float(value), MONEY_DECIMALS)


def gstin_checksum_char(first_fourteen: str) -> str:
    """
    The 15th (check) character of a GSTIN, from its first 14 characters (GSTN
    mod-36 algorithm: alternate weights 1 and 2, sum quotient + remainder of 36).
    """
    total = 0
    for index, char in enumerate(first_fourteen):
        weight = 1 if index % 2 == 0 else 2
        product = GSTIN_CHECKSUM_ALPHABET.index(char) * weight
        total += product // len(GSTIN_CHECKSUM_ALPHABET) + product % len(GSTIN_CHECKSUM_ALPHABET)
    alphabet_size = len(GSTIN_CHECKSUM_ALPHABET)
    return GSTIN_CHECKSUM_ALPHABET[(alphabet_size - total % alphabet_size) % alphabet_size]


def is_well_formed_gstin(gstin: Optional[str]) -> bool:
    """15-character GSTIN pattern (state digits + PAN + entity + 'Z' + check) and a known state code."""
    candidate = (gstin or "").strip().upper()
    return bool(GSTIN_PATTERN.match(candidate)) and candidate[:GSTIN_STATE_CODE_LENGTH] in GST_STATE_NAMES


def is_checksum_valid_gstin(gstin: Optional[str]) -> bool:
    """Well-formed GSTIN whose 15th character matches the GSTN checksum."""
    candidate = (gstin or "").strip().upper()
    return is_well_formed_gstin(candidate) and gstin_checksum_char(candidate[:14]) == candidate[14]


def pan_from_gstin(gstin: str) -> str:
    """Characters 3-12 of a GSTIN are the holder's PAN."""
    return gstin.strip().upper()[GSTIN_PAN_SLICE]


def place_of_supply_label(state_code: Optional[str]) -> Optional[str]:
    """`"06"` -> `"Haryana (06)"`; an unknown / missing code -> None."""
    name = GST_STATE_NAMES.get(state_code or "")
    return f"{name} ({state_code})" if name else None


def nominal_gst_rate_percent(rate_percent: float) -> float:
    """
    Snaps a derived rate to its GST slab when it is within `SLAB_SNAP_TOLERANCE`
    (18.06 -> 18, rounding noise on small notes); otherwise keeps it to 2 decimals.
    """
    nearest = min(STANDARD_GST_RATES, key=lambda slab: abs(slab - rate_percent))
    if abs(nearest - rate_percent) <= SLAB_SNAP_TOLERANCE:
        return nearest
    return round(rate_percent, RATE_DECIMALS)


def _format_rate(rate_percent: float) -> str:
    """`9.0` -> `"9"`, `2.5` -> `"2.5"`."""
    return f"{round(rate_percent, RATE_DECIMALS):g}"


def gst_tax_rows(
    cgst: float, sgst: float, igst: float, rate_percent: float
) -> List[GstTaxRow]:
    """
    Printable tax rows at the configured rate: one IGST row for an inter-state
    supply, else CGST + SGST at half the rate each. A document with no tax
    (e.g. a credit note after the s.34 deadline) has no tax rows.
    """
    if igst > 0:
        return [GstTaxRow(f"IGST @ {_format_rate(rate_percent)}%", _round_money(igst))]
    if cgst <= 0 and sgst <= 0:
        return []
    half_rate = _format_rate(rate_percent / 2.0)
    return [
        GstTaxRow(f"CGST @ {half_rate}%", _round_money(cgst)),
        GstTaxRow(f"SGST @ {half_rate}%", _round_money(sgst)),
    ]


def first_line_item(invoice: GstDocumentRow) -> Mapping[str, Any]:
    """The document's first stored line item (the issue-time snapshot), or {}."""
    items = invoice.line_items or []
    return items[0] if items and isinstance(items[0], Mapping) else {}


def invoice_rate_percent(invoice: GstDocumentRow) -> float:
    """
    GST rate printed on a document: the configured rate stored at issue
    (snapshot rows), else the legacy derived rate snapped to its GST slab.
    """
    first = first_line_item(invoice)
    stored = first.get("tax_rate_percent")
    if first.get(SNAPSHOT_VERSION_KEY) and stored is not None:
        return float(stored)
    taxable = float(invoice.freight_amount or 0.0)
    tax = float(invoice.cgst_amount or 0.0) + float(invoice.sgst_amount or 0.0) + float(
        invoice.igst_amount or 0.0
    )
    return nominal_gst_rate_percent(tax / taxable * 100.0) if taxable > 0 else 0.0


def invoice_tax_rows(invoice: GstDocumentRow) -> List[GstTaxRow]:
    """Tax rows of a stored document (see `gst_tax_rows`)."""
    return gst_tax_rows(
        float(invoice.cgst_amount or 0.0),
        float(invoice.sgst_amount or 0.0),
        float(invoice.igst_amount or 0.0),
        invoice_rate_percent(invoice),
    )


def is_note_document(invoice: GstDocumentRow) -> bool:
    """True for a credit / debit note (no due date; quotes the original invoice)."""
    return (invoice.note_type or InvoiceNoteType.INVOICE.value) != InvoiceNoteType.INVOICE.value


def document_display_name(invoice: GstDocumentRow) -> str:
    """"Tax Invoice" / "Credit Note" / "Debit Note"."""
    return DOCUMENT_DISPLAY_NAMES.get(
        invoice.note_type, DOCUMENT_DISPLAY_NAMES[InvoiceNoteType.INVOICE.value]
    )


def invoice_bill_to(invoice: GstDocumentRow) -> Optional[GstParty]:
    """The stored recipient; legacy rows only carried the buyer GSTIN (or nothing)."""
    first = first_line_item(invoice)
    return GstParty.from_snapshot(first.get(BILL_TO_KEY)) or _legacy_bill_to(first)


def invoice_supplier_name(invoice: GstDocumentRow) -> Optional[str]:
    """The supplier legal name frozen at issue (None on legacy rows)."""
    supplier = GstParty.from_snapshot(first_line_item(invoice).get(SUPPLIER_KEY))
    return supplier.name if supplier is not None and supplier.name else None


def is_specimen_tenant(slug: Optional[str], settings: Optional[Mapping[str, Any]]) -> bool:
    """Test tenants (allow-listed slug or `settings.environment == "test"`) print SPECIMEN."""
    environment = (settings or {}).get("environment") if isinstance(settings, Mapping) else None
    return (slug or "") in SPECIMEN_TENANT_SLUGS or environment == TEST_ENVIRONMENT_VALUE


def approved_kyc_gstin(entry: Any, supplier_gstin: Optional[str]) -> Optional[str]:
    """
    The merchant's GSTIN from their KYC entry (`settings.b2b_access_requests[uid]`)
    ONLY when it may be printed (audit C-01):
    - the B2B request was APPROVED, or this exact GSTIN was verified with the D2C
      company details (`gstin_status == APPROVED` and `verified_gstin == gstin`);
    - it is a well-formed GSTIN;
    - it is not the tenant's own GSTIN (a seller is never billed to the supplier).
    """
    if not isinstance(entry, Mapping):
        return None
    gstin = str(entry.get("gstin") or "").strip().upper()
    verified_d2c = (
        entry.get(GSTIN_STATUS_KEY) == KYC_APPROVED_STATUS
        and str(entry.get(VERIFIED_GSTIN_KEY) or "").strip().upper() == gstin
    )
    approved = entry.get(KYC_STATUS_KEY) == KYC_APPROVED_STATUS or verified_d2c
    own = (supplier_gstin or "").strip().upper()
    if not approved or not is_well_formed_gstin(gstin) or entry.get("same_as_tenant_gstin"):
        return None
    return gstin if gstin != own else None


def company_details_locked(entry: Any) -> bool:
    """
    True once a merchant's company details are on file: submitted from My profile, or
    an APPROVED B2B KYC with a GSTIN. They are then view-only (changes via a ticket).
    """
    if not isinstance(entry, Mapping):
        return False
    approved_kyc = entry.get(KYC_STATUS_KEY) == KYC_APPROVED_STATUS and bool(entry.get("gstin"))
    return bool(entry.get(COMPANY_DETAILS_SUBMITTED_AT_KEY)) or approved_kyc


def build_bill_to(
    entry: Any,
    account_name: str,
    fallback_address: str,
    fallback_state_code: Optional[str],
    supplier_gstin: Optional[str],
) -> GstParty:
    """
    Recipient ("Bill To") snapshot for a merchant's document: the KYC company name
    and billing address when present, else the account name and the shipment's
    pickup address; GSTIN only when approved (see `approved_kyc_gstin`).
    """
    kyc: Mapping[str, Any] = entry if isinstance(entry, Mapping) else {}
    gstin = approved_kyc_gstin(kyc, supplier_gstin)
    state_code = gstin[:GSTIN_STATE_CODE_LENGTH] if gstin else fallback_state_code
    return GstParty(
        name=str(kyc.get("company_name") or account_name or "").strip(),
        address=str(kyc.get(BILLING_ADDRESS_KEY) or fallback_address or "").strip(),
        gstin=gstin,
        state_code=state_code,
    )


def shipment_charge_lines(
    pricing_breakdown: Optional[Mapping[str, Any]], taxable_value: float
) -> List[ChargeLine]:
    """
    Pre-GST charge lines of a full shipment document, frozen at issue (C-04).

    Every non-zero `pricing_breakdown` component in `SHIPMENT_CHARGE_LABELS` becomes
    a line; any remainder (a surcharge not listed, or rounding) is one "Other
    Charges" line ("Freight Charges" when nothing matched), so the lines always add
    up to the taxable value. Components that exceed it (a stale breakdown) collapse
    to one "Freight Charges" line rather than print a negative balancing line.
    """
    breakdown = pricing_breakdown or {}
    lines: List[ChargeLine] = []
    for key, label in SHIPMENT_CHARGE_LABELS:
        amount = _round_money(float(breakdown.get(key) or 0.0))
        if amount != 0:
            lines.append(ChargeLine(label, amount))
    remainder = _round_money(taxable_value - sum(line.amount for line in lines))
    if remainder < 0:
        return [ChargeLine(LEGACY_CHARGE_LABEL, _round_money(taxable_value))]
    if remainder != 0:
        lines.append(ChargeLine(OTHER_CHARGES_LABEL if lines else LEGACY_CHARGE_LABEL, remainder))
    return lines


def charge_lines_snapshot(lines: Sequence[ChargeLine]) -> List[Dict[str, Any]]:
    """JSON-safe charge lines for `line_items[0]`."""
    return [{"label": line.label, "amount": line.amount} for line in lines]


def format_address(parts: Sequence[Optional[str]]) -> str:
    """Joins the non-blank address parts with ", " (line 1, line 2, landmark, city, state, pincode)."""
    return ", ".join(str(part).strip() for part in parts if part and str(part).strip())


def _stored_charge_lines(first: Mapping[str, Any], invoice: BillingInvoice) -> Tuple[ChargeLine, ...]:
    """Charge lines from the snapshot; legacy rows print one line of the taxable value."""
    raw = first.get(CHARGE_LINES_KEY)
    if isinstance(raw, list) and raw:
        return tuple(
            ChargeLine(str(item.get("label") or ""), float(item.get("amount") or 0.0))
            for item in raw
            if isinstance(item, Mapping)
        )
    description = first.get("description")
    is_vas = VAS_SERVICE_MARKER in (invoice.service_type or "").lower()
    label = VAS_CHARGE_LABEL if is_vas else (str(description) if description else LEGACY_CHARGE_LABEL)
    return (ChargeLine(label, float(invoice.freight_amount or 0.0)),)


def _legacy_supplier(invoice: BillingInvoice, tenant_legal_name: str, first: Mapping[str, Any]) -> GstParty:
    """Supplier of a pre-snapshot row: the stored GSTIN / address and the tenant's legal name."""
    return GstParty(
        name=tenant_legal_name,
        address=invoice.billing_address or "",
        gstin=invoice.gst_number or None,
        state_code=first.get("supplier_state_code"),
    )


def _legacy_bill_to(first: Mapping[str, Any]) -> Optional[GstParty]:
    """Recipient of a pre-snapshot row: only the buyer GSTIN was stored, if any."""
    gstin = first.get("buyer_gstin")
    if not gstin:
        return None
    return GstParty(name="", address="", gstin=gstin, state_code=str(gstin)[:GSTIN_STATE_CODE_LENGTH])


def _detail_line(first: Mapping[str, Any]) -> Optional[str]:
    """`"Chargeable weight 0.50 kg | Gurgaon -> Delhi"` from the snapshot, when present."""
    parts: List[str] = []
    weight = first.get(CHARGEABLE_WEIGHT_KEY)
    if weight:
        parts.append(f"Chargeable weight {float(weight):.2f} kg")
    origin, destination = first.get(ORIGIN_KEY), first.get(DESTINATION_KEY)
    if origin or destination:
        parts.append(f"{origin or '-'} -> {destination or '-'}")
    return " | ".join(parts) or None


def build_document_view(
    invoice: BillingInvoice,
    tenant_legal_name: str,
    is_specimen: bool,
) -> GstDocumentView:
    """
    The printable view of a stored GST document. Reads only the row; the tenant's
    legal name is used solely for legacy rows issued before the snapshot existed.
    """
    first = first_line_item(invoice)
    supplier = GstParty.from_snapshot(first.get(SUPPLIER_KEY)) or _legacy_supplier(
        invoice, tenant_legal_name, first
    )
    bill_to = invoice_bill_to(invoice)
    note_type = invoice.note_type or InvoiceNoteType.INVOICE.value
    is_invoice = note_type == InvoiceNoteType.INVOICE.value
    return GstDocumentView(
        title=DOCUMENT_TITLES.get(note_type, DOCUMENT_TITLES[InvoiceNoteType.INVOICE.value]),
        note_type=note_type,
        number=invoice.invoice_number,
        document_date=invoice.invoice_date,
        due_date=invoice.due_date if is_invoice else None,
        service_type=invoice.service_type or "",
        supplier=supplier,
        bill_to=bill_to,
        place_of_supply_label=place_of_supply_label(first.get("place_of_supply")),
        reverse_charge=bool(first.get(REVERSE_CHARGE_KEY, False)),
        tracking_id=first.get("tracking_id") or None,
        original_invoice_number=first.get("original_invoice_number") or None,
        original_invoice_date=first.get("original_invoice_date") or None,
        detail_line=_detail_line(first),
        charge_lines=_stored_charge_lines(first, invoice),
        taxable_value=_round_money(invoice.freight_amount or 0.0),
        tax_rows=tuple(invoice_tax_rows(invoice)),
        total=_round_money(invoice.total_amount or 0.0),
        warning=first.get("warning") or None,
        is_specimen=is_specimen,
    )


# ----------------------------------------------------------------------------
# PDF renderer (the only one for GST documents)
# ----------------------------------------------------------------------------


def _inr(amount: float) -> str:
    """`1234.5` -> `"INR 1,234.50"`."""
    return f"INR {amount:,.2f}"


def _display_date(value: Any) -> str:
    """`date(2026, 10, 30)` or `"2026-10-30"` -> `"30 Oct 2026"`."""
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    try:
        return date.fromisoformat(str(value)).strftime("%d %b %Y")
    except ValueError:
        return str(value)


def _draw_wrapped(
    c: canvas.Canvas, text: str, x: float, y: float, max_width: float, font_size: float = BODY_FONT_SIZE
) -> float:
    """Draws `text` wrapped to `max_width` from baseline `y`; returns the next free baseline."""
    c.setFont(FONT, font_size)
    for line in simpleSplit(text, FONT, font_size, max_width) or [""]:
        c.drawString(x, y, line)
        y -= LINE_GAP
    return y


def _draw_label_value(c: canvas.Canvas, label: str, value: str, x: float, y: float) -> float:
    """Draws `Label: value` (label in bold); returns the next baseline."""
    c.setFont(FONT_BOLD, BODY_FONT_SIZE)
    c.drawString(x, y, f"{label}:")
    c.setFont(FONT, BODY_FONT_SIZE)
    c.drawString(x + c.stringWidth(f"{label}: ", FONT_BOLD, BODY_FONT_SIZE), y, value)
    return y - LINE_GAP


def _draw_header(c: canvas.Canvas, view: GstDocumentView, width: float, height: float) -> float:
    """Supplier block (left) and document title / number / date (right)."""
    right = width - PAGE_MARGIN
    y = height - PAGE_MARGIN
    c.setFont(FONT_BOLD, NAME_FONT_SIZE)
    c.drawString(PAGE_MARGIN, y, view.supplier.name.upper())
    c.setFont(FONT_BOLD, TITLE_FONT_SIZE)
    c.drawRightString(right, y, view.title)
    c.setFont(FONT, BODY_FONT_SIZE)
    number_label = "Note No" if view.is_note else "Invoice No"
    date_label = "Note Date" if view.is_note else "Invoice Date"
    c.drawRightString(right, y - LINE_GAP, f"{number_label}: {view.number}")
    c.drawRightString(right, y - 2 * LINE_GAP, f"{date_label}: {_display_date(view.document_date)}")
    if view.due_date is not None:
        c.drawRightString(right, y - 3 * LINE_GAP, f"Due Date: {_display_date(view.due_date)}")
    left_width = (width - 2 * PAGE_MARGIN) * COLUMN_SPLIT_RATIO
    y = _draw_wrapped(c, view.supplier.address, PAGE_MARGIN, y - LINE_GAP, left_width)
    y = _draw_label_value(c, "GSTIN", view.supplier.gstin or "-", PAGE_MARGIN, y)
    state = place_of_supply_label(view.supplier.state_code)
    if state:
        y = _draw_label_value(c, "State", state, PAGE_MARGIN, y)
    y = _draw_label_value(c, "SAC", f"{SAC_CODE_COURIER} ({SAC_DESCRIPTION})", PAGE_MARGIN, y)
    y = min(y, height - PAGE_MARGIN - 4 * LINE_GAP) - LINE_GAP / 2
    c.line(PAGE_MARGIN, y, right, y)
    return y - SECTION_GAP


def _draw_parties(c: canvas.Canvas, view: GstDocumentView, width: float, y: float) -> float:
    """"Bill To" (left) and supply details (right): place of supply, RCM, AWB, original invoice."""
    usable = width - 2 * PAGE_MARGIN
    right_x = PAGE_MARGIN + usable * COLUMN_SPLIT_RATIO
    c.setFont(FONT_BOLD, TOTAL_FONT_SIZE)
    c.drawString(PAGE_MARGIN, y, "Bill To")
    c.drawString(right_x, y, "Supply Details")
    left_y = y - LINE_GAP * 1.3
    bill_to = view.bill_to
    if bill_to is not None and bill_to.name:
        c.setFont(FONT_BOLD, BODY_FONT_SIZE)
        c.drawString(PAGE_MARGIN, left_y, bill_to.name)
        left_y -= LINE_GAP
    if bill_to is not None and bill_to.address:
        left_y = _draw_wrapped(c, bill_to.address, PAGE_MARGIN, left_y, usable * COLUMN_SPLIT_RATIO - LINE_GAP)
    gstin_text = bill_to.gstin if bill_to is not None and bill_to.gstin else UNREGISTERED_GSTIN_TEXT
    left_y = _draw_label_value(c, "GSTIN", gstin_text, PAGE_MARGIN, left_y)
    right_y = y - LINE_GAP * 1.3
    right_y = _draw_label_value(c, "Place of Supply", view.place_of_supply_label or "-", right_x, right_y)
    right_y = _draw_label_value(c, "Reverse Charge", "Yes" if view.reverse_charge else "No", right_x, right_y)
    if view.service_type:
        right_y = _draw_label_value(c, "Service", view.service_type, right_x, right_y)
    if view.tracking_id:
        right_y = _draw_label_value(c, "AWB", view.tracking_id, right_x, right_y)
    if view.is_note and view.original_invoice_number:
        right_y = _draw_label_value(c, "Against Invoice", view.original_invoice_number, right_x, right_y)
        if view.original_invoice_date:
            right_y = _draw_label_value(
                c, "Invoice Date", _display_date(view.original_invoice_date), right_x, right_y
            )
    return min(left_y, right_y) - SECTION_GAP / 2


def _draw_charges(c: canvas.Canvas, view: GstDocumentView, width: float, y: float) -> float:
    """Charge table: lines, taxable value, tax rows and the total."""
    right = width - PAGE_MARGIN
    sac_x = right - SAC_COLUMN_OFFSET
    c.line(PAGE_MARGIN, y + LINE_GAP * 0.8, right, y + LINE_GAP * 0.8)
    c.setFont(FONT_BOLD, BODY_FONT_SIZE)
    c.drawString(PAGE_MARGIN, y, "Description")
    c.drawString(sac_x, y, "SAC")
    c.drawRightString(right, y, "Amount")
    y -= LINE_GAP * 0.5
    c.line(PAGE_MARGIN, y, right, y)
    y -= LINE_GAP
    c.setFont(FONT, BODY_FONT_SIZE)
    for line in view.charge_lines:
        c.drawString(PAGE_MARGIN, y, line.label)
        c.drawString(sac_x, y, SAC_CODE_COURIER)
        c.drawRightString(right, y, _inr(line.amount))
        y -= LINE_GAP
    if view.detail_line:
        c.setFont(FONT_ITALIC, SMALL_FONT_SIZE)
        c.drawString(PAGE_MARGIN, y, view.detail_line)
        y -= LINE_GAP
    c.line(PAGE_MARGIN, y + LINE_GAP * 0.4, right, y + LINE_GAP * 0.4)
    y -= LINE_GAP * 0.3
    c.setFont(FONT_BOLD, BODY_FONT_SIZE)
    c.drawString(PAGE_MARGIN, y, "Taxable Value")
    c.drawRightString(right, y, _inr(view.taxable_value))
    y -= LINE_GAP
    c.setFont(FONT, BODY_FONT_SIZE)
    for row in view.tax_rows:
        c.drawString(PAGE_MARGIN, y, row.label)
        c.drawRightString(right, y, _inr(row.amount))
        y -= LINE_GAP
    c.line(PAGE_MARGIN, y + LINE_GAP * 0.4, right, y + LINE_GAP * 0.4)
    y -= LINE_GAP * 0.4
    c.setFont(FONT_BOLD, TOTAL_FONT_SIZE)
    c.drawString(PAGE_MARGIN, y, "Total (incl. GST)")
    c.drawRightString(right, y, _inr(view.total))
    y -= SECTION_GAP
    if view.warning:
        y = _draw_wrapped(c, f"Note: {view.warning}", PAGE_MARGIN, y, width - 2 * PAGE_MARGIN)
    return y


def _draw_footer(c: canvas.Canvas, view: GstDocumentView, width: float) -> None:
    """Signatory block (right) and the computer-generated notice."""
    right = width - PAGE_MARGIN
    c.setFont(FONT_BOLD, BODY_FONT_SIZE)
    c.drawRightString(right, SIGNATURE_Y + 2 * LINE_GAP, f"For {view.supplier.name}")
    c.line(right - SIGNATURE_BLOCK_WIDTH, SIGNATURE_Y, right, SIGNATURE_Y)
    c.setFont(FONT, BODY_FONT_SIZE)
    c.drawRightString(right, SIGNATURE_Y - LINE_GAP, AUTHORISED_SIGNATORY_TEXT)
    c.setFont(FONT_ITALIC, SMALL_FONT_SIZE)
    c.drawString(PAGE_MARGIN, FOOTER_Y, COMPUTER_GENERATED_TEXT)


def _draw_specimen_watermark(c: canvas.Canvas, width: float, height: float) -> None:
    """Large diagonal translucent "SPECIMEN" across the page (C-14)."""
    c.saveState()
    c.setFillColor(WATERMARK_COLOR)
    c.translate(width / 2.0, height / 2.0)
    c.rotate(WATERMARK_ANGLE)
    c.setFont(FONT_BOLD, WATERMARK_FONT_SIZE)
    c.drawCentredString(0, 0, SPECIMEN_TEXT)
    c.setFont(FONT_BOLD, WATERMARK_SUBTEXT_SIZE)
    c.drawCentredString(0, -WATERMARK_SUBTEXT_SIZE * 2, SPECIMEN_SUBTEXT)
    c.restoreState()
    c.setFillColor(black)


def render_gst_document_pdf(view: GstDocumentView) -> io.BytesIO:
    """Renders one GST document (A4, single page) from its view; returns the PDF buffer."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = _draw_header(c, view, width, height)
    y = _draw_parties(c, view, width, y)
    _draw_charges(c, view, width, y)
    _draw_footer(c, view, width)
    if view.is_specimen:
        _draw_specimen_watermark(c, width, height)
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
