"""
WP6 GST documents (prelaunch audit C-01, C-02, C-03, C-04, C-05, C-12, C-14): pure unit
tests. No database and no FastAPI app: the service runs against an in-memory fake
repository, and PDFs are checked by extracting their text with `pypdf`.

Run without the DB-backed conftest:
    PYTHONDONTWRITEBYTECODE=1 poetry run pytest --noconftest scripts/tests/test_gst_documents_unit.py
"""

import copy
import io
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.models.delhivery_modules import BillingInvoice, InvoiceNoteType
from app.models.pickups import ShipmentType
from app.models.tenants import ServiceScope, UserRole
from app.repositories.delhivery_modules import (
    LOCK_NOT_AVAILABLE_SQLSTATE,
    DelhiveryModulesRepository,
    DocumentSeriesBusyError,
)
from app.schemas.v1.delhivery_modules import BillingInvoiceCreate, BillingInvoiceRead
from app.schemas.v1.tenants import SellerCompanyDetailsSubmit, UserSelfUpdate
from app.services import gst_documents as gd
from app.services.delhivery_modules import (
    DelhiveryModulesService,
    merchant_kyc_entry,
    render_gst_document,
    resolve_place_of_supply,
)
from app.services.tenants import TenantService
from app.services.wallet import today_ist
from scripts.tenant_data_core import ALLOWED_TEST_SLUGS

pypdf = pytest.importorskip("pypdf")

SUPPLIER_GSTIN = "06AAECL2138H1ZQ"
"""Haryana (06): the logismart-test fixture GSTIN, checksum-valid."""
BUYER_GSTIN_MH = "27AAPFU0939F1ZV"
"""Maharashtra (27), checksum-valid."""
BUYER_GSTIN_KA = "29AAGCB7383J1Z4"
"""Karnataka (29), checksum-valid."""
BAD_CHECKSUM_GSTIN = "27AABCL1234F1Z5"
"""Well-formed but the 15th character is wrong (the legacy fake GSTIN)."""
LEGAL_NAME = "LOGISMART PRIVATE LIMITED"
REGISTERED_ADDRESS = "H. NO-632/5, GALI NO-3, PATEL NAGAR, Gurgaon, Haryana, 122001"
BOOKING_TOTAL = 94.40
BOOKING_TAX = 14.40
BOOKING_BREAKDOWN = {
    "base_charge": 50.0,
    "fuel_surcharge": 5.0,
    "network_surcharge": 25.0,
    "subtotal": 80.0,
}


# ----------------------------------------------------------------------------
# Fakes
# ----------------------------------------------------------------------------


def _tenant_settings(kyc: Optional[Dict[str, Any]] = None, environment: str = "test") -> Dict[str, Any]:
    settings: Dict[str, Any] = {
        "environment": environment,
        "company": {
            "gstin": SUPPLIER_GSTIN,
            "legal_name": LEGAL_NAME,
            "registered_address": REGISTERED_ADDRESS,
            "invoice_prefix": "LTST",
        },
    }
    if kyc is not None:
        settings[gd.KYC_REQUESTS_SETTINGS_KEY] = kyc
    return settings


def _tenant(settings: Dict[str, Any], slug: str = "logismart-test") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), name="LOGISMART SHIPPING (TEST)", slug=slug, settings=settings)


def _user(tenant_id: uuid.UUID, role: UserRole = UserRole.customer, **extra: Any) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email="seller@example.com",
        full_name="Ramesh Seller",
        phone=None,
        role=role,
        service_scope=ServiceScope.B2C,
        **extra,
    )


def _address(tenant_id: uuid.UUID, city: str, state: str, pincode: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        address_line1="Plot 7, Sector 18",
        address_line2=None,
        landmark=None,
        city=city,
        state=state,
        pincode=pincode,
    )


