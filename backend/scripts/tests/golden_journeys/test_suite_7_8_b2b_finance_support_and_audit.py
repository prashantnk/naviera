"""Suite 7 & 8 (J27-J36): B2B PTL Cargo, UPI Wallet Recharges, COD Remittances, GST Notes, Support & Final Ledger Integrity Audit.

Covers:
  - J27: B2B Heavy Cargo LR Booking, E-Way Bill Guard & Carrier's Risk FOV (201 Created / 422 / 400 / 403)
  - J28: B2B Delivery Appointment Scheduling & B2B Dashboard Summary (200 OK)
  - J29: B2B PUR: Manifested vs Blind Pickup & Dispatch to COMPLETED (201 Created / 200 OK)
  - J30: UPI QR Recharge Intent -> User Confirm Paid -> Maker-Checker Guard -> Admin Approve #1 (+Rs.2,000.00) vs Reject #2 (Rs.0.00)
  - J31: Duplicate UTR 409 Conflict Anti-Replay Guard (409 Conflict / 403 Forbidden)
  - J32: Delivery OTP POD & Dual COD Settlement (Path A: Wallet Credit on Order #1; Path B: Bank UTR Batch on Order #3) + Anti-Double-Payout Guard
  - J33: GST Invoices, Credit Notes, Debit Notes, PDF & CSV Exports (200 OK)
  - J34: Support Desk Lifecycle & Counters: OPEN -> Support Reply -> RESOLVED -> Customer Reopen -> CLOSED (201 / 200 / 400 / 403)
  - J35: Read-Only Auditor Visibility & 403 Write-Block Matrix (200 OK on all GETs / 403 Forbidden on all mutations)
  - J36: Final System & Ledger Integrity Audit (G6) + Tenant-Wide CSV Export (0 Discrepancies across all wallets)

Runs ONLY against the guarded test tenant (`GOLDEN_TENANT_SLUG`, default
`logismart-test`), reset once per session by `golden_journeys/conftest.py`.
Uses the in-process `ASGITransport` like Suites 1-6 (no running server needed),
per-run random UTRs (the UTR column is globally unique), and no "already done,
skip" branches: every journey runs straight through on the fresh tenant.
"""

from datetime import date
from typing import Any
from uuid import UUID

import httpx
import pytest
from httpx import ASGITransport
from sqlmodel import select

from app.main import app
from app.models.delhivery_modules import (
    BillingInvoice,
    InvoiceNoteType,
    RemittanceState,
)
from app.models.manifests import ManifestStatus
from app.models.pickups import PickupStatus
from app.models.wallet import (
    UserWallet as Wallet,
)
from app.models.wallet import (
    WalletTransaction,
    WalletTxnStatus,
    WalletTxnType,
)

from .golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GOLDEN_TENANT_SLUG,
    OPERATIONS_EMAIL,
    OWNER_EMAIL,
    READONLY_EMAIL,
    SUPPORT_EMAIL,
    GoldenSessionLocal,
    allow_to_pay_bookings,
    document_prefix,
    find_seeded_address_id,
    find_wallet_txn_by_utr,
    load_accounts,
    load_settings_fixture,
    load_state,
    make_bank_utr,
    make_utr,
    order_ref,
    read_otp_as_merchant,
    receipt_prefix,
    require_state,
    save_state,
)
from .golden_env import (
    get_tenant_id as _get_tenant_id,
)

TENANT_SLUG = GOLDEN_TENANT_SLUG
ASGI_BASE_URL = "http://test"
HTTP_TIMEOUT_SECONDS = 30.0

LEDGER_CREDIT_TYPES = frozenset(
    {
        WalletTxnType.RECHARGE,
        WalletTxnType.REFUND,
        WalletTxnType.COD_SETTLEMENT,
        WalletTxnType.CHARGE_REVERSAL,
    }
)
"""Wallet txn types that add to the balance; every other type is a debit (J36 ledger sum)."""

STATE_BATCHES = ("batch2", "batch3", "batch4")
BATCH4_STATE = "batch4"
SUITE_8_REQUIRED_KEYS = ("order1_id", "order3_id", "order1_tracking_id", "warehouse_address_id")

GSTIN_LOGISMART = load_settings_fixture()["gstin"]
INVOICE_PREFIX = document_prefix(InvoiceNoteType.INVOICE.value)
CREDIT_NOTE_PREFIX = document_prefix(InvoiceNoteType.CREDIT_NOTE.value)
DEBIT_NOTE_PREFIX = document_prefix(InvoiceNoteType.DEBIT_NOTE.value)

B2B_WALLET_TOPUP = 10000.0
J30_APPROVED_AMOUNT = 2000.0
J30_REJECTED_AMOUNT = 500.0
J30_ADMIN_OWN_AMOUNT = 100.0
J31_REPLAY_AMOUNT = 300.0
J32_ORDER1_COD = 1500.0
J32_ORDER3_GOODS = 2000.0


def _client() -> httpx.AsyncClient:
    """Returns an in-process ASGI client (same transport as Suites 1-6)."""
    return httpx.AsyncClient(
        transport=ASGITransport(app=app),
        base_url=ASGI_BASE_URL,
        timeout=HTTP_TIMEOUT_SECONDS,
    )


def _load_state() -> dict[str, Any]:
    """Loads the merged Batch 2, 3 and 4 state files of this slug."""
    return load_state(*STATE_BATCHES)


def _save_state(updates: dict[str, Any]) -> dict[str, Any]:
    """Persists updates into this slug's Batch 4 state file."""
    return save_state(BATCH4_STATE, updates)


async def _ensure_b2b_saved_warehouse(accounts: dict[str, dict[str, Any]]) -> str:
    """
    Returns the seeded saved Gurugram (`122001`) pickup address of
    `customerb2b@logismart.in`. The seed/reset creates it; this suite never does.
    """
    state = _load_state()
    if state.get("b2b_warehouse_address_id"):
        return str(state["b2b_warehouse_address_id"])
    async with _client() as client:
        addr_id = await find_seeded_address_id(client, accounts, CUSTOMER_B2B_EMAIL)
    _save_state({"b2b_warehouse_address_id": addr_id})
    return addr_id


async def _fund_b2b_wallet(
    client: httpx.AsyncClient,
    b2b_headers: dict[str, str],
    admin_headers: dict[str, str],
    amount: float = B2B_WALLET_TOPUP,
) -> float:
    """
    Tops up `customerb2b@logismart.in` through the real Maker-Checker UPI flow
    (intent -> confirm with a fresh random UTR -> admin approve) and returns the
    new balance. Always runs: the fresh tenant starts every wallet at 0.
    """
    bal_before = float((await client.get("/api/v1/wallet", headers=b2b_headers)).json()["balance"])
    intent_resp = await client.post(
        "/api/v1/wallet/recharge/upi-intent", headers=b2b_headers, json={"amount": amount}
    )
    assert intent_resp.status_code == 200, intent_resp.text
    txn_id = intent_resp.json()["transaction_id"]

    confirm_resp = await client.post(
        f"/api/v1/wallet/recharge/{txn_id}/confirm",
        headers=b2b_headers,
        json={"utr_number": make_utr()},
    )
    assert confirm_resp.status_code == 200, confirm_resp.text

    approve_resp = await client.post(
        f"/api/v1/wallet/recharge/{txn_id}/approve", headers=admin_headers
    )
    assert approve_resp.status_code == 200, approve_resp.text
    new_balance = float(approve_resp.json()["balance"])
    assert round(new_balance, 2) == round(bal_before + amount, 2)
    return new_balance


