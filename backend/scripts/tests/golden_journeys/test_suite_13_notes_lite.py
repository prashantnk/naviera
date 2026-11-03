"""
Golden Suite 13: Phase D (lite) small fixes with no migration (ship-readiness plan §2 Phase D).

One test per backend-testable fix, pure API (in-process ASGI app, no browser):

- D1  DO1 wording: the shared dropdown labels in `frontend/src/lib/form-options.ts` read
      "Surface (Truck)", "Surface (Train)", "Air" and "Freight on Delivery (To-Pay)"
      (static source assertion, no browser needed).
- D2  Pickup cut-off: a late or past pickup slot is MOVED to the next slot with a notice,
      never rejected, and `time_slot` is normalised to the 4 known slots
      (`ManifestService._adjust_slot`, `POST /api/v1/manifests`).
- D3  PO numbers: up to 5 comma-separated PO numbers are accepted (and normalised), a 6th
      is refused with 422, on both booking and the appointment update
      (`app/schemas/v1/pickups.py`, DO1 `b2b-appointments`).
- D5  Alternate phone: printed next to the phone on the B2C label, the 4x2 thermal label
      and the B2B LR docket (`app/services/label.py::_format_phone`).
- D8  Serviceability stub: surface and air everywhere (no "pin ends in 9/8" rule); air is
      refused only for a pin in the tenant's `pricing_config.air_denylist_pincodes`
      (`PricingEngine._check_serviceability`). The deny-list case calls the pricing engine
      with an explicit `pricing_config` dict, so tenant settings are never edited.
- D9  B2B access request with the tenant's own GSTIN: accepted, but flagged
      `same_as_tenant_gstin` for the Owner's review screen (`app/services/tenants.py`).

Not covered here (frontend-only, no backend behaviour to assert; covered by the UI layer,
owner @ui-journeys, `backend/scripts/tests/ui_golden/**`):

- D4  HSN soft warning (booking form steps).
- D6  B2B detail upload type picker (`b2b/shipments/[id]/page.tsx`).
- D7  Soft "invoice file missing" warning on B2B booking.
  (The `/ops` card half of D5 is UI-only as well.)

Self-contained: the session fixture in `golden_journeys/conftest.py` resets
`logismart-test`; this suite creates every row it needs through the API and never reads
another suite's state files. Rows written: 2 B2C pickup requests, 1 B2C + 2 B2B TO_PAY
shipments (TO_PAY: no wallet debit) and the `b2bonboarding` B2B access-request entry
(J04 later overwrites it; J04 only asserts the start scope, which this suite never changes).

Spring analogy: a `@SpringBootTest` + `MockMvc` class per release note, plus a few plain
JUnit tests of a `@Service` helper with a fixed `Clock` bean.
"""

import io
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Tuple

import httpx
from httpx import ASGITransport

from app.main import app
from app.models.pickups import (
    FreightPaymentMode,
    PickupTimeSlot,
    ServiceOption,
    ServiceType,
)
from app.models.tenants import ServiceScope
from app.schemas.v1.pickups import PackageCreate
from app.services.label import LabelGenerator
from app.services.manifests import (
    DEFAULT_CUTOFF,
    PICKUP_TIMEZONE,
    SLOT_ADJUSTED_NOTICE,
    ManifestService,
)

from .golden_env import (
    B2B_ONBOARDING_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    OWNER_EMAIL,
    allow_to_pay_bookings,
    find_seeded_address_id,
    headers,
    load_accounts,
    load_settings_fixture,
    load_test_tenant,
    order_ref,
)

try:
    from pypdf import PdfReader
except ImportError:  # pypdf lives in the optional `e2e` poetry group.
    PdfReader = None

# --- Constants -------------------------------------------------------------

ASGI_BASE_URL = "http://test"
HTTP_TIMEOUT_SECONDS = 60.0

