import csv
import io
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm.attributes import set_committed_value
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.permissions import (
    assert_not_read_only,
    can_view_tenant_finance,
    is_tenant_staff,
)
from app.models.delhivery_modules import (
    BillingInvoice,
    BillToType,
    CodRemittance,
    InvoiceNoteType,
    InvoiceServiceType,
    InvoiceStatus,
    RemittanceState,
    SupportTicket,
    SupportTicketMessage,
    TicketCategoryGroup,
    TicketStatus,
    WeightDispute,
    WeightDisputeClaimStatus,
)
from app.models.pickups import (
    Address,
    CodRemittanceStatus,
    PaymentDetails,
    PickupRequest,
    PickupStatus,
    ShipmentType,
    WeightUnit,
)
from app.models.tenants import Tenant, User, UserRole
from app.repositories.delhivery_modules import (
    DelhiveryModulesRepository,
    DocumentSeriesBusyError,
)
from app.repositories.shipments import is_b2b_shipment
from app.repositories.wallet import WalletRepository
from app.schemas.v1.delhivery_modules import (
    BillingInvoiceCreate,
    CodRemittanceCreate,
    CodRemittancePreview,
    CodRemittancePreviewLine,
    SupportTicketCreate,
    SupportTicketDetailRead,
    SupportTicketMessageCreate,
    SupportTicketMessageRead,
    SupportTicketRead,
    SupportTicketStatusUpdate,
    SupportTicketSummary,
    WeightDisputeClaimCreate,
    WeightDisputeResolveRequest,
)
from app.services.cod_payout import cod_payout_amount
from app.services.gst_documents import (
    BILL_TO_KEY,
    CHARGE_LINES_KEY,
    CHARGEABLE_WEIGHT_KEY,
    DESTINATION_KEY,
    KYC_REQUESTS_SETTINGS_KEY,
    LEGACY_CHARGE_LABEL,
    NOTE_DEFAULT_DESCRIPTIONS,
    ORIGIN_KEY,
    REVERSE_CHARGE_KEY,
    SEPARATE_CHARGE_DESCRIPTION,
    SNAPSHOT_VERSION,
    SNAPSHOT_VERSION_KEY,
    SUPPLIER_KEY,
    ChargeLine,
    GstParty,
    build_bill_to,
    build_document_view,
    charge_lines_snapshot,
    format_address,
    is_specimen_tenant,
    nominal_gst_rate_percent,
    render_gst_document_pdf,
    shipment_charge_lines,
)
from app.services.pricing.sell_price import GST_PERCENT
from app.services.wallet import (
    FINANCIAL_YEAR_START_MONTH,
    IST,  # also re-exported for scripts/tenant_data_core.py
    indian_financial_year_label,
    today_ist,
)

logger = logging.getLogger(__name__)

MONEY_DECIMALS = 2
MONEY_TOLERANCE = 0.01
"""Rupee rounding tolerance when comparing a client-confirmed total with the server's."""
SECTION_34_DEADLINE_MONTH = 11
SECTION_34_DEADLINE_DAY = 30
"""CGST Act s.34: a credit note may reduce GST only until 30 November after the FY ends."""
SECTION_34_WARNING = (
    "Section 34 deadline passed: credit recorded as a financial credit with no GST reduction."
)
SEPARATE_CHARGE_LINE_FLAG = "separate_charge"
"""Line-item flag for notes of charges outside the bill (read by services/integrity_audit.py)."""
MANUAL_DOCUMENT_MISSING_VALUE = "NOT PROVIDED"
GRAMS_PER_KG = 1000.0
INVOICE_DUE_DAYS = 15
DOCUMENT_SERIES_BUSY_DETAIL = (
    "Billing is busy issuing another GST document. Nothing was charged; please try again in a moment."
)
DOCUMENT_SERIES_BUSY_RETRY_AFTER_S = "5"
PERCENT = 100.0

# --- GST documents ----------------------------------------------------------
DOCUMENT_SERIAL_WIDTH = 6
DOCUMENT_NUMBER_MAX_LENGTH = 16
"""GST Rule 46: a document serial is at most 16 characters."""
TENANT_PREFIX_MAX_LENGTH = 4
FALLBACK_TENANT_PREFIX = "INV"
DOCUMENT_TYPE_CODES: Dict[str, str] = {
    InvoiceNoteType.INVOICE.value: "I",
    InvoiceNoteType.CREDIT_NOTE.value: "C",
    InvoiceNoteType.DEBIT_NOTE.value: "D",
}
GSTIN_NOT_CONFIGURED = "Not Configured"
LEGACY_FAKE_GSTINS = frozenset({"27AABCL1234F1Z5"})
GSTIN_STATE_CODE_LENGTH = 2
B2B_PTL_SERVICE_TYPE = "B2B_PTL"

GST_STATE_CODES: Dict[str, str] = {
    "jammuandkashmir": "01", "jk": "01",
    "himachalpradesh": "02", "hp": "02",
    "punjab": "03", "pb": "03",
    "chandigarh": "04", "ch": "04",
    "uttarakhand": "05", "uttaranchal": "05", "uk": "05", "ut": "05",
    "haryana": "06", "hr": "06",
    "delhi": "07", "newdelhi": "07", "nctofdelhi": "07", "dl": "07",
    "rajasthan": "08", "rj": "08",
    "uttarpradesh": "09", "up": "09",
    "bihar": "10", "br": "10",
    "sikkim": "11", "sk": "11",
    "arunachalpradesh": "12", "ar": "12",
    "nagaland": "13", "nl": "13",
    "manipur": "14", "mn": "14",
    "mizoram": "15", "mz": "15",
    "tripura": "16", "tr": "16",
    "meghalaya": "17", "ml": "17",
    "assam": "18", "as": "18",
    "westbengal": "19", "wb": "19",
    "jharkhand": "20", "jh": "20",
    "odisha": "21", "orissa": "21", "od": "21", "or": "21",
    "chhattisgarh": "22", "chattisgarh": "22", "cg": "22", "ct": "22",
    "madhyapradesh": "23", "mp": "23",
    "gujarat": "24", "gj": "24",
    "dadraandnagarhavelianddamananddiu": "26", "damananddiu": "26",
    "dadraandnagarhaveli": "26", "dd": "26", "dn": "26",
    "maharashtra": "27", "mh": "27",
    "karnataka": "29", "ka": "29",
    "goa": "30", "ga": "30",
    "lakshadweep": "31", "ld": "31",
    "kerala": "32", "kl": "32",
    "tamilnadu": "33", "tn": "33",
    "puducherry": "34", "pondicherry": "34", "py": "34",
    "andamanandnicobarislands": "35", "andamanandnicobar": "35", "an": "35",
    "telangana": "36", "ts": "36", "tg": "36",
    "andhrapradesh": "37", "ap": "37",
    "ladakh": "38", "la": "38",
}
"""GST state codes (first two digits of a GSTIN) by normalized state name / abbreviation."""
VALID_GST_STATE_CODES = frozenset(GST_STATE_CODES.values())
NON_ALNUM_RE = re.compile(r"[^a-z0-9]")
NON_PREFIX_CHARS_RE = re.compile(r"[^A-Z0-9]")

# --- Weight disputes -------------------------------------------------------
WEIGHT_DISPUTE_REFUND_REMARK = "Weight dispute claim ACCEPTED"
SHIPMENT_NOT_FOUND_DETAIL = "Shipment not found."
FINANCE_STAFF_ONLY_DETAIL = (
    "Remittances and GST documents are visible to the Owner, Admins and Read-only "
    "finance users only."
)
"""Generic 404 text: never echoes the AWB, so a foreign AWB reveals nothing (H-5, J54)."""
SHORT_SHIPMENT_TICKET_SUBCATEGORY = "Short Shipment / Missing Boxes"
WEIGHT_CLAIM_TICKET_SUBCATEGORY = "Weight Dispute / Mismatch Claim"
"""Sub-category of the ticket a weight claim opens; claim resolution only touches these."""
SHIPMENT_STATUS_LABELS: Dict[PickupStatus, str] = {
    PickupStatus.COMPLETED: "Delivered",
    PickupStatus.RTO_INITIATED: "RTO",
    PickupStatus.RTO_IN_TRANSIT: "RTO",
    PickupStatus.RTO_DELIVERED: "RTO delivered",
    PickupStatus.CANCELLED: "Cancelled",
    PickupStatus.LOST: "Lost",
}
"""Weight-mismatch "Status" column per shipment status; anything else is "In-transit"."""
IN_TRANSIT_STATUS_LABEL = "In-transit"
TICKET_SERIAL_WIDTH = 4
"""Zero-padded width of a support ticket serial (grows past 9999)."""
DUPLICATE_TICKET_DETAIL = (
    "Ticket {ticket_number} is already open for AWB {tracking_id}. "
    "Please add a comment on that ticket instead of raising a new one."
)
"""Delhivery One "Ticket Already Exists": one open ticket per AWB (help slug support-tickets)."""
MERCHANT_EMAIL_ATTR = "merchant_email"
"""Transient attribute read by the `merchant_email` field of the finance Read DTOs."""
MerchantOwnedRow = Union[CodRemittance, BillingInvoice, WeightDispute]
"""Finance rows owned by one merchant (`merchant_user_id`)."""
ClaimSettler = Callable[[WeightDispute], Awaitable[Any]]
"""Settles an ACCEPTED weight claim inside the caller's transaction (see resolve_weight_dispute)."""
"""Remark prefix on the REFUND wallet txn; doubles as the idempotency marker."""
FINAL_CLAIM_STATUSES = frozenset(
    {WeightDisputeClaimStatus.ACCEPTED.value, WeightDisputeClaimStatus.REJECTED.value}
)


