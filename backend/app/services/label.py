# backend/app/services/label.py
import functools
import io
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import inch
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont
from reportlab.pdfgen import canvas

from app.core.money import ZERO_MONEY
from app.models.pickups import (
    Address,
    PaymentDetails,
    PickupRequest,
    ServiceOption,
    WeightUnit,
)
from app.models.tenants import Tenant
from app.repositories.shipments import is_b2b_shipment
from app.schemas.v1.pickups import carrier_display_name
from app.services.cod_payout import door_collectible

THERMAL_4X2_FORMAT = "thermal_4x2"

# --- Page geometry (ReportLab points; 72 pt = 1 inch) ---
LABEL_WIDTH = 4 * inch
"""Thermal labels (4x6 and 4x2) are 4 inches (288 pt) wide."""
LABEL_4X6_HEIGHT = 6 * inch
LABEL_4X2_HEIGHT = 2 * inch
LABEL_TEXT_X = 0.2 * inch
"""Left edge of label text."""
LABEL_RULE_INSET = 0.1 * inch
"""Horizontal rules and barcodes keep this distance from the label edge."""
LABEL_TEXT_WIDTH = LABEL_WIDTH - 2 * LABEL_TEXT_X
LABEL_BARCODE_USABLE_WIDTH = LABEL_WIDTH - 2 * LABEL_RULE_INSET
"""Widest a label barcode may be, quiet zones included, so it is never clipped."""

# --- Barcodes ---
BARCODE_MAX_BAR_WIDTH = 1.5
"""Widest Code128 module (pt): short AWBs stay at this width instead of stretching."""
DOCKET_BARCODE_MAX_BAR_WIDTH = 1.2
"""Module width cap for the master LR barcode on the A4 docket."""
BARCODE_QUIET_ZONE_MODULES = 10
"""Code128 needs a blank margin of 10 modules on each side to scan."""
QR_ERROR_CORRECTION_LEVEL = "M"
"""QR error correction level M (~15 %) survives smudged thermal prints."""

# --- Fonts & text ---
BASE_FONT = "Helvetica"
BOLD_FONT = "Helvetica-Bold"
LINE_HEIGHT_FACTOR = 1.2
"""Baseline-to-baseline distance as a multiple of the font size."""
CAP_HEIGHT_FACTOR = 0.7
"""Approximate capital-letter height as a multiple of the font size (vertical centring)."""
ELLIPSIS = "..."
EMPTY_TRACKING_ID = "PENDING"

# --- Money ---
RUPEE_SYMBOL = "\u20b9"
RUPEE_FALLBACK_PREFIX = "Rs. "
"""Used when no font with the rupee glyph is installed (Helvetica has no U+20B9)."""
RUPEE_FONT_NAME = "LabelRupeeSansBold"
RUPEE_FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
)
"""Bold TrueType fonts that contain the rupee glyph, tried in order."""
INDIAN_LAST_GROUP_DIGITS = 3
INDIAN_GROUP_DIGITS = 2
"""en-IN digit grouping: 12,34,567.89 (last three digits, then pairs)."""
PREPAID_LABEL = "PREPAID"
COD_LABEL_TEMPLATE = "COD \u2013 Collect {amount}"

# --- Weights ---
GRAMS_PER_KG = 1000.0

# --- Terms footer ---
TERMS_URL_PATH = "/terms"
"""Tenant-relative terms page (public-ux, board #356); the backend has no tenant host yet."""
TERMS_FOOTER_TEMPLATE = "Carried subject to {tenant} Terms of Service & Carriage: {url}"

# --- B2C 4x6 layout (y measured from the bottom of the page) ---
B2C_HEADER_Y = 5.6 * inch
B2C_HEADER_RULE_Y = 5.4 * inch
B2C_HEADER_BRAND_FONT_SIZE = 16
B2C_HEADER_SERVICE_FONT_SIZE = 12
B2C_ADDRESS_TOP_Y = 5.3 * inch
B2C_ADDRESS_FLOOR_Y = 2.8 * inch
"""Address text must stay above this line (top of the payment block plus a gap)."""
B2C_SECTION_GAP = 6
B2C_PAYMENT_BOX_Y = 2.3 * inch
B2C_PAYMENT_BOX_HEIGHT = 0.45 * inch
B2C_PAYMENT_FONT_SIZE = 16
B2C_PAYMENT_MIN_FONT_SIZE = 9
B2C_PAYMENT_TEXT_PADDING = 6
B2C_INFO_FONT_SIZE = 10
B2C_INFO_MIN_FONT_SIZE = 7
"""Long info lines (e.g. a carrier AWB) shrink to this size before being ellipsized."""
B2C_WEIGHT_Y = 2.05 * inch
B2C_BOXES_Y = 1.83 * inch
B2C_REF_Y = 1.61 * inch
B2C_CARRIER_Y = 1.39 * inch
"""Fourth info line: the carrier and its own AWB once ops entered it."""
B2C_QR_SIZE = 0.95 * inch
B2C_QR_Y = 1.25 * inch
B2C_QR_X = LABEL_WIDTH - LABEL_TEXT_X - B2C_QR_SIZE
B2C_INFO_TEXT_WIDTH = B2C_QR_X - LABEL_TEXT_X - B2C_SECTION_GAP
B2C_INFO_RULE_Y = 1.2 * inch
B2C_BARCODE_Y = 0.48 * inch
B2C_BARCODE_HEIGHT = 0.65 * inch
B2C_AWB_TEXT_Y = 0.3 * inch
B2C_AWB_FONT_SIZE = 12
B2C_FOOTER_Y = 0.12 * inch
B2C_FOOTER_FONT_SIZE = 6

# --- 4x2 thermal and B2B box label barcodes / QR ---
THERMAL_BARCODE_Y = 0.55 * inch
THERMAL_BARCODE_HEIGHT = 0.42 * inch
BOX_LABEL_BARCODE_Y = 1.1 * inch
BOX_LABEL_BARCODE_HEIGHT = 0.8 * inch
BOX_LABEL_COUNTER_Y = 5.1 * inch
BOX_LABEL_COUNTER_FONT_SIZE = 10
BOX_LABEL_MIN_FONT_SIZE = 7
BOX_LABEL_QR_SIZE = 0.7 * inch
BOX_LABEL_QR_X = LABEL_WIDTH - LABEL_TEXT_X - BOX_LABEL_QR_SIZE
BOX_LABEL_QR_Y = 2.7 * inch