def _build_b2b_drop_address() -> dict[str, Any]:
    """Return a standard B2B industrial consignee drop address in Mumbai (400001)."""
    return {
        "label": "Mumbai Industrial Consignee",
        "name": "Vikramaditya Mehta",
        "company": "Mehta Heavy Engineering Pvt Ltd",
        "phone": "+919820011223",
        "email": "receiving@mehtaheavy.in",
        "address_line1": "Unit 14, Ballard Estate Industrial Dock",
        "address_line2": "Fort",
        "city": "Mumbai",
        "state": "Maharashtra",
        "pincode": "400001",
        "country": "IN",
        "address_category": "WAREHOUSE",
        "is_saved": False,
        "scope": "PRIVATE",
    }


async def _get_shipment(
    client: httpx.AsyncClient, hdrs: dict[str, str], shipment_id: str
) -> dict[str, Any]:
    """Reads one shipment through the API with the given headers."""
    resp = await client.get(f"/api/v1/shipments/{shipment_id}", headers=hdrs)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wallet_balance(client: httpx.AsyncClient, hdrs: dict[str, str]) -> float:
    """Reads the caller's wallet balance through the API."""
    resp = await client.get("/api/v1/wallet", headers=hdrs)
    assert resp.status_code == 200, resp.text
    return float(resp.json()["balance"])


# ==============================================================================
# SUITE 7: B2B PTL Heavy Cargo, E-Way Bill, FOV, Appointments & Blind Pickup PUR
# ==============================================================================


@pytest.mark.asyncio
async def test_j27_b2b_heavy_cargo_lr_booking_eway_bill_and_fov() -> None:
    """J27: B2B Heavy Cargo LR Booking, E-Way Bill Guard & Carrier's Risk FOV."""
    accounts = await load_accounts()
    b2b_headers = accounts[CUSTOMER_B2B_EMAIL]["headers"]
    b2c_headers = accounts[CUSTOMER_B2C_EMAIL]["headers"]
    admin_headers = accounts[ADMIN_EMAIL]["headers"]
    warehouse_id = await _ensure_b2b_saved_warehouse(accounts)
    tenant_id = await _get_tenant_id()
    state = _load_state()
    require_state(state, ("warehouse_address_id",))
    today_iso = date.today().isoformat()

    async with _client() as client:
        # 1. Cross-scope guard: B2B customer attempting a pure B2C parcel booking -> 403 Forbidden
        b2c_attempt_payload = {
            "pickup_address_id": warehouse_id,
            "new_delivery_address": _build_b2b_drop_address(),
            "requested_pickup_date": today_iso,
            "shipment_type": "FORWARD",
            "service_type": "SURFACE_ROAD",
            "product_category": "ELECTRONICS",
            "packages": [
                {
                    "box_count": 1,
                    "length": 20.0,
                    "breadth": 15.0,
                    "height": 10.0,
                    "dimension_unit": "CM",
                    "weight": 1.0,
                    "weight_unit": "KG",
                    "description": "Small B2C Parcel",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "PREPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_value": 1200.0,
                "shipment_tax_value": 0.0,
                "shipment_total_value": 1200.0,
            },
        }
        b2c_attempt_resp = await client.post(
            "/api/v1/shipments", headers=b2b_headers, json=b2c_attempt_payload
        )
        assert b2c_attempt_resp.status_code == 403, (
            f"Expected 403 when B2B-scoped customer books B2C order, got {b2c_attempt_resp.status_code}: {b2c_attempt_resp.text}"
        )

        # Also verify B2C customer attempting a B2B commercial booking -> 403 Forbidden
        b2b_by_b2c_payload = {
            **b2c_attempt_payload,
            "pickup_address_id": state["warehouse_address_id"],
            "product_category": "COMMERCIAL",
            "po_number": "PO-CROSS-SCOPE",
            "is_carriers_risk": True,
        }
        b2b_by_b2c_resp = await client.post(
            "/api/v1/shipments", headers=b2c_headers, json=b2b_by_b2c_payload
        )
        assert b2b_by_b2c_resp.status_code == 403, (
            f"Expected 403 when B2C-scoped customer books B2B order, got {b2b_by_b2c_resp.status_code}: {b2b_by_b2c_resp.text}"
        )

        # 2. E-Way Bill Mandatory Guard: Rs.75,000 (>= Rs.50,000) without eway_bill_numbers -> 400/422
        missing_ewb_payload = {
            "order_reference_id": order_ref("J27-LR1"),
            "pickup_address_id": warehouse_id,
            "new_delivery_address": _build_b2b_drop_address(),
            "requested_pickup_date": today_iso,
            "shipment_type": "FORWARD",
            "service_type": "SURFACE_ROAD",
            "product_category": "COMMERCIAL",
            "po_number": "PO-B2B-9001",
            "is_carriers_risk": True,
            "packages": [
                {
                    "box_count": 5,
                    "length": 130.0,
                    "breadth": 60.0,
                    "height": 50.0,
                    "dimension_unit": "CM",
                    "weight": 15.0,
                    "weight_unit": "KG",
                    "packaging_type": "WOODEN_CRATE",
                    "description": "Industrial CNC Spindles",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "PREPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_value": 75000.0,
                "shipment_tax_value": 0.0,
                "shipment_total_value": 75000.0,
                "eway_bill_numbers": [],
                "invoice_numbers": ["INV-B2B-9001"],
            },
        }
        missing_ewb_resp = await client.post(
            "/api/v1/shipments", headers=b2b_headers, json=missing_ewb_payload
        )
        assert missing_ewb_resp.status_code in (400, 422), (
            f"Expected 400/422 for missing E-Way Bill on Rs.75,000 cargo, got {missing_ewb_resp.status_code}: {missing_ewb_resp.text}"
        )

        # Also test invalid short E-Way Bill (< 12 digits) -> 400/422
        invalid_ewb_payload = {
            **missing_ewb_payload,
            "payment_details": {
                **missing_ewb_payload["payment_details"],
                "eway_bill_numbers": ["12345"],
            },
        }
        invalid_ewb_resp = await client.post(
            "/api/v1/shipments", headers=b2b_headers, json=invalid_ewb_payload
        )
        assert invalid_ewb_resp.status_code in (400, 422), (
            f"Expected 400/422 for short E-Way Bill, got {invalid_ewb_resp.status_code}: {invalid_ewb_resp.text}"
        )

        # 3. Fund the fresh B2B wallet through Maker-Checker, then book B2B LR #1
        balance_before = await _fund_b2b_wallet(client, b2b_headers, admin_headers)

        valid_b2b_payload = {
            **missing_ewb_payload,
            "documents": [
                {
                    "document_type": "GST_INVOICE",
                    "file_url": "https://cdn.logismart.in/docs/inv-b2b-9001.pdf",
                    "file_name": "inv-b2b-9001.pdf",
                }
            ],
            "payment_details": {
                **missing_ewb_payload["payment_details"],
                "eway_bill_numbers": ["987654321098"],
                "invoice_numbers": ["INV-B2B-9001"],
            },
        }
        create_resp = await client.post(
            "/api/v1/shipments", headers=b2b_headers, json=valid_b2b_payload
        )
        assert create_resp.status_code == 201, (
            f"Booking B2B LR #1 failed ({create_resp.status_code}): {create_resp.text}"
        )
        b2b_lr1_data = create_resp.json()
        b2b_lr1_id = b2b_lr1_data["id"]

        balance_after = await _wallet_balance(client, b2b_headers)
        total_cost = float(b2b_lr1_data["payment_details"]["total_logistics_cost"])
        assert round(balance_before - balance_after, 2) == round(total_cost, 2), (
            f"Expected B2B wallet debit of Rs.{total_cost}, got {balance_before} -> {balance_after}"
        )
        _save_state(
            {
                "b2b_lr1_id": b2b_lr1_id,
                "b2b_lr1_tracking_id": b2b_lr1_data["tracking_id"],
                "b2b_lr1_total_cost": total_cost,
                "b2b_wallet_balance_before_lr1": balance_before,
                "b2b_wallet_balance_after_lr1": balance_after,
            }
        )

        # Verify B2B LR #1 pricing breakdown on Prime lane (122001 -> 400001, Sameer Transport):
        # 5 boxes 130x60x50 cm, 15 kg each -> actual 75 kg, volumetric 433.333 kg -> chargeable 433.333 kg
        # Carrier cost: FREIGHT 4333.33 + DOCKET 100.00 + PICKUP 600.00 = 5033.33
        # +20% markup: FREIGHT 5200.00 + DOCKET 120.00 + PICKUP 720.00 = 6040.00 (+18% GST 1087.20 = 7127.20)
        pd = b2b_lr1_data["payment_details"]
        pb = pd["pricing_breakdown"]
        assert pb["service_option"] == "PRIME_SURFACE"
        assert float(pb["base_charge"]) == 6040.0, f"Expected base_charge=6040.0, got {pb}"
        assert round(float(pd["total_logistics_cost"]), 2) == 7127.20
        assert float(pb["total_actual_weight"]) == 75.0
        assert round(float(pb["total_volumetric_weight"]), 2) == 433.33
        assert round(float(pd["chargeable_weight"]), 2) == 433.33
        sell_codes = [line["code"] for line in (pb.get("sell_lines") or [])]
        assert sell_codes == ["FREIGHT", "DOCKET", "PICKUP", "GST"], sell_codes
        assert b2b_lr1_data["is_carriers_risk"] is True
        assert "987654321098" in pd["eway_bill_numbers"]

        # MVP Scope (DESIGN.md v4 §9): B2B REVERSE LR bookings are refused with 400
        b2b_rev_payload = {
            **valid_b2b_payload,
            "order_reference_id": order_ref("J27-B2B-REV"),
            "shipment_type": "REVERSE",
        }
        b2b_rev_resp = await client.post(
            "/api/v1/shipments", headers=b2b_headers, json=b2b_rev_payload
        )
        assert b2b_rev_resp.status_code == 400, b2b_rev_resp.text
        assert "reverse" in b2b_rev_resp.json()["detail"].lower()

        # Verify WalletTransaction (SPEND, service_category=B2B) and correlated BillingInvoice (INVOICE_PREFIX, service_type=B2B_PTL)
        async with GoldenSessionLocal() as session:
            spend_txn = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.tenant_id == tenant_id,
                        WalletTransaction.shipment_id == UUID(b2b_lr1_id),
                        WalletTransaction.txn_type == WalletTxnType.SPEND,
                    )
                )
            ).first()
            assert spend_txn is not None, "Expected B2B SPEND WalletTransaction"
            assert spend_txn.service_category == "B2B"
            assert spend_txn.receipt_number is not None
            assert spend_txn.receipt_number.startswith(receipt_prefix("INV"))

            all_b2b_invs = (
                await session.exec(
                    select(BillingInvoice).where(
                        BillingInvoice.tenant_id == tenant_id,
                        BillingInvoice.note_type == InvoiceNoteType.INVOICE.value,
                        BillingInvoice.service_type == "B2B_PTL",
                    )
                )
            ).all()
        b2b_inv = next(
            (
                inv
                for inv in all_b2b_invs
                if any(
                    isinstance(li, dict) and li.get("shipment_id") == str(b2b_lr1_id)
                    for li in (inv.line_items or [])
                )
            ),
            None,
        )
        assert b2b_inv is not None, "Expected correlated B2B BillingInvoice"
        assert b2b_inv.invoice_number.startswith(INVOICE_PREFIX)
        assert b2b_inv.note_type == InvoiceNoteType.INVOICE.value
        assert b2b_inv.service_type == "B2B_PTL"
        assert round(float(b2b_inv.total_amount), 2) == round(float(pd["total_logistics_cost"]), 2)

        # Verify A4 and Thermal 4x2 PDF labels
        for fmt in ("a4", "thermal_4x2"):
            lbl_resp = await client.get(
                f"/api/v1/shipments/{b2b_lr1_id}/label?label_format={fmt}",
                headers=b2b_headers,
            )
            assert lbl_resp.status_code == 200
            assert lbl_resp.content.startswith(b"%PDF-")