class FakeRepo:
    """In-memory stand-in for `DelhiveryModulesRepository` (only what the GST paths use)."""

    def __init__(self, tenant: SimpleNamespace, users: List[SimpleNamespace], addresses: List[SimpleNamespace]):
        self.tenant = tenant
        self.users = {u.id: u for u in users}
        self.addresses = {a.id: a for a in addresses}
        self.invoices: List[BillingInvoice] = []
        self.serials: Dict[str, int] = {}

    async def get_tenant(self, tenant_id: uuid.UUID) -> Optional[SimpleNamespace]:
        return self.tenant if tenant_id == self.tenant.id else None

    async def get_tenant_user(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Optional[SimpleNamespace]:
        user = self.users.get(user_id)
        return user if user is not None and user.tenant_id == tenant_id else None

    async def get_address(self, address_id: Optional[uuid.UUID]) -> Optional[SimpleNamespace]:
        return self.addresses.get(address_id) if address_id else None

    async def get_shipment_billing_document(
        self, tenant_id: uuid.UUID, shipment_id: uuid.UUID, note_type: str = InvoiceNoteType.INVOICE.value
    ) -> Optional[BillingInvoice]:
        return next(
            (
                inv
                for inv in self.invoices
                if inv.tenant_id == tenant_id and inv.shipment_id == shipment_id and inv.note_type == note_type
            ),
            None,
        )

    async def get_invoice_by_identifier(self, tenant_id: uuid.UUID, identifier: str) -> Optional[BillingInvoice]:
        return next(
            (inv for inv in self.invoices if inv.tenant_id == tenant_id and inv.invoice_number == identifier),
            None,
        )

    async def allocate_document_sequence(
        self, *, tenant_id: uuid.UUID, financial_year: str, note_type: str, number_prefix: str
    ) -> int:
        self.serials[number_prefix] = self.serials.get(number_prefix, 0) + 1
        return self.serials[number_prefix]

    async def save_invoice(self, invoice: BillingInvoice, commit: bool = True) -> BillingInvoice:
        if invoice.id is None:
            invoice.id = uuid.uuid4()
        self.invoices.append(invoice)
        return invoice


def _world(kyc_for_seller: Optional[Dict[str, Any]] = None):
    """Tenant (Haryana supplier), one seller, a Gurgaon pickup and a Mumbai drop."""
    tenant = _tenant(_tenant_settings())
    seller = _user(tenant.id)
    if kyc_for_seller is not None:
        tenant.settings[gd.KYC_REQUESTS_SETTINGS_KEY] = {str(seller.id): kyc_for_seller}
    pickup = _address(tenant.id, "Gurgaon", "Haryana", "122001")
    drop = _address(tenant.id, "Mumbai", "Maharashtra", "400001")
    repo = FakeRepo(tenant, [seller], [pickup, drop])
    shipment = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        tracking_id="LSAWB0001",
        order_reference_id="ORD-1",
        pickup_address_id=pickup.id,
        delivery_address_id=drop.id,
        created_by_user_id=seller.id,
        payment_details=SimpleNamespace(
            total_logistics_cost=BOOKING_TOTAL,
            tax_amount=BOOKING_TAX,
            pricing_breakdown=dict(BOOKING_BREAKDOWN),
            chargeable_weight=0.5,
        ),
    )
    return tenant, seller, repo, shipment, DelhiveryModulesService(repo)


def _pdf_text(buffer: io.BytesIO) -> str:
    """The PDF's text with whitespace collapsed (a bold label and its value are separate runs)."""
    reader = pypdf.PdfReader(buffer)
    return " ".join(" ".join(page.extract_text() or "" for page in reader.pages).split())


# ----------------------------------------------------------------------------
# Pure helpers
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("gstin", [SUPPLIER_GSTIN, BUYER_GSTIN_MH, BUYER_GSTIN_KA])
def test_checksum_accepts_real_gstins(gstin):
    assert gd.is_checksum_valid_gstin(gstin)
    assert gd.is_checksum_valid_gstin(gstin.lower())


@pytest.mark.parametrize(
    "gstin", [BAD_CHECKSUM_GSTIN, "99AAPFU0939F1ZV", "27AAPFU0939F1Z", "27AAPFU0939F1XV", "", None]
)
def test_checksum_rejects_bad_gstins(gstin):
    assert not gd.is_checksum_valid_gstin(gstin)


def test_pan_and_place_of_supply_label():
    assert gd.pan_from_gstin(SUPPLIER_GSTIN) == "AAECL2138H"
    assert gd.place_of_supply_label("06") == "Haryana (06)"
    assert gd.place_of_supply_label("27") == "Maharashtra (27)"
    assert gd.place_of_supply_label("99") is None
    assert gd.place_of_supply_label(None) is None


@pytest.mark.parametrize(
    "derived, printed", [(18.06, 18.0), (17.94, 18.0), (5.2, 5.0), (0.0, 0.0), (17.2, 17.2), (15.0, 15.0)]
)
def test_rate_snaps_to_gst_slab_only_when_close(derived, printed):
    assert gd.nominal_gst_rate_percent(derived) == printed


def test_tax_rows_are_cgst_sgst_or_igst_at_the_configured_rate():
    intra = gd.gst_tax_rows(cgst=7.2, sgst=7.2, igst=0.0, rate_percent=18.0)
    assert [(r.label, r.amount) for r in intra] == [("CGST @ 9%", 7.2), ("SGST @ 9%", 7.2)]
    inter = gd.gst_tax_rows(cgst=0.0, sgst=0.0, igst=14.4, rate_percent=18.0)
    assert [(r.label, r.amount) for r in inter] == [("IGST @ 18%", 14.4)]
    assert gd.gst_tax_rows(cgst=0.0, sgst=0.0, igst=0.0, rate_percent=0.0) == []
    assert gd.gst_tax_rows(cgst=0.5, sgst=0.5, igst=0.0, rate_percent=5.0)[0].label == "CGST @ 2.5%"