FRONTEND_FORM_OPTIONS_PATH = (
    Path(__file__).resolve().parents[4] / "frontend" / "src" / "lib" / "form-options.ts"
)
"""`naviera/frontend/src/lib/form-options.ts` (this file is `naviera/backend/scripts/tests/golden_journeys/...`)."""

OPTION_LABEL_PATTERN = re.compile(
    r"\[(?P<enum>\w+)\.(?P<member>\w+)\]:\s*\{\s*label:\s*\"(?P<label>[^\"]*)\""
)
"""Matches `[ServiceType.AIR]: { label: "Air"` entries of the option maps."""

D1_EXPECTED_LABELS: Dict[Tuple[str, str], str] = {
    ("ServiceType", ServiceType.SURFACE_ROAD.name): "Surface (Truck)",
    ("ServiceType", ServiceType.SURFACE_TRAIN.name): "Surface (Train)",
    ("ServiceType", ServiceType.AIR.name): "Air",
    ("FreightPaymentMode", FreightPaymentMode.TO_PAY.name): "Freight on Delivery (To-Pay)",
}
D1_RETIRED_LABELS = frozenset({"Surface Road", "To Pay"})

# D2: pickup slots and cut-off
KNOWN_PICKUP_SLOTS = tuple(slot.value for slot in PickupTimeSlot)
LATE_TENANT_CUTOFF = "23:00"
FUTURE_PICKUP_OFFSET_DAYS = 7
PAST_PICKUP_DATE = date(2020, 1, 1)
B2C_PUR_DECLARED_BOXES = 1
# Fixed clocks for `_adjust_slot(now=...)`; the cut-off is read in IST (PICKUP_TIMEZONE).
CLOCK_DAY = date(2026, 11, 2)
IST_MORNING = datetime(2026, 11, 2, 9, 0, tzinfo=PICKUP_TIMEZONE)
IST_AFTER_FIRST_SLOT = datetime(2026, 11, 2, 10, 30, tzinfo=PICKUP_TIMEZONE)
UTC_AT_IST_CUTOFF = datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc)  # 13:00 IST exactly
IST_EVENING = datetime(2026, 11, 2, 20, 30, tzinfo=PICKUP_TIMEZONE)

# D3: PO numbers
MAX_PO_NUMBERS = 5
FIVE_PO_INPUT = " PO-D3-1, PO-D3-2 ,PO-D3-3,  PO-D3-4 , PO-D3-5 "
FIVE_PO_NORMALISED = "PO-D3-1,PO-D3-2,PO-D3-3,PO-D3-4,PO-D3-5"
SIX_PO_INPUT = "PO-D3-1,PO-D3-2,PO-D3-3,PO-D3-4,PO-D3-5,PO-D3-6"
FIVE_PO_SLOT_INPUT = "PO-D3-A,PO-D3-B,PO-D3-C,PO-D3-D,PO-D3-E"
TOO_MANY_PO_MESSAGE = "Maximum 5 comma-separated PO numbers are allowed."
APPOINTMENT_START = "2026-12-01T10:00:00+05:30"
APPOINTMENT_END = "2026-12-01T14:00:00+05:30"

# D5: alternate phone
B2C_CONSIGNEE_PHONE = "9810013101"
B2C_CONSIGNEE_ALT_PHONE = "9810013102"
B2B_CONSIGNEE_PHONE = "9820013101"
B2B_CONSIGNEE_ALT_PHONE = "9820013102"
LABEL_FORMAT_A4 = "a4"
LABEL_FORMAT_THERMAL = "thermal_4x2"
PDF_CONTENT_TYPE = "application/pdf"
B2C_GOODS_VALUE_INR = 1500.0
B2B_GOODS_VALUE_INR = 20000.0  # below the e-way bill threshold