@pytest.mark.asyncio
async def test_j28_b2b_delivery_appointment_and_dashboard_summary() -> None:
    """J28: B2B Delivery Appointment Scheduling & B2B Dashboard Summary."""
    accounts = await load_accounts()
    b2b_headers = accounts[CUSTOMER_B2B_EMAIL]["headers"]
    admin_headers = accounts[ADMIN_EMAIL]["headers"]
    state = _load_state()
    require_state(state, ("b2b_lr1_id",))
    b2b_lr1_id = state["b2b_lr1_id"]

    async with _client() as client:
        cur_data = await _get_shipment(client, b2b_headers, b2b_lr1_id)
        assert cur_data["status"] == PickupStatus.OPEN.value

        # 1. Schedule B2B delivery appointment via PATCH /api/v1/shipments/{id}/appointment
        appt_payload = {
            "appointment_start": "2026-11-10T10:00:00+05:30",
            "appointment_end": "2026-11-10T14:00:00+05:30",
            "po_number": "PO-B2B-9001-SLOT",
            "po_expiry_date": "2026-11-30",
        }
        appt_resp = await client.patch(
            f"/api/v1/shipments/{b2b_lr1_id}/appointment",
            headers=b2b_headers,
            json=appt_payload,
        )
        assert appt_resp.status_code == 200, (
            f"PATCH appointment failed ({appt_resp.status_code}): {appt_resp.text}"
        )
        appt_data = appt_resp.json()
        assert appt_data["po_number"] == "PO-B2B-9001-SLOT"
        assert appt_data["po_expiry_date"] == "2026-11-30"
        assert "2026-11-10" in appt_data["appointment_start"]
        assert "2026-11-10" in appt_data["appointment_end"]

        # 2. Verify audit timeline has Appointment Updated event
        tl_resp = await client.get(
            f"/api/v1/shipments/{b2b_lr1_id}/timeline", headers=admin_headers
        )
        assert tl_resp.status_code == 200
        timeline_summaries = [ev.get("summary") for ev in tl_resp.json()]
        assert "Appointment Updated" in timeline_summaries, (
            f"Expected Appointment Updated in timeline, got {timeline_summaries}"
        )

        # 3. Verify B2B Dashboard Summary reflects the B2B flow
        dash_resp = await client.get(
            "/api/v1/dashboard/summary?service_flow=B2B&days=30", headers=b2b_headers
        )
        assert dash_resp.status_code == 200, f"B2B dashboard summary failed: {dash_resp.text}"
        dash_data = dash_resp.json()
        assert dash_data["service_flow"] == "B2B"
        stages = dash_data["stages"]
        total_b2b_lrs = (
            stages.get("lrs_manifested", 0)
            + stages.get("in_transit", 0)
            + stages.get("exceptions", 0)
            + stages.get("delivered", 0)
            + stages.get("rto", 0)
        )
        assert total_b2b_lrs >= 1