def test_legacy_row_prints_slab_rate_not_rounding_noise():
    """C-12: a small legacy note whose amounts give 18.06% prints 'IGST @ 18%'."""
    legacy = BillingInvoice(
        tenant_id=uuid.uuid4(),
        merchant_user_id=uuid.uuid4(),
        invoice_number="LTST2627D000001",
        note_type=InvoiceNoteType.DEBIT_NOTE.value,
        invoice_date=date(2026, 10, 1),
        due_date=date(2026, 10, 16),
        freight_amount=4.43,
        igst_amount=0.80,
        total_amount=5.23,
        line_items=[{"tax_rate_percent": 18.06, "place_of_supply": "27"}],
    )
    assert [r.label for r in gd.invoice_tax_rows(legacy)] == ["IGST @ 18%"]


@pytest.mark.parametrize(
    "entry, expected",
    [
        ({"status": "APPROVED", "gstin": BUYER_GSTIN_MH}, BUYER_GSTIN_MH),
        ({"status": "PENDING", "gstin": BUYER_GSTIN_MH}, None),
        ({"status": "REJECTED", "gstin": BUYER_GSTIN_MH}, None),
        ({"status": "APPROVED", "gstin": SUPPLIER_GSTIN}, None),
        ({"status": "APPROVED", "gstin": BUYER_GSTIN_MH, "same_as_tenant_gstin": True}, None),
        ({"status": "APPROVED", "gstin": "NOTAGSTIN"}, None),
        ({"gstin_status": "APPROVED", "verified_gstin": BUYER_GSTIN_MH, "gstin": BUYER_GSTIN_MH}, BUYER_GSTIN_MH),
        ({"gstin_status": "APPROVED", "verified_gstin": BUYER_GSTIN_MH, "gstin": BUYER_GSTIN_KA}, None),
        ({"gstin": BUYER_GSTIN_MH}, None),
        (None, None),
    ],
)
def test_only_approved_non_supplier_gstins_print(entry, expected):
    assert gd.approved_kyc_gstin(entry, SUPPLIER_GSTIN) == expected


def test_merchant_kyc_entry_is_looked_up_by_user_id():
    uid = uuid.uuid4()
    entry = {"status": "APPROVED", "gstin": BUYER_GSTIN_MH}
    settings = {gd.KYC_REQUESTS_SETTINGS_KEY: {str(uid): entry}}
    assert merchant_kyc_entry(settings, uid) == entry
    assert merchant_kyc_entry(settings, uuid.uuid4()) is None
    assert merchant_kyc_entry(settings, None) is None
    assert merchant_kyc_entry({gd.KYC_REQUESTS_SETTINGS_KEY: "bad"}, uid) is None


def test_bill_to_prefers_kyc_company_and_falls_back_to_account_and_pickup():
    kyc = {"status": "APPROVED", "gstin": BUYER_GSTIN_MH, "company_name": "Acme Traders", "billing_address": "Andheri, Mumbai"}
    party = gd.build_bill_to(kyc, "Ramesh", "Gurgaon 122001", "06", SUPPLIER_GSTIN)
    assert (party.name, party.address, party.gstin, party.state_code) == (
        "Acme Traders",
        "Andheri, Mumbai",
        BUYER_GSTIN_MH,
        "27",
    )
    fallback = gd.build_bill_to(None, "Ramesh", "Gurgaon 122001", "06", SUPPLIER_GSTIN)
    assert (fallback.name, fallback.address, fallback.gstin, fallback.state_code) == (
        "Ramesh",
        "Gurgaon 122001",
        None,
        "06",
    )


def test_charge_lines_always_add_up_to_the_taxable_value():
    lines = gd.shipment_charge_lines({**BOOKING_BREAKDOWN, "rto_surcharge": 0}, 80.0)
    assert [(line.label, line.amount) for line in lines] == [
        ("Base Freight", 50.0),
        ("Fuel Surcharge", 5.0),
        ("Network Surcharge", 25.0),
    ]
    with_unlisted = gd.shipment_charge_lines(BOOKING_BREAKDOWN, 92.5)
    assert with_unlisted[-1] == gd.ChargeLine("Other Charges", 12.5)
    assert round(sum(line.amount for line in with_unlisted), 2) == 92.5
    assert gd.shipment_charge_lines({}, 80.0) == [gd.ChargeLine("Freight Charges", 80.0)]
    assert gd.shipment_charge_lines(BOOKING_BREAKDOWN, 60.0) == [gd.ChargeLine("Freight Charges", 60.0)]


def test_company_details_lock_rules():
    assert not gd.company_details_locked(None)
    assert not gd.company_details_locked({"status": "PENDING", "gstin": BUYER_GSTIN_MH})
    assert gd.company_details_locked({"status": "APPROVED", "gstin": BUYER_GSTIN_MH})
    assert gd.company_details_locked({gd.COMPANY_DETAILS_SUBMITTED_AT_KEY: "2026-10-30T00:00:00+00:00"})