# D8: serviceability
PIN_ENDING_IN_NINE = "400009"
PIN_ENDING_IN_EIGHT = "400008"
DENIED_AIR_PIN = PIN_ENDING_IN_NINE
AIR_DENYLIST_KEY = "air_denylist_pincodes"
AIR_REFUSED_MESSAGE = "Air cargo service not available for this remote pin."
ALL_SERVICE_TYPES = (ServiceType.AIR, ServiceType.SURFACE_TRAIN, ServiceType.SURFACE_ROAD)
SURFACE_SERVICE_TYPES = (ServiceType.SURFACE_TRAIN, ServiceType.SURFACE_ROAD)
RATE_PICKUP_PIN = "122001"

# D9: B2B access request GSTIN
TENANT_GSTIN_KEY = "gstin"
D9_COMPANY_NAME = "Golden D9 Same-GSTIN Probe"
D9_OTHER_GSTIN = "29AAGCB7383J1Z4"
GSTIN_PAN_SLICE = slice(2, 12)
STATUS_PENDING = "PENDING"
STATUS_APPROVED = "APPROVED"
B2B_CAPABLE_SCOPES = frozenset({ServiceScope.B2B.value, ServiceScope.BOTH.value})

# --- Small helpers ---------------------------------------------------------


def _client() -> httpx.AsyncClient:
    """In-process ASGI client (no running server needed)."""
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url=ASGI_BASE_URL, timeout=HTTP_TIMEOUT_SECONDS
    )


def _ist_today() -> date:
    """Today's date on the pickup clock `ManifestService._adjust_slot` uses (IST)."""
    return datetime.now(PICKUP_TIMEZONE).date()


def _package(description: str, weight_kg: float = 1.0, box_count: int = 1) -> Dict[str, Any]:
    """One small CM/KG package body."""
    return {
        "length": 20.0,
        "breadth": 15.0,
        "height": 10.0,
        "dimension_unit": "CM",
        "weight": weight_kg,
        "weight_unit": "KG",
        "box_count": box_count,
        "description": description,
    }


def _to_pay_payment(goods_value: float) -> Dict[str, Any]:
    """TO_PAY (Freight on Delivery) payment block: the consignee pays, no wallet debit."""
    return {
        "freight_payment_mode": FreightPaymentMode.TO_PAY.value,
        "is_cod": False,
        "cod_amount": 0.0,
        "shipment_value": goods_value,
        "shipment_tax_value": 0.0,
        "shipment_total_value": goods_value,
        "add_shipping_to_cod": False,
    }


def _consignee(name: str, phone: str, alternate_phone: str, pincode: str) -> Dict[str, Any]:
    """A transient (unsaved) Mumbai consignee address with an alternate phone."""
    return {
        "name": name,
        "phone": phone,
        "alternate_phone": alternate_phone,
        "address_line1": "Unit 14, Ballard Estate",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": pincode,
        "country": "IN",
        "category": "WAREHOUSE",
    }


def _b2c_booking(warehouse_id: str, label: str) -> Dict[str, Any]:
    """B2C forward TO_PAY booking body (no B2B markers) whose consignee has an alternate phone."""
    return {
        "order_reference_id": order_ref(label),
        "shipment_type": "FORWARD",
        "service_type": ServiceType.SURFACE_ROAD.value,
        "requested_pickup_date": date.today().isoformat(),
        "product_category": "HOUSEHOLD_PERSONAL",
        "pickup_address_id": warehouse_id,
        "new_delivery_address": _consignee(
            "Notes D5 B2C Consignee", B2C_CONSIGNEE_PHONE, B2C_CONSIGNEE_ALT_PHONE, "400076"
        ),
        "packages": [_package(f"Notes {label}")],
        "payment_details": _to_pay_payment(B2C_GOODS_VALUE_INR),
    }