def _utc_now_naive() -> datetime:
    """Return current UTC timestamp as a naive datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)



def _round_money(value: float) -> float:
    """Rounds an INR amount to paise."""
    return round(float(value), MONEY_DECIMALS)


# ----------------------------------------------------------------------------
# GST helpers (pure functions, shared with `services/receipt_pdf.py`)
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class SupplierGstProfile:
    """The tenant (supplier of the courier service) as printed on GST documents."""

    gstin: str
    legal_name: str
    address: str
    state_code: Optional[str]


@dataclass(frozen=True)
class GstBreakdown:
    """Taxable value and the CGST+SGST or IGST split of one GST document."""

    taxable_value: float
    cgst: float
    sgst: float
    igst: float
    total: float
    is_intra_state: bool
    supplier_state_code: Optional[str]
    place_of_supply: Optional[str]
    tax_rate_percent: float

    @property
    def tax_total(self) -> float:
        """CGST + SGST + IGST."""
        return _round_money(self.cgst + self.sgst + self.igst)


def gst_state_code_from_gstin(gstin: Optional[str]) -> Optional[str]:
    """First two digits of a GSTIN when they are a valid GST state code."""
    candidate = (gstin or "").strip()[:GSTIN_STATE_CODE_LENGTH]
    return candidate if candidate in VALID_GST_STATE_CODES else None


def gst_state_code_from_state(state: Optional[str]) -> Optional[str]:
    """
    Maps a free-text address state ("Haryana", "MH", "Tamil Nadu", "06") to its
    GST state code, or None when it is not recognised.
    """
    raw = (state or "").strip().lower().replace("&", "and")
    if raw in VALID_GST_STATE_CODES:
        return raw
    return GST_STATE_CODES.get(NON_ALNUM_RE.sub("", raw))


def _clean_gstin(value: Any) -> str:
    """Upper-cased GSTIN with legacy placeholder values dropped."""
    candidate = str(value or "").strip().upper()
    return "" if candidate in LEGACY_FAKE_GSTINS else candidate


def resolve_supplier_gst_profile(tenant: Tenant) -> SupplierGstProfile:
    """
    Supplier GSTIN / legal name / address strictly from the tenant's own settings
    (`company`, then `wallet_config`, `contact`, root `gstin`). Nothing is
    hard-coded per tenant; an unset GSTIN prints as "Not Configured".
    """
    settings: Mapping[str, Any] = tenant.settings or {}
    company: Mapping[str, Any] = settings.get("company") or {}
    wallet_cfg: Mapping[str, Any] = settings.get("wallet_config") or {}
    contact: Mapping[str, Any] = settings.get("contact") or {}
    gstin = (
        _clean_gstin(company.get("gstin"))
        or _clean_gstin(wallet_cfg.get("gstin"))
        or _clean_gstin(contact.get("gstin"))
        or _clean_gstin(settings.get("gstin"))
    )
    legal_name = str(
        company.get("legal_name") or wallet_cfg.get("merchant_name") or tenant.name or ""
    ).strip()
    address = str(company.get("registered_address") or contact.get("address") or "").strip()
    state_code = gst_state_code_from_gstin(gstin) or gst_state_code_from_state(
        str(company.get("state_code") or company.get("state_name") or "")
    )
    return SupplierGstProfile(
        gstin=gstin or GSTIN_NOT_CONFIGURED,
        legal_name=legal_name,
        address=address,
        state_code=state_code,
    )


def merchant_kyc_entry(
    tenant_settings: Optional[Mapping[str, Any]], merchant_user_id: Optional[uuid.UUID]
) -> Optional[Mapping[str, Any]]:
    """The merchant's KYC / company-details entry (`settings.b2b_access_requests[uid]`), if any."""
    if merchant_user_id is None or not isinstance(tenant_settings, Mapping):
        return None
    requests_map = tenant_settings.get(KYC_REQUESTS_SETTINGS_KEY)
    entry = requests_map.get(str(merchant_user_id)) if isinstance(requests_map, Mapping) else None
    return entry if isinstance(entry, Mapping) else None


def render_gst_document(invoice: BillingInvoice, tenant: Tenant) -> io.BytesIO:
    """
    The ONE PDF renderer for a GST document (C-04): built only from the stored row,
    so `/finances/invoices/{id}/pdf` and `/shipments/{id}/invoice-pdf` print the
    same layout and an issued document never changes on re-download. Test tenants
    get a SPECIMEN watermark (C-14).
    """
    view = build_document_view(
        invoice,
        tenant_legal_name=resolve_supplier_gst_profile(tenant).legal_name,
        is_specimen=is_specimen_tenant(tenant.slug, tenant.settings),
    )
    return render_gst_document_pdf(view)


def resolve_place_of_supply(
    supplier_state_code: Optional[str],
    buyer_gstin: Optional[str],
    pickup_state: Optional[str],
    delivery_state: Optional[str] = None,
    shipment_type: Optional[Union[ShipmentType, str]] = None,
) -> Optional[str]:
    """
    Place of supply for a courier / goods-transport service (IGST Act s.12(8)):
    1. registered recipient: the state code of the merchant's GSTIN;
    2. otherwise the merchant's shipment side: `delivery_state` (return-to warehouse)
       on a `REVERSE` DTO shipment, or `pickup_state` on a `FORWARD` shipment;
    3. otherwise (no shipment, e.g. a manual invoice) the supplier's own state.
    """
    is_reverse = shipment_type == ShipmentType.REVERSE
    merchant_state = (
        delivery_state if is_reverse and delivery_state is not None else pickup_state
    )
    return (
        gst_state_code_from_gstin(buyer_gstin)
        or gst_state_code_from_state(merchant_state)
        or supplier_state_code
    )


def split_gst(
    total: float,
    tax_total: float,
    supplier_state_code: Optional[str],
    place_of_supply: Optional[str],
) -> GstBreakdown:
    """
    Splits the GST already charged on a tax-inclusive `total`.

    Rule: CGST + SGST (half each) when the supplier's state (first two digits of
    the tenant GSTIN) equals the place of supply; otherwise IGST. An unknown
    supplier state is treated as inter-state (IGST).
    """
    gross = _round_money(total)
    tax = _round_money(max(0.0, min(tax_total, gross)))
    taxable = _round_money(gross - tax)
    is_intra = supplier_state_code is not None and place_of_supply == supplier_state_code
    cgst = _round_money(tax / 2.0) if is_intra else 0.0
    sgst = _round_money(tax - cgst) if is_intra else 0.0
    igst = 0.0 if is_intra else tax
    rate = _round_money(tax / taxable * PERCENT) if taxable > 0 else 0.0
    return GstBreakdown(
        taxable_value=taxable,
        cgst=cgst,
        sgst=sgst,
        igst=igst,
        total=gross,
        is_intra_state=is_intra,
        supplier_state_code=supplier_state_code,
        place_of_supply=place_of_supply,
        tax_rate_percent=rate,
    )


def tenant_gst_rate(tenant: Optional[Tenant]) -> float:
    """Logismart's GST rate as a fraction (0.18). Fixed by the pricing redesign (C-13), not a setting."""
    return float(GST_PERCENT) / 100.0


def shipment_effective_gst_rate(payment: Optional[PaymentDetails]) -> Optional[float]:
    """
    GST rate the pricing engine actually applied to the shipment (tax / taxable subtotal),
    snapped to its GST slab. Paise rounding (15.25 / 84.75 = 17.994 %) must not shift
    the taxable value of a credit / debit note by a paisa (BUG-01).
    """
    if payment is None or float(payment.tax_amount or 0.0) <= 0:
        return None
    breakdown = payment.pricing_breakdown or {}
    tax = float(payment.tax_amount)
    subtotal = float(
        breakdown.get("subtotal") or (float(payment.total_logistics_cost or 0.0) - tax)
    )
    if subtotal <= 0:
        return None
    return nominal_gst_rate_percent(tax / subtotal * PERCENT) / PERCENT


def tenant_document_prefix(tenant: Tenant) -> str:
    """
    Series prefix for GST documents: `settings.company.invoice_prefix` when set,
    otherwise the tenant slug; upper-case A-Z0-9 only, at most 4 characters.
    """
    company: Mapping[str, Any] = (tenant.settings or {}).get("company") or {}
    raw = str(company.get("invoice_prefix") or tenant.slug or "").upper()
    cleaned = NON_PREFIX_CHARS_RE.sub("", raw)[:TENANT_PREFIX_MAX_LENGTH]
    return cleaned or FALLBACK_TENANT_PREFIX


def document_number_prefix(tenant: Tenant, financial_year: str, note_type: str) -> str:
    """`<PFX><FY4><I|C|D>` with no separators; the 6-digit serial is appended to it."""
    type_code = DOCUMENT_TYPE_CODES.get(note_type, DOCUMENT_TYPE_CODES[InvoiceNoteType.INVOICE.value])
    return f"{tenant_document_prefix(tenant)}{financial_year}{type_code}"


def format_document_number(number_prefix: str, serial: int) -> str:
    """
    GST Rule 46 document number, e.g. `LOGI2627I` + 1 -> `LOGI2627I000001` (15 chars).
    Raises 500 rather than ever issuing a number longer than 16 characters.
    """
    number = f"{number_prefix}{serial:0{DOCUMENT_SERIAL_WIDTH}d}"
    if len(number) > DOCUMENT_NUMBER_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                f"GST document number '{number}' exceeds {DOCUMENT_NUMBER_MAX_LENGTH} "
                "characters (GST Rule 46); check the tenant invoice prefix or series."
            ),
        )
    return number