def test_specimen_tenants_match_the_test_allow_list():
    assert gd.SPECIMEN_TENANT_SLUGS == ALLOWED_TEST_SLUGS
    assert gd.is_specimen_tenant("logismart-test", {})
    assert gd.is_specimen_tenant("other", {"environment": "test"})
    assert not gd.is_specimen_tenant("logismart", {"environment": "production"})
    assert not gd.is_specimen_tenant(None, None)


# ----------------------------------------------------------------------------
# Issuing (service against the fake repository)
# ----------------------------------------------------------------------------


async def test_booking_invoice_snapshots_bill_to_rate_and_charge_lines():
    kyc = {"status": "APPROVED", "gstin": BUYER_GSTIN_MH, "company_name": "Acme Traders", "billing_address": "Andheri East, Mumbai 400069"}
    tenant, _seller, repo, shipment, service = _world(kyc)

    invoice = await service.record_shipment_billing_note(shipment=shipment)

    first = invoice.line_items[0]
    assert invoice.note_type == InvoiceNoteType.INVOICE.value
    assert first[gd.SNAPSHOT_VERSION_KEY] == gd.SNAPSHOT_VERSION
    assert first[gd.BILL_TO_KEY] == {
        "name": "Acme Traders",
        "address": "Andheri East, Mumbai 400069",
        "gstin": BUYER_GSTIN_MH,
        "state_code": "27",
    }
    assert first[gd.SUPPLIER_KEY]["name"] == LEGAL_NAME
    assert first["place_of_supply"] == "27"
    assert (invoice.igst_amount, invoice.cgst_amount, invoice.freight_amount) == (BOOKING_TAX, 0.0, 80.0)
    assert first["tax_rate_percent"] == 18.0
    assert first[gd.REVERSE_CHARGE_KEY] is False
    assert sum(line["amount"] for line in first[gd.CHARGE_LINES_KEY]) == invoice.freight_amount
    assert (first[gd.ORIGIN_KEY], first[gd.DESTINATION_KEY], first[gd.CHARGEABLE_WEIGHT_KEY]) == (
        "Gurgaon",
        "Mumbai",
        0.5,
    )


async def test_unapproved_kyc_gstin_never_reaches_the_document():
    tenant, _seller, repo, shipment, service = _world({"status": "PENDING", "gstin": BUYER_GSTIN_MH, "company_name": "Acme"})

    invoice = await service.record_shipment_billing_note(shipment=shipment)

    first = invoice.line_items[0]
    assert first[gd.BILL_TO_KEY]["gstin"] is None
    assert first["buyer_gstin"] is None
    assert first["place_of_supply"] == "06"
    assert invoice.cgst_amount == invoice.sgst_amount == 7.2
    assert first[gd.BILL_TO_KEY]["address"].endswith("Gurgaon, Haryana, 122001")


async def test_debit_note_without_an_original_is_issued_as_an_invoice():
    """C-03: a Mathadi / Freight Collection charge on a shipment with no INVOICE."""
    _tenant_obj, _seller, repo, shipment, service = _world()

    doc = await service.record_shipment_billing_note(
        shipment=shipment,
        note_type=InvoiceNoteType.DEBIT_NOTE.value,
        amount_override=59.0,
        is_separate_charge=True,
    )

    assert doc.note_type == InvoiceNoteType.INVOICE.value
    assert doc.original_invoice_id is None
    assert doc.invoice_number.startswith("LTST") and "I" in doc.invoice_number[4:9]
    first = doc.line_items[0]
    assert first["separate_charge"] is True
    assert first[gd.CHARGE_LINES_KEY] == [{"label": gd.SEPARATE_CHARGE_DESCRIPTION, "amount": 50.0}]


async def test_debit_and_credit_notes_quote_the_original_invoice():
    _tenant_obj, _seller, repo, shipment, service = _world()
    original = await service.record_shipment_billing_note(shipment=shipment)

    debit = await service.record_shipment_billing_note(
        shipment=shipment, note_type=InvoiceNoteType.DEBIT_NOTE.value, amount_override=11.80
    )
    credit = await service.record_shipment_billing_note(
        shipment=shipment,
        note_type=InvoiceNoteType.CREDIT_NOTE.value,
        amount_override=5.90,
        description="Weight dispute accepted",
    )

    for note in (debit, credit):
        assert note.original_invoice_id == original.id
        assert note.line_items[0]["original_invoice_number"] == original.invoice_number
        assert note.line_items[0]["tax_rate_percent"] == 18.0
    assert debit.line_items[0][gd.CHARGE_LINES_KEY][0]["label"] == "Additional Freight Charges"
    assert credit.line_items[0][gd.CHARGE_LINES_KEY][0]["label"] == "Weight dispute accepted"