def _b2b_booking(warehouse_id: str, label: str, po_number: str) -> Dict[str, Any]:
    """B2B COMMERCIAL forward TO_PAY LR body whose consignee has an alternate phone."""
    return {
        "order_reference_id": order_ref(label),
        "shipment_type": "FORWARD",
        "service_type": ServiceType.SURFACE_ROAD.value,
        "requested_pickup_date": date.today().isoformat(),
        "product_category": "COMMERCIAL",
        "po_number": po_number,
        "pickup_address_id": warehouse_id,
        "new_delivery_address": _consignee(
            "Notes D5 B2B Consignee", B2B_CONSIGNEE_PHONE, B2B_CONSIGNEE_ALT_PHONE, "400001"
        ),
        "packages": [_package(f"Notes {label}", weight_kg=12.0, box_count=2)],
        "payment_details": {
            **_to_pay_payment(B2B_GOODS_VALUE_INR),
            "invoice_numbers": [f"INV-{label}"],
        },
    }


async def _post_booking(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], email: str, body: Mapping[str, Any]
) -> httpx.Response:
    """POST /api/v1/shipments as `email` (allows legacy TO_PAY seeding in suite 13)."""
    with allow_to_pay_bookings():
        return await client.post("/api/v1/shipments", headers=headers(accounts, email), json=dict(body))


async def _book(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], email: str, body: Mapping[str, Any]
) -> Dict[str, Any]:
    """Books one shipment and returns its JSON (201 required)."""
    resp = await _post_booking(client, accounts, email, body)
    assert resp.status_code == 201, f"booking failed ({resp.status_code}): {resp.text}"
    return resp.json()


def _error_messages(resp: httpx.Response) -> List[str]:
    """Flattens a FastAPI error body into its message strings."""
    detail = resp.json().get("detail")
    if isinstance(detail, list):
        return [str(item.get("msg", "")) for item in detail]
    return [str(detail)]


def _assert_po_refused(resp: httpx.Response) -> None:
    """A 6th PO number is a 422 naming the 5-PO limit."""
    assert resp.status_code == 422, f"expected 422 for 6 POs, got {resp.status_code}: {resp.text}"
    messages = _error_messages(resp)
    assert any(TOO_MANY_PO_MESSAGE in msg for msg in messages), f"422 without the PO limit: {messages}"


async def _create_b2c_pur(
    client: httpx.AsyncClient,
    accounts: Mapping[str, Any],
    warehouse_id: str,
    scheduled_date: date,
    time_slot: str,
) -> Dict[str, Any]:
    """Creates a B2C pickup request (expected package count, no shipments) as `customerb2c`."""
    resp = await client.post(
        "/api/v1/manifests",
        headers=headers(accounts, CUSTOMER_B2C_EMAIL),
        json={
            "pickup_address_id": warehouse_id,
            "scheduled_date": scheduled_date.isoformat(),
            "time_slot": time_slot,
            "service_flow": "B2C",
            "is_blind_pickup": False,
            "total_boxes": B2C_PUR_DECLARED_BOXES,
            "shipment_ids": [],
        },
    )
    assert resp.status_code == 201, (
        f"pickup request must never be rejected ({resp.status_code}): {resp.text}"
    )
    return resp.json()


def _adjust_at(
    now: datetime, scheduled: date, slot: str, cutoff: str = DEFAULT_CUTOFF
) -> Tuple[date, str, bool]:
    """Runs the pure `ManifestService._adjust_slot` helper on a fixed clock (no I/O)."""
    service = ManifestService(session=None)  # type: ignore[arg-type]  # pure helper, no session use
    return service._adjust_slot(scheduled, slot, cutoff, now=now)


async def _pdf_text(
    client: httpx.AsyncClient, hdrs: Mapping[str, str], shipment_id: str, label_format: str
) -> str:
    """Downloads a label PDF and returns its text with whitespace collapsed."""
    resp = await client.get(
        f"/api/v1/shipments/{shipment_id}/label",
        headers=dict(hdrs),
        params={"label_format": label_format},
    )
    assert resp.status_code == 200, f"label {label_format} failed ({resp.status_code}): {resp.text}"
    assert resp.headers["content-type"] == PDF_CONTENT_TYPE, resp.headers["content-type"]
    reader = PdfReader(io.BytesIO(resp.content))
    raw = " ".join(page.extract_text() or "" for page in reader.pages)
    return " ".join(raw.split())