class DelhiveryModulesService:
    """
    Business logic service for Delhivery One parity modules:
    1. COD Remittances (`/api/v1/remittances`)
    2. Billing Invoices & GST PDFs (`/api/v1/invoices`)
    3. Support Tickets & Thread Replies (`/api/v1/support-tickets`)
    4. Weight Mismatch & Dispute Claims (`/api/v1/disputes/weight-mismatch`)
    """

    def __init__(self, repo: DelhiveryModulesRepository):
        self.repo = repo

    @staticmethod
    def _is_admin(user: User) -> bool:
        return user.role in (UserRole.admin, UserRole.owner)

    @staticmethod
    def _is_staff(user: User) -> bool:
        return user.role != UserRole.customer

    def _require_admin(self, user: User, detail: str) -> None:
        if not self._is_admin(user):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)

    @staticmethod
    def _finance_scope_user_id(user: User) -> Optional[uuid.UUID]:
        """
        Row scope for remittances and GST documents (B-07): owner / admin / read_only
        (`can_view_tenant_finance`) see the whole tenant; a customer sees ONLY their own
        rows (`None` = tenant-wide). Operations / support staff have no access to sellers'
        payouts, UTRs or tax documents (403).

        Raises:
            HTTPException(403): tenant staff without finance access.
        """
        if can_view_tenant_finance(user):
            return None
        if is_tenant_staff(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=FINANCE_STAFF_ONLY_DETAIL
            )
        return user.id

    @staticmethod
    def _dispute_scope_user_id(user: User) -> Optional[uuid.UUID]:
        """
        Row scope for the weight-dispute queue: every staff role works it tenant-wide
        (operations / support resolve disputes); a customer sees only their own rows.
        """
        if can_view_tenant_finance(user) or is_tenant_staff(user):
            return None
        return user.id

    async def _attach_merchant_emails(
        self, tenant_id: uuid.UUID, rows: Sequence[MerchantOwnedRow]
    ) -> None:
        """
        Labels each tenant-wide finance row (remittance, GST document, weight dispute)
        with its merchant's email as the transient `merchant_email` attribute, so staff
        can see whose row it is (one query for the whole page).

        Args:
            tenant_id: Tenant whose users are looked up.
            rows: ORM rows carrying `merchant_user_id`; mutated in place.
        """
        emails = await self.repo.get_user_emails(
            tenant_id, [row.merchant_user_id for row in rows]
        )
        for row in rows:
            object.__setattr__(row, MERCHANT_EMAIL_ATTR, emails.get(row.merchant_user_id))

    # ------------------------------------------------------------------
    # 1. COD Remittances
    # ------------------------------------------------------------------

    async def list_remittances(
        self,
        user: User,
        tenant_id: uuid.UUID,
        search: Optional[str] = None,
        processed_date: Optional[date] = None,
    ) -> List[CodRemittance]:
        rows = await self.repo.list_remittances(
            tenant_id=tenant_id,
            merchant_user_id=self._finance_scope_user_id(user),
            search=search,
            processed_date=processed_date,
        )
        await self._attach_merchant_emails(tenant_id, rows)
        return rows

    async def get_remittance(
        self, user: User, tenant_id: uuid.UUID, identifier: str
    ) -> CodRemittance:
        remittance = await self.repo.get_remittance_by_identifier(tenant_id, identifier)
        scope_user_id = self._finance_scope_user_id(user)
        if not remittance or (
            scope_user_id is not None and remittance.merchant_user_id != scope_user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="COD Remittance record not found",
            )
        await self._attach_merchant_emails(tenant_id, [remittance])
        return remittance

    @staticmethod
    def _bad_request(detail: str) -> HTTPException:
        """400 helper for business-rule rejections."""
        return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

    async def _resolve_remittance_merchant(
        self, tenant_id: uuid.UUID, payload: CodRemittanceCreate
    ) -> Tuple[uuid.UUID, Optional[List[uuid.UUID]]]:
        """
        Resolves the single merchant a batch pays, locking the candidate shipments.

        - `merchant_user_id` given: must be a user of this tenant; explicit
          `shipment_ids` (if any) must all belong to that merchant.
        - only `shipment_ids` given: the merchant is derived from them and the
          batch is rejected when they span more than one merchant.
        - neither: rejected (a batch never sweeps the whole tenant).
        Returns the merchant id and the de-duplicated explicit shipment ids.
        """
        shipment_ids = list(dict.fromkeys(payload.shipment_ids or [])) or None
        if payload.merchant_user_id is None and not shipment_ids:
            raise self._bad_request(
                "Select the merchant (merchant_user_id) or the shipments to remit; "
                "a remittance batch pays exactly one merchant."
            )
        if payload.merchant_user_id is not None:
            merchant = await self.repo.get_tenant_user(tenant_id, payload.merchant_user_id)
            if merchant is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Merchant not found in this workspace.",
                )

        locked = await self.repo.lock_cod_shipments_for_remittance(
            tenant_id=tenant_id,
            merchant_user_id=None if shipment_ids else payload.merchant_user_id,
            shipment_ids=shipment_ids,
        )
        owners = {s.created_by_user_id for s in locked}
        if shipment_ids and len(locked) != len(shipment_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="One or more COD shipments were not found in this workspace.",
            )
        if len(owners) > 1:
            raise self._bad_request(
                "The selected shipments belong to more than one merchant. "
                "Create one remittance batch per merchant."
            )
        merchant_id = payload.merchant_user_id or next(iter(owners))
        if owners and owners != {merchant_id}:
            raise self._bad_request(
                "The selected shipments do not belong to the selected merchant."
            )
        return merchant_id, shipment_ids

    @staticmethod
    def _build_remittance_lines(
        shipments: Sequence[PickupRequest],
    ) -> Tuple[List[Dict[str, Any]], float]:
        """
        Per-AWB payout lines and their total. Each line pays the merchant's share
        of the cash collected (`cod_payout_amount`, decision D26: on TO_PAY + COD
        the freight collected at the door stays with the carrier).
        """
        lines: List[Dict[str, Any]] = []
        total = 0.0
        for shipment in shipments:
            payout = cod_payout_amount(shipment.payment_details)
            total = _round_money(total + payout)
            lines.append(
                {
                    "shipment_id": str(shipment.id),
                    "tracking_id": shipment.tracking_id or "",
                    "order_reference_id": shipment.order_reference_id or "",
                    "amount_collected": payout,
                }
            )
        return lines, total

    async def _merchant_wallet_balance(self, tenant_id: uuid.UUID, merchant_id: uuid.UUID) -> float:
        """The merchant's current wallet balance (0.0 when no wallet row exists yet)."""
        wallet = await WalletRepository(self.repo.session).get_wallet(
            user_id=merchant_id, tenant_id=tenant_id, for_update=False
        )
        return _round_money(float(wallet.balance)) if wallet else 0.0

    @staticmethod
    def _payout_blocked_reason(wallet_balance: float) -> Optional[str]:
        """
        A-05 (DO1 `cod-remittance`): a bank payout is held while the merchant's wallet is
        negative, otherwise unrecovered RTO / weight debits are paid out in cash.
        """
        if wallet_balance >= 0:
            return None
        return (
            f"The merchant's wallet is ₹{wallet_balance:,.2f}. COD payouts are on hold until it is "
            "back to ₹0 or more (the merchant can recharge, or use Settle COD to wallet, which "
            "nets the deficit)."
        )

    async def preview_remittance(
        self,
        admin_user: User,
        tenant_id: uuid.UUID,
        merchant_user_id: uuid.UUID,
        selected_ids: Optional[Sequence[uuid.UUID]] = None,
    ) -> CodRemittancePreview:
        """
        A-06: every AWB one merchant can be paid for right now, with the server-computed
        amounts, plus the payout total of the ticked ones (`selected_ids`; all when None),
        so finance ticks exactly what the bank transfer covered and never adds up in the UI.
        """
        self._require_admin(admin_user, "Only Tenant Admins can prepare COD remittances.")
        merchant = await self.repo.get_tenant_user(tenant_id, merchant_user_id)
        if merchant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Merchant not found in this workspace.",
            )
        shipments = await self.repo.get_remittable_cod_shipments(
            tenant_id=tenant_id, merchant_user_id=merchant_user_id
        )
        lines, _ = self._build_remittance_lines(shipments)
        selected = {str(sid) for sid in selected_ids} if selected_ids is not None else None
        _, selected_total = self._build_remittance_lines(
            [s for s in shipments if selected is None or str(s.id) in selected]
        )
        balance = await self._merchant_wallet_balance(tenant_id, merchant_user_id)
        return CodRemittancePreview(
            merchant_user_id=merchant_user_id,
            merchant_email=merchant.email,
            wallet_balance=balance,
            payout_blocked_reason=self._payout_blocked_reason(balance),
            lines=[
                CodRemittancePreviewLine(
                    shipment_id=uuid.UUID(line["shipment_id"]),
                    tracking_id=line["tracking_id"],
                    order_reference_id=line["order_reference_id"],
                    amount=line["amount_collected"],
                )
                for line in lines
            ],
            selected_count=len(lines) if selected is None else sum(
                1 for line in lines if line["shipment_id"] in selected
            ),
            total=selected_total,
        )

    @classmethod
    def _assert_remittance_request(cls, payload: CodRemittanceCreate) -> None:
        """A-06: a batch names its UTR, the ticked AWBs and the total finance saw."""
        if not payload.bank_utr or not payload.bank_utr.strip():
            raise cls._bad_request("Bank transaction ID (UTR) is required.")
        if not payload.shipment_ids:
            raise cls._bad_request(
                "Tick the AWBs this bank transfer pays. A remittance never sweeps every "
                "pending order automatically."
            )
        if payload.expected_total is None:
            raise cls._bad_request("Send the payout total shown for the ticked AWBs.")

    async def create_remittance(
        self,
        admin_user: User,
        tenant_id: uuid.UUID,
        payload: CodRemittanceCreate,
    ) -> CodRemittance:
        """
        Records one merchant's COD bank payout and marks the ticked shipments REMITTED.
        Only delivered COD shipments that never went through RTO and were neither
        remitted nor settled to the wallet are included; amounts and counts are
        always computed server-side and must match the total finance confirmed (A-06).
        Refused while the merchant's wallet is negative (A-05). The candidates are locked
        first and re-read afterwards, so a concurrent wallet settlement can't pay the same
        AWB twice (A-24).
        """
        self._require_admin(
            admin_user, "Only Tenant Admins can create COD remittance batches."
        )
        self._assert_remittance_request(payload)
        merchant_id, shipment_ids = await self._resolve_remittance_merchant(
            tenant_id, payload
        )
        shipments = await self.repo.get_remittable_cod_shipments(
            tenant_id=tenant_id,
            merchant_user_id=merchant_id,
            shipment_ids=shipment_ids,
        )
        if shipment_ids and len(shipments) != len(shipment_ids):
            raise self._bad_request(
                f"{len(shipment_ids) - len(shipments)} selected shipment(s) are not "
                "eligible: only delivered COD orders that were not returned (RTO), "
                "remitted, or settled to the wallet can be remitted."
            )
        if not shipments:
            raise self._bad_request(
                "No delivered COD shipments are pending remittance for this merchant."
            )

        lines, total_amount = self._build_remittance_lines(shipments)
        if abs(total_amount - _round_money(float(payload.expected_total or 0.0))) > MONEY_TOLERANCE:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"The payout total for the ticked AWBs is now ₹{total_amount:,.2f}, not "
                    f"₹{float(payload.expected_total or 0.0):,.2f}. Reload the list and check "
                    "the bank transfer amount."
                ),
            )
        blocked = self._payout_blocked_reason(
            await self._merchant_wallet_balance(tenant_id, merchant_id)
        )
        if blocked:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=blocked)
        for shipment in shipments:
            payment = shipment.payment_details
            if payment is not None:
                payment.cod_remittance_status = CodRemittanceStatus.REMITTED
                self.repo.session.add(payment)

        proc_date = payload.processed_date or today_ist()
        remit_number = (
            payload.remittance_number.strip()
            if payload.remittance_number and payload.remittance_number.strip()
            else f"R471378{proc_date.strftime('%Y%m%d')}{uuid.uuid4().int % 100000:05d}"
        )
        remittance = CodRemittance(
            tenant_id=tenant_id,
            merchant_user_id=merchant_id,
            remittance_number=remit_number,
            processed_date=proc_date,
            bank_utr=payload.bank_utr.strip(),
            state=payload.state or RemittanceState.COMPLETED.value,
            total_remittance=total_amount,
            total_orders=len(lines),
            shipment_breakdown=lines,
        )
        return await self.repo.save_remittance(remittance)

    async def export_remittance_csv(
        self, user: User, tenant_id: uuid.UUID, identifier: str
    ) -> Tuple[str, io.StringIO]:
        remittance = await self.get_remittance(user, tenant_id, identifier)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["AWB Number", "Order Reference", "Amount Collected (INR)"])
        breakdown = remittance.shipment_breakdown or []
        if breakdown:
            for item in breakdown:
                if isinstance(item, dict):
                    writer.writerow(
                        [
                            item.get("tracking_id", ""),
                            item.get("order_reference_id", ""),
                            f"{float(item.get('amount_collected', 0.0)):.2f}",
                        ]
                    )
        else:
            writer.writerow(
                [
                    remittance.remittance_number,
                    remittance.bank_utr,
                    f"{remittance.total_remittance:.2f}",
                ]
            )
        output.seek(0)
        return remittance.remittance_number, output

    # ------------------------------------------------------------------
    # 2. Billing Invoices
    # ------------------------------------------------------------------

    async def list_invoices(
        self,
        user: User,
        tenant_id: uuid.UUID,
        note_type: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[BillingInvoice]:
        rows = await self.repo.list_invoices(
            tenant_id=tenant_id,
            merchant_user_id=self._finance_scope_user_id(user),
            note_type=note_type,
            search=search,
        )
        await self._attach_merchant_emails(tenant_id, rows)
        return rows

    async def get_invoice(
        self, user: User, tenant_id: uuid.UUID, identifier: str
    ) -> BillingInvoice:
        invoice = await self.repo.get_invoice_by_identifier(tenant_id, identifier)
        scope_user_id = self._finance_scope_user_id(user)
        if not invoice or (
            scope_user_id is not None and invoice.merchant_user_id != scope_user_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Billing invoice not found",
            )
        await self._attach_merchant_emails(tenant_id, [invoice])
        return invoice

    @staticmethod
    def _normalize_note_type(note_type: Optional[str]) -> str:
        """Upper-cased INVOICE / CREDIT_NOTE / DEBIT_NOTE; 400 for anything else."""
        normalized = (note_type or InvoiceNoteType.INVOICE.value).strip().upper()
        if normalized not in DOCUMENT_TYPE_CODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="note_type must be INVOICE, CREDIT_NOTE, or DEBIT_NOTE.",
            )
        return normalized

    async def _require_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        """Loads the tenant whose settings drive GST documents (404 if missing)."""
        tenant = await self.repo.get_tenant(tenant_id)
        if tenant is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found"
            )
        return tenant

    async def _allocate_document_number(
        self, tenant: Tenant, note_type: str, document_date: date
    ) -> str:
        """
        Next number in `<PFX><FY4><I|C|D><SEQ6>` (decision D29, GST Rule 46):
        sequential per tenant, financial year and document type, allocated under a
        transaction-scoped advisory lock so concurrent bookings never collide or
        leave gaps. Must run inside the transaction that inserts the document.
        """
        financial_year = indian_financial_year_label(document_date)
        number_prefix = document_number_prefix(tenant, financial_year, note_type)
        try:
            serial = await self.repo.allocate_document_sequence(
                tenant_id=tenant.id,
                financial_year=financial_year,
                note_type=note_type,
                number_prefix=number_prefix,
            )
        except DocumentSeriesBusyError as exc:
            raise self._series_busy() from exc
        return format_document_number(number_prefix, serial)

    @staticmethod
    def _series_busy() -> HTTPException:
        """503 for a GST series lock wait that timed out (BUG-03): the whole request rolls back."""
        return HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=DOCUMENT_SERIES_BUSY_DETAIL,
            headers={"Retry-After": DOCUMENT_SERIES_BUSY_RETRY_AFTER_S},
        )

    async def _shipment_pickup_address(self, shipment: PickupRequest) -> Optional[Address]:
        """The shipment's pickup address snapshot, only when it belongs to the same tenant."""
        pickup = await self.repo.get_address(shipment.pickup_address_id)
        return pickup if pickup is not None and pickup.tenant_id == shipment.tenant_id else None

    async def _shipment_delivery_address(self, shipment: PickupRequest) -> Optional[Address]:
        """The shipment's delivery address snapshot, only when it belongs to the same tenant."""
        delivery = await self.repo.get_address(shipment.delivery_address_id)
        return delivery if delivery is not None and delivery.tenant_id == shipment.tenant_id else None

    @staticmethod
    def _configured_rate_percent(tenant: Tenant, payment: Optional[PaymentDetails]) -> float:
        """
        GST rate printed on a document (C-12): the rate the pricing engine applied to the
        shipment (snapped to its slab, so rounding never prints 18.06%), else the tenant's
        configured rate.
        """
        rate = shipment_effective_gst_rate(payment)
        if rate is None:
            rate = tenant_gst_rate(tenant)
        return nominal_gst_rate_percent(rate * PERCENT)

    async def _bill_to_party(
        self,
        tenant: Tenant,
        merchant_user_id: uuid.UUID,
        supplier: SupplierGstProfile,
        pickup: Optional[Address],
    ) -> GstParty:
        """
        Recipient snapshot for a merchant's document (C-01): KYC company name / billing
        address / APPROVED GSTIN, else the account name and the pickup address.
        """
        merchant = await self.repo.get_tenant_user(tenant.id, merchant_user_id)
        account_name = (merchant.full_name or merchant.email) if merchant is not None else ""
        pickup_text = (
            format_address(
                [pickup.address_line1, pickup.address_line2, pickup.landmark, pickup.city, pickup.state, pickup.pincode]
            )
            if pickup is not None
            else ""
        )
        return build_bill_to(
            merchant_kyc_entry(tenant.settings, merchant_user_id),
            account_name=account_name,
            fallback_address=pickup_text,
            fallback_state_code=gst_state_code_from_state(pickup.state) if pickup is not None else None,
            supplier_gstin=supplier.gstin,
        )

    @staticmethod
    def _gst_line_item(
        breakdown: GstBreakdown,
        supplier: SupplierGstProfile,
        bill_to: GstParty,
        rate_percent: float,
        charge_lines: List[ChargeLine],
    ) -> Dict[str, Any]:
        """
        The issue-time snapshot stored on `line_items[0]` (C-04, no schema change): GST
        split, configured rate, supplier and recipient parties and the pre-GST charge
        lines. The PDF and the API read only this, never the live shipment or settings.
        """
        return {
            SNAPSHOT_VERSION_KEY: SNAPSHOT_VERSION,
            "freight_amount": breakdown.taxable_value,
            "cgst_amount": breakdown.cgst,
            "sgst_amount": breakdown.sgst,
            "igst_amount": breakdown.igst,
            "total_amount": breakdown.total,
            "tax_rate_percent": rate_percent,
            "supplier_state_code": supplier.state_code,
            "place_of_supply": breakdown.place_of_supply,
            "buyer_gstin": bill_to.gstin,
            REVERSE_CHARGE_KEY: False,
            SUPPLIER_KEY: GstParty(
                name=supplier.legal_name,
                address=supplier.address,
                gstin=supplier.gstin,
                state_code=supplier.state_code,
            ).to_snapshot(),
            BILL_TO_KEY: bill_to.to_snapshot(),
            CHARGE_LINES_KEY: charge_lines_snapshot(charge_lines),
        }

    @staticmethod
    def _shipment_tax_component(
        tenant: Tenant,
        payment: Optional[PaymentDetails],
        total: float,
        amount_override: Optional[float],
    ) -> float:
        """
        GST contained in a tax-inclusive shipment amount.

        - Full document (no override): the pricing engine's `tax_amount`, so every
          surcharge (fuel, docket, FOV, COD fee, ...) stays in the taxable value.
          Example: base 50, subtotal 80, total 94.40 -> tax 14.40 (never 44.40).
        - Partial amount (credit / debit note override): back out GST at the rate
          applied to the shipment, else the tenant's configured rate.
        """
        if amount_override is None and payment is not None and float(payment.tax_amount or 0.0) > 0:
            return _round_money(payment.tax_amount)
        rate = shipment_effective_gst_rate(payment)
        if rate is None:
            rate = tenant_gst_rate(tenant)
        taxable = _round_money(total / (1.0 + rate))
        return _round_money(total - taxable)

    @staticmethod
    def _manual_document_audit(payload: BillingInvoiceCreate, admin_user: User) -> Dict[str, Any]:
        """Reason + original reference recorded on a manual GST document (plan B12)."""
        return {
            "manual_reason": (payload.reason or "").strip() or MANUAL_DOCUMENT_MISSING_VALUE,
            "original_reference": (payload.original_reference or "").strip()
            or MANUAL_DOCUMENT_MISSING_VALUE,
            "issued_by": admin_user.email,
        }

    async def _manual_original_invoice(
        self, tenant_id: uuid.UUID, merchant_id: uuid.UUID, note_type: str, reference: Optional[str]
    ) -> Optional[BillingInvoice]:
        """
        The INVOICE a manual credit / debit note corrects (CGST Rule 53): it must be an
        INVOICE of the same merchant in this tenant. None for a manual INVOICE.
        """
        if note_type == InvoiceNoteType.INVOICE.value:
            return None
        original = await self.repo.get_invoice_by_identifier(tenant_id, (reference or "").strip())
        if (
            original is None
            or original.note_type != InvoiceNoteType.INVOICE.value
            or original.merchant_user_id != merchant_id
        ):
            raise self._bad_request(
                "A credit or debit note must quote an original invoice of the same merchant "
                "(original_reference = its invoice number)."
            )
        return original

    async def create_invoice(
        self,
        admin_user: User,
        tenant_id: uuid.UUID,
        payload: BillingInvoiceCreate,
    ) -> BillingInvoice:
        """
        Manually issues a GST document (hidden in the MVP UI, audit C-05). The taxable
        value is `freight_amount`; GST, totals, the supplier / recipient snapshot and the
        sequential number are always computed server-side.

        Guards (C-05): the document is billed to a named merchant (never defaulted to
        the admin), dated today (GST series stay in date order), carries a reason, and a
        credit / debit note quotes an original invoice of that merchant.
        """
        assert_not_read_only(admin_user, "issue GST billing invoices")
        self._require_admin(
            admin_user, "Only Tenant Admins can issue GST billing invoices."
        )
        taxable = _round_money(payload.freight_amount or 0.0)
        if taxable <= 0:
            raise self._bad_request("freight_amount (taxable value) must be greater than 0.")
        if payload.merchant_user_id is None:
            raise self._bad_request("Choose the merchant this document is billed to.")
        if not (payload.reason or "").strip():
            raise self._bad_request("Give the reason for this manual GST document.")
        inv_date = today_ist()
        if payload.invoice_date is not None and payload.invoice_date != inv_date:
            raise self._bad_request("A manual GST document can only be dated today.")
        merchant_id = payload.merchant_user_id
        if await self.repo.get_tenant_user(tenant_id, merchant_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Merchant not found in this workspace.",
            )
        note_type = self._normalize_note_type(payload.note_type)
        original = await self._manual_original_invoice(
            tenant_id, merchant_id, note_type, payload.original_reference
        )
        tenant = await self._require_tenant(tenant_id)
        supplier = resolve_supplier_gst_profile(tenant)
        bill_to = await self._bill_to_party(tenant, merchant_id, supplier, None)
        tax = _round_money(taxable * tenant_gst_rate(tenant))
        breakdown = split_gst(
            total=taxable + tax,
            tax_total=tax,
            supplier_state_code=supplier.state_code,
            place_of_supply=resolve_place_of_supply(supplier.state_code, bill_to.gstin, None),
        )
        service_type = payload.service_type or InvoiceServiceType.DOMESTIC.value
        line = self._gst_line_item(
            breakdown,
            supplier,
            bill_to,
            nominal_gst_rate_percent(tenant_gst_rate(tenant) * PERCENT),
            [ChargeLine(service_type, breakdown.taxable_value)],
        )
        line.update(
            {
                "description": service_type,
                "service_type": service_type,
                **self._manual_document_audit(payload, admin_user),
            }
        )
        if original is not None:
            line.update(
                {
                    "original_invoice_number": original.invoice_number,
                    "original_invoice_date": original.invoice_date.isoformat(),
                }
            )

        invoice = BillingInvoice(
            tenant_id=tenant_id,
            merchant_user_id=merchant_id,
            original_invoice_id=original.id if original is not None else None,
            invoice_number=await self._allocate_document_number(tenant, note_type, inv_date),
            note_type=note_type,
            service_type=service_type,
            invoice_date=inv_date,
            due_date=payload.due_date or (inv_date + timedelta(days=INVOICE_DUE_DAYS)),
            status=payload.status or InvoiceStatus.PAID.value,
            gst_number=supplier.gstin,
            billing_address=supplier.address,
            freight_amount=breakdown.taxable_value,
            cgst_amount=breakdown.cgst,
            sgst_amount=breakdown.sgst,
            igst_amount=breakdown.igst,
            total_amount=breakdown.total,
            line_items=[line],
        )
        return await self.repo.save_invoice(invoice)

    @staticmethod
    def section_34_deadline(original_invoice_date: date) -> date:
        """
        Last day a GST credit note may reduce output tax for an invoice (CGST Act s.34):
        30 November following the end of the invoice's financial year.

        Args:
            original_invoice_date: Date of the original INVOICE.

        Returns:
            The deadline date.
        """
        fy_start_year = (
            original_invoice_date.year
            if original_invoice_date.month >= FINANCIAL_YEAR_START_MONTH
            else original_invoice_date.year - 1
        )
        return date(fy_start_year + 1, SECTION_34_DEADLINE_MONTH, SECTION_34_DEADLINE_DAY)

    async def _original_invoice_for(
        self, shipment: PickupRequest, note_type: str
    ) -> Optional[BillingInvoice]:
        """The shipment's INVOICE that a CREDIT_NOTE / DEBIT_NOTE must quote (Rule 53)."""
        if note_type == InvoiceNoteType.INVOICE.value:
            return None
        return await self.repo.get_shipment_billing_document(
            shipment.tenant_id, shipment.id, InvoiceNoteType.INVOICE.value
        )

    def _is_section_34_expired(
        self, note_type: str, original: Optional[BillingInvoice], on_date: date
    ) -> bool:
        """True when a credit note is past the Section 34 deadline of its original invoice."""
        return (
            note_type == InvoiceNoteType.CREDIT_NOTE.value
            and original is not None
            and on_date > self.section_34_deadline(original.invoice_date)
        )

    async def _resolve_note_type(
        self, shipment: PickupRequest, requested_note: str
    ) -> Tuple[str, Optional[BillingInvoice]]:
        """
        The document type actually issued and the INVOICE it quotes (CGST Rule 53).

        A DEBIT_NOTE needs an original invoice; when the shipment has none (a TO_PAY
        or staff-POSTPAID parcel charged Freight Collection / Mathadi, audit C-03), the
        charge is invoiced instead, generalising the RTO rule in repricing.
        """
        original = await self._original_invoice_for(shipment, requested_note)
        if requested_note == InvoiceNoteType.DEBIT_NOTE.value and original is None:
            logger.info(
                "No INVOICE for %s: issuing an INVOICE instead of an orphan DEBIT_NOTE",
                shipment.tracking_id,
            )
            return InvoiceNoteType.INVOICE.value, None
        return requested_note, original

    @staticmethod
    def _note_charge_lines(
        note_type: str,
        payment: Optional[PaymentDetails],
        taxable_value: float,
        amount_override: Optional[float],
        description: Optional[str],
        is_separate_charge: bool,
    ) -> List[ChargeLine]:
        """
        Pre-GST charge lines frozen on the document (C-04): the shipment's priced
        components for a full document, otherwise one line describing the adjustment.
        """
        if amount_override is None and not description:
            breakdown = payment.pricing_breakdown if payment is not None else None
            return shipment_charge_lines(breakdown, taxable_value)
        default_label = (
            SEPARATE_CHARGE_DESCRIPTION
            if is_separate_charge
            else NOTE_DEFAULT_DESCRIPTIONS.get(note_type, LEGACY_CHARGE_LABEL)
        )
        return [ChargeLine(description or default_label, taxable_value)]

    async def _shipment_detail_snapshot(
        self,
        shipment: PickupRequest,
        pickup: Optional[Address],
        delivery: Optional[Address] = None,
    ) -> Dict[str, Any]:
        """AWB, references, chargeable weight and origin / destination city frozen at issue."""
        if delivery is None:
            delivery = await self._shipment_delivery_address(shipment)
        payment = shipment.payment_details
        return {
            "shipment_id": str(shipment.id),
            "tracking_id": shipment.tracking_id or "",
            "order_reference_id": shipment.order_reference_id or "",
            CHARGEABLE_WEIGHT_KEY: float(payment.chargeable_weight or 0.0) if payment else None,
            ORIGIN_KEY: pickup.city if pickup is not None else None,
            DESTINATION_KEY: delivery.city if delivery is not None else None,
        }

    async def record_shipment_billing_note(
        self,
        *,
        shipment: PickupRequest,
        note_type: str = InvoiceNoteType.INVOICE.value,
        amount_override: Optional[float] = None,
        is_b2b: bool = False,
        is_separate_charge: bool = False,
        description: Optional[str] = None,
    ) -> Optional[BillingInvoice]:
        """
        Records the correlated GST document (`INVOICE`, `CREDIT_NOTE` or `DEBIT_NOTE`) for a
        booking, cancellation, re-price or charge. Does NOT commit (it joins the caller's
        transaction, which also holds the numbering advisory lock).

        - Every CREDIT_NOTE / DEBIT_NOTE stores `original_invoice_id` and quotes the original
          invoice number and date on its line (CGST Rule 53). A DEBIT_NOTE requested for a
          shipment with no INVOICE is issued as an INVOICE (C-03).
        - A CREDIT_NOTE after the Section 34 deadline still records the credit, but with no GST
          reduction (taxable value = the full amount, zero tax) and a warning on the line.
        - `is_separate_charge` marks notes for charges outside the bill (Mathadi / union), so the
          integrity audit keeps them out of INVOICE + DN − CN.
        - The supplier, recipient ("Bill To"), configured rate and charge lines are frozen on
          `line_items[0]` (C-01, C-04, C-12); `description` labels a partial-amount line.

        Amounts: `amount_override` (or the shipment's `total_logistics_cost`) is the
        tax-inclusive value; see `_shipment_tax_component` and `split_gst`.
        """
        payment = shipment.payment_details
        total = _round_money(
            amount_override
            if amount_override is not None
            else (payment.total_logistics_cost if payment else 0.0)
        )
        if total <= 0:
            return None

        normalized_note, original = await self._resolve_note_type(
            shipment, self._normalize_note_type(note_type)
        )
        tenant = await self._require_tenant(shipment.tenant_id)
        supplier = resolve_supplier_gst_profile(tenant)
        pickup = await self._shipment_pickup_address(shipment)
        delivery = await self._shipment_delivery_address(shipment)
        shipment_type = getattr(shipment, "shipment_type", None)
        seller_address = (
            delivery
            if shipment_type == ShipmentType.REVERSE and delivery is not None
            else pickup
        )
        bill_to = await self._bill_to_party(
            tenant, shipment.created_by_user_id, supplier, seller_address
        )
        inv_date = today_ist()
        section_34_expired = self._is_section_34_expired(normalized_note, original, inv_date)
        breakdown = split_gst(
            total=total,
            tax_total=(
                0.0
                if section_34_expired
                else self._shipment_tax_component(tenant, payment, total, amount_override)
            ),
            supplier_state_code=supplier.state_code,
            place_of_supply=resolve_place_of_supply(
                supplier.state_code,
                bill_to.gstin,
                pickup.state if pickup is not None else None,
                delivery_state=delivery.state if delivery is not None else None,
                shipment_type=shipment_type,
            ),
        )
        svc_type = B2B_PTL_SERVICE_TYPE if is_b2b else InvoiceServiceType.DOMESTIC.value
        line = self._gst_line_item(
            breakdown,
            supplier,
            bill_to,
            0.0 if section_34_expired else self._configured_rate_percent(tenant, payment),
            self._note_charge_lines(
                normalized_note,
                payment,
                breakdown.taxable_value,
                amount_override,
                description,
                is_separate_charge,
            ),
        )
        line.update(await self._shipment_detail_snapshot(shipment, pickup, delivery))
        line["service_type"] = svc_type
        if original is not None:
            line.update(
                {
                    "original_invoice_number": original.invoice_number,
                    "original_invoice_date": original.invoice_date.isoformat(),
                }
            )
        if is_separate_charge:
            line[SEPARATE_CHARGE_LINE_FLAG] = True
        if section_34_expired:
            line.update({"section_34_expired": True, "warning": SECTION_34_WARNING})
            logger.warning(
                "Section 34 deadline passed for %s: credit recorded without GST reduction",
                shipment.tracking_id,
            )

        invoice = BillingInvoice(
            tenant_id=shipment.tenant_id,
            merchant_user_id=shipment.created_by_user_id,
            shipment_id=shipment.id,
            original_invoice_id=original.id if original is not None else None,
            bill_to_type=BillToType.MERCHANT.value,
            invoice_number=await self._allocate_document_number(
                tenant, normalized_note, inv_date
            ),
            note_type=normalized_note,
            service_type=svc_type,
            invoice_date=inv_date,
            due_date=inv_date + timedelta(days=INVOICE_DUE_DAYS),
            status=InvoiceStatus.PAID.value,
            gst_number=supplier.gstin,
            billing_address=supplier.address,
            freight_amount=breakdown.taxable_value,
            cgst_amount=breakdown.cgst,
            sgst_amount=breakdown.sgst,
            igst_amount=breakdown.igst,
            total_amount=breakdown.total,
            line_items=[line],
        )
        return await self.repo.save_invoice(invoice, commit=False)

    async def get_or_issue_shipment_invoice(
        self, shipment: PickupRequest, tenant: Tenant
    ) -> BillingInvoice:
        """
        The register INVOICE row for a shipment, so the shipment invoice PDF prints
        the same number as `/finances/invoices`. Legacy shipments booked before the
        register existed get their invoice allocated now (under the series lock,
        re-checked to avoid issuing two invoices for one shipment) and committed.
        """
        existing = await self.repo.get_shipment_billing_document(
            tenant.id, shipment.id, InvoiceNoteType.INVOICE.value
        )
        if existing is not None:
            return existing
        try:
            await self.repo.lock_document_series(
                tenant.id,
                indian_financial_year_label(today_ist()),
                InvoiceNoteType.INVOICE.value,
            )
        except DocumentSeriesBusyError as exc:
            raise self._series_busy() from exc
        existing = await self.repo.get_shipment_billing_document(
            tenant.id, shipment.id, InvoiceNoteType.INVOICE.value
        )
        if existing is not None:
            return existing
        issued = await self.record_shipment_billing_note(
            shipment=shipment,
            note_type=InvoiceNoteType.INVOICE.value,
            is_b2b=is_b2b_shipment(shipment),
        )
        if issued is None:
            raise self._bad_request(
                "This shipment has no billable freight, so no GST invoice exists."
            )
        await self.repo.session.commit()
        return issued

    async def generate_invoice_pdf(
        self, user: User, tenant: Tenant, identifier: str
    ) -> Tuple[str, io.BytesIO]:
        """The stored GST document as a PDF (same renderer as the shipment invoice PDF)."""
        invoice = await self.get_invoice(user, tenant.id, identifier)
        return invoice.invoice_number, render_gst_document(invoice, tenant)

    async def export_invoice_transactions_csv(
        self, user: User, tenant_id: uuid.UUID, identifier: str
    ) -> Tuple[str, io.StringIO]:
        invoice = await self.get_invoice(user, tenant_id, identifier)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Invoice Number",
                "AWB / Ref",
                "Service Type",
                "Taxable Value (INR)",
                "CGST (INR)",
                "SGST (INR)",
                "IGST (INR)",
                "Total (INR)",
                "Place of Supply",
            ]
        )
        items = invoice.line_items or []
        if items:
            for item in items:
                if isinstance(item, dict):
                    writer.writerow(
                        [
                            invoice.invoice_number,
                            item.get("tracking_id") or item.get("description") or invoice.invoice_number,
                            item.get("service_type") or invoice.service_type,
                            f"{float(item.get('freight_amount', invoice.freight_amount)):.2f}",
                            f"{float(item.get('cgst_amount', invoice.cgst_amount)):.2f}",
                            f"{float(item.get('sgst_amount', invoice.sgst_amount)):.2f}",
                            f"{float(item.get('igst_amount', invoice.igst_amount)):.2f}",
                            f"{float(item.get('total_amount', invoice.total_amount)):.2f}",
                            item.get("place_of_supply") or "",
                        ]
                    )
        else:
            writer.writerow(
                [
                    invoice.invoice_number,
                    invoice.invoice_number,
                    invoice.service_type,
                    f"{invoice.freight_amount:.2f}",
                    f"{invoice.cgst_amount:.2f}",
                    f"{invoice.sgst_amount:.2f}",
                    f"{invoice.igst_amount:.2f}",
                    f"{invoice.total_amount:.2f}",
                    "",
                ]
            )
        output.seek(0)
        return invoice.invoice_number, output

    # ------------------------------------------------------------------
    # 3. Support Tickets
    # ------------------------------------------------------------------

    @staticmethod
    def _to_ticket_detail(
        ticket: SupportTicket, messages: List[SupportTicketMessage]
    ) -> SupportTicketDetailRead:
        base = SupportTicketRead.model_validate(ticket)
        return SupportTicketDetailRead(
            **base.model_dump(),
            messages=[SupportTicketMessageRead.model_validate(m) for m in messages],
        )

    async def list_tickets(
        self,
        user: User,
        tenant_id: uuid.UUID,
        status_filter: Optional[str] = None,
        search: Optional[str] = None,
    ) -> List[SupportTicket]:
        user_filter = None if self._is_staff(user) else user.id
        return await self.repo.list_tickets(
            tenant_id=tenant_id,
            user_id=user_filter,
            status=status_filter,
            search=search,
        )

    async def get_ticket_summary(
        self, user: User, tenant_id: uuid.UUID
    ) -> SupportTicketSummary:
        """
        Support card counters for the home dashboard.
        Customers count only their own tickets; tenant staff count the whole tenant.
        """
        counts = await self.repo.support_ticket_summary(
            tenant_id=tenant_id,
            user_id=None if self._is_staff(user) else user.id,
        )
        return SupportTicketSummary(**counts)

    async def _next_ticket_number(self, tenant_id: uuid.UUID, now_utc: datetime) -> str:
        """
        `TKT-<IST yyyymmdd>-<serial>`: the serial comes from the repository's per-tenant
        locked allocator (call inside the transaction that saves the ticket), the date is
        India time so a ticket raised at 04:00 IST is not labelled with yesterday's date.
        """
        serial = await self.repo.allocate_ticket_serial(tenant_id)
        ist_day = now_utc.replace(tzinfo=timezone.utc).astimezone(IST).strftime("%Y%m%d")
        return f"TKT-{ist_day}-{serial:0{TICKET_SERIAL_WIDTH}d}"

    async def _resolve_ticket_shipment(
        self,
        user: User,
        tenant_id: uuid.UUID,
        raw_tracking_id: Optional[str],
    ) -> Tuple[Optional[uuid.UUID], Optional[str]]:
        """
        Resolves an optional AWB (`tracking_id`) on ticket creation.
        Client-supplied `shipment_id` is always ignored (B-09); for customer
        callers the shipment must also belong to `user.id`.
        """
        tracking_id = raw_tracking_id.strip() if raw_tracking_id else None
        if not tracking_id:
            return None, None
        shipment = await self.repo.find_shipment_by_tracking_id(
            tenant_id=tenant_id, tracking_id=tracking_id
        )
        if shipment is None or (
            not self._is_staff(user) and shipment.created_by_user_id != user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Shipment not found.",
            )
        return shipment.id, shipment.tracking_id or tracking_id

    async def _assert_no_open_ticket_for_awb(
        self, tenant_id: uuid.UUID, tracking_id: Optional[str]
    ) -> None:
        """
        Delhivery One "Ticket Already Exists": an AWB has at most one OPEN ticket; a new
        request is pointed at it (the seller comments there instead).

        Raises:
            HTTPException(409): an OPEN ticket already exists for `tracking_id`.
        """
        if not tracking_id:
            return
        open_tickets = await self.repo.get_open_tickets_by_tracking_id(tenant_id, tracking_id)
        if open_tickets:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=DUPLICATE_TICKET_DETAIL.format(
                    ticket_number=open_tickets[0].ticket_number, tracking_id=tracking_id
                ),
            )

    async def create_ticket(
        self,
        user: User,
        tenant_id: uuid.UUID,
        payload: SupportTicketCreate,
    ) -> SupportTicketDetailRead:
        assert_not_read_only(user, "create support tickets")
        now = _utc_now_naive()
        shipment_id, tracking_id = await self._resolve_ticket_shipment(
            user=user,
            tenant_id=tenant_id,
            raw_tracking_id=payload.tracking_id,
        )
        await self._assert_no_open_ticket_for_awb(tenant_id, tracking_id)
        ticket_number = await self._next_ticket_number(tenant_id, now)

        subject = (
            payload.subject.strip()
            if payload.subject and payload.subject.strip()
            else payload.sub_category.strip()
        )
        cat_group = (
            payload.category_group or TicketCategoryGroup.SHIPMENT_ISSUE.value
        ).strip().upper()

        ticket = SupportTicket(
            tenant_id=tenant_id,
            user_id=user.id,
            ticket_number=ticket_number,
            shipment_id=shipment_id,
            tracking_id=tracking_id,
            category_group=cat_group,
            sub_category=payload.sub_category.strip(),
            subject=subject,
            description=payload.description.strip(),
            status=TicketStatus.OPEN.value,
            cc_emails=[e.strip() for e in (payload.cc_emails or []) if e and e.strip()],
            email_notifications=payload.email_notifications,
            raised_by_email=user.email,
            created_at=now,
            updated_at=now,
        )
        await self.repo.save_ticket(ticket, commit=False)

        initial_msg = SupportTicketMessage(
            ticket_id=ticket.id,
            sender_user_id=user.id,
            sender_email=user.email,
            sender_role=user.role.value,
            message=payload.description.strip(),
            attachment_url=payload.attachment_url,
            created_at=now,
        )
        await self.repo.save_ticket_message(initial_msg, commit=True)
        await self.repo.session.refresh(ticket)
        return self._to_ticket_detail(ticket, [initial_msg])

    async def get_ticket_detail(
        self, user: User, tenant_id: uuid.UUID, ticket_id: str
    ) -> SupportTicketDetailRead:
        ticket = await self.repo.get_ticket_by_identifier(tenant_id, ticket_id)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
            )
        if not self._is_staff(user) and ticket.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
            )
        messages = await self.repo.list_ticket_messages(ticket.id)
        return self._to_ticket_detail(ticket, messages)

    async def add_ticket_message(
        self,
        user: User,
        tenant_id: uuid.UUID,
        ticket_id: str,
        payload: SupportTicketMessageCreate,
    ) -> SupportTicketDetailRead:
        assert_not_read_only(user, "reply to support tickets")
        ticket = await self.repo.get_ticket_by_identifier(tenant_id, ticket_id)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
            )
        if not self._is_staff(user) and ticket.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
            )
        if ticket.status == TicketStatus.CLOSED.value and not self._is_staff(user):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This ticket is closed and cannot receive new replies. "
                    "Please reopen by raising a new ticket."
                ),
            )

        now = _utc_now_naive()
        msg = SupportTicketMessage(
            ticket_id=ticket.id,
            sender_user_id=user.id,
            sender_email=user.email,
            sender_role=user.role.value,
            message=payload.message.strip(),
            attachment_url=payload.attachment_url,
            created_at=now,
        )
        await self.repo.save_ticket_message(msg, commit=False)

        # If ticket was RESOLVED and customer replies, auto-reopen to OPEN
        if ticket.status == TicketStatus.RESOLVED.value and (
            user.role == UserRole.customer or user.id == ticket.user_id
        ):
            ticket.status = TicketStatus.OPEN.value
        ticket.updated_at = now
        await self.repo.save_ticket(ticket, commit=True)

        messages = await self.repo.list_ticket_messages(ticket.id)
        return self._to_ticket_detail(ticket, messages)

    async def update_ticket_status(
        self,
        user: User,
        tenant_id: uuid.UUID,
        ticket_id: str,
        payload: SupportTicketStatusUpdate,
    ) -> SupportTicketDetailRead:
        assert_not_read_only(user, "update support ticket status")
        ticket = await self.repo.get_ticket_by_identifier(tenant_id, ticket_id)
        if not ticket:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
            )
        if not self._is_staff(user) and ticket.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Support ticket not found"
            )

        desired = payload.status.strip().upper()
        valid_statuses = {
            TicketStatus.OPEN.value,
            TicketStatus.RESOLVED.value,
            TicketStatus.CLOSED.value,
        }
        if desired not in valid_statuses:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid ticket status '{payload.status}'. Must be OPEN, RESOLVED, or CLOSED.",
            )
        if not self._is_staff(user) and (
            ticket.status == TicketStatus.CLOSED.value
            or desired == TicketStatus.OPEN.value
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Closed tickets cannot be reopened. "
                    "Please reopen by raising a new ticket."
                ),
            )

        ticket.status = desired
        ticket.updated_at = _utc_now_naive()
        await self.repo.save_ticket(ticket, commit=True)
        messages = await self.repo.list_ticket_messages(ticket.id)
        return self._to_ticket_detail(ticket, messages)

    # ------------------------------------------------------------------
    # 4. Weight Disputes
    # ------------------------------------------------------------------

    @staticmethod
    def _format_shipment_dims(shipment: PickupRequest) -> str:
        pkgs = getattr(shipment, "packages", None) or []
        if pkgs:
            first = pkgs[0]
            if float(first.length or 0) > 0 and float(first.breadth or 0) > 0 and float(first.height or 0) > 0:
                return f"{first.length:g} x {first.breadth:g} x {first.height:g} cm"
        return ""

    @staticmethod
    def _shipment_status_label(shipment_status: Optional[PickupStatus]) -> str:
        """Weight-mismatch "Status" column text for a shipment status (`SHIPMENT_STATUS_LABELS`)."""
        if shipment_status is None:
            return IN_TRANSIT_STATUS_LABEL
        return SHIPMENT_STATUS_LABELS.get(PickupStatus(shipment_status), IN_TRANSIT_STATUS_LABEL)

    @classmethod
    def _map_shipment_status_label(cls, shipment: PickupRequest) -> str:
        return cls._shipment_status_label(shipment.status)

    async def record_weight_audit_dispute(
        self,
        shipment: PickupRequest,
        old_weight_kg: float,
        audited_weight_kg: float,
        old_total: float,
        new_total: float,
        charged_dims: Optional[str] = None,
        evidence_urls: Optional[Sequence[str]] = None,
    ) -> Optional[WeightDispute]:
        """
        Creates or updates a WeightDispute row when a shipment's weight is measured.
        Does NOT commit (the calling ShipmentService owns the unit of work).

        `cost_diff_inr` is cumulative against the bill before the FIRST measurement, so a
        second audit never shrinks what an accepted claim can refund. `charged_dims` is the
        measured box size ("L x B x H cm"); empty string is stored when only a weight was keyed (C-09).
        """
        if not shipment.tracking_id:
            return None
        if round(audited_weight_kg, 3) == round(old_weight_kg, 3) and round(
            new_total, 2
        ) == round(old_total, 2):
            return None

        manifested_g = round(max(old_weight_kg, 0.0) * GRAMS_PER_KG, MONEY_DECIMALS)
        if manifested_g <= 0:
            pkgs = getattr(shipment, "packages", None) or []
            if pkgs:
                pkg = pkgs[0]
                manifested_g = round(
                    float(pkg.weight)
                    * (1.0 if pkg.weight_unit == WeightUnit.G else GRAMS_PER_KG),
                    MONEY_DECIMALS,
                )
            else:
                manifested_g = 500.0

        charged_g = round(audited_weight_kg * GRAMS_PER_KG, MONEY_DECIMALS)
        cost_diff = round(max(0.0, new_total - old_total), MONEY_DECIMALS)
        pd = shipment.payment_details
        shipment_val = round(
            float(pd.shipment_total_value if pd else 0.0), MONEY_DECIMALS
        )
        first_photo = next((u.strip() for u in (evidence_urls or []) if u and u.strip()), None)

        existing = await self.repo.get_weight_dispute_by_tracking_id(
            tenant_id=shipment.tenant_id, tracking_id=shipment.tracking_id
        )
        now = _utc_now_naive()
        if existing:
            first_billed = float(existing.shipping_cost_inr or 0.0) - float(existing.cost_diff_inr or 0.0)
            existing.charged_weight_g = charged_g
            existing.shipping_cost_inr = round(new_total, MONEY_DECIMALS)
            existing.shipment_value_inr = shipment_val
            existing.cost_diff_inr = round(max(0.0, new_total - first_billed), MONEY_DECIMALS)
            if charged_dims is not None:
                existing.charged_dims = charged_dims
            if first_photo:
                existing.sorter_image_url = first_photo
            existing.shipment_status = self._map_shipment_status_label(shipment)
            existing.updated_at = now
            return await self.repo.save_weight_dispute(existing, commit=False)

        if cost_diff <= 0 and charged_g <= manifested_g:
            return None

        dispute = WeightDispute(
            tenant_id=shipment.tenant_id,
            merchant_user_id=shipment.created_by_user_id,
            shipment_id=shipment.id,
            tracking_id=shipment.tracking_id,
            order_reference_id=shipment.order_reference_id,
            shipment_status=self._map_shipment_status_label(shipment),
            manifested_weight_g=manifested_g,
            charged_weight_g=charged_g,
            manifested_dims=self._format_shipment_dims(shipment),
            charged_dims=charged_dims or "",
            shipping_cost_inr=round(new_total, MONEY_DECIMALS),
            shipment_value_inr=shipment_val,
            cost_diff_inr=cost_diff,
            sorter_image_url=first_photo,
            claim_status=WeightDisputeClaimStatus.NONE.value,
            raised_at=now,
            updated_at=now,
        )
        return await self.repo.save_weight_dispute(dispute, commit=False)

    async def list_weight_disputes(
        self,
        user: User,
        tenant_id: uuid.UUID,
        search: Optional[str] = None,
        claim_status: Optional[str] = None,
    ) -> List[WeightDispute]:
        """
        Weight-mismatch rows in the caller's scope, each labelled with its merchant's
        email (staff view) and the shipment's CURRENT status: the stored label is only
        refreshed on a re-audit, so a parcel audited in transit would otherwise stay
        "In-transit" after delivery.
        """
        rows = await self.repo.list_weight_disputes(
            tenant_id=tenant_id,
            merchant_user_id=self._dispute_scope_user_id(user),
            search=search,
            claim_status=claim_status,
        )
        await self._attach_merchant_emails(tenant_id, rows)
        await self._refresh_dispute_status_labels(tenant_id, rows)
        return rows

    async def _refresh_dispute_status_labels(
        self, tenant_id: uuid.UUID, rows: Sequence[WeightDispute]
    ) -> None:
        """
        Overwrites each row's `shipment_status` with the live shipment status label, as a
        committed (not dirty) value so this read never writes back to the table.
        """
        shipment_ids = [row.shipment_id for row in rows if row.shipment_id is not None]
        if not shipment_ids:
            return
        statuses = await self.repo.get_shipment_statuses(tenant_id, shipment_ids)
        for row in rows:
            if row.shipment_id in statuses:
                set_committed_value(
                    row,
                    "shipment_status",
                    self._shipment_status_label(statuses[row.shipment_id]),
                )

    async def _load_claimable_dispute(
        self, user: User, tenant_id: uuid.UUID, tracking_id: str
    ) -> WeightDispute:
        """
        The audit-created dispute a claim may be raised on, row-locked.

        - 404 when the AWB is unknown or (for customers) not their own shipment,
          so another merchant's AWB is indistinguishable from a missing one.
        - 400 when ops never recorded a weight discrepancy (no audit dispute row);
          claims never invent a dispute or a cost difference.
        - 400 when the claim was already ACCEPTED / REJECTED (final states).
        """
        shipment = await self.repo.find_shipment_by_tracking_id(tenant_id, tracking_id)
        if shipment is None or (
            not is_tenant_staff(user) and shipment.created_by_user_id != user.id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=SHIPMENT_NOT_FOUND_DETAIL,
            )
        dispute = await self.repo.get_weight_dispute_by_tracking_id(
            tenant_id, tracking_id, for_update=True
        )
        if dispute is None:
            raise self._bad_request(
                f"No weight discrepancy recorded for this AWB ({tracking_id})."
            )
        if dispute.claim_status in FINAL_CLAIM_STATUSES:
            raise self._bad_request(
                f"The weight claim for {tracking_id} is already {dispute.claim_status} "
                "and cannot be raised again."
            )
        if dispute.claim_status == WeightDisputeClaimStatus.CLAIM_RAISED.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A weight claim is already under review for {tracking_id} "
                    "and cannot be modified while pending resolution."
                ),
            )
        if float(dispute.cost_diff_inr or 0.0) <= 0:
            raise self._bad_request(
                f"No upward weight billing difference is recorded on {tracking_id}."
            )
        return dispute

    async def _open_claim_ticket(
        self, user: User, tenant_id: uuid.UUID, dispute: WeightDispute, now: datetime
    ) -> None:
        """
        Opens the correlated support ticket (in the merchant's name) unless an OPEN weight
        claim ticket already exists for the AWB. Other open tickets on the AWB (e.g. a
        delivery query) do not suppress it: the claim must always be visible in Support.
        """
        tracking_id = dispute.tracking_id
        if await self.repo.get_open_tickets_by_tracking_id(
            tenant_id, tracking_id, sub_category=WEIGHT_CLAIM_TICKET_SUBCATEGORY
        ):
            return
        ticket_number = await self._next_ticket_number(tenant_id, now)
        claim_desc = dispute.claim_remarks or (
            f"Weight mismatch claim raised for {tracking_id} "
            f"(Manifested: {dispute.manifested_weight_g:.0f}g vs "
            f"Charged: {dispute.charged_weight_g:.0f}g)"
        )
        linked_ticket = SupportTicket(
            tenant_id=tenant_id,
            user_id=dispute.merchant_user_id,
            ticket_number=ticket_number,
            shipment_id=dispute.shipment_id,
            tracking_id=tracking_id,
            category_group=TicketCategoryGroup.SHIPMENT_ISSUE.value,
            sub_category=WEIGHT_CLAIM_TICKET_SUBCATEGORY,
            subject=f"Weight Mismatch Claim — {tracking_id}",
            description=claim_desc,
            status=TicketStatus.OPEN.value,
            cc_emails=[],
            email_notifications=True,
            raised_by_email=user.email,
            created_at=now,
            updated_at=now,
        )
        await self.repo.save_ticket(linked_ticket, commit=False)
        initial_msg = SupportTicketMessage(
            ticket_id=linked_ticket.id,
            sender_user_id=user.id,
            sender_email=user.email,
            sender_role=user.role.value,
            message=claim_desc,
            created_at=now,
        )
        await self.repo.save_ticket_message(initial_msg, commit=False)

    async def raise_weight_claims(
        self,
        user: User,
        tenant_id: uuid.UUID,
        payload: WeightDisputeClaimCreate,
    ) -> List[WeightDispute]:
        """
        Raises (or updates an open) weight claim on audited AWBs. Customers may only
        claim their own shipments; staff (except read-only) may claim on a
        merchant's behalf. The whole request is atomic: any invalid AWB rejects it.
        """
        assert_not_read_only(user, "raise weight mismatch claims")
        cleaned_ids = list(
            dict.fromkeys(
                tid.strip() for tid in (payload.tracking_ids or []) if tid and tid.strip()
            )
        )
        if not cleaned_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one AWB / tracking_id is required to raise a weight claim.",
            )
        if len(cleaned_ids) > 1:
            raise self._bad_request(
                "Bulk weight claims with a single weight are disabled. "
                "Please raise a claim for one AWB at a time."
            )

        updated_rows: List[WeightDispute] = []
        now = _utc_now_naive()
        for tid in cleaned_ids:
            dispute = await self._load_claimable_dispute(user, tenant_id, tid)
            manifested_g = float(dispute.manifested_weight_g or 0.0)
            effective_claimed_g = (
                float(payload.claimed_weight_g)
                if payload.claimed_weight_g is not None
                else manifested_g
            )
            charged_g = float(dispute.charged_weight_g or 0.0)
            is_fee_only_dispute = (
                charged_g <= manifested_g and float(dispute.cost_diff_inr or 0.0) > 0
            )
            invalid_claimed_weight = (
                effective_claimed_g <= 0
                or (
                    effective_claimed_g > charged_g
                    if is_fee_only_dispute
                    else effective_claimed_g >= charged_g
                )
            )
            if invalid_claimed_weight:
                raise self._bad_request(
                    f"Claimed weight ({effective_claimed_g:g} g) must be greater than 0 g "
                    f"and strictly less than the charged weight ({charged_g:g} g)."
                )
            dispute.claimed_weight_g = effective_claimed_g
            if payload.claim_remarks is not None:
                dispute.claim_remarks = payload.claim_remarks.strip()
            dispute.claim_status = WeightDisputeClaimStatus.CLAIM_RAISED.value
            dispute.updated_at = now
            saved = await self.repo.save_weight_dispute(dispute, commit=False)
            updated_rows.append(saved)
            await self._open_claim_ticket(user, tenant_id, saved, now)

        await self.repo.session.commit()
        for row in updated_rows:
            await self.repo.session.refresh(row)
        return updated_rows

    async def open_short_shipment_ticket(
        self,
        *,
        shipment: PickupRequest,
        actor: User,
        delivered_boxes: int,
        declared_boxes: int,
    ) -> Optional[str]:
        """
        Opens a "Short Shipment / Missing boxes" ticket in the merchant's name when fewer
        boxes were delivered than booked (plan B6; loss handled through claims, DO1
        `lost-and-damage-claims-b2b-1`). Skipped when an OPEN ticket already exists for the
        AWB. Does NOT commit.

        Returns:
            The new ticket number, or None when one was already open.
        """
        tracking_id = shipment.tracking_id or str(shipment.id)
        if await self.repo.get_open_tickets_by_tracking_id(shipment.tenant_id, tracking_id):
            return None
        now = _utc_now_naive()
        ticket_number = await self._next_ticket_number(shipment.tenant_id, now)
        description = (
            f"Short shipment on {tracking_id}: {delivered_boxes} of {declared_boxes} boxes "
            "delivered. The missing boxes are being traced; raise a loss claim if they are not found."
        )
        ticket = SupportTicket(
            tenant_id=shipment.tenant_id,
            user_id=shipment.created_by_user_id,
            ticket_number=ticket_number,
            shipment_id=shipment.id,
            tracking_id=tracking_id,
            category_group=TicketCategoryGroup.SHIPMENT_ISSUE.value,
            sub_category=SHORT_SHIPMENT_TICKET_SUBCATEGORY,
            subject=f"Short Shipment — {tracking_id}",
            description=description,
            status=TicketStatus.OPEN.value,
            cc_emails=[],
            email_notifications=True,
            raised_by_email=actor.email,
            created_at=now,
            updated_at=now,
        )
        await self.repo.save_ticket(ticket, commit=False)
        await self.repo.save_ticket_message(
            SupportTicketMessage(
                ticket_id=ticket.id,
                sender_user_id=actor.id,
                sender_email=actor.email,
                sender_role=actor.role.value,
                message=description,
                created_at=now,
            ),
            commit=False,
        )
        return ticket_number

    async def resolve_weight_dispute(
        self,
        admin_user: User,
        tenant_id: uuid.UUID,
        dispute_id: uuid.UUID,
        payload: WeightDisputeResolveRequest,
        claim_settler: Optional[ClaimSettler] = None,
    ) -> WeightDispute:
        """
        Accepts or rejects a raised claim. Only CLAIM_RAISED -> ACCEPTED / REJECTED is
        allowed; both outcomes are final, so the settlement runs once, under a row lock.

        On ACCEPTED, `claim_settler` (ShipmentService.settle_accepted_weight_claim, injected
        by the controller to avoid an import cycle) re-bills the shipment on the claimed
        weight through RepricingService: refund + CREDIT_NOTE of exactly the difference, and
        the bill and COD collectible are restored (plan B3).
        """
        assert_not_read_only(admin_user, "resolve weight mismatch claims")
        self._require_admin(
            admin_user, "Only Tenant Admins can resolve weight mismatch claims."
        )
        desired = payload.claim_status.strip().upper()
        if desired not in FINAL_CLAIM_STATUSES:
            raise self._bad_request("claim_status must be ACCEPTED or REJECTED.")
        dispute = await self.repo.get_weight_dispute_by_id(
            tenant_id, dispute_id, for_update=True
        )
        if not dispute:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Weight dispute record not found",
            )
        if dispute.claim_status in FINAL_CLAIM_STATUSES:
            raise self._bad_request(
                f"This weight claim is already {dispute.claim_status}; resolved claims are final."
            )
        if dispute.claim_status != WeightDisputeClaimStatus.CLAIM_RAISED.value:
            raise self._bad_request(
                "No claim has been raised on this weight discrepancy yet."
            )
        if payload.expected_claimed_weight_g is not None:
            actual_claimed_g = float(
                dispute.claimed_weight_g
                if dispute.claimed_weight_g is not None
                else dispute.manifested_weight_g or 0.0
            )
            if abs(float(payload.expected_claimed_weight_g) - actual_claimed_g) > 0.01:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "The claimed weight on this dispute changed since you opened it; "
                        "please refresh before resolving."
                    ),
                )

        dispute.claim_status = desired
        if payload.claim_remarks is not None:
            dispute.claim_remarks = payload.claim_remarks.strip()
        now = _utc_now_naive()
        dispute.updated_at = now
        await self.repo.save_weight_dispute(dispute, commit=False)

        if (
            desired == WeightDisputeClaimStatus.ACCEPTED.value
            and dispute.shipment_id is not None
            and claim_settler is not None
        ):
            await claim_settler(dispute)

        # Auto-resolve the correlated OPEN weight-claim ticket(s) for this AWB; unrelated
        # tickets on the same AWB (delivery query, damage, ...) stay open.
        open_tickets = await self.repo.get_open_tickets_by_tracking_id(
            tenant_id, dispute.tracking_id, sub_category=WEIGHT_CLAIM_TICKET_SUBCATEGORY
        )
        for tkt in open_tickets:
            tkt.status = TicketStatus.RESOLVED.value
            tkt.updated_at = now
            await self.repo.save_ticket(tkt, commit=False)
            res_msg = SupportTicketMessage(
                ticket_id=tkt.id,
                sender_user_id=admin_user.id,
                sender_email=admin_user.email,
                sender_role=admin_user.role.value,
                message=(
                    f"Weight dispute claim {desired}: "
                    f"{dispute.claim_remarks or 'Resolved by Admin'}"
                ),
                created_at=now,
            )
            await self.repo.save_ticket_message(res_msg, commit=False)

        await self.repo.session.commit()
        await self.repo.session.refresh(dispute)
        return dispute

    async def export_weight_disputes_csv(
        self,
        user: User,
        tenant_id: uuid.UUID,
        search: Optional[str] = None,
        claim_status: Optional[str] = None,
    ) -> io.StringIO:
        rows = await self.list_weight_disputes(
            user=user,
            tenant_id=tenant_id,
            search=search,
            claim_status=claim_status,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "AWB / Tracking ID",
                "Order Reference",
                "Shipment Status",
                "Manifested Weight (g)",
                "Charged Weight (g)",
                "Claimed Weight (g)",
                "Manifested Dims",
                "Charged Dims",
                "Shipping Cost (INR)",
                "Cost Diff (INR)",
                "Claim Status",
                "Updated At",
            ]
        )
        for r in rows:
            writer.writerow(
                [
                    r.tracking_id,
                    r.order_reference_id or "",
                    r.shipment_status,
                    f"{r.manifested_weight_g:.0f}",
                    f"{r.charged_weight_g:.0f}",
                    f"{r.claimed_weight_g:.0f}" if r.claimed_weight_g is not None else "",
                    r.manifested_dims,
                    r.charged_dims,
                    f"{r.shipping_cost_inr:.2f}",
                    f"{r.cost_diff_inr:.2f}",
                    r.claim_status,
                    r.updated_at.strftime("%Y-%m-%d %H:%M:%S"),
                ]
            )
        output.seek(0)
        return output


def get_delhivery_modules_service(
    session: AsyncSession = Depends(get_session),
) -> DelhiveryModulesService:
    repo = DelhiveryModulesRepository(session)
    return DelhiveryModulesService(repo)