@pytest.mark.asyncio
async def test_j29_b2b_pur_manifested_and_blind_pickup_dispatch_to_completed() -> None:
    """J29: B2B PUR: Manifested vs Blind Pickup & Dispatch to COMPLETED."""
    accounts = await load_accounts()
    b2b_headers = accounts[CUSTOMER_B2B_EMAIL]["headers"]
    ops_headers = accounts[OPERATIONS_EMAIL]["headers"]
    warehouse_id = await _ensure_b2b_saved_warehouse(accounts)
    state = _load_state()
    require_state(state, ("b2b_lr1_id",))
    b2b_lr1_id = state["b2b_lr1_id"]
    today_iso = date.today().isoformat()

    async with _client() as client:
        # 1. Book Blind Pickup B2B LR #2 (TO_PAY, is_blind_pickup=True, estimated_box_count=12, packages=[])
        wallet_before = await _wallet_balance(client, b2b_headers)
        blind_lr_payload = {
            "order_reference_id": order_ref("J29-LR2-BLIND"),
            "pickup_address_id": warehouse_id,
            "new_delivery_address": _build_b2b_drop_address(),
            "requested_pickup_date": today_iso,
            "shipment_type": "FORWARD",
            "service_type": "SURFACE_ROAD",
            "product_category": "COMMERCIAL",
            "po_number": "PO-B2B-BLIND-02",
            "is_blind_pickup": True,
            "estimated_box_count": 12,
            "packages": [],
            "payment_details": {
                "freight_payment_mode": "TO_PAY",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_value": 25000.0,
                "shipment_tax_value": 0.0,
                "shipment_total_value": 25000.0,
            },
        }
        # MVP Scope: new TO_PAY bookings are refused with 400 by default
        refused_blind = await client.post(
            "/api/v1/shipments", headers=b2b_headers, json=blind_lr_payload
        )
        assert refused_blind.status_code == 400, refused_blind.text

        with allow_to_pay_bookings():
            blind_resp = await client.post(
                "/api/v1/shipments", headers=b2b_headers, json=blind_lr_payload
            )
        assert blind_resp.status_code == 201, (
            f"Blind B2B LR #2 booking failed ({blind_resp.status_code}): {blind_resp.text}"
        )
        b2b_lr2_data = blind_resp.json()
        wallet_after = await _wallet_balance(client, b2b_headers)
        assert round(wallet_before - wallet_after, 2) == 0.0, (
            "Expected Rs.0.00 upfront debit on TO_PAY Blind B2B LR #2"
        )
        _save_state(
            {
                "b2b_lr2_id": b2b_lr2_data["id"],
                "b2b_lr2_tracking_id": b2b_lr2_data["tracking_id"],
            }
        )
        assert b2b_lr2_data["is_blind_pickup"] is True
        assert b2b_lr2_data["total_box_count"] == 12
        assert b2b_lr2_data["packages"] == []

        # 2. B2B Pickup Request (service_flow=B2B, is_blind_pickup=True, total_boxes=12) with LR #1
        pur_resp = await client.post(
            "/api/v1/manifests",
            headers=b2b_headers,
            json={
                "pickup_address_id": warehouse_id,
                "scheduled_date": today_iso,
                "time_slot": "10:00 - 14:00",
                "service_flow": "B2B",
                "is_blind_pickup": True,
                "total_boxes": 12,
                "shipment_ids": [b2b_lr1_id],
            },
        )
        assert pur_resp.status_code == 201, (
            f"Creating B2B PUR failed ({pur_resp.status_code}): {pur_resp.text}"
        )
        b2b_pur_data = pur_resp.json()
        b2b_pur_id = b2b_pur_data["id"]
        _save_state(
            {
                "b2b_pur_id": b2b_pur_id,
                "b2b_pur_code": b2b_pur_data.get("pickup_request_number"),
            }
        )
        assert b2b_pur_data["service_flow"] == "B2B"
        assert b2b_pur_data["is_blind_pickup"] is True
        assert b2b_pur_data["total_boxes"] == 12
        assert b2b_pur_data["status"] == ManifestStatus.SCHEDULED.value

        # 3. Ops dispatches the B2B PUR
        disp_resp = await client.post(
            f"/api/v1/manifests/{b2b_pur_id}/dispatch",
            headers=ops_headers,
            json={"picked_shipment_ids": [b2b_lr1_id]},
        )
        assert disp_resp.status_code == 200, (
            f"Dispatching B2B PUR failed ({disp_resp.status_code}): {disp_resp.text}"
        )
        assert disp_resp.json()["status"] == ManifestStatus.PICKED.value

        # 4. The merchant reads the OTP; ops delivers B2B LR #1 with it
        b2b_lr1_otp = await read_otp_as_merchant(client, accounts, CUSTOMER_B2B_EMAIL, b2b_lr1_id)
        deliv_resp = await client.patch(
            f"/api/v1/shipments/{b2b_lr1_id}",
            headers=ops_headers,
            json={
                "status": PickupStatus.COMPLETED.value,
                "delivery_otp": b2b_lr1_otp,
                "pod_received_by": "Vikramaditya Mehta (Dock 14)",
                "comment": "5 wooden crates received intact",
            },
        )
        assert deliv_resp.status_code == 200, (
            f"Delivering B2B LR #1 failed ({deliv_resp.status_code}): {deliv_resp.text}"
        )
        assert deliv_resp.json()["status"] == PickupStatus.COMPLETED.value


# ==============================================================================
# SUITE 8: UPI Recharges, COD Remittances, GST Notes, Support & Final Audit (G6)
# ==============================================================================