def _quote_request(delivery_pin: str) -> Dict[str, Any]:
    """B2C quote request to `delivery_pin`."""
    return {
        "service_flow": "B2C",
        "pickup_pincode": RATE_PICKUP_PIN,
        "delivery_pincode": delivery_pin,
        "packages": [PackageCreate(**_package("Notes D8")).model_dump(mode="json")],
    }


def _quotes_by_option(options: List[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    """Indexes quote option cards by `service_option` value."""
    return {str(q["service_option"]): q for q in options}


def _assert_serviceable(quote: Mapping[str, Any], where: str) -> None:
    """A serviceable option card carries a positive total and no unavailable code."""
    assert quote["serviceable"] is True, f"{where}: {quote}"
    assert quote.get("unavailable_code") is None, f"{where}: {quote}"
    assert float(quote.get("total_amount") or 0) > 0, f"{where}: {quote}"


async def _user_row(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], user_id: str
) -> Dict[str, Any]:
    """The Owner's team-page row (`GET /api/v1/users`) for `user_id`."""
    resp = await client.get("/api/v1/users", headers=headers(accounts, OWNER_EMAIL))
    assert resp.status_code == 200, resp.text
    rows = [row for row in resp.json() if row["id"] == user_id]
    assert len(rows) == 1, f"expected exactly one row for {user_id}, got {len(rows)}"
    return rows[0]


async def _request_b2b(
    client: httpx.AsyncClient, accounts: Mapping[str, Any], gstin: str
) -> Dict[str, Any]:
    """`b2bonboarding` submits a B2B access request with `gstin` (200 required)."""
    resp = await client.post(
        "/api/v1/users/me/request-b2b",
        headers=headers(accounts, B2B_ONBOARDING_EMAIL),
        json={"company_name": D9_COMPANY_NAME, "gstin": gstin},
    )
    assert resp.status_code == 200, (
        f"B2B request must be accepted ({resp.status_code}): {resp.text}"
    )
    return resp.json()


# --- D1 ----------------------------------------------------------------------


def test_d1_form_options_use_do1_wording() -> None:
    """D1: service and freight-mode dropdown labels use the DO1 terms; old wording is gone."""
    assert FRONTEND_FORM_OPTIONS_PATH.is_file(), f"missing {FRONTEND_FORM_OPTIONS_PATH}"
    source = FRONTEND_FORM_OPTIONS_PATH.read_text(encoding="utf-8")
    labels = {
        (m.group("enum"), m.group("member")): m.group("label")
        for m in OPTION_LABEL_PATTERN.finditer(source)
    }
    for key, expected in D1_EXPECTED_LABELS.items():
        assert labels.get(key) == expected, f"{key}: expected {expected!r}, got {labels.get(key)!r}"
    retired = sorted(set(labels.values()) & D1_RETIRED_LABELS)
    assert retired == [], f"retired wording still used as a label: {retired}"


# --- D2 ----------------------------------------------------------------------


async def test_d2_future_pickup_slot_is_normalised_and_kept() -> None:
    """D2: a future slot typed without spaces becomes the canonical slot; date kept, no notice."""
    accounts = await load_accounts()
    future_day = _ist_today() + timedelta(days=FUTURE_PICKUP_OFFSET_DAYS)
    async with _client() as client:
        warehouse_id = await find_seeded_address_id(client, accounts, CUSTOMER_B2C_EMAIL)
        body = await _create_b2c_pur(client, accounts, warehouse_id, future_day, "14:00-18:00")
    assert body["scheduled_date"] == future_day.isoformat(), body["scheduled_date"]
    assert body["time_slot"] == PickupTimeSlot.AFTERNOON_14_18.value, body["time_slot"]
    assert body["total_boxes"] == B2C_PUR_DECLARED_BOXES, body["total_boxes"]
    assert body.get("notice") is None, f"unexpected notice on an on-time slot: {body.get('notice')!r}"


async def test_d2_past_pickup_slot_is_moved_with_notice_not_rejected() -> None:
    """D2: a past date is accepted (201), moved to IST today/tomorrow on a known slot, with the notice."""
    accounts = await load_accounts()
    async with _client() as client:
        warehouse_id = await find_seeded_address_id(client, accounts, CUSTOMER_B2C_EMAIL)
        today = _ist_today()
        body = await _create_b2c_pur(
            client, accounts, warehouse_id, PAST_PICKUP_DATE, PickupTimeSlot.EVENING_18_22.value
        )
    allowed_days = {today.isoformat(), (today + timedelta(days=1)).isoformat()}
    assert body["scheduled_date"] in allowed_days, (
        f"moved to {body['scheduled_date']}, expected one of {sorted(allowed_days)}"
    )
    assert body["time_slot"] in KNOWN_PICKUP_SLOTS, body["time_slot"]
    assert body.get("notice") == SLOT_ADJUSTED_NOTICE, f"missing slot notice: {body.get('notice')!r}"


def test_d2_cutoff_moves_late_slot_to_next_slot() -> None:
    """D2: on a fixed IST clock, late slots move forward (never rejected) and the tenant cut-off is honoured."""
    afternoon = PickupTimeSlot.AFTERNOON_14_18.value
    evening = PickupTimeSlot.EVENING_18_22.value
    cases = [
        # (label, now, scheduled, slot text, cut-off, expected)
        ("open slot before cut-off is kept", IST_MORNING, CLOCK_DAY, afternoon, DEFAULT_CUTOFF,
         (CLOCK_DAY, afternoon, False)),
        ("ended slot moves to the next slot today", IST_AFTER_FIRST_SLOT, CLOCK_DAY,
         PickupTimeSlot.MORNING_06_10.value, DEFAULT_CUTOFF,
         (CLOCK_DAY, PickupTimeSlot.MIDDAY_10_14.value, True)),
        ("past date moves to today, compact text normalised", IST_MORNING,
         CLOCK_DAY - timedelta(days=1), "18:00-22:00", DEFAULT_CUTOFF, (CLOCK_DAY, evening, True)),
        ("at the IST cut-off (given in UTC) rolls to tomorrow's first slot", UTC_AT_IST_CUTOFF,
         CLOCK_DAY, afternoon, DEFAULT_CUTOFF,
         (CLOCK_DAY + timedelta(days=1), afternoon, True)),
        ("later tenant cut-off keeps today's evening slot", IST_EVENING, CLOCK_DAY, evening,
         LATE_TENANT_CUTOFF, (CLOCK_DAY, evening, False)),
        ("default cut-off moves the same evening request", IST_EVENING, CLOCK_DAY, evening,
         DEFAULT_CUTOFF, (CLOCK_DAY + timedelta(days=1), evening, True)),
    ]
    for label, now, scheduled, slot, cutoff, expected in cases:
        got = _adjust_at(now, scheduled, slot, cutoff)
        assert got == expected, f"{label}: expected {expected}, got {got}"


# --- D3 ----------------------------------------------------------------------


async def test_d3_up_to_five_po_numbers_accepted_six_refused() -> None:
    """D3: 5 comma-separated POs accepted + normalised on booking and appointment; a 6th is 422."""
    accounts = await load_accounts()
    b2b_headers = headers(accounts, CUSTOMER_B2B_EMAIL)
    async with _client() as client:
        warehouse_id = await find_seeded_address_id(client, accounts, CUSTOMER_B2B_EMAIL)

        refused = await _post_booking(
            client, accounts, CUSTOMER_B2B_EMAIL, _b2b_booking(warehouse_id, "D3-LR6", SIX_PO_INPUT)
        )
        _assert_po_refused(refused)

        lr = await _book(
            client, accounts, CUSTOMER_B2B_EMAIL, _b2b_booking(warehouse_id, "D3-LR5", FIVE_PO_INPUT)
        )
        assert lr["po_number"] == FIVE_PO_NORMALISED, lr["po_number"]
        assert len(lr["po_number"].split(",")) == MAX_PO_NUMBERS

        slot = {"appointment_start": APPOINTMENT_START, "appointment_end": APPOINTMENT_END}
        too_many = await client.patch(
            f"/api/v1/shipments/{lr['id']}/appointment",
            headers=b2b_headers,
            json={**slot, "po_number": SIX_PO_INPUT},
        )
        _assert_po_refused(too_many)

        updated = await client.patch(
            f"/api/v1/shipments/{lr['id']}/appointment",
            headers=b2b_headers,
            json={**slot, "po_number": FIVE_PO_SLOT_INPUT},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["po_number"] == FIVE_PO_SLOT_INPUT, updated.json()["po_number"]


# --- D5 ----------------------------------------------------------------------


async def test_d5_alternate_phone_printed_on_label_and_lr() -> None:
    """D5: the consignee's alternate phone follows the phone on the B2C label, 4x2 label and B2B LR."""
    accounts = await load_accounts()
    b2c_phones = f"{B2C_CONSIGNEE_PHONE}, {B2C_CONSIGNEE_ALT_PHONE}"
    b2b_phones = f"{B2B_CONSIGNEE_PHONE}, {B2B_CONSIGNEE_ALT_PHONE}"
    b2c_hdrs = headers(accounts, CUSTOMER_B2C_EMAIL)
    b2b_hdrs = headers(accounts, CUSTOMER_B2B_EMAIL)
    async with _client() as client:
        b2c_wh = await find_seeded_address_id(client, accounts, CUSTOMER_B2C_EMAIL)
        b2b_wh = await find_seeded_address_id(client, accounts, CUSTOMER_B2B_EMAIL)
        parcel = await _book(client, accounts, CUSTOMER_B2C_EMAIL, _b2c_booking(b2c_wh, "D5-B2C"))
        lr = await _book(
            client, accounts, CUSTOMER_B2B_EMAIL, _b2b_booking(b2b_wh, "D5-LR", "PO-D5-1")
        )
        assert parcel["delivery_address"]["alternate_phone"] == B2C_CONSIGNEE_ALT_PHONE
        assert lr["delivery_address"]["alternate_phone"] == B2B_CONSIGNEE_ALT_PHONE

        if PdfReader is None:
            # pypdf not installed: assert the exact string the label helper prints instead.
            for row, phones in ((parcel, b2c_phones), (lr, b2b_phones)):
                printed = LabelGenerator._format_phone(SimpleNamespace(**row["delivery_address"]))
                assert printed == phones, printed
            return

        a4_text = await _pdf_text(client, b2c_hdrs, parcel["id"], LABEL_FORMAT_A4)
        thermal_text = await _pdf_text(client, b2c_hdrs, parcel["id"], LABEL_FORMAT_THERMAL)
        lr_text = await _pdf_text(client, b2b_hdrs, lr["id"], LABEL_FORMAT_A4)
    assert f"Ph: {b2c_phones}" in a4_text, f"B2C 4x6 label lacks the alternate phone: {a4_text}"
    assert f"Ph: {b2c_phones}" in thermal_text, f"4x2 label lacks the alternate phone: {thermal_text}"
    assert f"Phone: {b2b_phones}" in lr_text, f"B2B LR lacks the alternate phone: {lr_text}"


# --- D8 ----------------------------------------------------------------------


async def test_d8_surface_and_air_everywhere_without_denylist() -> None:
    """D8: no 'ends in 9/8' rule: pins 400009 and 400008 get both B2C Delhivery options."""
    accounts = await load_accounts()
    expected_options = (ServiceOption.DELHIVERY_SURFACE.value, ServiceOption.DELHIVERY_EXPRESS.value)
    async with _client() as client:
        for pin in (PIN_ENDING_IN_NINE, PIN_ENDING_IN_EIGHT):
            resp = await client.post(
                "/api/v1/quotes",
                headers=headers(accounts, CUSTOMER_B2C_EMAIL),
                json=_quote_request(pin),
            )
            assert resp.status_code == 200, resp.text
            quotes = _quotes_by_option(resp.json()["options"])
            assert sorted(quotes) == sorted(expected_options), sorted(quotes)
            for opt in expected_options:
                _assert_serviceable(quotes[opt], f"{opt} to {pin}")


async def test_d8_air_refused_only_for_denylisted_pin() -> None:
    """D8: unserviceable pin ('999999') is refused with NOT_SERVICEABLE; valid pins stay open."""
    accounts = await load_accounts()
    expected_options = (ServiceOption.DELHIVERY_SURFACE.value, ServiceOption.DELHIVERY_EXPRESS.value)
    async with _client() as client:
        resp = await client.post(
            "/api/v1/quotes",
            headers=headers(accounts, CUSTOMER_B2C_EMAIL),
            json=_quote_request("999999"),
        )
        assert resp.status_code == 200, resp.text
        denied = _quotes_by_option(resp.json()["options"])
        for opt in expected_options:
            assert denied[opt]["serviceable"] is False, denied[opt]
            assert denied[opt]["unavailable_code"] == "NOT_SERVICEABLE", denied[opt]


# --- D9 ----------------------------------------------------------------------


async def test_d9_b2b_request_with_tenant_gstin_accepted_but_flagged() -> None:
    """D9: the tenant's own GSTIN is accepted on a B2B request but flagged `same_as_tenant_gstin`."""
    accounts = await load_accounts()
    tenant = await load_test_tenant()
    tenant_gstin = (tenant.settings or {}).get(TENANT_GSTIN_KEY)
    assert tenant_gstin == load_settings_fixture()[TENANT_GSTIN_KEY], tenant_gstin
    onboarding_id = accounts[B2B_ONBOARDING_EMAIL]["id"]

    async with _client() as client:
        start = await _user_row(client, accounts, onboarding_id)
        # Order-independent: J04 may already have upgraded this account to BOTH.
        expected_status = (
            STATUS_APPROVED if start["service_scope"] in B2B_CAPABLE_SCOPES else STATUS_PENDING
        )

        # Lower-case on purpose: the service upper-cases before comparing with the tenant GSTIN.
        flagged = await _request_b2b(client, accounts, tenant_gstin.lower())
        assert flagged["gstin"] == tenant_gstin, flagged
        assert flagged["pan"] == tenant_gstin[GSTIN_PAN_SLICE], flagged
        assert flagged["b2b_request_status"] == expected_status, flagged
        assert flagged["same_as_tenant_gstin"] is True, flagged
        assert flagged["service_scope"] == start["service_scope"], flagged

        review_row = await _user_row(client, accounts, onboarding_id)
        assert review_row["same_as_tenant_gstin"] is True, "Owner review row must show the flag"
        assert review_row["gstin"] == tenant_gstin, review_row
        assert review_row["b2b_request_status"] == expected_status, review_row

        # A different GSTIN clears the flag; the account's scope is never changed here.
        cleared = await _request_b2b(client, accounts, D9_OTHER_GSTIN)
        assert cleared["gstin"] == D9_OTHER_GSTIN, cleared
        assert cleared["same_as_tenant_gstin"] is False, cleared

        final_row = await _user_row(client, accounts, onboarding_id)
        assert final_row["same_as_tenant_gstin"] is False, final_row
        assert final_row["service_scope"] == start["service_scope"], final_row