@pytest.mark.parametrize(
    ("override_state", "note_type", "amount", "taxable", "tax"),
    [
        # J64: booked 159.30 (135.00 + 24.30), admin override to 100.00 -> refund 59.30.
        ((100.0, 15.25, 84.75), InvoiceNoteType.CREDIT_NOTE, 59.30, 50.25, 9.05),
        # Override up to 200.00 -> debit 40.70.
        ((200.0, 30.51, 169.49), InvoiceNoteType.DEBIT_NOTE, 40.70, 34.49, 6.21),
        # BUG-01b (prod S3): booked 47.88, override up to 106.88 -> debit 59.00 (was 42.09 + 16.91).
        ((106.88, 16.30, 90.58), InvoiceNoteType.DEBIT_NOTE, 59.00, 50.00, 9.00),
    ],
)
@pytest.mark.parametrize("inter_state", [False, True])
async def test_override_notes_split_at_18_percent(override_state, note_type, amount, taxable, tax, inter_state):
    """
    BUG-01: notes for an admin price override back out GST at 18 % (intra-state CGST + SGST,
    inter-state IGST). The overridden bill's own rate is 15.25 / 84.75 = 17.994 %, which must
    snap to the 18 % slab instead of moving the taxable value by a paisa.
    """
    kyc = {"status": "APPROVED", "gstin": BUYER_GSTIN_MH} if inter_state else None
    _tenant_obj, _seller, repo, shipment, service = _world(kyc)
    payment = shipment.payment_details
    payment.total_logistics_cost, payment.tax_amount = 159.30, 24.30
    payment.pricing_breakdown = {"subtotal": 135.0}
    original = await service.record_shipment_billing_note(shipment=shipment)
    total, tax_amount, subtotal = override_state
    payment.total_logistics_cost, payment.tax_amount = total, tax_amount
    payment.pricing_breakdown = {"subtotal": subtotal}

    note = await service.record_shipment_billing_note(
        shipment=shipment, note_type=note_type.value, amount_override=amount
    )

    assert note.note_type == note_type.value and note.original_invoice_id == original.id
    assert (note.total_amount, note.freight_amount) == (amount, taxable)
    assert round(note.cgst_amount + note.sgst_amount + note.igst_amount, 2) == tax
    if inter_state:
        assert (note.cgst_amount, note.sgst_amount, note.igst_amount) == (0.0, 0.0, tax)
    else:
        assert note.igst_amount == 0.0 and round(abs(note.cgst_amount - note.sgst_amount), 2) <= 0.01
    assert note.line_items[0]["tax_rate_percent"] == 18.0