@pytest.mark.asyncio
async def test_j30_upi_qr_recharge_maker_checker_approve_and_reject() -> None:
    """J30: UPI QR Recharge Intent -> User Confirm Paid -> Maker-Checker Guard -> Admin Approve #1 vs Reject #2."""
    accounts = await load_accounts()
    b2c_headers = accounts[CUSTOMER_B2C_EMAIL]["headers"]
    admin_headers = accounts[ADMIN_EMAIL]["headers"]
    owner_headers = accounts[OWNER_EMAIL]["headers"]
    approved_utr = make_utr()
    rejected_utr = make_utr()

    async with _client() as client:
        # 1. Recharge #1 (+Rs.2,000.00): Intent -> Confirm -> Admin Approve
        bal_before = await _wallet_balance(client, b2c_headers)
        intent1_resp = await client.post(
            "/api/v1/wallet/recharge/upi-intent",
            headers=b2c_headers,
            json={"amount": J30_APPROVED_AMOUNT},
        )
        assert intent1_resp.status_code == 200, f"UPI intent #1 failed: {intent1_resp.text}"
        intent1_data = intent1_resp.json()
        txn1_id = intent1_data["transaction_id"]
        merchant_vpa = intent1_data["merchant_vpa"]
        assert merchant_vpa, "UPI intent must carry the tenant's merchant VPA"
        assert merchant_vpa.split("@")[0] in intent1_data["upi_uri"]
        assert "2000.00" in intent1_data["upi_uri"]

        # Balance unchanged while PENDING
        assert round(await _wallet_balance(client, b2c_headers), 2) == round(bal_before, 2)

        # Customer clicks "I Have Paid" -> POST /api/v1/wallet/recharge/{id}/confirm
        confirm1_resp = await client.post(
            f"/api/v1/wallet/recharge/{txn1_id}/confirm",
            headers=b2c_headers,
            json={"utr_number": approved_utr},
        )
        assert confirm1_resp.status_code == 200, f"Confirm UPI #1 failed: {confirm1_resp.text}"
        confirm1_data = confirm1_resp.json()
        assert confirm1_data["status"] == "PENDING", (
            "Customer confirm must keep transaction PENDING awaiting Admin verification"
        )
        assert confirm1_data["transaction"]["utr_number"] == approved_utr

        # Customer cannot call the Admin approve endpoint -> 403 Forbidden
        self_approve_resp = await client.post(
            f"/api/v1/wallet/recharge/{txn1_id}/approve", headers=b2c_headers
        )
        assert self_approve_resp.status_code == 403

        # Admin approves Recharge #1 -> status=COMPLETED, balance += Rs.2,000.00
        approve1_resp = await client.post(
            f"/api/v1/wallet/recharge/{txn1_id}/approve", headers=admin_headers
        )
        assert approve1_resp.status_code == 200, f"Admin approve #1 failed: {approve1_resp.text}"
        approve1_data = approve1_resp.json()
        assert approve1_data["status"] == "COMPLETED"
        txn_obj = approve1_data["transaction"]
        assert txn_obj["receipt_number"].startswith(receipt_prefix("REC"))
        assert round(float(txn_obj["opening_balance"]), 2) == round(bal_before, 2)
        assert round(float(txn_obj["closing_balance"]), 2) == round(
            bal_before + J30_APPROVED_AMOUNT, 2
        )
        bal_after = await _wallet_balance(client, b2c_headers)
        assert round(bal_after, 2) == round(bal_before + J30_APPROVED_AMOUNT, 2)

        stored = await find_wallet_txn_by_utr(approved_utr)
        assert stored is not None and str(stored.id) == txn1_id
        assert stored.status == WalletTxnStatus.COMPLETED

        _save_state(
            {
                "j30_approved_txn_id": txn1_id,
                "j30_approved_utr": approved_utr,
                "j30_balance_before_recharge": bal_before,
                "j30_balance_after_recharge": bal_after,
            }
        )

        # Recharge Receipt PDF download
        rcpt_resp = await client.get(
            f"/api/v1/wallet/transactions/{txn1_id}/receipt-pdf", headers=b2c_headers
        )
        assert rcpt_resp.status_code == 200
        assert rcpt_resp.content.startswith(b"%PDF-")

        # 2. Maker-Checker Self-Approval Guard: Admin cannot approve their own recharge -> 403
        admin_intent_resp = await client.post(
            "/api/v1/wallet/recharge/upi-intent",
            headers=admin_headers,
            json={"amount": J30_ADMIN_OWN_AMOUNT},
        )
        assert admin_intent_resp.status_code == 200
        admin_own_txn_id = admin_intent_resp.json()["transaction_id"]

        maker_checker_resp = await client.post(
            f"/api/v1/wallet/recharge/{admin_own_txn_id}/approve", headers=admin_headers
        )
        assert maker_checker_resp.status_code == 403, (
            f"Expected 403 Maker-Checker violation on self-approval, got {maker_checker_resp.status_code}: {maker_checker_resp.text}"
        )

        # Owner rejects the admin's own intent so no dangling PENDING intent remains
        cleanup_resp = await client.post(
            f"/api/v1/wallet/recharge/{admin_own_txn_id}/reject", headers=owner_headers
        )
        assert cleanup_resp.status_code == 200, cleanup_resp.text

        # 3. Recharge #2 (Rs.500.00): Intent -> Confirm -> Admin Reject -> FAILED, Rs.0.00 change
        bal_before_rej = await _wallet_balance(client, b2c_headers)
        intent2_resp = await client.post(
            "/api/v1/wallet/recharge/upi-intent",
            headers=b2c_headers,
            json={"amount": J30_REJECTED_AMOUNT},
        )
        assert intent2_resp.status_code == 200
        txn2_id = intent2_resp.json()["transaction_id"]

        confirm2_resp = await client.post(
            f"/api/v1/wallet/recharge/{txn2_id}/confirm",
            headers=b2c_headers,
            json={"utr_number": rejected_utr},
        )
        assert confirm2_resp.status_code == 200
        assert confirm2_resp.json()["status"] == "PENDING"

        reject2_resp = await client.post(
            f"/api/v1/wallet/recharge/{txn2_id}/reject", headers=admin_headers
        )
        assert reject2_resp.status_code == 200, f"Admin reject #2 failed: {reject2_resp.text}"
        assert reject2_resp.json()["status"] == "FAILED"

        bal_after_rej = await _wallet_balance(client, b2c_headers)
        assert round(bal_after_rej, 2) == round(bal_before_rej, 2), (
            "Rejected UPI recharge must not alter wallet balance"
        )
        _save_state({"j30_rejected_txn_id": txn2_id, "j30_rejected_utr": rejected_utr})


@pytest.mark.asyncio
async def test_j31_duplicate_utr_409_conflict_anti_replay_guard() -> None:
    """J31: Duplicate UTR 409 Conflict Anti-Replay Guard & Admin-only verify-utr guard."""
    accounts = await load_accounts()
    b2c_headers = accounts[CUSTOMER_B2C_EMAIL]["headers"]
    admin_headers = accounts[ADMIN_EMAIL]["headers"]
    owner_headers = accounts[OWNER_EMAIL]["headers"]
    state = _load_state()
    require_state(state, ("j30_approved_utr",))
    used_utr = state["j30_approved_utr"]

    async with _client() as client:
        # 1. Customer attempting Admin-only /recharge/verify-utr -> 403 Forbidden
        cust_verify_resp = await client.post(
            "/api/v1/wallet/recharge/verify-utr",
            headers=b2c_headers,
            json={"utr_number": make_utr(), "amount": 500.0},
        )
        assert cust_verify_resp.status_code == 403

        # 2. Admin re-submitting the UTR already used in J30 via /recharge/verify-utr -> 409 Conflict
        dup_verify_resp = await client.post(
            "/api/v1/wallet/recharge/verify-utr",
            headers=admin_headers,
            json={"utr_number": used_utr, "amount": 500.0},
        )
        assert dup_verify_resp.status_code == 409, (
            f"Expected 409 Conflict on duplicate UTR verify-utr, got {dup_verify_resp.status_code}: {dup_verify_resp.text}"
        )

        # 3. Customer confirming a new UPI intent with the already-used UTR -> 409 Conflict
        new_intent_resp = await client.post(
            "/api/v1/wallet/recharge/upi-intent",
            headers=b2c_headers,
            json={"amount": J31_REPLAY_AMOUNT},
        )
        assert new_intent_resp.status_code == 200
        replay_txn_id = new_intent_resp.json()["transaction_id"]

        replay_confirm_resp = await client.post(
            f"/api/v1/wallet/recharge/{replay_txn_id}/confirm",
            headers=b2c_headers,
            json={"utr_number": used_utr},
        )
        assert replay_confirm_resp.status_code == 409, (
            f"Expected 409 Conflict on duplicate UTR confirm, got {replay_confirm_resp.status_code}: {replay_confirm_resp.text}"
        )

        # Reject the temporary replay intent so no dangling PENDING intent remains
        cleanup_resp = await client.post(
            f"/api/v1/wallet/recharge/{replay_txn_id}/reject", headers=owner_headers
        )
        assert cleanup_resp.status_code == 200, cleanup_resp.text