# --- B2B Lorry Receipt (A4 docket) ---
LR_COPY_LABELS: Tuple[str, ...] = (
    "CONSIGNOR COPY",
    "CONSIGNEE COPY",
    "DRIVER / TRANSPORTER COPY",
)
"""Indian LR practice: the consignor keeps one copy, the driver carries the consignee's and his own."""
BOX_LABEL_TITLE = "BOX LABEL"
BOX_LABEL_TITLE_FONT_SIZE = 10
BOX_LABEL_BRAND_FONT_SIZE = 14
DOCKET_TITLE = "LORRY RECEIPT / FREIGHT DOCKET"
DOCKET_TITLE_FONT_SIZE = 14
DOCKET_BRAND_FONT_SIZE = 22
DOCKET_BRAND_MIN_FONT_SIZE = 12
DOCKET_BRAND_TITLE_GAP = 12
DOCKET_CELL_PADDING = 4
DOCKET_LEDGER_RULE_RISE = 11
"""Rule above the GST row: clear of 9 pt text (the old +5 struck through it)."""
DOCKET_TOTAL_RULE_RISE = 13
DOCKET_COPY_TAG_Y = 806
DOCKET_COPY_TAG_FONT_SIZE = 9
DOCKET_COPY_TAG_PADDING = 4
DOCKET_SPECS_ROW_HEIGHT = 48
"""Header + values row of the specs table; the compliance row sits below it."""
DOCKET_COMPLIANCE_FONT_SIZE = 8
DOCKET_COMPLIANCE_BASELINE_OFFSET = 16
DOCKET_MAX_CHARGE_LINES = 6
"""Rows that fit the ledger box above GST + total; extra rows are folded into "Other charges"."""
SELL_LINES_KEY = "sell_lines"
GST_SELL_LINE_CODE = "GST"
OTHER_CHARGES_LABEL = "Other charges"
NOT_AVAILABLE = "N/A"
LEGACY_DOCKET_LINES: Tuple[Tuple[str, str], ...] = (
    ("docket_charge", "Docket Fee"),
    ("fov_charge", "FOV Surcharge (Carrier's Risk)"),
    ("fuel_surcharge", "Fuel Surcharge"),
)
LEGACY_OPTIONAL_DOCKET_LINES: Tuple[Tuple[str, str], ...] = (
    ("oversized_surcharge", "Oversized Surcharge"),
    ("network_surcharge", "Network Surcharge"),
    ("cod_fee", "COD Collection Fee"),
    ("rto_surcharge", "RTO Surcharge"),
)
"""Right of the weight/dims lines, between the 2.65" and 3.45" rules."""


@dataclass(frozen=True)
class AddressStyle:
    """Typography of one address block on the 4x6 label."""

    title: str
    heading_font_size: float
    body_font_size: float
    street_max_lines: int
    locality_max_lines: int


FROM_ADDRESS_STYLE = AddressStyle("FROM", 9, 8, 2, 1)
TO_ADDRESS_STYLE = AddressStyle("TO", 12, 10, 3, 2)

TextRow = Tuple[str, str, float, int]
"""(text, font name, font size, max wrapped lines) for one label row."""


def safe_float(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def fitted_code128(
    value: str,
    usable_width: float,
    bar_height: float,
    max_bar_width: float = BARCODE_MAX_BAR_WIDTH,
) -> code128.Code128:
    """
    Builds a Code128 barcode whose total width (quiet zones included) fits `usable_width`.

    The module (bar) width is derived from the encoded symbol count, so long AWBs such as
    `LOGISMART-TEST-X9A2B3C4-B12` shrink to fit instead of being clipped by the page edge.

    Args:
        value: Text to encode.
        usable_width: Horizontal space available, in points.
        bar_height: Bar height, in points.
        max_bar_width: Upper bound for the module width (short values don't stretch).

    Returns:
        The barcode, ready for `drawOn`.
    """
    modules = code128.Code128(value, barWidth=1.0, quiet=False).width
    bar_width = min(max_bar_width, usable_width / (modules + 2 * BARCODE_QUIET_ZONE_MODULES))
    quiet = BARCODE_QUIET_ZONE_MODULES * bar_width
    return code128.Code128(
        value, barWidth=bar_width, barHeight=bar_height, lquiet=quiet, rquiet=quiet
    )


def _draw_centered_barcode(
    c: canvas.Canvas, value: str, y: float, bar_height: float
) -> None:
    """Draws a label-width-fitted Code128 barcode centred on a 4" label."""
    barcode = fitted_code128(value, LABEL_BARCODE_USABLE_WIDTH, bar_height)
    barcode.drawOn(c, (LABEL_WIDTH - barcode.width) / 2.0, y)


def _draw_qr(c: canvas.Canvas, value: str, x: float, y: float, size: float) -> None:
    """
    Draws a square QR code of `value` with its lower-left corner at (x, y).

    Args:
        c: Target canvas.
        value: Text to encode (the AWB).
        x: Left edge, in points.
        y: Bottom edge, in points.
        size: Side length, in points.
    """
    widget = QrCodeWidget(value, barLevel=QR_ERROR_CORRECTION_LEVEL)
    x0, y0, x1, y1 = widget.getBounds()
    drawing = Drawing(
        size, size, transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0]
    )
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def _with_ellipsis(text: str, font: str, size: float, width: float) -> str:
    """Appends an ellipsis to `text`, cutting characters until the result fits `width`."""
    while text and pdfmetrics.stringWidth(text + ELLIPSIS, font, size) > width:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