class _LockSession:
    """Fake AsyncSession for `lock_document_series`: records SQL, optionally times out the lock."""

    def __init__(self, lock_error: Optional[Exception] = None):
        self.lock_error = lock_error
        self.statements: List[str] = []

    async def exec(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if "pg_advisory_xact_lock" in sql and self.lock_error is not None:
            raise self.lock_error
        return SimpleNamespace(first=lambda: ("0",))


def _db_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("SELECT pg_advisory_xact_lock", {}, SimpleNamespace(sqlstate=sqlstate))


async def test_series_lock_waits_at_most_the_timeout_and_restores_it():
    """BUG-03: the GST series lock is taken under a local lock_timeout, restored in the same round trip."""
    session = _LockSession()
    await DelhiveryModulesRepository(session).lock_document_series(uuid.uuid4(), "2627", "INVOICE")
    set_timeout, lock = session.statements
    assert "set_config('lock_timeout', :timeout, true)" in set_timeout
    assert "pg_advisory_xact_lock" in lock and "set_config('lock_timeout', :previous, true)" in lock


async def test_series_lock_timeout_becomes_a_retryable_503():
    """A lock wait that times out (55P03) aborts the request with 503 before anything commits."""
    tenant, _seller, repo, shipment, _service = _world()
    session = _LockSession(lock_error=_db_error(LOCK_NOT_AVAILABLE_SQLSTATE))
    real_repo = DelhiveryModulesRepository(session)
    with pytest.raises(DocumentSeriesBusyError):
        await real_repo.lock_document_series(tenant.id, "2627", "INVOICE")
    service = DelhiveryModulesService(real_repo)
    with pytest.raises(HTTPException) as exc:
        await service._allocate_document_number(tenant, InvoiceNoteType.INVOICE.value, today_ist())
    assert exc.value.status_code == 503
    assert exc.value.headers == {"Retry-After": "5"}
    assert "Nothing was charged" in exc.value.detail


async def test_other_lock_errors_are_not_masked():
    session = _LockSession(lock_error=_db_error("40P01"))
    with pytest.raises(DBAPIError):
        await DelhiveryModulesRepository(session).lock_document_series(uuid.uuid4(), "2627", "INVOICE")


async def test_issued_invoice_pdf_never_changes_after_a_reweigh():
    """C-04: re-downloading the original invoice after a re-price prints the same lines."""
    tenant, _seller, repo, shipment, service = _world()
    invoice = await service.record_shipment_billing_note(shipment=shipment)
    before = _pdf_text(render_gst_document(invoice, tenant))

    shipment.payment_details.pricing_breakdown = {"base_charge": 150.0, "subtotal": 180.0}
    shipment.payment_details.chargeable_weight = 2.5
    tenant.settings["company"]["legal_name"] = "RENAMED LATER PVT LTD"
    after = _pdf_text(render_gst_document(invoice, tenant))

    assert before == after
    assert "Base Freight" in after and "150.00" not in after and "2.50 kg" not in after


async def test_invoice_pdf_has_bill_to_supply_details_signatory_and_specimen():
    kyc = {"status": "APPROVED", "gstin": BUYER_GSTIN_MH, "company_name": "Acme Traders", "billing_address": "Andheri East, Mumbai 400069"}
    tenant, _seller, repo, shipment, service = _world(kyc)
    invoice = await service.record_shipment_billing_note(shipment=shipment)

    text = _pdf_text(render_gst_document(invoice, tenant))

    for expected in (
        "TAX INVOICE",
        LEGAL_NAME,
        "Bill To",
        "Acme Traders",
        BUYER_GSTIN_MH,
        "Place of Supply: Maharashtra (27)",
        "Reverse Charge: No",
        "IGST @ 18%",
        "AWB: LSAWB0001",
        "Due Date",
        "Authorised Signatory",
        "SPECIMEN",
    ):
        assert expected in text, expected
    assert "Billing Address" not in text
    assert "LOGISMART SHIPPING (TEST)" not in text


async def test_credit_note_pdf_quotes_original_and_has_no_due_date_or_specimen_on_live():
    tenant, _seller, repo, shipment, service = _world()
    tenant.slug, tenant.settings["environment"] = "logismart", "production"
    original = await service.record_shipment_billing_note(shipment=shipment)
    credit = await service.record_shipment_billing_note(
        shipment=shipment, note_type=InvoiceNoteType.CREDIT_NOTE.value, amount_override=11.80
    )

    text = _pdf_text(render_gst_document(credit, tenant))

    assert "CREDIT NOTE" in text and "Note No" in text
    assert f"Against Invoice: {original.invoice_number}" in text
    assert "Due Date" not in text and "Invoice No" not in text
    assert "CGST @ 9%" in text and "SGST @ 9%" in text
    assert "GSTIN: Unregistered" in text
    assert "SPECIMEN" not in text


def test_legacy_row_renders_from_its_stored_fields():
    tenant = _tenant(_tenant_settings(environment="production"), slug="logismart")
    legacy = BillingInvoice(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        merchant_user_id=uuid.uuid4(),
        invoice_number="LOGI2627I000001",
        invoice_date=date(2026, 9, 1),
        due_date=date(2026, 9, 16),
        gst_number=SUPPLIER_GSTIN,
        billing_address=REGISTERED_ADDRESS,
        freight_amount=80.0,
        cgst_amount=7.2,
        sgst_amount=7.2,
        total_amount=94.4,
        line_items=[{"place_of_supply": "06", "supplier_state_code": "06", "tracking_id": "AWB9"}],
    )

    view = gd.build_document_view(legacy, tenant_legal_name=LEGAL_NAME, is_specimen=False)

    assert view.supplier.name == LEGAL_NAME and view.supplier.gstin == SUPPLIER_GSTIN
    assert view.charge_lines == (gd.ChargeLine("Freight Charges", 80.0),)
    assert [r.label for r in view.tax_rows] == ["CGST @ 9%", "SGST @ 9%"]
    assert view.bill_to is None and view.place_of_supply_label == "Haryana (06)"
    assert "GSTIN: Unregistered" in _pdf_text(gd.render_gst_document_pdf(view))


async def test_read_schema_exposes_display_fields_without_frontend_math():
    kyc = {"status": "APPROVED", "gstin": BUYER_GSTIN_MH, "company_name": "Acme Traders"}
    _tenant_obj, _seller, repo, shipment, service = _world(kyc)
    invoice = await service.record_shipment_billing_note(shipment=shipment)
    invoice.created_at = invoice.created_at or today_ist()

    body = BillingInvoiceRead.model_validate(invoice).model_dump()

    assert body["tax_rows"] == [{"label": "IGST @ 18%", "amount": BOOKING_TAX}]
    assert body["place_of_supply_label"] == "Maharashtra (27)"
    assert body["bill_to"]["gstin"] == BUYER_GSTIN_MH
    assert body["supplier_name"] == LEGAL_NAME
    assert body["tracking_id"] == "LSAWB0001"


# ----------------------------------------------------------------------------
# Manual documents (C-05 guards)
# ----------------------------------------------------------------------------


async def test_manual_document_guards():
    tenant, seller, repo, shipment, service = _world()
    admin = _user(tenant.id, role=UserRole.admin)
    repo.users[admin.id] = admin

    async def issue(**fields: Any) -> BillingInvoice:
        payload = BillingInvoiceCreate(freight_amount=100.0, reason="Rate card correction", **fields)
        return await service.create_invoice(admin, tenant.id, payload)

    with pytest.raises(HTTPException) as no_merchant:
        await issue()
    assert no_merchant.value.status_code == 400
    with pytest.raises(HTTPException) as back_dated:
        await issue(merchant_user_id=seller.id, invoice_date=today_ist() - timedelta(days=3))
    assert back_dated.value.status_code == 400
    with pytest.raises(HTTPException) as orphan_note:
        await issue(merchant_user_id=seller.id, note_type=InvoiceNoteType.CREDIT_NOTE.value, original_reference="NOPE")
    assert orphan_note.value.status_code == 400
    with pytest.raises(HTTPException) as no_reason:
        await service.create_invoice(admin, tenant.id, BillingInvoiceCreate(freight_amount=100.0, merchant_user_id=seller.id))
    assert no_reason.value.status_code == 400

    invoice = await issue(merchant_user_id=seller.id)
    credit = await issue(
        merchant_user_id=seller.id,
        note_type=InvoiceNoteType.CREDIT_NOTE.value,
        original_reference=invoice.invoice_number,
    )
    assert invoice.merchant_user_id == seller.id
    assert invoice.line_items[0][gd.BILL_TO_KEY]["name"] == "Ramesh Seller"
    assert credit.original_invoice_id == invoice.id
    assert (invoice.cgst_amount, invoice.sgst_amount, invoice.total_amount) == (9.0, 9.0, 118.0)


# ----------------------------------------------------------------------------
# Seller company details (C-01, DO1 `profile`: submit once, then locked)
# ----------------------------------------------------------------------------


class FakeTenantRepo:
    """In-memory stand-in for `TenantRepository` (profile paths only)."""

    def __init__(self, tenant: SimpleNamespace):
        self.tenant = tenant
        self.locked_reads = 0

    async def get_tenant_for_update(self, tenant_id: uuid.UUID) -> Optional[SimpleNamespace]:
        self.locked_reads += 1
        return self.tenant if tenant_id == self.tenant.id else None

    async def get_tenant_by_id(self, tenant_id: uuid.UUID) -> Optional[SimpleNamespace]:
        return self.tenant if tenant_id == self.tenant.id else None

    async def save_tenant(self, tenant: SimpleNamespace) -> SimpleNamespace:
        return tenant

    async def commit_and_refresh(self, tenant: SimpleNamespace) -> None:
        return None

    async def create_user(self, user: SimpleNamespace) -> SimpleNamespace:
        return user


@pytest.fixture
def no_flag_modified(monkeypatch):
    """`flag_modified` needs an ORM instance; the fake tenant is a plain namespace."""
    monkeypatch.setattr("app.services.tenants.flag_modified", lambda *_args: None)


def _profile_world():
    tenant = _tenant(_tenant_settings(kyc={}))
    repo = FakeTenantRepo(tenant)
    seller = _user(tenant.id)
    return tenant, repo, seller, TenantService(repo)


def _submit(gstin: Optional[str] = BUYER_GSTIN_KA) -> UserSelfUpdate:
    return UserSelfUpdate(
        company_details=SellerCompanyDetailsSubmit(
            legal_name="Acme Traders", billing_address="12 MG Road, Bengaluru 560001", gstin=gstin
        )
    )


async def test_company_details_submit_once_then_locked(no_flag_modified):
    tenant, repo, seller, service = _profile_world()

    profile = await service.update_my_profile(seller, _submit())

    entry = tenant.settings[gd.KYC_REQUESTS_SETTINGS_KEY][str(seller.id)]
    assert repo.locked_reads == 1
    assert entry["gstin"] == entry[gd.VERIFIED_GSTIN_KEY] == BUYER_GSTIN_KA
    assert entry[gd.GSTIN_STATUS_KEY] == gd.KYC_APPROVED_STATUS and entry["pan"] == "AAGCB7383J"
    assert profile.company_details_locked is True
    assert profile.billing_address == "12 MG Road, Bengaluru 560001"
    assert gd.approved_kyc_gstin(entry, SUPPLIER_GSTIN) == BUYER_GSTIN_KA

    snapshot = copy.deepcopy(tenant.settings)
    with pytest.raises(HTTPException) as second:
        await service.update_my_profile(seller, _submit(BUYER_GSTIN_MH))
    assert second.value.status_code == 409
    assert tenant.settings == snapshot


async def test_company_details_without_gstin_are_unregistered(no_flag_modified):
    tenant, _repo, seller, service = _profile_world()

    await service.update_my_profile(seller, _submit(gstin=None))

    entry = tenant.settings[gd.KYC_REQUESTS_SETTINGS_KEY][str(seller.id)]
    assert entry["gstin"] is None and entry[gd.GSTIN_STATUS_KEY] is None
    assert gd.approved_kyc_gstin(entry, SUPPLIER_GSTIN) is None
    assert gd.company_details_locked(entry)


@pytest.mark.parametrize("gstin", [BAD_CHECKSUM_GSTIN, SUPPLIER_GSTIN, "ABC"])
async def test_company_details_reject_invalid_or_tenant_gstin(no_flag_modified, gstin):
    tenant, _repo, seller, service = _profile_world()

    with pytest.raises(HTTPException) as rejected:
        await service.update_my_profile(seller, _submit(gstin))

    assert rejected.value.status_code == 422
    assert str(seller.id) not in tenant.settings[gd.KYC_REQUESTS_SETTINGS_KEY]


# ----------------------------------------------------------------------------
# C-18 (A4-33): settings PATCH rejects unknown keys & locks invoice_prefix
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_payload",
    [
        {"unknown_root_key": True},
        {"pricing_config": {"gst_percent": 18.0}},
        {"b2b_access_requests": {"forged": {"status": "APPROVED"}}},
        {"company": {"unknown_company_key": "x"}},
        {"company": {"invoice_prefix": "TOO_LONG_PREFIX"}},
    ],
)
def test_settings_reject_unknown_keys_and_invalid_prefix(bad_payload):
    with pytest.raises(HTTPException) as exc:
        TenantService._validate_settings_payload(bad_payload)
    assert exc.value.status_code == 422