@pytest.mark.asyncio
async def test_j32_delivery_otp_pod_and_dual_cod_settlement_plus_anti_double_payout() -> None:
    """J32: Delivery OTP POD & Dual COD Settlement (Path A: Wallet Credit on Order #1; Path B: Bank UTR Batch on Order #3)."""
    accounts = await load_accounts()
    b2c_headers = accounts[CUSTOMER_B2C_EMAIL]["headers"]
    ops_headers = accounts[OPERATIONS_EMAIL]["headers"]
    admin_headers = accounts[ADMIN_EMAIL]["headers"]
    b2c_user_id = str(accounts[CUSTOMER_B2C_EMAIL]["id"])
    tenant_id = await _get_tenant_id()
    state = _load_state()
    require_state(state, SUITE_8_REQUIRED_KEYS)
    order1_id = state["order1_id"]
    order3_id = state["order3_id"]
    bank_utr_order3 = make_bank_utr()

    async with _client() as client:
        # STEP 1: Deliver Order #1 (PREPAID + COD Rs.1,500.00) with OTP verification
        assert (await _get_shipment(client, b2c_headers, order1_id))["status"] == PickupStatus.IN_TRANSIT.value
        bad_otp_resp = await client.patch(
            f"/api/v1/shipments/{order1_id}",
            headers=ops_headers,
            json={"status": PickupStatus.COMPLETED.value, "delivery_otp": "000000"},
        )
        assert bad_otp_resp.status_code == 400, (
            f"Expected 400 on wrong delivery OTP for Order #1, got {bad_otp_resp.status_code}: {bad_otp_resp.text}"
        )
        o1_otp = await read_otp_as_merchant(client, accounts, CUSTOMER_B2C_EMAIL, order1_id)
        good_otp_resp = await client.patch(
            f"/api/v1/shipments/{order1_id}",
            headers=ops_headers,
            json={
                "status": PickupStatus.COMPLETED.value,
                "delivery_otp": o1_otp,
                "pod_received_by": "Aarav Sharma (Consignee)",
                "pod_notes": "COD Rs.1,500 collected in cash at doorstep",
            },
        )
        assert good_otp_resp.status_code == 200, f"Delivering Order #1 failed: {good_otp_resp.text}"
        assert good_otp_resp.json()["status"] == PickupStatus.COMPLETED.value

        # STEP 2: Path A - Admin settles Order #1 COD (Rs.1,500.00) into the customer wallet.
        # A customer never self-settles (paid in the remittance cycle, coordinator 2026-11-01).
        # Order #3 is still IN_TRANSIT here, so settle-cod settles ONLY Order #1.
        o1_check = await _get_shipment(client, b2c_headers, order1_id)
        assert o1_check["payment_details"]["cod_remittance_status"] != "REMITTED"
        self_settle = await client.post("/api/v1/wallet/settle-cod", headers=b2c_headers)
        assert self_settle.status_code == 403, (
            f"Customer self-settle must be refused, got {self_settle.status_code}: {self_settle.text}"
        )
        bal_before_cod = await _wallet_balance(client, b2c_headers)
        settle_resp = await client.post(
            "/api/v1/wallet/settle-cod",
            headers=admin_headers,
            params={"merchant_user_id": b2c_user_id},
        )
        assert settle_resp.status_code == 200, f"Wallet COD settlement failed: {settle_resp.text}"
        settle_data = settle_resp.json()
        assert settle_data["settled_count"] == 1
        assert round(float(settle_data["settled_amount"]), 2) == J32_ORDER1_COD
        assert round(float(settle_data["new_balance"]), 2) == round(bal_before_cod + J32_ORDER1_COD, 2)
        _save_state(
            {
                "j32_wallet_balance_before_cod1": bal_before_cod,
                "j32_wallet_balance_after_cod1": float(settle_data["new_balance"]),
            }
        )

        o1_after = await _get_shipment(client, b2c_headers, order1_id)
        assert o1_after["payment_details"]["cod_remittance_status"] == "REMITTED"

        async with GoldenSessionLocal() as session:
            cod_txns = list(
                (
                    await session.exec(
                        select(WalletTransaction).where(
                            WalletTransaction.tenant_id == tenant_id,
                            WalletTransaction.txn_type == WalletTxnType.COD_SETTLEMENT,
                        )
                    )
                ).all()
            )
        assert len(cod_txns) == 1
        assert round(float(cod_txns[0].amount), 2) == J32_ORDER1_COD
        assert (cod_txns[0].receipt_number or "").startswith(receipt_prefix("COD"))

        # STEP 3: Deliver Order #3 (TO_PAY + COD Rs.2,000.00) with OTP
        bad_otp3_resp = await client.patch(
            f"/api/v1/shipments/{order3_id}",
            headers=ops_headers,
            json={"status": PickupStatus.COMPLETED.value, "delivery_otp": "000000"},
        )
        assert bad_otp3_resp.status_code == 400
        o3_otp = await read_otp_as_merchant(client, accounts, CUSTOMER_B2C_EMAIL, order3_id)
        good_otp3_resp = await client.patch(
            f"/api/v1/shipments/{order3_id}",
            headers=ops_headers,
            json={
                "status": PickupStatus.COMPLETED.value,
                "delivery_otp": o3_otp,
                "pod_received_by": "Rohan Kapoor (Consignee)",
                "pod_notes": "Collected Rs.2,000 COD + TO_PAY freight at door",
            },
        )
        assert good_otp3_resp.status_code == 200, f"Delivering Order #3 failed: {good_otp3_resp.text}"
        assert good_otp3_resp.json()["status"] == PickupStatus.COMPLETED.value

        # STEP 4: Path B - Remit Order #3 via a bank UTR batch (POST /api/v1/remittances)
        bal_before_bank = await _wallet_balance(client, b2c_headers)
        rem_resp = await client.post(
            "/api/v1/remittances",
            headers=admin_headers,
            json={
                "shipment_ids": [order3_id],
                "bank_utr": bank_utr_order3,
                "expected_total": J32_ORDER3_GOODS,
            },
        )
        assert rem_resp.status_code == 201, (
            f"Bank UTR COD remittance on Order #3 failed ({rem_resp.status_code}): {rem_resp.text}"
        )
        rem_data = rem_resp.json()
        rem3_id = rem_data["id"]
        assert rem_data["state"] == RemittanceState.COMPLETED.value
        assert rem_data["bank_utr"] == bank_utr_order3
        assert rem_data["total_orders"] == 1
        # D26: TO_PAY + COD Rs.2,000.00 -> seller receives the goods value; the carrier keeps the freight
        assert round(float(rem_data["total_remittance"]), 2) == J32_ORDER3_GOODS
        bal_after_bank = await _wallet_balance(client, b2c_headers)
        assert round(bal_after_bank, 2) == round(bal_before_bank, 2), (
            "Bank UTR remittance must not credit wallet balance"
        )
        _save_state({"j32_order3_remittance_id": rem3_id, "j32_order3_bank_utr": bank_utr_order3})

        # Remittance CSV download
        csv_resp = await client.get(f"/api/v1/remittances/{rem3_id}/csv", headers=b2c_headers)
        assert csv_resp.status_code == 200
        assert "2000" in csv_resp.text

        # STEP 5: Anti-Double-Payout Guard
        dup_rem1_resp = await client.post(
            "/api/v1/remittances",
            headers=admin_headers,
            json={
                "shipment_ids": [order1_id],
                "bank_utr": make_bank_utr(),
                "expected_total": J32_ORDER1_COD,
            },
        )
        assert dup_rem1_resp.status_code == 400, (
            f"Expected 400 when re-remitting Wallet-settled Order #1 via Bank UTR, got {dup_rem1_resp.status_code}"
        )
        dup_rem3_resp = await client.post(
            "/api/v1/remittances",
            headers=admin_headers,
            json={
                "shipment_ids": [order3_id],
                "bank_utr": make_bank_utr(),
                "expected_total": J32_ORDER3_GOODS,
            },
        )
        assert dup_rem3_resp.status_code == 400, (
            f"Expected 400 when re-remitting Bank-settled Order #3, got {dup_rem3_resp.status_code}"
        )
        dup_wallet_settle = await client.post(
            "/api/v1/wallet/settle-cod",
            headers=admin_headers,
            params={"merchant_user_id": b2c_user_id},
        )
        assert dup_wallet_settle.status_code == 200
        assert dup_wallet_settle.json()["settled_count"] == 0
        assert float(dup_wallet_settle.json()["settled_amount"]) == 0.0