def _ellipsize(text: str, font: str, size: float, width: float) -> str:
    """`text` unchanged when it fits `width`, else cut with an ellipsis."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    return _with_ellipsis(text, font, size, width)


def wrap_text(text: str, font: str, size: float, width: float, max_lines: int) -> List[str]:
    """
    Wraps `text` to `width` (ReportLab `simpleSplit`), keeping at most `max_lines` lines.

    Args:
        text: Text to wrap.
        font: Font name used to measure.
        size: Font size, in points.
        width: Line width, in points.
        max_lines: Line budget; the last kept line gets an ellipsis if text was cut.

    Returns:
        Lines that each fit `width`.
    """
    lines = [_ellipsize(line, font, size, width) for line in simpleSplit(text, font, size, width)]
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    kept[-1] = _with_ellipsis(kept[-1], font, size, width)
    return kept


def _fit_font_size(text: str, font: str, max_size: float, min_size: float, width: float) -> float:
    """Largest whole font size in [min_size, max_size] at which `text` fits `width`."""
    size = max_size
    while size > min_size and pdfmetrics.stringWidth(text, font, size) > width:
        size -= 1
    return size


def format_inr(amount: Decimal) -> str:
    """
    Formats a rupee amount with en-IN digit grouping and 2 decimals, e.g. `12,34,567.50`.

    Display only: the amount is formatted, never recomputed.
    """
    whole, fraction = f"{amount:.2f}".split(".")
    sign = "-" if whole.startswith("-") else ""
    digits = whole.lstrip("-")
    head, tail = digits[:-INDIAN_LAST_GROUP_DIGITS], digits[-INDIAN_LAST_GROUP_DIGITS:]
    groups: List[str] = []
    while head:
        groups.insert(0, head[-INDIAN_GROUP_DIGITS:])
        head = head[:-INDIAN_GROUP_DIGITS]
    return f"{sign}{','.join(groups + [tail])}.{fraction}"


@functools.lru_cache(maxsize=1)
def _rupee_font() -> Optional[str]:
    """Registers (once) the first installed font with the rupee glyph; None if there is none."""
    for path in RUPEE_FONT_PATHS:
        if not os.path.isfile(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(RUPEE_FONT_NAME, path))
        except TTFError:
            continue
        return RUPEE_FONT_NAME
    return None


def payment_font_and_currency() -> Tuple[str, str]:
    """(font, currency prefix) for money text: ₹ with a Unicode font, else `Rs. ` in Helvetica."""
    font = _rupee_font()
    if font:
        return font, RUPEE_SYMBOL
    return BOLD_FONT, RUPEE_FALLBACK_PREFIX


def payment_block_text(payment: Optional[PaymentDetails], currency: str) -> str:
    """
    The rider's payment instruction: `COD – Collect ₹X` or `PREPAID`.

    X is `cod_payout.door_collectible` (the single source of the door amount); nothing
    is recomputed here. Zero (or no payment details) means nothing to collect.

    Args:
        payment: The shipment's payment details.
        currency: Currency prefix (`₹` or the `Rs. ` fallback).

    Returns:
        The text for the payment block.
    """
    amount = door_collectible(payment)
    if amount <= ZERO_MONEY:
        return PREPAID_LABEL
    return COD_LABEL_TEMPLATE.format(amount=f"{currency}{format_inr(amount)}")


def total_boxes(shipment: PickupRequest) -> int:
    """
    Real carton count: the blind-pickup estimate, else the sum of package box counts.

    Args:
        shipment: The shipment.

    Returns:
        At least 1.
    """
    if shipment.is_blind_pickup and shipment.estimated_box_count:
        return shipment.estimated_box_count
    packaged = sum((pkg.box_count or 1) for pkg in (shipment.packages or []))
    return packaged or (shipment.estimated_box_count or 1)


def _physical_weight_kg(shipment: PickupRequest) -> float:
    """Declared weight across all boxes in KG (each package weight × its box count)."""
    total = 0.0
    for pkg in shipment.packages or []:
        weight = safe_float(pkg.weight)
        if pkg.weight_unit == WeightUnit.G:
            weight /= GRAMS_PER_KG
        total += weight * (pkg.box_count or 1)
    return total


def label_weight_kg(shipment: PickupRequest) -> float:
    """
    Shipment weight printed on labels: the billed `chargeable_weight` when priced,
    else the declared weight summed over every box.
    """
    payment = shipment.payment_details
    chargeable = safe_float(payment.chargeable_weight) if payment else 0.0
    return chargeable if chargeable > 0 else _physical_weight_kg(shipment)


def _non_empty(value: Optional[str]) -> Optional[str]:
    """The stripped value, or None when it is missing or blank."""
    stripped = (value or "").strip()
    return stripped or None


def _format_phone(addr: Address) -> str:
    """Primary phone, plus the alternate one when present."""
    if getattr(addr, "alternate_phone", None):
        return f"{addr.phone}, {addr.alternate_phone}"
    return addr.phone


def address_rows(addr: Address, style: AddressStyle) -> List[TextRow]:
    """
    Rows of one address block: name, street (line 1 + line 2), landmark, locality, phone.

    Args:
        addr: The address snapshot.
        style: Fonts and line budgets of the block.

    Returns:
        Rows in print order; empty fields are left out.
    """
    street = ", ".join(
        part for part in (_non_empty(addr.address_line1), _non_empty(addr.address_line2)) if part
    )
    landmark = _non_empty(addr.landmark)
    locality = f"{addr.city}, {addr.state} {addr.pincode}"
    rows: List[TextRow] = [(f"{style.title}: {addr.name}", BOLD_FONT, style.heading_font_size, 1)]
    if street:
        rows.append((street, BASE_FONT, style.body_font_size, style.street_max_lines))
    if landmark:
        rows.append((f"Landmark: {landmark}", BASE_FONT, style.body_font_size, 1))
    rows.append((locality, BOLD_FONT, style.heading_font_size, style.locality_max_lines))
    rows.append((f"Ph: {_format_phone(addr)}", BASE_FONT, style.body_font_size, 1))
    return rows


def draw_text_rows(c: canvas.Canvas, rows: List[TextRow], top_y: float, width: float) -> float:
    """
    Draws wrapped rows top-down from `top_y` at the label text margin.

    Args:
        c: Target canvas.
        rows: Rows to draw.
        top_y: Top of the first line, in points.
        width: Wrap width, in points.

    Returns:
        The y of the last baseline drawn (the block's bottom).
    """
    y = top_y
    for text, font, size, max_lines in rows:
        c.setFont(font, size)
        for line in wrap_text(text, font, size, width, max_lines):
            y -= size * LINE_HEIGHT_FACTOR
            c.drawString(LABEL_TEXT_X, y, line)
    return y


def b2c_info_lines(shipment: PickupRequest) -> List[str]:
    """
    WEIGHT / BOXES / REF / CARRIER lines of the B2C label.

    REF is left out when empty. The carrier line ("DELHIVERY AWB: 1234") appears once ops
    entered the carrier's own AWB, so the parcel can be matched to the carrier's label.
    """
    lines = [
        f"WEIGHT: {label_weight_kg(shipment):.2f} KG",
        f"BOXES: {total_boxes(shipment)}",
    ]
    reference = _non_empty(shipment.order_reference_id)
    if reference:
        lines.append(f"REF: {reference}")
    carrier_awb = _non_empty(shipment.carrier_awb)
    if carrier_awb:
        carrier = carrier_display_name(shipment.service_option or ServiceOption.DELHIVERY_SURFACE)
        lines.append(f"{carrier.upper()} AWB: {carrier_awb}")
    return lines


def terms_footer_text(tenant: Tenant) -> str:
    """Footer line pointing to the tenant's terms of carriage."""
    return TERMS_FOOTER_TEMPLATE.format(tenant=tenant.name, url=TERMS_URL_PATH)


def _sell_line_rows(breakdown: dict) -> Optional[List[Tuple[str, float]]]:
    """
    Pre-GST `(label, amount)` rows from the backend `sell_lines`, or None when absent.

    `sell_lines` are the exact rows the customer saw on the quote (freight, docket, pickup,
    door delivery, FOV ...), so the printed LR matches the booking screen.
    """
    raw = breakdown.get(SELL_LINES_KEY)
    if not isinstance(raw, list) or not raw:
        return None
    return [
        (str(line.get("label") or line.get("code") or ""), safe_float(line.get("amount")))
        for line in raw
        if isinstance(line, dict) and line.get("code") != GST_SELL_LINE_CODE
    ]


def _legacy_charge_rows(payment: PaymentDetails, breakdown: dict) -> List[Tuple[str, float]]:
    """Rows for shipments priced before `sell_lines`: base freight, fixed rows, non-zero extras."""
    rows = [("Base Freight", safe_float(payment.base_freight))]
    rows += [(label_text, safe_float(breakdown.get(key))) for key, label_text in LEGACY_DOCKET_LINES]
    rows += [
        (label_text, safe_float(breakdown.get(key)))
        for key, label_text in LEGACY_OPTIONAL_DOCKET_LINES
        if safe_float(breakdown.get(key)) > 0
    ]
    return rows


def docket_charge_lines(payment: Optional[PaymentDetails]) -> List[Tuple[str, float]]:
    """
    Pre-GST charge rows printed in the LR docket's freight ledger.

    Rows beyond `DOCKET_MAX_CHARGE_LINES` are folded into one "Other charges" row so the
    ledger never overflows its box.

    Args:
        payment: The shipment's payment details (None prints nothing).

    Returns:
        `(label, amount)` rows, at most `DOCKET_MAX_CHARGE_LINES`.
    """
    if payment is None:
        return []
    breakdown = payment.pricing_breakdown or {}
    rows = _sell_line_rows(breakdown) or _legacy_charge_rows(payment, breakdown)
    if len(rows) <= DOCKET_MAX_CHARGE_LINES:
        return rows
    kept = rows[: DOCKET_MAX_CHARGE_LINES - 1]
    folded = sum(amount for _, amount in rows[DOCKET_MAX_CHARGE_LINES - 1:])
    return kept + [(OTHER_CHARGES_LABEL, folded)]


def _joined_or_na(values: Optional[List[str]]) -> str:
    """Comma-joined non-blank values, or `N/A`."""
    cleaned = [value.strip() for value in (values or []) if value and value.strip()]
    return ", ".join(cleaned) if cleaned else NOT_AVAILABLE


def docket_compliance_text(shipment: PickupRequest) -> str:
    """
    The LR docket's compliance row: GST invoice no(s), e-way bill no(s), goods value and, once
    ops have booked it on the carrier, the carrier's AWB (Delhivery One `b2b-order-creation`:
    every B2B LR carries its invoice, and an e-way bill above Rs 50,000).
    """
    payment = shipment.payment_details
    invoices = _joined_or_na(payment.invoice_numbers if payment else None)
    eway_bills = _joined_or_na(payment.eway_bill_numbers if payment else None)
    goods_value = safe_float(payment.shipment_total_value if payment else 0.0)
    parts = [
        f"INVOICE NO: {invoices}",
        f"E-WAY BILL NO: {eway_bills}",
        f"GOODS VALUE: Rs. {goods_value:,.2f}",
    ]
    carrier_awb = _non_empty(shipment.carrier_awb)
    if carrier_awb:
        carrier = carrier_display_name(shipment.service_option or ServiceOption.DELHIVERY_SURFACE)
        parts.append(f"{carrier.upper()} AWB: {carrier_awb}")
    return "  |  ".join(parts)


class LabelGenerator:
    """
    Generates shipping labels and freight dockets.
    Supports consolidated multi-page A4 + 4x6 layouts for B2B cargo,
    and standard 4x6 labels for B2C express shipments.
    """

    @staticmethod
    def _format_phone(addr) -> str:
        return _format_phone(addr)

    @staticmethod
    def _is_b2b(shipment: PickupRequest, tenant: Tenant) -> bool:
        """
        True when the shipment gets the B2B LR docket + box labels layout.

        Uses the shared classifier `is_b2b_shipment` (same rule as listings,
        pricing and the wallet), plus a tenant configured as B2B-only.
        """
        if is_b2b_shipment(shipment):
            return True
        settings = tenant.settings or {}
        return settings.get("is_b2b") is True or settings.get("mode") == "b2b"

    @staticmethod
    def generate_pdf(
        shipment: PickupRequest, tenant: Tenant, label_format: str = "a4"
    ) -> io.BytesIO:
        return LabelGenerator.generate_batch_pdf([shipment], tenant, label_format)

    @staticmethod
    def generate_batch_pdf(
        shipments: List[PickupRequest], tenant: Tenant, label_format: str = "a4"
    ) -> io.BytesIO:
        """
        Renders labels for N shipments into ONE merged PDF (e.g. 'Print label' on a Pickup Request).
        Each shipment keeps its own layout (thermal 4x2, B2B LR docket + box labels, or B2C 4x6);
        page sizes are switched per page on a single ReportLab canvas, so no PDF-merge library is needed.
        """
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer)
        for shipment in shipments:
            LabelGenerator._draw_shipment_pages(c, shipment, tenant, label_format)
        c.save()
        buffer.seek(0)
        return buffer

    @staticmethod
    def _draw_shipment_pages(
        c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant, label_format: str
    ) -> None:
        """Dispatches one shipment to the right label layout on a shared canvas."""
        if label_format == THERMAL_4X2_FORMAT:
            LabelGenerator._draw_thermal_4x2_pages(c, shipment, tenant)
        elif LabelGenerator._is_b2b(shipment, tenant):
            LabelGenerator._draw_b2b_pages(c, shipment, tenant)
        else:
            LabelGenerator._draw_b2c_pages(c, shipment, tenant)

    @staticmethod
    def _draw_thermal_4x2_pages(
        c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant
    ) -> None:
        """
        Draws compact 4\"x2\" thermal box labels (one page per box or 1 master page).
        """
        label_width = LABEL_WIDTH
        label_height = LABEL_4X2_HEIGHT

        tracking_str = shipment.tracking_id or EMPTY_TRACKING_ID
        box_total = total_boxes(shipment)
        total_weight = label_weight_kg(shipment)

        for box_idx in range(1, box_total + 1):
            c.setPageSize((label_width, label_height))
            child_awb = (
                f"{tracking_str}-B{box_idx}" if box_total > 1 else tracking_str
            )
            right_meta = (
                f"{shipment.service_type.value.replace('_', ' ')} | BOX {box_idx}/{box_total}"
            )
            c.setFont(BOLD_FONT, 8)
            c.drawRightString(3.85 * inch, 1.78 * inch, right_meta)
            brand = tenant.name.upper()
            brand_width = (
                3.7 * inch
                - pdfmetrics.stringWidth(right_meta, BOLD_FONT, 8)
                - B2C_SECTION_GAP
            )
            brand_size = _fit_font_size(brand, BOLD_FONT, 10, 7, brand_width)
            c.setFont(BOLD_FONT, brand_size)
            c.drawString(
                0.15 * inch,
                1.78 * inch,
                _ellipsize(brand, BOLD_FONT, brand_size, brand_width),
            )
            c.line(0.1 * inch, 1.70 * inch, 3.9 * inch, 1.70 * inch)

            c.setFont("Helvetica-Bold", 8)
            c.drawString(
                0.15 * inch,
                1.53 * inch,
                f"TO: {shipment.delivery_address.name[:28]} ({shipment.delivery_address.pincode})",
            )
            c.setFont("Helvetica", 7.5)
            c.drawString(
                0.15 * inch,
                1.38 * inch,
                f"{shipment.delivery_address.city}, {shipment.delivery_address.state} | Ph: {LabelGenerator._format_phone(shipment.delivery_address)}",
            )
            c.drawString(
                0.15 * inch,
                1.23 * inch,
                f"FROM: {shipment.pickup_address.city} ({shipment.pickup_address.pincode}) | WT: {total_weight:.1f} KG",
            )
            c.line(0.1 * inch, 1.13 * inch, 3.9 * inch, 1.13 * inch)

            _draw_centered_barcode(c, child_awb, THERMAL_BARCODE_Y, THERMAL_BARCODE_HEIGHT)

            c.setFont("Helvetica-Bold", 9)
            c.drawCentredString(label_width / 2.0, 0.35 * inch, child_awb)
            c.setFont("Helvetica", 7)
            c.drawCentredString(
                label_width / 2.0,
                0.18 * inch,
                f"Master LR: {tracking_str} | PO: {shipment.po_number or 'N/A'}",
            )
            c.showPage()

    @staticmethod
    def _draw_b2c_pages(c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant) -> None:
        """
        Draws the B2C 4x6 label: header, FROM/TO, payment block, weight/boxes/ref + QR,
        AWB barcode and the terms footer.
        """
        c.setPageSize((LABEL_WIDTH, LABEL_4X6_HEIGHT))
        LabelGenerator._draw_b2c_header(c, shipment, tenant)
        LabelGenerator._draw_b2c_addresses(c, shipment)
        LabelGenerator._draw_b2c_payment_block(c, shipment)
        LabelGenerator._draw_b2c_info(c, shipment)
        LabelGenerator._draw_b2c_awb(c, shipment, tenant)
        # Finalize this label page (the caller saves the shared canvas)
        c.showPage()

    @staticmethod
    def _draw_b2c_header(c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant) -> None:
        """Brand on the left, service type on the right, then a rule."""
        service = shipment.service_type.value
        c.setFont(BOLD_FONT, B2C_HEADER_SERVICE_FONT_SIZE)
        c.drawRightString(LABEL_WIDTH - LABEL_TEXT_X, B2C_HEADER_Y, service)
        brand_width = (
            LABEL_TEXT_WIDTH
            - pdfmetrics.stringWidth(service, BOLD_FONT, B2C_HEADER_SERVICE_FONT_SIZE)
            - B2C_SECTION_GAP
        )
        c.setFont(BOLD_FONT, B2C_HEADER_BRAND_FONT_SIZE)
        c.drawString(
            LABEL_TEXT_X,
            B2C_HEADER_Y,
            _ellipsize(tenant.name.upper(), BOLD_FONT, B2C_HEADER_BRAND_FONT_SIZE, brand_width),
        )
        c.line(LABEL_RULE_INSET, B2C_HEADER_RULE_Y, LABEL_WIDTH - LABEL_RULE_INSET, B2C_HEADER_RULE_Y)

    @staticmethod
    def _draw_b2c_addresses(c: canvas.Canvas, shipment: PickupRequest) -> float:
        """
        Draws the FROM block, a rule, then the TO block, wrapping long lines.

        Returns:
            The y of the last baseline (stays above `B2C_ADDRESS_FLOOR_Y` by design).
        """
        y = draw_text_rows(
            c,
            address_rows(shipment.pickup_address, FROM_ADDRESS_STYLE),
            B2C_ADDRESS_TOP_Y,
            LABEL_TEXT_WIDTH,
        )
        y -= B2C_SECTION_GAP
        c.line(LABEL_RULE_INSET, y, LABEL_WIDTH - LABEL_RULE_INSET, y)
        return draw_text_rows(
            c,
            address_rows(shipment.delivery_address, TO_ADDRESS_STYLE),
            y - B2C_SECTION_GAP,
            LABEL_TEXT_WIDTH,
        )

    @staticmethod
    def _draw_b2c_payment_block(c: canvas.Canvas, shipment: PickupRequest) -> None:
        """Full-width black bar with `COD – Collect ₹X` or `PREPAID` in white."""
        font, currency = payment_font_and_currency()
        text = payment_block_text(shipment.payment_details, currency)
        box_width = LABEL_WIDTH - 2 * LABEL_RULE_INSET
        size = _fit_font_size(
            text,
            font,
            B2C_PAYMENT_FONT_SIZE,
            B2C_PAYMENT_MIN_FONT_SIZE,
            box_width - 2 * B2C_PAYMENT_TEXT_PADDING,
        )
        c.rect(LABEL_RULE_INSET, B2C_PAYMENT_BOX_Y, box_width, B2C_PAYMENT_BOX_HEIGHT, stroke=0, fill=1)
        c.setFillColorRGB(1, 1, 1)
        c.setFont(font, size)
        baseline = B2C_PAYMENT_BOX_Y + (B2C_PAYMENT_BOX_HEIGHT - size * CAP_HEIGHT_FACTOR) / 2.0
        c.drawCentredString(LABEL_WIDTH / 2.0, baseline, text)
        c.setFillColorRGB(0, 0, 0)

    @staticmethod
    def _draw_b2c_info(c: canvas.Canvas, shipment: PickupRequest) -> None:
        """WEIGHT / BOXES / REF / CARRIER on the left and a QR of the AWB on the right."""
        info_rows_y = (B2C_WEIGHT_Y, B2C_BOXES_Y, B2C_REF_Y, B2C_CARRIER_Y)
        for line, y in zip(b2c_info_lines(shipment), info_rows_y):
            size = _fit_font_size(
                line, BOLD_FONT, B2C_INFO_FONT_SIZE, B2C_INFO_MIN_FONT_SIZE, B2C_INFO_TEXT_WIDTH
            )
            c.setFont(BOLD_FONT, size)
            c.drawString(LABEL_TEXT_X, y, _ellipsize(line, BOLD_FONT, size, B2C_INFO_TEXT_WIDTH))
        if shipment.tracking_id:
            _draw_qr(c, shipment.tracking_id, B2C_QR_X, B2C_QR_Y, B2C_QR_SIZE)
        c.line(LABEL_RULE_INSET, B2C_INFO_RULE_Y, LABEL_WIDTH - LABEL_RULE_INSET, B2C_INFO_RULE_Y)

    @staticmethod
    def _draw_b2c_awb(c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant) -> None:
        """Fitted Code128 barcode of the AWB, the AWB in text, and the terms footer."""
        tracking_str = shipment.tracking_id or EMPTY_TRACKING_ID
        _draw_centered_barcode(c, tracking_str, B2C_BARCODE_Y, B2C_BARCODE_HEIGHT)
        c.setFont(BOLD_FONT, B2C_AWB_FONT_SIZE)
        c.drawCentredString(LABEL_WIDTH / 2.0, B2C_AWB_TEXT_Y, tracking_str)
        c.setFont(BASE_FONT, B2C_FOOTER_FONT_SIZE)
        c.drawCentredString(
            LABEL_WIDTH / 2.0,
            B2C_FOOTER_Y,
            _ellipsize(terms_footer_text(tenant), BASE_FONT, B2C_FOOTER_FONT_SIZE, LABEL_TEXT_WIDTH),
        )

    @staticmethod
    def _draw_docket_copy_tag(c: canvas.Canvas, right_x: float, copy_label: str) -> None:
        """Boxed copy marker (`CONSIGNOR COPY` ...) right-aligned above the docket title."""
        c.setFont(BOLD_FONT, DOCKET_COPY_TAG_FONT_SIZE)
        width = pdfmetrics.stringWidth(copy_label, BOLD_FONT, DOCKET_COPY_TAG_FONT_SIZE)
        pad = DOCKET_COPY_TAG_PADDING
        c.rect(
            right_x - width - 2 * pad,
            DOCKET_COPY_TAG_Y - pad,
            width + 2 * pad,
            DOCKET_COPY_TAG_FONT_SIZE + 2 * pad,
        )
        c.drawRightString(right_x - pad, DOCKET_COPY_TAG_Y, copy_label)

    @staticmethod
    def _draw_box_label_counter_row(
        c: canvas.Canvas, master_awb: Optional[str], box_number: int, box_total: int
    ) -> None:
        """`MASTER LR: <awb>` on the left, `BOX: n OF N` on the right; the AWB shrinks to fit."""
        counter = f"BOX: {box_number} OF {box_total}"
        master = f"MASTER LR: {master_awb or EMPTY_TRACKING_ID}"
        c.setFont(BOLD_FONT, BOX_LABEL_COUNTER_FONT_SIZE)
        c.drawRightString(LABEL_WIDTH - LABEL_TEXT_X, BOX_LABEL_COUNTER_Y, counter)
        width = (
            LABEL_TEXT_WIDTH
            - pdfmetrics.stringWidth(counter, BOLD_FONT, BOX_LABEL_COUNTER_FONT_SIZE)
            - B2C_SECTION_GAP
        )
        size = _fit_font_size(
            master, BOLD_FONT, BOX_LABEL_COUNTER_FONT_SIZE, BOX_LABEL_MIN_FONT_SIZE, width
        )
        c.setFont(BOLD_FONT, size)
        c.drawString(
            LABEL_TEXT_X, BOX_LABEL_COUNTER_Y, _ellipsize(master, BOLD_FONT, size, width)
        )

    @staticmethod
    def _draw_b2b_pages(c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant) -> None:
        """
        B2B LR print: one A4 Lorry Receipt docket per copy in `LR_COPY_LABELS` (consignor,
        consignee, driver/transporter), then one 4x6 label per box (child AWB barcode + QR).
        """
        for copy_label in LR_COPY_LABELS:
            LabelGenerator._draw_b2b_docket_page(c, shipment, tenant, copy_label)
        LabelGenerator._draw_b2b_box_labels(c, shipment, tenant)

    @staticmethod
    def _draw_b2b_docket_page(
        c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant, copy_label: str
    ) -> None:
        """Draws one A4 Lorry Receipt docket page marked with its copy, e.g. `CONSIGNEE COPY`."""
        c.setPageSize(A4)
        
        # =========================================================================
        # PAGE 1: Lorry Receipt (LR) Docket (A4 size)
        # =========================================================================
        
        # Margins & Boundaries
        left_margin = 36
        right_margin = 595.27 - 36
        bottom_y = 36
        
        # --- 1. Header (Company & Title) ---
        c.setFont(BOLD_FONT, DOCKET_TITLE_FONT_SIZE)
        c.drawRightString(right_margin, 785, DOCKET_TITLE)
        # The brand shrinks (then ellipsizes) so a long tenant name never runs into the title.
        brand_width = (
            right_margin - left_margin
            - pdfmetrics.stringWidth(DOCKET_TITLE, BOLD_FONT, DOCKET_TITLE_FONT_SIZE)
            - DOCKET_BRAND_TITLE_GAP
        )
        brand = tenant.name.upper()
        brand_size = _fit_font_size(
            brand, BOLD_FONT, DOCKET_BRAND_FONT_SIZE, DOCKET_BRAND_MIN_FONT_SIZE, brand_width
        )
        c.setFont(BOLD_FONT, brand_size)
        c.drawString(left_margin, 785, _ellipsize(brand, BOLD_FONT, brand_size, brand_width))
        LabelGenerator._draw_docket_copy_tag(c, right_margin, copy_label)
        
        c.line(left_margin, 775, right_margin, 775)
        
        # --- 2. Master Tracking ID & Barcode ---
        tracking_str = shipment.tracking_id or "PENDING"
        if tracking_str != "PENDING":
            # Master Barcode (Code128)
            barcode = fitted_code128(
                tracking_str,
                (right_margin - left_margin) / 2,
                32,
                max_bar_width=DOCKET_BARCODE_MAX_BAR_WIDTH,
            )
            barcode.drawOn(c, right_margin - barcode.width, 735)
            c.setFont("Helvetica-Bold", 10)
            c.drawRightString(right_margin, 722, f"Master LR No: {tracking_str}")
            
        c.setFont("Helvetica", 10)
        date_str = shipment.created_at.strftime("%d/%m/%Y")
        c.drawString(left_margin, 755, f"LR Date: {date_str}")
        c.drawString(left_margin, 740, f"Service Speed: {shipment.service_type.value.replace('_', ' ')}")
        
        # --- 3. Consignor (FROM) & Consignee (TO) Details Box ---
        box_top = 710
        box_bottom = 560
        box_height = box_top - box_bottom
        middle_x = (left_margin + right_margin) / 2
        
        # Outer box & separator
        c.rect(left_margin, box_bottom, right_margin - left_margin, box_height)
        c.line(middle_x, box_bottom, middle_x, box_top)
        
        # Section Titles
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left_margin + 10, box_top - 15, "CONSIGNOR (FROM):")
        c.drawString(middle_x + 10, box_top - 15, "CONSIGNEE (TO):")
        
        # Consignor details
        c.setFont("Helvetica", 9)
        c.drawString(left_margin + 10, box_top - 32, shipment.pickup_address.name)
        if shipment.pickup_address.company_name:
            c.drawString(left_margin + 10, box_top - 46, shipment.pickup_address.company_name)
        c.drawString(left_margin + 10, box_top - 60, shipment.pickup_address.address_line1)
        addr2 = shipment.pickup_address.address_line2 or ""
        c.drawString(left_margin + 10, box_top - 74, addr2)
        c.drawString(
            left_margin + 10,
            box_top - 88,
            f"{shipment.pickup_address.city}, {shipment.pickup_address.state} - {shipment.pickup_address.pincode}"
        )
        c.drawString(left_margin + 10, box_top - 102, f"Phone: {LabelGenerator._format_phone(shipment.pickup_address)}")
        
        c.setFont("Helvetica-Bold", 9)
        c.drawString(left_margin + 10, box_top - 122, f"GSTIN: {shipment.pickup_address.gstin or 'N/A'}")
        
        # Consignee details
        c.setFont("Helvetica", 9)
        c.drawString(middle_x + 10, box_top - 32, shipment.delivery_address.name)
        if shipment.delivery_address.company_name:
            c.drawString(middle_x + 10, box_top - 46, shipment.delivery_address.company_name)
        c.drawString(middle_x + 10, box_top - 60, shipment.delivery_address.address_line1)
        addr2_del = shipment.delivery_address.address_line2 or ""
        c.drawString(middle_x + 10, box_top - 74, addr2_del)
        c.drawString(
            middle_x + 10,
            box_top - 88,
            f"{shipment.delivery_address.city}, {shipment.delivery_address.state} - {shipment.delivery_address.pincode}"
        )
        c.drawString(middle_x + 10, box_top - 102, f"Phone: {LabelGenerator._format_phone(shipment.delivery_address)}")
        
        c.setFont("Helvetica-Bold", 9)
        c.drawString(middle_x + 10, box_top - 122, f"GSTIN: {shipment.delivery_address.gstin or 'N/A'}")
        
        # --- 4. Cargo & Shipment Specs Table ---
        tbl_top = 550
        tbl_bottom = 475
        tbl_height = tbl_top - tbl_bottom
        
        c.rect(left_margin, tbl_bottom, right_margin - left_margin, tbl_height)
        c.line(left_margin, tbl_top - 20, right_margin, tbl_top - 20)
        specs_row_bottom = tbl_top - DOCKET_SPECS_ROW_HEIGHT
        c.line(left_margin, specs_row_bottom, right_margin, specs_row_bottom)
        
        # Headers
        c.setFont("Helvetica-Bold", 8)
        c.drawString(left_margin + 5, tbl_top - 14, "PO NO & DATE")
        c.drawString(left_margin + 120, tbl_top - 14, "APPOINTMENT ID")
        c.drawString(left_margin + 220, tbl_top - 14, "HSN CODE")
        c.drawString(left_margin + 290, tbl_top - 14, "BOX COUNT")
        c.drawString(left_margin + 360, tbl_top - 14, "ACTUAL WT")
        c.drawString(left_margin + 430, tbl_top - 14, "VOL WT")
        c.drawRightString(right_margin - DOCKET_CELL_PADDING, tbl_top - 14, "CHG WT")
        
        # Dividers
        c.line(left_margin + 115, specs_row_bottom, left_margin + 115, tbl_top)
        c.line(left_margin + 215, specs_row_bottom, left_margin + 215, tbl_top)
        c.line(left_margin + 285, specs_row_bottom, left_margin + 285, tbl_top)
        c.line(left_margin + 355, specs_row_bottom, left_margin + 355, tbl_top)
        c.line(left_margin + 425, specs_row_bottom, left_margin + 425, tbl_top)
        c.line(left_margin + 485, specs_row_bottom, left_margin + 485, tbl_top)
        
        # Values
        c.setFont("Helvetica", 8)
        po_no = shipment.po_number or "N/A"
        po_dt = shipment.po_date.strftime("%d/%m/%Y") if shipment.po_date else ""
        po_str = f"{po_no} {po_dt}".strip()
        c.drawString(left_margin + 5, tbl_top - 35, po_str)
        c.drawString(left_margin + 120, tbl_top - 35, shipment.appointment_id or "N/A")
        
        hsn = "N/A"
        if shipment.payment_details:
            hsn = shipment.payment_details.hsn_code or "N/A"
        c.drawString(left_margin + 220, tbl_top - 35, hsn)
        
        # Box Count
        box_total = total_boxes(shipment)
        c.drawString(left_margin + 290, tbl_top - 35, str(box_total))
        
        # Weights
        pricing_breakdown = {}
        if shipment.payment_details and shipment.payment_details.pricing_breakdown:
            pricing_breakdown = shipment.payment_details.pricing_breakdown
            
        actual_wt = safe_float(pricing_breakdown.get("total_actual_weight")) or safe_float(sum(p.weight * p.box_count for p in shipment.packages) if shipment.packages else 0.0)
        vol_wt = safe_float(pricing_breakdown.get("total_volumetric_weight"))
        chg_wt = safe_float(shipment.payment_details.chargeable_weight if shipment.payment_details else 0.0)
        
        c.drawString(left_margin + 360, tbl_top - 35, f"{actual_wt:.2f} KG")
        c.drawString(left_margin + 430, tbl_top - 35, f"{vol_wt:.2f} KG")
        c.drawRightString(right_margin - DOCKET_CELL_PADDING, tbl_top - 35, f"{chg_wt:.2f} KG")
        c.setFont(BOLD_FONT, DOCKET_COMPLIANCE_FONT_SIZE)
        c.drawString(
            left_margin + 5,
            specs_row_bottom - DOCKET_COMPLIANCE_BASELINE_OFFSET,
            _ellipsize(
                docket_compliance_text(shipment),
                BOLD_FONT,
                DOCKET_COMPLIANCE_FONT_SIZE,
                right_margin - left_margin - 10,
            ),
        )
        
        # --- 5. Billing Details & Zero-Math Pricing Ledger ---
        ledger_top = 465
        ledger_bottom = 295
        ledger_height = ledger_top - ledger_bottom
        ledger_middle = left_margin + 250
        
        c.rect(left_margin, ledger_bottom, right_margin - left_margin, ledger_height)
        c.line(ledger_middle, ledger_bottom, ledger_middle, ledger_top)
        
        # Left Side: Freight Mode & COD Info
        c.setFont("Helvetica-Bold", 10)
        c.drawString(left_margin + 10, ledger_top - 20, "BILLING & PAYMENT DETAILS:")
        
        pay_mode = "N/A"
        if shipment.payment_details:
            pay_mode = shipment.payment_details.freight_payment_mode.value
            
        c.setFont("Helvetica-Bold", 12)
        # Highlight in Deep Indigo
        c.setFillColorRGB(0.18, 0.18, 0.54)
        c.drawString(left_margin + 10, ledger_top - 45, f"FREIGHT MODE: {pay_mode}")
        c.setFillColorRGB(0, 0, 0)
        
        c.setFont("Helvetica", 9)
        is_cod = shipment.payment_details.is_cod if shipment.payment_details else False
        cod_amt = shipment.payment_details.cod_amount if shipment.payment_details else 0.0
        c.drawString(left_margin + 10, ledger_top - 70, f"Cash On Delivery (COD): {'YES' if is_cod else 'NO'}")
        if is_cod:
            c.drawString(left_margin + 10, ledger_top - 85, f"COD Collectible Amount: Rs. {cod_amt:,.2f}")
            
        # Right Side: Zero-Math Pricing Ledger (Strict adherence)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(ledger_middle + 10, ledger_top - 20, "FREIGHT CHARGES LEDGER (INR):")
        
        c.setFont("Helvetica", 9)
        tax_amount = safe_float(shipment.payment_details.tax_amount if shipment.payment_details else 0.0)
        total_cost = safe_float(shipment.payment_details.total_logistics_cost if shipment.payment_details else 0.0)

        y_offset = ledger_top - 25
        for line_label, line_amount in docket_charge_lines(shipment.payment_details):
            y_offset -= 15
            c.drawString(ledger_middle + 10, y_offset, f"{line_label}:")
            c.drawRightString(right_margin - 10, y_offset, f"{line_amount:,.2f}")

        y_offset -= 15
        c.line(ledger_middle, y_offset + DOCKET_LEDGER_RULE_RISE, right_margin, y_offset + DOCKET_LEDGER_RULE_RISE)
        c.drawString(ledger_middle + 10, y_offset, "GST / Tax (18%):")
        c.drawRightString(right_margin - 10, y_offset, f"{tax_amount:,.2f}")
        
        y_offset -= 20
        c.line(ledger_middle, y_offset + DOCKET_TOTAL_RULE_RISE, right_margin, y_offset + DOCKET_TOTAL_RULE_RISE)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(ledger_middle + 10, y_offset, "TOTAL FREIGHT CHARGES:")
        c.drawRightString(right_margin - 10, y_offset, f"{total_cost:,.2f}")
        
        # --- 6. Package Breakdown Summary ---
        pkg_top = 285
        pkg_bottom = 175
        pkg_height = pkg_top - pkg_bottom
        
        c.rect(left_margin, pkg_bottom, right_margin - left_margin, pkg_height)
        c.setFont("Helvetica-Bold", 9)
        c.drawString(left_margin + 10, pkg_top - 15, "CARGO PACKAGES & DETERMINISTIC CHILD AWBs:")
        
        c.setFont("Helvetica", 8)
        if shipment.is_blind_pickup:
            c.drawString(left_margin + 10, pkg_top - 35, "BLIND PICKUP: Package dimensions and weights are hidden.")
            c.drawString(left_margin + 10, pkg_top - 50, f"Consolidated Box Count: {shipment.estimated_box_count} boxes.")
            c.drawString(
                left_margin + 10,
                pkg_top - 65,
                f"Deterministic child AWB range: {shipment.tracking_id}-B1 to {shipment.tracking_id}-B{shipment.estimated_box_count}"
            )
        else:
            y_offset = pkg_top - 30
            c.drawString(left_margin + 10, y_offset, "Box #")
            c.drawString(left_margin + 60, y_offset, "Dimensions (LxBxH)")
            c.drawString(left_margin + 180, y_offset, "Weight")
            c.drawString(left_margin + 250, y_offset, "Child AWB Number")
            c.line(left_margin + 10, y_offset - 4, right_margin - 10, y_offset - 4)
            
            y_offset -= 15
            box_counter = 0
            for _idx, pkg in enumerate(shipment.packages):
                dim_unit = pkg.dimension_unit.value
                w_unit = pkg.weight_unit.value
                for _b in range(pkg.box_count):
                    box_counter += 1
                    if box_counter <= 4:
                        child_awb = f"{shipment.tracking_id}-B{box_counter}"
                        c.drawString(left_margin + 10, y_offset, f"Box {box_counter}")
                        c.drawString(left_margin + 60, y_offset, f"{pkg.length} x {pkg.breadth} x {pkg.height} {dim_unit}")
                        c.drawString(left_margin + 180, y_offset, f"{pkg.weight} {w_unit}")
                        c.drawString(left_margin + 250, y_offset, child_awb)
                        y_offset -= 12
                    else:
                        break
                if box_counter > 4:
                    c.drawString(left_margin + 10, y_offset, f"... and {box_total - 4} more boxes")
                    break
                    
        # --- 7. Signature & Terms Block ---
        sig_top = 165
        col_width = (right_margin - left_margin) / 3
        
        # Consignor Signature
        c.setFont("Helvetica-Bold", 8)
        c.drawString(left_margin + 10, sig_top - 65, "CONSIGNOR SIGNATURE")
        c.setFont("Helvetica", 7)
        c.drawString(left_margin + 10, sig_top - 75, "Signature & Stamp")
        c.line(left_margin + 10, sig_top - 52, left_margin + col_width - 10, sig_top - 52)
        
        # Consignee Signature
        c.setFont("Helvetica-Bold", 8)
        c.drawString(left_margin + col_width + 10, sig_top - 65, "CONSIGNEE SIGNATURE")
        c.setFont("Helvetica", 7)
        c.drawString(left_margin + col_width + 10, sig_top - 75, "Received in good condition")
        c.line(left_margin + col_width + 10, sig_top - 52, left_margin + 2 * col_width - 10, sig_top - 52)
        
        # Authorized Signatory
        c.setFont("Helvetica-Bold", 8)
        c.drawString(left_margin + 2 * col_width + 10, sig_top - 65, f"For {tenant.name.upper()}")
        c.setFont("Helvetica", 7)
        c.drawString(left_margin + 2 * col_width + 10, sig_top - 75, "Authorized Signatory")
        c.line(left_margin + 2 * col_width + 10, sig_top - 52, right_margin - 10, sig_top - 52)
        
        # T&C Footer
        c.setFont("Helvetica", 7)
        c.drawCentredString(
            (left_margin + right_margin) / 2.0,
            bottom_y,
            "Subject to standard terms of carriage. All disputes subject to local jurisdiction."
        )
        
        c.showPage()

    @staticmethod
    def _draw_b2b_box_labels(c: canvas.Canvas, shipment: PickupRequest, tenant: Tenant) -> None:
        """One 4x6 label per carton: consignee, PIN, box n of N, child AWB barcode + QR."""
        label_width = 4 * inch
        label_height = 6 * inch
        box_total = total_boxes(shipment)

        for i in range(box_total):
            c.setPageSize((label_width, label_height))
            
            # --- Box Header ---
            c.setFont(BOLD_FONT, BOX_LABEL_TITLE_FONT_SIZE)
            c.drawRightString(3.8 * inch, 5.6 * inch, BOX_LABEL_TITLE)
            brand_width = (
                3.6 * inch
                - pdfmetrics.stringWidth(BOX_LABEL_TITLE, BOLD_FONT, BOX_LABEL_TITLE_FONT_SIZE)
                - B2C_SECTION_GAP
            )
            brand = tenant.name.upper()
            brand_size = _fit_font_size(
                brand, BOLD_FONT, BOX_LABEL_BRAND_FONT_SIZE, BOX_LABEL_MIN_FONT_SIZE, brand_width
            )
            c.setFont(BOLD_FONT, brand_size)
            c.drawString(0.2 * inch, 5.6 * inch, _ellipsize(brand, BOLD_FONT, brand_size, brand_width))
            
            c.line(0.1 * inch, 5.45 * inch, 3.9 * inch, 5.45 * inch)
            
            # --- Master LR & Box Counter ---
            LabelGenerator._draw_box_label_counter_row(c, shipment.tracking_id, i + 1, box_total)
            
            c.line(0.1 * inch, 4.95 * inch, 3.9 * inch, 4.95 * inch)
            
            # --- Consignee & Destination Address ---
            c.setFont("Helvetica", 9)
            c.drawString(0.2 * inch, 4.7 * inch, "TO (CONSIGNEE):")
            c.setFont("Helvetica-Bold", 11)
            c.drawString(0.2 * inch, 4.5 * inch, shipment.delivery_address.name)
            c.setFont("Helvetica", 9)
            c.drawString(0.2 * inch, 4.3 * inch, shipment.delivery_address.address_line1)
            c.drawString(
                0.2 * inch,
                4.1 * inch,
                f"{shipment.delivery_address.city}, {shipment.delivery_address.state}"
            )
            
            # Destination Pincode
            c.setFont("Helvetica-Bold", 16)
            c.drawString(0.2 * inch, 3.65 * inch, f"PIN: {shipment.delivery_address.pincode}")
            
            c.line(0.1 * inch, 3.45 * inch, 3.9 * inch, 3.45 * inch)
            
            # --- Package Details ---
            c.setFont("Helvetica-Bold", 9)
            if shipment.is_blind_pickup:
                c.drawString(0.2 * inch, 3.15 * inch, "Weight: Default / Hidden (Blind)")
                c.drawString(0.2 * inch, 2.95 * inch, "Dimensions: Hidden (Blind)")
            else:
                # Find the package corresponding to this box index i
                current_box = 0
                pkg_found = None
                for p in shipment.packages:
                    if current_box + p.box_count > i:
                        pkg_found = p
                        break
                    current_box += p.box_count
                    
                if pkg_found:
                    c.drawString(
                        0.2 * inch,
                        3.15 * inch,
                        f"Weight: {pkg_found.weight} {pkg_found.weight_unit.value}"
                    )
                    c.drawString(
                        0.2 * inch,
                        2.95 * inch,
                        f"Dims: {pkg_found.length}x{pkg_found.breadth}x{pkg_found.height} {pkg_found.dimension_unit.value}"
                    )
                else:
                    c.drawString(0.2 * inch, 3.15 * inch, "Weight: N/A")
                    c.drawString(0.2 * inch, 2.95 * inch, "Dims: N/A")
                    
            c.line(0.1 * inch, 2.65 * inch, 3.9 * inch, 2.65 * inch)
            
            # --- Child AWB Barcode ---
            child_awb = f"{shipment.tracking_id}-B{i + 1}"
            
            # Code128 barcode (fitted to the label width) and QR of the child AWB
            _draw_centered_barcode(c, child_awb, BOX_LABEL_BARCODE_Y, BOX_LABEL_BARCODE_HEIGHT)
            _draw_qr(c, child_awb, BOX_LABEL_QR_X, BOX_LABEL_QR_Y, BOX_LABEL_QR_SIZE)
            
            c.setFont("Helvetica-Bold", 12)
            c.drawCentredString(label_width / 2.0, 0.7 * inch, child_awb)
            
            # Commit Box Page
            c.showPage()