def test_settings_lock_invoice_prefix_mid_fy_and_preserve_on_restore():
    current = {"company": {"invoice_prefix": "LTST"}, "b2b_access_requests": {"u1": {"status": "APPROVED"}}}

    # Same prefix is allowed
    TenantService._assert_invoice_prefix_locked(
        current, TenantService._validate_settings_payload({"company": {"invoice_prefix": "ltst"}})
    )

    # Changing configured prefix mid-FY is rejected with 422
    with pytest.raises(HTTPException) as exc:
        TenantService._assert_invoice_prefix_locked(
            current, TenantService._validate_settings_payload({"company": {"invoice_prefix": "NEWP"}})
        )
    assert exc.value.status_code == 422

    # Restoring an older snapshot strips retired `pricing_config` and keeps current KYC + prefix
    old_snapshot = {
        "pricing_config": {"gst_percent": 18.0},
        "company": {"invoice_prefix": "OLD1", "legal_name": LEGAL_NAME},
        "b2b_access_requests": {"u1": {"status": "PENDING"}},
    }
    restored = TenantService._carry_forward_runtime_keys(old_snapshot, current)
    assert "pricing_config" not in restored
    assert restored["company"]["invoice_prefix"] == "LTST"
    assert restored["b2b_access_requests"]["u1"]["status"] == "APPROVED"