@pytest.mark.asyncio
async def test_j33_gst_invoices_credit_debit_notes_pdf_and_csv() -> None:
    """J33: GST Invoices, Credit Notes, Debit Notes, PDF & CSV Exports."""
    accounts = await load_accounts()
    owner_headers = accounts[OWNER_EMAIL]["headers"]
    b2b_user_id = accounts[CUSTOMER_B2B_EMAIL]["id"]

    async with _client() as client:
        # 1. Fetch all 3 GST note types
        inv_resp = await client.get("/api/v1/invoices?note_type=INVOICE", headers=owner_headers)
        cn_resp = await client.get("/api/v1/invoices?note_type=CREDIT_NOTE", headers=owner_headers)
        dn_resp = await client.get("/api/v1/invoices?note_type=DEBIT_NOTE", headers=owner_headers)
        assert inv_resp.status_code == 200
        assert cn_resp.status_code == 200
        assert dn_resp.status_code == 200

        invoices = inv_resp.json()
        credit_notes = cn_resp.json()
        debit_notes = dn_resp.json()

        assert len(invoices) >= 4, (
            f"Expected at least 4 GST INVOICE notes (3 B2C + 1 B2B), got {len(invoices)}"
        )
        assert len(credit_notes) >= 2, (
            f"Expected at least 2 GST CREDIT_NOTE notes (Order #2 cancel + Order #1 weight claim), got {len(credit_notes)}"
        )
        assert len(debit_notes) >= 2, (
            f"Expected at least 2 GST DEBIT_NOTE notes (weight audits + Order #5 RTO), got {len(debit_notes)}"
        )

        # 2. GST Rule 46 (<= 16 chars), GSTIN, test-tenant prefix and tax math on every note
        for note_list, expected_prefix in (
            (invoices, INVOICE_PREFIX),
            (credit_notes, CREDIT_NOTE_PREFIX),
            (debit_notes, DEBIT_NOTE_PREFIX),
        ):
            for note in note_list:
                inv_no = note["invoice_number"]
                assert inv_no.startswith(expected_prefix), (
                    f"Expected prefix {expected_prefix}, got {inv_no}"
                )
                assert len(inv_no) <= 16, f"GST Rule 46 violation: {inv_no} exceeds 16 chars"
                assert note["gst_number"] == GSTIN_LOGISMART

                freight = float(note["freight_amount"])
                cgst = float(note["cgst_amount"])
                sgst = float(note["sgst_amount"])
                igst = float(note["igst_amount"])
                total = float(note["total_amount"])
                assert round(freight + cgst + sgst + igst, 2) == round(total, 2), (
                    f"GST math mismatch on {inv_no}: {note}"
                )
                if note.get("merchant_user_id") == b2b_user_id:
                    assert igst > 0, f"B2B Karnataka invoice {inv_no} should have IGST"
                    assert cgst == 0 and sgst == 0, f"B2B Karnataka invoice {inv_no} must not have CGST/SGST"
                    assert round(igst, 2) == round(float(note["freight_amount"]) * 0.18, 2)

        # 3. PDF and Transactions CSV downloads on a sample Invoice, Credit Note and Debit Note
        for sample_note in (invoices[0], credit_notes[0], debit_notes[0]):
            nid = sample_note["id"]
            pdf_resp = await client.get(f"/api/v1/invoices/{nid}/pdf", headers=owner_headers)
            assert pdf_resp.status_code == 200
            assert pdf_resp.content.startswith(b"%PDF-")

            csv_resp = await client.get(
                f"/api/v1/invoices/{nid}/transactions-csv", headers=owner_headers
            )
            assert csv_resp.status_code == 200
            assert sample_note["invoice_number"] in csv_resp.text


@pytest.mark.asyncio
async def test_j34_support_desk_lifecycle_and_counters() -> None:
    """J34: Support Desk Lifecycle & Counters: OPEN -> Support Reply -> RESOLVED -> Customer Reopen -> CLOSED."""
    accounts = await load_accounts()
    b2c_headers = accounts[CUSTOMER_B2C_EMAIL]["headers"]
    support_headers = accounts[SUPPORT_EMAIL]["headers"]
    state = _load_state()
    require_state(state, ("order1_tracking_id",))
    order1_awb = state["order1_tracking_id"]

    async with _client() as client:
        # 1. support@logismart.in is blocked from initiating wallet recharges (403)
        sup_wallet_resp = await client.post(
            "/api/v1/wallet/recharge/upi-intent",
            headers=support_headers,
            json={"amount": 500.0},
        )
        assert sup_wallet_resp.status_code == 403, (
            f"Expected 403 when support agent calls recharge intent, got {sup_wallet_resp.status_code}"
        )

        # 2. Customer raises a fresh SHIPMENT_ISSUE ticket
        tkt_resp = await client.post(
            "/api/v1/support-tickets",
            headers=b2c_headers,
            json={
                "category_group": "SHIPMENT_ISSUE",
                "sub_category": "COD Remittance Query",
                "subject": "Verify COD settlement receipt for Order #1",
                "description": "Please confirm the wallet settlement receipt for my COD shipment.",
                "tracking_id": order1_awb,
            },
        )
        assert tkt_resp.status_code == 201, f"Creating support ticket failed: {tkt_resp.text}"
        tkt_data = tkt_resp.json()
        tkt_id = tkt_data["id"]
        tkt_number = tkt_data["ticket_number"]
        assert tkt_data["status"] == "OPEN"
        assert tkt_number.startswith("TKT-")

        # Summary counter: last sender is customerb2c -> awaiting_support >= 1
        sum1 = (await client.get("/api/v1/support-tickets/summary", headers=b2c_headers)).json()
        assert sum1["open"] >= 1
        assert sum1["awaiting_support"] >= 1

        # 3. Support replies -> need_your_input >= 1 for customerb2c
        msg1_resp = await client.post(
            f"/api/v1/support-tickets/{tkt_id}/messages",
            headers=support_headers,
            json={
                "message": "Your COD amount of Rs.1,500.00 has been credited to your wallet under receipt COD-2026."
            },
        )
        assert msg1_resp.status_code == 200
        assert len(msg1_resp.json()["messages"]) >= 2

        sum2 = (await client.get("/api/v1/support-tickets/summary", headers=b2c_headers)).json()
        assert sum2["need_your_input"] >= 1

        # 4. Support resolves -> RESOLVED
        res_resp = await client.patch(
            f"/api/v1/support-tickets/{tkt_id}/status",
            headers=support_headers,
            json={"status": "RESOLVED"},
        )
        assert res_resp.status_code == 200
        assert res_resp.json()["status"] == "RESOLVED"

        # 5. Customer replies to the RESOLVED ticket -> auto-reopens to OPEN
        reopen_resp = await client.post(
            f"/api/v1/support-tickets/{tkt_id}/messages",
            headers=b2c_headers,
            json={"message": "Thank you! Could you also confirm the GST invoice number?"},
        )
        assert reopen_resp.status_code == 200
        assert reopen_resp.json()["status"] == "OPEN", (
            "Customer reply on a RESOLVED ticket must auto-reopen ticket to OPEN"
        )

        # 6. Support replies and closes -> CLOSED
        reply2_resp = await client.post(
            f"/api/v1/support-tickets/{tkt_id}/messages",
            headers=support_headers,
            json={"message": "Confirmed! Closing this ticket now."},
        )
        assert reply2_resp.status_code == 200, reply2_resp.text
        close_resp = await client.patch(
            f"/api/v1/support-tickets/{tkt_id}/status",
            headers=support_headers,
            json={"status": "CLOSED"},
        )
        assert close_resp.status_code == 200
        assert close_resp.json()["status"] == "CLOSED"

        # 7. Invalid status transition attempt -> 400 Bad Request
        bad_status_resp = await client.patch(
            f"/api/v1/support-tickets/{tkt_id}/status",
            headers=support_headers,
            json={"status": "INVALID_STATUS"},
        )
        assert bad_status_resp.status_code == 400

        _save_state({"j34_ticket_id": tkt_id, "j34_ticket_number": tkt_number})