async def test_reverse_dto_uses_delivery_warehouse_for_place_of_supply_and_bill_to_fallback():
    """BUG-08: on a REVERSE DTO return, the seller/merchant side is the delivery (return-to) address."""
    tenant, seller, repo, shipment, service = _world()
    consumer_pickup = _address(tenant.id, "Bangalore", "Karnataka", "560001")
    seller_warehouse = _address(tenant.id, "Gurgaon", "Haryana", "122001")
    repo.addresses = {consumer_pickup.id: consumer_pickup, seller_warehouse.id: seller_warehouse}
    shipment.pickup_address_id = consumer_pickup.id
    shipment.delivery_address_id = seller_warehouse.id
    shipment.shipment_type = ShipmentType.REVERSE

    # 1. Unregistered merchant: place of supply is delivery (Haryana 06), so HR->HR is CGST+SGST
    assert (
        resolve_place_of_supply(
            "06",
            None,
            "Karnataka",
            delivery_state="Haryana",
            shipment_type=ShipmentType.REVERSE,
        )
        == "06"
    )
    invoice = await service.record_shipment_billing_note(shipment=shipment)
    credit = await service.record_shipment_billing_note(
        shipment=shipment,
        note_type=InvoiceNoteType.CREDIT_NOTE.value,
        amount_override=BOOKING_TOTAL,
    )
    assert invoice.cgst_amount == 7.20 and invoice.sgst_amount == 7.20 and invoice.igst_amount == 0.0
    assert credit.cgst_amount == 7.20 and credit.sgst_amount == 7.20 and credit.igst_amount == 0.0
    assert invoice.line_items[0]["place_of_supply"] == "06"
    assert "Gurgaon" in invoice.line_items[0][gd.BILL_TO_KEY]["address"]

    # 2. Approved merchant GSTIN state still wins over address state
    assert (
        resolve_place_of_supply(
            "06",
            BUYER_GSTIN_KA,
            "Karnataka",
            delivery_state="Haryana",
            shipment_type=ShipmentType.REVERSE,
        )
        == "29"
    )