@pytest.mark.asyncio
async def test_j35_readonly_auditor_visibility_and_403_write_block_matrix() -> None:
    """J35: Read-Only Auditor Visibility (200 OK on all GETs) & 403 Write-Block Matrix."""
    accounts = await load_accounts()
    ro_headers = accounts[READONLY_EMAIL]["headers"]
    state = _load_state()
    require_state(state, ("warehouse_address_id", "order1_id"))
    today_iso = date.today().isoformat()

    async with _client() as client:
        # 1. 200 OK across all read endpoints for readonly@logismart.in
        get_endpoints = [
            "/api/v1/wallet",
            "/api/v1/wallet/transactions",
            "/api/v1/shipments",
            "/api/v1/manifests",
            "/api/v1/remittances",
            "/api/v1/invoices",
            "/api/v1/support-tickets",
            "/api/v1/dashboard/summary?service_flow=B2C&days=30",
            "/api/v1/disputes/weight-mismatch",
            "/api/v1/exceptions?service_flow=B2C",
        ]
        for ep in get_endpoints:
            r = await client.get(ep, headers=ro_headers)
            assert r.status_code == 200, (
                f"Expected 200 OK for readonly auditor on GET {ep}, got {r.status_code}: {r.text}"
            )
        # Team & Access and the Settings editor stay Admin/Owner-only, even for reads.
        for ep in ("/api/v1/users", "/api/v1/tenants/settings"):
            r = await client.get(ep, headers=ro_headers)
            assert r.status_code == 403, (
                f"Expected 403 for readonly auditor on admin-only GET {ep}, got {r.status_code}: {r.text}"
            )

        # Tenant-wide visibility: the auditor sees transactions from both B2C and B2B customers
        ro_txns_payload = (await client.get("/api/v1/wallet/transactions", headers=ro_headers)).json()
        ro_txns = (
            ro_txns_payload["items"]
            if isinstance(ro_txns_payload, dict) and "items" in ro_txns_payload
            else ro_txns_payload
        )
        assert len(ro_txns) >= 7, (
            f"Expected readonly auditor to see all tenant wallet transactions (>=7), got {len(ro_txns)}"
        )

        # 2. 403 Forbidden across write/mutation endpoints
        write_checks = [
            (
                "POST",
                "/api/v1/shipments",
                {
                    "pickup_address_id": state["warehouse_address_id"],
                    "new_delivery_address": _build_b2b_drop_address(),
                    "requested_pickup_date": today_iso,
                    "shipment_type": "FORWARD",
                    "service_type": "SURFACE_ROAD",
                    "product_category": "ELECTRONICS",
                    "packages": [
                        {
                            "box_count": 1,
                            "length": 10.0,
                            "breadth": 10.0,
                            "height": 10.0,
                            "dimension_unit": "CM",
                            "weight": 0.5,
                            "weight_unit": "KG",
                        }
                    ],
                    "payment_details": {
                        "freight_payment_mode": "PREPAID",
                        "is_cod": False,
                        "cod_amount": 0.0,
                        "shipment_value": 500.0,
                        "shipment_tax_value": 0.0,
                        "shipment_total_value": 500.0,
                    },
                },
            ),
            (
                "POST",
                "/api/v1/manifests",
                {
                    "pickup_address_id": state["warehouse_address_id"],
                    "scheduled_date": today_iso,
                    "time_slot": "10:00 - 14:00",
                    "shipment_ids": [],
                },
            ),
            ("POST", "/api/v1/wallet/recharge/upi-intent", {"amount": 500.0}),
            (
                "POST",
                "/api/v1/remittances",
                {"shipment_ids": [state["order1_id"]], "bank_utr": make_bank_utr()},
            ),
            ("PATCH", "/api/v1/tenants/settings", {"name": "Unauthorized Rename"}),
        ]

        for method, ep, payload in write_checks:
            if method == "POST":
                resp = await client.post(ep, headers=ro_headers, json=payload)
            else:
                resp = await client.patch(ep, headers=ro_headers, json=payload)
            assert resp.status_code == 403, (
                f"Expected 403 Forbidden for readonly auditor on {method} {ep}, got {resp.status_code}: {resp.text}"
            )


@pytest.mark.asyncio
async def test_j36_final_system_and_ledger_integrity_audit_g6_and_csv_export() -> None:
    """J36: Final System & Ledger Integrity Audit (G6) + Tenant-Wide CSV Export."""
    accounts = await load_accounts()
    owner_headers = accounts[OWNER_EMAIL]["headers"]
    b2c_headers = accounts[CUSTOMER_B2C_EMAIL]["headers"]
    b2b_headers = accounts[CUSTOMER_B2B_EMAIL]["headers"]
    tenant_id = await _get_tenant_id()

    async with _client() as client:
        # 1. G6 Ledger & System Integrity Audit
        audit_resp = await client.get("/api/v1/wallet/audit-integrity", headers=owner_headers)
        assert audit_resp.status_code == 200, (
            f"G6 audit-integrity failed ({audit_resp.status_code}): {audit_resp.text}"
        )
        audit_data = audit_resp.json()
        assert audit_data["passed"] is True, (
            f"G6 Ledger Integrity Audit failed with discrepancies: {audit_data}"
        )
        assert audit_data["discrepancy_count"] == 0
        assert audit_data["discrepancies"] == []
        assert audit_data["wallets_checked"] >= 2

        # 2. Final wallet balances for customerb2c and customerb2b
        b2c_wallet = (await client.get("/api/v1/wallet", headers=b2c_headers)).json()
        b2b_wallet = (await client.get("/api/v1/wallet", headers=b2b_headers)).json()

        # Every test-tenant wallet's balance equals the signed sum of its COMPLETED ledger
        # (amounts are stored unsigned; credits add, every other type debits).
        async with GoldenSessionLocal() as session:
            wallets = list(
                (await session.exec(select(Wallet).where(Wallet.tenant_id == tenant_id))).all()
            )
            for w in wallets:
                txns = list(
                    (
                        await session.exec(
                            select(WalletTransaction).where(
                                WalletTransaction.tenant_id == tenant_id,
                                WalletTransaction.wallet_id == w.id,
                                WalletTransaction.status == WalletTxnStatus.COMPLETED,
                            )
                        )
                    ).all()
                )
                signed_sum = round(
                    sum(
                        float(t.amount) if t.txn_type in LEDGER_CREDIT_TYPES else -float(t.amount)
                        for t in txns
                    ),
                    2,
                )
                assert signed_sum == round(float(w.balance), 2), (
                    f"Wallet {w.id} balance {w.balance} != signed ledger sum {signed_sum}"
                )

        # 3. Tenant-Wide Wallet Ledger CSV Export
        csv_resp = await client.get("/api/v1/wallet/export/csv", headers=owner_headers)
        assert csv_resp.status_code == 200
        assert (
            "Transaction ID,Receipt / Invoice No,Date (UTC),User Email,Type,Service Category,AWB / Tracking ID,UTR Number,Opening Balance (INR),Amount (INR),Closing Balance (INR),Status,Remarks"
            in csv_resp.text
        )

        _save_state(
            {
                "j36_audit_passed": audit_data["passed"],
                "j36_wallets_checked": audit_data["wallets_checked"],
                "j36_transactions_checked": audit_data["transactions_checked"],
                "j36_shipments_checked": audit_data["shipments_checked"],
                "j36_invoices_checked": audit_data["invoices_checked"],
                "j36_remittances_checked": audit_data["remittances_checked"],
                "j36_discrepancy_count": audit_data["discrepancy_count"],
                "final_customerb2c_wallet_balance": float(b2c_wallet["balance"]),
                "final_customerb2b_wallet_balance": float(b2b_wallet["balance"]),
            }
        )
