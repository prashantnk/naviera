"""
Golden Test Suite 5 & 6 (`J19-J26`):
- Suite 5: Hub Operations, Weight Audit, Public Tracking & NDR Exceptions (`J19-J24`)
- Suite 6: Reverse Shipments (`DTO`), Grid Sub-Tabs & Doorstep QC (`J25-J26`)

Runs ONLY against the guarded test tenant (`GOLDEN_TENANT_SLUG`, default
`logismart-test`), reset once per session by `golden_journeys/conftest.py`, with
real JWT sessions for the canonical test accounts. Verifies rupee-and-paisa
wallet balances, GST debit/credit notes, weight dispute claims, NDR 3-strike
auto-RTO, reverse doorstep QC (`G2`/`G3`), and
`GET /api/v1/wallet/audit-integrity`.

Every journey runs straight through: there are no "already done, skip"
branches and no direct database writes. State from Suite 3 & 4 is read from
the slug-namespaced batch file written by `test_j18`.
"""

import uuid
from datetime import date
from typing import Any, Dict

import httpx
import pytest
from httpx import ASGITransport
from sqlmodel import select

from app.main import app
from app.models.delhivery_modules import (
    BillingInvoice,
    InvoiceNoteType,
    TicketStatus,
    WeightDisputeClaimStatus,
)
from app.models.pickups import (
    NdrAction,
    NdrExceptionReason,
    PickupRequest,
    PickupStatus,
    ServiceType,
)
from app.models.wallet import WalletTransaction, WalletTxnStatus, WalletTxnType

from .golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GOLDEN_TENANT_SLUG,
    OPERATIONS_EMAIL,
    OWNER_EMAIL,
    SUPPORT_EMAIL,
    GoldenSessionLocal,
    document_prefix,
    load_state,
    order_ref,
    read_otp_as_merchant,
    receipt_prefix,
    require_state,
    save_state,
)
from .golden_env import (
    get_wallet_balance as _get_wallet_balance,
)
from .golden_env import (
    headers as _headers,
)
from .golden_env import (
    load_accounts as _load_accounts,
)

TENANT_SLUG = GOLDEN_TENANT_SLUG
J23_CHARGE_EXCL_GST = 100.0
J23_CHARGE_GROSS = round(J23_CHARGE_EXCL_GST * 1.18, 2)
"""D55: the ADDITIONAL_CHARGES amount is GST-exclusive; the wallet is debited it + 18% GST."""
BATCH2_STATE = "batch2"
BATCH3_STATE = "batch3"
CREDIT_NOTE_PREFIX = document_prefix(InvoiceNoteType.CREDIT_NOTE.value)
DEBIT_NOTE_PREFIX = document_prefix(InvoiceNoteType.DEBIT_NOTE.value)
BATCH2_REQUIRED_KEYS = ("order1_id", "order3_id", "order5_id", "warehouse_address_id")

STATE: Dict[str, Any] = {}


def _load_batch2_state() -> Dict[str, Any]:
    """Loads the Suite 3 & 4 state (slug-namespaced) once and returns the shared dict."""
    if not STATE:
        STATE.update(load_state(BATCH2_STATE))
    require_state(STATE, BATCH2_REQUIRED_KEYS)
    return STATE


async def _get_shipment(
    client: httpx.AsyncClient, accounts: Dict[str, Dict[str, Any]], shipment_id: str
) -> Dict[str, Any]:
    """Reads one shipment through the API as the merchant `customerb2c@logismart.in`."""
    resp = await client.get(
        f"/api/v1/shipments/{shipment_id}",
        headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.asyncio
async def test_j19_public_tracking_portal_and_privacy_redaction():
    """
    J19:
    - Adds an internal private (`is_public=False`) ops comment to Order #1.
    - Queries unauthenticated `GET /api/v1/shipments/tracking/{awb}` and `/api/v1/tracking/{awb}`.
    - Verifies `status == "IN_TRANSIT"`, public timeline events exist, and sensitive fields
      (`delivery_otp` value, `wallet`, `closing_balance`, `opening_balance`, and private comments)
      are 100% absent from the public payload.
    """
    accounts = await _load_accounts()
    st = _load_batch2_state()
    order1_id = st["order1_id"]
    order1_awb = st["order1_tracking_id"]
    order1_otp = st[f"otp_{order1_id}"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Log a private internal ops note on Order #1
        private_marker = "PRIVATE_HUB_INTERNAL_COMMENT_DO_NOT_EXPOSE_991"
        priv_resp = await client.patch(
            f"/api/v1/shipments/{order1_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "comment": private_marker,
                "is_public": False,
            },
        )
        assert priv_resp.status_code == 200, priv_resp.text

        # 2. Query public tracking endpoint without Authorization header
        for path in (
            f"/api/v1/shipments/tracking/{order1_awb}",
            f"/api/v1/tracking/{order1_awb}",
        ):
            pub_resp = await client.get(
                path,
                headers={"X-Tenant-Slug": TENANT_SLUG},
            )
            assert pub_resp.status_code == 200, pub_resp.text
            raw_text = pub_resp.text
            body = pub_resp.json()

            assert body["tracking_id"] == order1_awb
            assert body["status"] == "IN_TRANSIT"
            assert body.get("delivery_otp") is None
            assert isinstance(body.get("timeline"), list)
            assert len(body["timeline"]) >= 1
            assert isinstance(body.get("package_details"), list)
            # B-03: public tracking omits box contents & dimensions for privacy
            assert body["package_details"] == []

            # Security & privacy redaction checks
            assert order1_otp not in raw_text
            assert "wallet" not in raw_text.lower()
            assert "closing_balance" not in raw_text
            assert "opening_balance" not in raw_text
            assert private_marker not in raw_text


@pytest.mark.asyncio
async def test_j20_hub_weight_audit_auto_debit_note_customer_claim_accept_and_reject():
    """
    J20:
    Part A (Accept Claim on Order #1):
    - `operations@logismart.in` audits Order #1 (`POST /api/v1/shipments/{order1_id}/audit-weight`
      with `audited_weight_kg = 3.0`).
    - Verifies exact delta is debited from `customerb2c` wallet (`WalletTxnType.WEIGHT_AUDIT_DEBIT`),
      a GST `DEBIT_NOTE` is issued in `billing_invoices`, and a `WeightDispute` row is created.
    - `customerb2c@logismart.in` raises a claim -> `claim_status == "CLAIM_RAISED"` and a linked
      `SupportTicket` (`TKT-`) is auto-created.
    - `admin@logismart.in` accepts the claim -> `WalletTxnType.REFUND` credits the delta, a GST
      `CREDIT_NOTE` is issued, and the linked `SupportTicket` moves to `RESOLVED`.

    Part B (Reject Claim on Order #5):
    - Dispatches Order #5 to `IN_TRANSIT` via a B2C PUR (`PUR-4`), audits weight to `2.5 kg`,
      customer raises claim, and `admin@logismart.in` rejects -> `claim_status == "REJECTED"`,
      zero refund.
    """
    accounts = await _load_accounts()
    st = _load_batch2_state()
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]
    order1_id = st["order1_id"]
    order1_awb = st["order1_tracking_id"]
    order5_id = st["order5_id"]
    order5_awb = st["order5_tracking_id"]
    warehouse_id = st["warehouse_address_id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # ------------------------------------------------------------------
        # Part A: Order #1 Weight Audit (0.5 kg -> 3.0 kg) -> Claim -> Accept & Refund
        # ------------------------------------------------------------------
        disp_list_resp = await client.get(
            f"/api/v1/disputes/weight-mismatch?search={order1_awb}",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert disp_list_resp.status_code == 200, disp_list_resp.text
        assert disp_list_resp.json() == [], "Fresh tenant: Order #1 has no dispute yet"

        ord1_before = await _get_shipment(client, accounts, order1_id)
        old_cost_1 = round(
            float(ord1_before["payment_details"]["total_logistics_cost"]), 2
        )
        bal_before_1 = await _get_wallet_balance(b2c_user_id)

        audit1_resp = await client.post(
            f"/api/v1/shipments/{order1_id}/audit-weight",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={"audited_weight_kg": 3.0},
        )
        assert audit1_resp.status_code == 200, audit1_resp.text
        ord1_after = audit1_resp.json()
        new_cost_1 = round(
            float(ord1_after["payment_details"]["total_logistics_cost"]), 2
        )
        assert round(float(ord1_after["payment_details"]["chargeable_weight"]), 2) == 3.0
        delta_1 = round(new_cost_1 - old_cost_1, 2)
        assert delta_1 > 0
        bal_after_audit_1 = await _get_wallet_balance(b2c_user_id)
        assert bal_after_audit_1 == round(bal_before_1 - delta_1, 2)

        disp_rows = (
            await client.get(
                f"/api/v1/disputes/weight-mismatch?search={order1_awb}",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            )
        ).json()
        assert len(disp_rows) == 1
        dispute1_id = disp_rows[0]["id"]
        assert disp_rows[0]["claim_status"] == WeightDisputeClaimStatus.NONE.value

        claim1_resp = await client.post(
            "/api/v1/disputes/weight-mismatch/claims",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "tracking_ids": [order1_awb],
                "claimed_weight_g": 500.0,
                "claim_remarks": "Actual parcel is 500g earbuds box; sorter double-read",
            },
        )
        assert claim1_resp.status_code == 200, claim1_resp.text
        assert (
            claim1_resp.json()[0]["claim_status"]
            == WeightDisputeClaimStatus.CLAIM_RAISED.value
        )

        resolve1_resp = await client.patch(
            f"/api/v1/disputes/weight-mismatch/{dispute1_id}/resolve",
            headers=_headers(accounts, ADMIN_EMAIL),
            json={
                "claim_status": WeightDisputeClaimStatus.ACCEPTED.value,
                "claim_remarks": "Verified hub camera image; refunding weight delta",
            },
        )
        assert resolve1_resp.status_code == 200, resolve1_resp.text
        bal_after_accept_1 = await _get_wallet_balance(b2c_user_id)
        assert bal_after_accept_1 == bal_before_1

        dispute1 = resolve1_resp.json()
        assert round(float(dispute1["cost_diff_inr"]), 2) == delta_1
        assert round(float(dispute1["charged_weight_g"]), 2) == 3000.0
        assert round(float(dispute1["claimed_weight_g"]), 2) == 500.0
        assert dispute1["claim_status"] == WeightDisputeClaimStatus.ACCEPTED.value
        STATE["order1_weight_audit_delta"] = delta_1

        # Verify the linked RESOLVED SupportTicket
        tkt_list_resp = await client.get(
            f"/api/v1/support-tickets?search={order1_awb}",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert tkt_list_resp.status_code == 200, tkt_list_resp.text
        tkts1 = tkt_list_resp.json()
        assert len(tkts1) == 1
        linked_tkt1 = tkts1[0]
        assert linked_tkt1["ticket_number"].startswith("TKT-")
        assert linked_tkt1["status"] == TicketStatus.RESOLVED.value
        STATE["order1_weight_ticket_number"] = linked_tkt1["ticket_number"]

        # Verify WEIGHT_AUDIT_DEBIT, REFUND, DEBIT_NOTE and CREDIT_NOTE in PostgreSQL
        async with GoldenSessionLocal() as session:
            wad_txn = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.shipment_id == uuid.UUID(order1_id),
                        WalletTransaction.txn_type == WalletTxnType.WEIGHT_AUDIT_DEBIT,
                    )
                )
            ).first()
            assert wad_txn is not None
            assert wad_txn.status == WalletTxnStatus.COMPLETED
            assert round(float(wad_txn.amount), 2) == delta_1

            ref_txn = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.shipment_id == uuid.UUID(order1_id),
                        WalletTransaction.txn_type == WalletTxnType.REFUND,
                    )
                )
            ).first()
            assert ref_txn is not None
            assert ref_txn.status == WalletTxnStatus.COMPLETED
            assert round(float(ref_txn.amount), 2) == delta_1

            debit_notes = (
                await session.exec(
                    select(BillingInvoice).where(
                        BillingInvoice.merchant_user_id == uuid.UUID(b2c_user_id),
                        BillingInvoice.note_type == InvoiceNoteType.DEBIT_NOTE.value,
                    )
                )
            ).all()
            ord1_dn = next(
                (
                    dn
                    for dn in debit_notes
                    if any(
                        isinstance(item, dict) and item.get("shipment_id") == order1_id
                        for item in (dn.line_items or [])
                    )
                ),
                None,
            )
            assert ord1_dn is not None, "Expected GST DEBIT_NOTE for Order #1 weight audit"
            assert ord1_dn.invoice_number.startswith(DEBIT_NOTE_PREFIX)
            assert len(ord1_dn.invoice_number) <= 16
            assert round(float(ord1_dn.total_amount), 2) == delta_1
            STATE["order1_weight_debit_note"] = ord1_dn.invoice_number

            credit_notes = (
                await session.exec(
                    select(BillingInvoice).where(
                        BillingInvoice.merchant_user_id == uuid.UUID(b2c_user_id),
                        BillingInvoice.note_type == InvoiceNoteType.CREDIT_NOTE.value,
                    )
                )
            ).all()
            ord1_cn = next(
                (
                    cn
                    for cn in credit_notes
                    if any(
                        isinstance(item, dict) and item.get("shipment_id") == order1_id
                        for item in (cn.line_items or [])
                    )
                ),
                None,
            )
            assert ord1_cn is not None, "Expected GST CREDIT_NOTE for accepted Order #1 claim"
            assert ord1_cn.invoice_number.startswith(CREDIT_NOTE_PREFIX)
            assert len(ord1_cn.invoice_number) <= 16
            assert round(float(ord1_cn.total_amount), 2) == delta_1
            STATE["order1_weight_credit_note"] = ord1_cn.invoice_number

        # ------------------------------------------------------------------
        # Part B: Dispatch Order #5 -> Weight Audit (2.5 kg) -> Claim -> Admin Rejects
        # ------------------------------------------------------------------
        ord5_start = await _get_shipment(client, accounts, order5_id)
        assert ord5_start["status"] == PickupStatus.OPEN.value

        pur4_resp = await client.post(
            "/api/v1/manifests",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "pickup_address_id": warehouse_id,
                "scheduled_date": date.today().isoformat(),
                "time_slot": "10:00 - 14:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "shipment_ids": [order5_id],
            },
        )
        assert pur4_resp.status_code == 201, pur4_resp.text
        pur4_id = pur4_resp.json()["id"]
        STATE["pur4_id"] = pur4_id

        disp4_resp = await client.post(
            f"/api/v1/manifests/{pur4_id}/dispatch",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={"picked_shipment_ids": [order5_id]},
        )
        assert disp4_resp.status_code == 200, disp4_resp.text

        ord5_before = await _get_shipment(client, accounts, order5_id)
        assert ord5_before["status"] == PickupStatus.IN_TRANSIT.value
        old_cost_5 = round(
            float(ord5_before["payment_details"]["total_logistics_cost"]), 2
        )
        bal_before_5 = await _get_wallet_balance(b2c_user_id)

        audit5_resp = await client.post(
            f"/api/v1/shipments/{order5_id}/audit-weight",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={"audited_weight_kg": 2.5},
        )
        assert audit5_resp.status_code == 200, audit5_resp.text
        new_cost_5 = round(
            float(audit5_resp.json()["payment_details"]["total_logistics_cost"]), 2
        )
        delta_5 = round(new_cost_5 - old_cost_5, 2)
        assert delta_5 > 0

        bal_after_audit_5 = await _get_wallet_balance(b2c_user_id)
        assert bal_after_audit_5 == round(bal_before_5 - delta_5, 2)

        disp5_list = (
            await client.get(
                f"/api/v1/disputes/weight-mismatch?search={order5_awb}",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            )
        ).json()
        assert len(disp5_list) == 1
        dispute5_id = disp5_list[0]["id"]

        claim5_resp = await client.post(
            "/api/v1/disputes/weight-mismatch/claims",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "tracking_ids": [order5_awb],
                "claimed_weight_g": 500.0,
                "claim_remarks": "Disputing 2.5kg sorter reading",
            },
        )
        assert claim5_resp.status_code == 200, claim5_resp.text

        resolve5_resp = await client.patch(
            f"/api/v1/disputes/weight-mismatch/{dispute5_id}/resolve",
            headers=_headers(accounts, ADMIN_EMAIL),
            json={
                "claim_status": WeightDisputeClaimStatus.REJECTED.value,
                "claim_remarks": "Dimension & weight laser scan confirmed 2.50 kg",
            },
        )
        assert resolve5_resp.status_code == 200, resolve5_resp.text
        bal_after_reject_5 = await _get_wallet_balance(b2c_user_id)
        assert bal_after_reject_5 == bal_after_audit_5

        dispute5 = resolve5_resp.json()
        assert round(float(dispute5["cost_diff_inr"]), 2) == delta_5
        assert round(float(dispute5["charged_weight_g"]), 2) == 2500.0
        assert round(float(dispute5["claimed_weight_g"]), 2) == 500.0
        assert dispute5["claim_status"] == WeightDisputeClaimStatus.REJECTED.value
        STATE["order5_weight_audit_delta"] = delta_5


@pytest.mark.asyncio
async def test_j21_ndr_delivery_attempt_reattempt_and_update_consignee_same_pincode_rule():
    """
    J21:
    0) Preconditions read through the API (no direct DB writes): Order #1 is
       `IN_TRANSIT` with `ndr_attempt_count == 0` after J18-J20.
    1) `operations@logismart.in` raises `EXCEPTION` on Order #1 with
       `ndr_reason = "CONSIGNEE_UNAVAILABLE"` -> `ndr_attempt_count == 1`.
    2) `customerb2c@logismart.in` calls `REATTEMPT` -> Order #1 returns to `IN_TRANSIT`.
    3) Ops raises `CONSIGNEE_DETAILS_REQUIRED` on Order #1.
    4) `UPDATE_CONSIGNEE` with a different pincode (`110001` vs `122002`) -> `400`.
    5) `UPDATE_CONSIGNEE` with phone + address line in pincode `122002` -> new address
       snapshot created and Order #1 returns to `IN_TRANSIT`.
    """
    accounts = await _load_accounts()
    st = _load_batch2_state()
    order1_id = st["order1_id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ord1_start = await _get_shipment(client, accounts, order1_id)
        assert ord1_start["status"] == PickupStatus.IN_TRANSIT.value
        assert ord1_start["ndr_attempt_count"] == 0

        # 1. Ops raises CONSIGNEE_UNAVAILABLE on Order #1 -> attempt 1
        exc1_resp = await client.patch(
            f"/api/v1/shipments/{order1_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.CONSIGNEE_UNAVAILABLE.value,
                "ndr_remark": "Door locked on 1st attempt",
            },
        )
        assert exc1_resp.status_code == 200, exc1_resp.text
        exc1_body = exc1_resp.json()
        assert exc1_body["status"] == PickupStatus.EXCEPTION.value
        assert exc1_body["ndr_reason"] == NdrExceptionReason.CONSIGNEE_UNAVAILABLE.value
        assert exc1_body["ndr_attempt_count"] == 1
        old_deliv_addr_id = exc1_body["delivery_address"]["id"]

        # 2. Customer requests REATTEMPT -> returns to IN_TRANSIT
        reattempt_resp = await client.post(
            f"/api/v1/exceptions/{order1_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "action": NdrAction.REATTEMPT.value,
                "notes": "Buyer confirmed availability after 2 PM",
            },
        )
        assert reattempt_resp.status_code == 200, reattempt_resp.text
        assert reattempt_resp.json()["status"] == PickupStatus.IN_TRANSIT.value

        # 3. Ops raises CONSIGNEE_DETAILS_REQUIRED on Order #1
        exc2_resp = await client.patch(
            f"/api/v1/shipments/{order1_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED.value,
                "ndr_remark": "Landmark and flat number missing on doorbell",
            },
        )
        assert exc2_resp.status_code == 200, exc2_resp.text
        assert exc2_resp.json()["status"] == PickupStatus.EXCEPTION.value
        assert (
            exc2_resp.json()["ndr_reason"]
            == NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED.value
        )

        # 4. UPDATE_CONSIGNEE with a different pincode (110001 != 122002) -> 400 Bad Request
        wrong_pin_resp = await client.post(
            f"/api/v1/exceptions/{order1_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "action": NdrAction.UPDATE_CONSIGNEE.value,
                "consignee_phone": "9810099887",
                "consignee_address_line1": "Tower 4, Flat 902, DLF Cyber Park",
                "consignee_pincode": "110001",
            },
        )
        assert wrong_pin_resp.status_code == 400, wrong_pin_resp.text

        # 5. Valid UPDATE_CONSIGNEE within same pincode (122002) -> new address snapshot + IN_TRANSIT
        upd_cons_resp = await client.post(
            f"/api/v1/exceptions/{order1_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "action": NdrAction.UPDATE_CONSIGNEE.value,
                "consignee_phone": "9810099887",
                "consignee_address_line1": "Tower 4, Flat 902, DLF Phase 3",
                "landmark": "Near Moulsari Avenue Metro",
                "consignee_pincode": "122002",
            },
        )
        assert upd_cons_resp.status_code == 200, upd_cons_resp.text
        upd_row = upd_cons_resp.json()
        assert upd_row["status"] == PickupStatus.IN_TRANSIT.value
        assert upd_row["consignee"]["phone"] == "9810099887"
        assert upd_row["consignee"]["address_line1"] == "Tower 4, Flat 902, DLF Phase 3"

        ord1_refreshed = await _get_shipment(client, accounts, order1_id)
        assert ord1_refreshed["status"] == PickupStatus.IN_TRANSIT.value
        assert ord1_refreshed["delivery_address"]["id"] != old_deliv_addr_id, (
            "Expected fresh delivery Address snapshot row on UPDATE_CONSIGNEE"
        )


@pytest.mark.asyncio
async def test_j22_shipment_exceptions_eway_bill_missing_and_payment_dispute():
    """
    J22:
    1) Ops raises `EWAY_BILL_MISSING` on Order #1. A short e-way bill is rejected
       (400); `UPDATE_EWAY_BILL` with a 12-digit number + invoice number returns it to
       `IN_TRANSIT` and records both numbers.
    2) Ops raises `PAYMENT_DISPUTE` on Order #5 (`IN_TRANSIT` since J20). The customer
       switches it to COD (`cod_amount == 900.0`), then a second dispute switches it
       back to PREPAID (`cod_amount == 0.0`).
    """
    accounts = await _load_accounts()
    st = _load_batch2_state()
    order1_id = st["order1_id"]
    order5_id = st["order5_id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. EWAY_BILL_MISSING on Order #1 -> UPDATE_EWAY_BILL
        ewb_exc = await client.patch(
            f"/api/v1/shipments/{order1_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.EWAY_BILL_MISSING.value,
                "ndr_remark": "State border checkpost requested E-Way Bill",
            },
        )
        assert ewb_exc.status_code == 200, ewb_exc.text
        assert ewb_exc.json()["status"] == PickupStatus.EXCEPTION.value

        bad_ewb = await client.post(
            f"/api/v1/exceptions/{order1_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "action": NdrAction.UPDATE_EWAY_BILL.value,
                "eway_bill_number": "12345",
            },
        )
        assert bad_ewb.status_code == 400, bad_ewb.text

        good_ewb = await client.post(
            f"/api/v1/exceptions/{order1_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "action": NdrAction.UPDATE_EWAY_BILL.value,
                "eway_bill_number": "123456789012",
                "invoice_number": "INV-1001",
            },
        )
        assert good_ewb.status_code == 200, good_ewb.text
        assert good_ewb.json()["status"] == PickupStatus.IN_TRANSIT.value

        ord1_check = await _get_shipment(client, accounts, order1_id)
        assert "123456789012" in (
            ord1_check["payment_details"].get("eway_bill_numbers") or []
        )
        assert "INV-1001" in (ord1_check["payment_details"].get("invoice_numbers") or [])

        # 2. PAYMENT_DISPUTE on Order #5 -> UPDATE_PAYMENT_MODE (COD, then back to PREPAID)
        ord5_state = await _get_shipment(client, accounts, order5_id)
        assert ord5_state["status"] == PickupStatus.IN_TRANSIT.value

        pay_exc1 = await client.patch(
            f"/api/v1/shipments/{order5_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.PAYMENT_DISPUTE.value,
                "ndr_remark": "Consignee requested COD collection verification",
            },
        )
        assert pay_exc1.status_code == 200, pay_exc1.text

        to_cod_resp = await client.post(
            f"/api/v1/exceptions/{order5_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"action": NdrAction.UPDATE_PAYMENT_MODE.value, "is_cod": True},
        )
        assert to_cod_resp.status_code == 200, to_cod_resp.text
        assert to_cod_resp.json()["status"] == PickupStatus.IN_TRANSIT.value
        assert to_cod_resp.json()["payment_mode"] == "COD"
        assert round(float(to_cod_resp.json()["cod_amount"]), 2) == 900.0

        pay_exc2 = await client.patch(
            f"/api/v1/shipments/{order5_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.PAYMENT_DISPUTE.value,
                "ndr_remark": "Consignee paid merchant directly via UPI; switch to Prepaid",
            },
        )
        assert pay_exc2.status_code == 200, pay_exc2.text

        to_prepaid_resp = await client.post(
            f"/api/v1/exceptions/{order5_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"action": NdrAction.UPDATE_PAYMENT_MODE.value, "is_cod": False},
        )
        assert to_prepaid_resp.status_code == 200, to_prepaid_resp.text
        assert to_prepaid_resp.json()["status"] == PickupStatus.IN_TRANSIT.value
        assert to_prepaid_resp.json()["payment_mode"] == "PREPAID"
        assert round(float(to_prepaid_resp.json()["cod_amount"]), 2) == 0.0


@pytest.mark.asyncio
async def test_j23_charge_exceptions_d30_staff_403_guard_and_customer_acknowledge_wallet_debit():
    """
    J23:
    1) Ops raises `EXCEPTION` on Order #1 with `ndr_reason = "ADDITIONAL_CHARGES"`,
       `charge_amount = 100.0`.
    2) D30 guard: `operations@logismart.in` and `support@logismart.in` calling
       `ACKNOWLEDGE_CHARGES` receive `403 Forbidden`.
    3) `customerb2c@logismart.in` acknowledges -> exactly one
       `WalletTxnType.ADDITIONAL_CHARGE` debit of `100.00` (`ADC-2026-`), `charge_amount`
       clears and Order #1 returns to `IN_TRANSIT`.
    """
    accounts = await _load_accounts()
    st = _load_batch2_state()
    order1_id = st["order1_id"]
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]

    async with GoldenSessionLocal() as session:
        prior_charges = (
            await session.exec(
                select(WalletTransaction).where(
                    WalletTransaction.shipment_id == uuid.UUID(order1_id),
                    WalletTransaction.txn_type == WalletTxnType.ADDITIONAL_CHARGE,
                )
            )
        ).all()
    assert prior_charges == [], "Fresh tenant: Order #1 has no ADDITIONAL_CHARGE yet"

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Ops raises ADDITIONAL_CHARGES (100.00) on Order #1
        chg_exc = await client.patch(
            f"/api/v1/shipments/{order1_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.ADDITIONAL_CHARGES.value,
                "charge_amount": 100.0,
                "ndr_remark": "Mall union entry fee Rs.100",
            },
        )
        assert chg_exc.status_code == 200, chg_exc.text
        assert chg_exc.json()["status"] == PickupStatus.EXCEPTION.value
        assert round(float(chg_exc.json()["charge_amount"]), 2) == 100.0

        # 2. D30 Guard: operations_user and support_user must get 403 Forbidden
        for staff_email in (OPERATIONS_EMAIL, SUPPORT_EMAIL):
            staff_ack = await client.post(
                f"/api/v1/exceptions/{order1_id}/actions",
                headers=_headers(accounts, staff_email),
                json={"action": NdrAction.ACKNOWLEDGE_CHARGES.value},
            )
            assert staff_ack.status_code == 403, (
                f"Expected 403 for {staff_email} on ACKNOWLEDGE_CHARGES, "
                f"got {staff_ack.status_code}: {staff_ack.text}"
            )

        # 3. Customer acknowledges -> exactly one 100.00 wallet debit
        bal_before = await _get_wallet_balance(b2c_user_id)
        cust_ack = await client.post(
            f"/api/v1/exceptions/{order1_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "action": NdrAction.ACKNOWLEDGE_CHARGES.value,
                "notes": "Approved Rs.100 mall entry charge",
            },
        )
        assert cust_ack.status_code == 200, cust_ack.text
        ack_row = cust_ack.json()
        assert ack_row["status"] == PickupStatus.IN_TRANSIT.value
        assert ack_row["charge_amount"] is None

        # D55: ops enter the charge GST-exclusive; the merchant is debited it plus 18% GST
        # (a separate charge outside the bill, with its own DEBIT_NOTE).
        bal_after = await _get_wallet_balance(b2c_user_id)
        assert bal_after == round(bal_before - J23_CHARGE_GROSS, 2)

        async with GoldenSessionLocal() as session:
            add_txns = (
                await session.exec(
                    select(WalletTransaction).where(
                        WalletTransaction.shipment_id == uuid.UUID(order1_id),
                        WalletTransaction.txn_type == WalletTxnType.ADDITIONAL_CHARGE,
                    )
                )
            ).all()
        assert len(add_txns) == 1
        add_txn = add_txns[0]
        assert add_txn.status == WalletTxnStatus.COMPLETED
        assert round(float(add_txn.amount), 2) == J23_CHARGE_GROSS
        assert round(float(add_txn.opening_balance), 2) == bal_before
        assert round(float(add_txn.closing_balance), 2) == bal_after
        assert add_txn.receipt_number.startswith(receipt_prefix("ADC"))


@pytest.mark.asyncio
async def test_j24_three_strike_auto_rto_surcharge_debit_note_and_bulk_ndr_action():
    """
    J24 on Order #5 (`PREPAID`, `IN_TRANSIT` since J20):
    - Strike 1 (`CONSIGNEE_UNAVAILABLE`) -> `ndr_attempt_count == 1`, resolved through the
      Bulk NDR Action endpoint (`POST /api/v1/exceptions/bulk-action`, `REATTEMPT`).
    - Strike 2 (`CONSIGNEE_REFUSED`) -> `ndr_attempt_count == 2`, resolved via `REATTEMPT`.
    - Strike 3 (`CONSIGNEE_UNAVAILABLE`) -> `ndr_attempt_count == 3` ->
      `enforce_ndr_attempt_limit` moves Order #5 to `RTO_INITIATED`, adds `rto_surcharge`
      to `pricing_breakdown`, debits the RTO delta from `customerb2c`'s wallet and issues
      a GST `DEBIT_NOTE`.
    """
    accounts = await _load_accounts()
    st = _load_batch2_state()
    order5_id = st["order5_id"]
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ord5_start = await _get_shipment(client, accounts, order5_id)
        assert ord5_start["status"] == PickupStatus.IN_TRANSIT.value
        assert ord5_start["ndr_attempt_count"] == 0

        # Strike 1
        s1_resp = await client.patch(
            f"/api/v1/shipments/{order5_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.CONSIGNEE_UNAVAILABLE.value,
                "ndr_remark": "Strike 1 - Consignee unavailable",
            },
        )
        assert s1_resp.status_code == 200, s1_resp.text
        assert s1_resp.json()["status"] == PickupStatus.EXCEPTION.value
        assert s1_resp.json()["ndr_attempt_count"] == 1

        # Resolve Strike 1 using the Bulk NDR Action endpoint
        bulk_resp = await client.post(
            "/api/v1/exceptions/bulk-action",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"action": NdrAction.REATTEMPT.value, "shipment_ids": [order5_id]},
        )
        assert bulk_resp.status_code == 200, bulk_resp.text
        bulk_body = bulk_resp.json()
        assert order5_id in [str(x) for x in bulk_body["succeeded"]]
        assert bulk_body["failed"] == []

        # Strike 2
        s2_resp = await client.patch(
            f"/api/v1/shipments/{order5_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.CONSIGNEE_REFUSED.value,
                "ndr_remark": "Strike 2 - Consignee refused delivery",
            },
        )
        assert s2_resp.status_code == 200, s2_resp.text
        assert s2_resp.json()["status"] == PickupStatus.EXCEPTION.value
        assert s2_resp.json()["ndr_attempt_count"] == 2

        re2_resp = await client.post(
            f"/api/v1/exceptions/{order5_id}/actions",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={"action": NdrAction.REATTEMPT.value},
        )
        assert re2_resp.status_code == 200, re2_resp.text
        assert re2_resp.json()["status"] == PickupStatus.IN_TRANSIT.value

        bal_before_rto = await _get_wallet_balance(b2c_user_id)
        ord5_pre_rto = await _get_shipment(client, accounts, order5_id)
        cost_pre_rto = round(
            float(ord5_pre_rto["payment_details"]["total_logistics_cost"]), 2
        )

        # Strike 3 -> Auto-RTO + RTO surcharge + wallet debit + GST DEBIT_NOTE
        s3_resp = await client.patch(
            f"/api/v1/shipments/{order5_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.EXCEPTION.value,
                "ndr_reason": NdrExceptionReason.CONSIGNEE_UNAVAILABLE.value,
                "ndr_remark": "Strike 3 - Door locked on final 3rd attempt",
            },
        )
        assert s3_resp.status_code == 200, s3_resp.text
        ord5_curr = s3_resp.json()
        cost_post_rto = round(
            float(ord5_curr["payment_details"]["total_logistics_cost"]), 2
        )
        rto_delta = round(cost_post_rto - cost_pre_rto, 2)
        assert rto_delta > 0
        bal_after_rto = await _get_wallet_balance(b2c_user_id)
        assert bal_after_rto == round(bal_before_rto - rto_delta, 2)

        assert ord5_curr["ndr_attempt_count"] == 3
        assert ord5_curr["status"] == PickupStatus.RTO_INITIATED.value
        assert ord5_curr["ndr_reason"] is None

        pd_rto = ord5_curr["payment_details"]
        rto_surcharge = round(
            float((pd_rto.get("pricing_breakdown") or {}).get("rto_surcharge", 0.0)), 2
        )
        assert rto_surcharge > 0, f"Expected rto_surcharge > 0 in pricing_breakdown: {pd_rto}"

        async with GoldenSessionLocal() as session:
            debit_notes = (
                await session.exec(
                    select(BillingInvoice)
                    .where(
                        BillingInvoice.merchant_user_id == uuid.UUID(b2c_user_id),
                        BillingInvoice.note_type == InvoiceNoteType.DEBIT_NOTE.value,
                    )
                    .order_by(BillingInvoice.invoice_number)
                )
            ).all()
        ord5_dns = [
            dn
            for dn in debit_notes
            if any(
                isinstance(item, dict) and item.get("shipment_id") == order5_id
                for item in (dn.line_items or [])
            )
        ]
        assert len(ord5_dns) >= 2, (
            "Expected both the Weight Audit and the Auto-RTO GST DEBIT_NOTEs for Order #5"
        )
        rto_dn = next(
            (dn for dn in ord5_dns if round(float(dn.total_amount), 2) == rto_delta), None
        )
        assert rto_dn is not None, f"No DEBIT_NOTE for the RTO delta {rto_delta}"
        assert rto_dn.invoice_number.startswith(DEBIT_NOTE_PREFIX)
        assert len(rto_dn.invoice_number) <= 16
        STATE["order5_rto_delta"] = rto_delta
        STATE["order5_rto_debit_note"] = rto_dn.invoice_number


def _reverse_payload(
    *,
    label: str,
    product_category: str,
    reason: str,
    qc_notes: str,
    warehouse_id: str,
    pickup: Dict[str, Any],
    package: Dict[str, Any],
    goods_value: float,
) -> Dict[str, Any]:
    """
    Builds a B2C REVERSE (DTO) booking payload. `pickup` is either
    `{"new_pickup_address": <address dict>}` or `{"pickup_address_id": "<id>"}`.
    """
    return {
        "order_reference_id": order_ref(label),
        "shipment_type": "REVERSE",
        "service_type": ServiceType.SURFACE_ROAD.value,
        "requested_pickup_date": date.today().isoformat(),
        "product_category": product_category,
        "reason_for_return": reason,
        "qc_required": True,
        "qc_notes": qc_notes,
        **pickup,
        "delivery_address_id": warehouse_id,
        "packages": [package],
        "payment_details": {
            "freight_payment_mode": "PREPAID",
            "is_cod": False,
            "cod_amount": 0.0,
            "shipment_value": goods_value,
            "shipment_tax_value": 0.0,
            "shipment_total_value": goods_value,
        },
    }


@pytest.mark.asyncio
async def test_j25_b2c_reverse_return_dto_booking_and_g2_forward_reverse_subtabs():
    """
    J25 as `customerb2c@logismart.in`:
    - Books Return #1 (`REVERSE`, `qc_required`, pickup at the customer doorstep `122002`,
      delivery back to the merchant warehouse `122001`) and Return #2 from the SAME doorstep
      address id, so both can share one pickup request (no DB patching).
    - Verifies each booking debits exactly its freight.
    - Verifies the G2 sub-tab filter: `shipment_type=FORWARD` excludes both returns,
      `shipment_type=REVERSE` contains only REVERSE shipments, including both returns.
    """
    accounts = await _load_accounts()
    st = _load_batch2_state()
    warehouse_id = st["warehouse_address_id"]
    b2c_user_id = accounts[CUSTOMER_B2C_EMAIL]["id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Return #1 (Doorstep QC required -> will fail QC in J26)
        bal_before_1 = await _get_wallet_balance(b2c_user_id)
        ret1_resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json=_reverse_payload(
                label="J25-RET1",
                product_category="ELECTRONICS",
                reason="Defective / Damaged Item",
                qc_notes="Check IMEI on box & unbroken brand tag",
                warehouse_id=warehouse_id,
                pickup={
                    "new_pickup_address": {
                        "name": "Aarav Sharma",
                        "phone": "9810099887",
                        "address_line1": "Tower 4, Flat 902, DLF Phase 3",
                        "city": "Gurugram",
                        "state": "Haryana",
                        "pincode": "122002",
                        "country": "IN",
                        "category": "HOME",
                    }
                },
                package={
                    "length": 20.0,
                    "breadth": 15.0,
                    "height": 10.0,
                    "dimension_unit": "CM",
                    "weight": 0.5,
                    "weight_unit": "KG",
                    "box_count": 1,
                    "description": "Returned Wireless ANC Earbuds",
                },
                goods_value=1500.0,
            ),
        )
        assert ret1_resp.status_code == 201, ret1_resp.text
        ret1 = ret1_resp.json()
        ret1_cost = round(float(ret1["payment_details"]["total_logistics_cost"]), 2)
        assert await _get_wallet_balance(b2c_user_id) == round(bal_before_1 - ret1_cost, 2)

        return1_id = ret1["id"]
        return1_pickup_address_id = ret1["pickup_address"]["id"]
        STATE["return1_id"] = return1_id
        STATE["return1_tracking_id"] = ret1["tracking_id"]
        STATE["return1_pickup_address_id"] = return1_pickup_address_id
        assert ret1["shipment_type"] == "REVERSE"
        assert ret1["qc_required"] is True
        assert ret1["qc_notes"] == "Check IMEI on box & unbroken brand tag"
        ret1_pb = ret1["payment_details"].get("pricing_breakdown") or {}
        assert ret1_pb.get("leg") == "REVERSE"
        assert float(ret1_pb.get("base_charge", 0.0)) == 105.0

        # 2. Return #2 from the same doorstep address (passes QC & completes in J26)
        bal_before_2 = await _get_wallet_balance(b2c_user_id)
        ret2_resp = await client.post(
            "/api/v1/shipments",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json=_reverse_payload(
                label="J25-RET2",
                product_category="APPAREL",
                reason="Size / Fit Issue",
                qc_notes="Verify shirt tag intact",
                warehouse_id=warehouse_id,
                pickup={"pickup_address_id": return1_pickup_address_id},
                package={
                    "length": 25.0,
                    "breadth": 20.0,
                    "height": 8.0,
                    "dimension_unit": "CM",
                    "weight": 0.4,
                    "weight_unit": "KG",
                    "box_count": 1,
                    "description": "Returned Cotton Oxford Shirt",
                },
                goods_value=1200.0,
            ),
        )
        assert ret2_resp.status_code == 201, ret2_resp.text
        ret2 = ret2_resp.json()
        ret2_cost = round(float(ret2["payment_details"]["total_logistics_cost"]), 2)
        assert await _get_wallet_balance(b2c_user_id) == round(bal_before_2 - ret2_cost, 2)

        return2_id = ret2["id"]
        STATE["return2_id"] = return2_id
        STATE["return2_tracking_id"] = ret2["tracking_id"]
        STATE["return2_pickup_address_id"] = ret2["pickup_address"]["id"]
        assert ret2["pickup_address"]["id"] == return1_pickup_address_id
        assert ret2["shipment_type"] == "REVERSE"
        assert ret2["qc_required"] is True
        assert ret2["qc_notes"] == "Verify shirt tag intact"

        # 3. G2 Sub-Tabs Filter: FORWARD vs REVERSE
        fwd_resp = await client.get(
            "/api/v1/shipments?is_b2b=false&shipment_type=FORWARD&size=100",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert fwd_resp.status_code == 200, fwd_resp.text
        fwd_items = fwd_resp.json()["items"]
        assert len(fwd_items) >= 3
        assert all(item["shipment_type"] == "FORWARD" for item in fwd_items)
        fwd_ids = {item["id"] for item in fwd_items}
        assert return1_id not in fwd_ids
        assert return2_id not in fwd_ids

        rev_resp = await client.get(
            "/api/v1/shipments?is_b2b=false&shipment_type=REVERSE&size=100",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert rev_resp.status_code == 200, rev_resp.text
        rev_items = rev_resp.json()["items"]
        assert len(rev_items) == 2
        assert all(item["shipment_type"] == "REVERSE" for item in rev_items)
        assert {item["id"] for item in rev_items} == {return1_id, return2_id}


@pytest.mark.asyncio
async def test_j26_reverse_doorstep_qc_fail_g3_vs_pass_to_completed_and_audit_integrity():
    """
    J26:
    - Links Return #1 and Return #2 (same doorstep address) to one B2C PUR (`ASSIGNED`).
    - Return #1 (G3 Fail Doorstep QC): ops marks `QC_FAILED` with a remark -> it
      auto-detaches from the PUR and the timeline logs
      `"Doorstep QC Failed — Return Rejected at Pickup"`.
    - Return #2 (Pass Doorstep QC): ops dispatches the PUR with only Return #2
      (`IN_TRANSIT`); the merchant reads the OTP and ops delivers it (`COMPLETED`).
    - Orders #1 and #3 are still `IN_TRANSIT` with COD intact for Suite 8 (J32).
    - Saves Batch 3 state and verifies `audit-integrity` passes with 0 discrepancies.
    """
    accounts = await _load_accounts()
    _load_batch2_state()
    return1_id = STATE["return1_id"]
    return2_id = STATE["return2_id"]
    ret_pickup_addr_id = STATE["return1_pickup_address_id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        ret1_curr = await _get_shipment(client, accounts, return1_id)
        ret2_curr = await _get_shipment(client, accounts, return2_id)
        assert ret1_curr["status"] == PickupStatus.OPEN.value
        assert ret2_curr["status"] == PickupStatus.OPEN.value

        # 1. One B2C PUR for both returns (same pickup address in 122002)
        pur_rev_resp = await client.post(
            "/api/v1/manifests",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "pickup_address_id": ret_pickup_addr_id,
                "scheduled_date": date.today().isoformat(),
                "time_slot": "14:00 - 18:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "shipment_ids": [return1_id, return2_id],
            },
        )
        assert pur_rev_resp.status_code == 201, pur_rev_resp.text
        pur_rev = pur_rev_resp.json()
        pur_rev_id = pur_rev["id"]
        STATE["pur_rev_id"] = pur_rev_id
        assert pur_rev["status"] == "SCHEDULED"
        assert pur_rev["expected_awbs"] == 2

        # 2. Ops marks Return #1 as QC_FAILED at the doorstep
        qc_fail_resp = await client.patch(
            f"/api/v1/shipments/{return1_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.QC_FAILED.value,
                "comment": "Brand seal broken & wrong item",
                "is_public": True,
            },
        )
        assert qc_fail_resp.status_code == 200, qc_fail_resp.text
        ret1_failed = qc_fail_resp.json()
        assert ret1_failed["status"] == PickupStatus.QC_FAILED.value
        assert ret1_failed["manifest_id"] is None, (
            "QC_FAILED return must auto-detach from its Pickup Request"
        )
        assert ret1_failed["latest_status_comment"] == "Brand seal broken & wrong item"

        # 3. Return #2 passes QC -> PUR dispatched -> IN_TRANSIT -> COMPLETED with OTP
        disp_rev_resp = await client.post(
            f"/api/v1/manifests/{pur_rev_id}/dispatch",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={"picked_shipment_ids": [return2_id]},
        )
        assert disp_rev_resp.status_code == 200, disp_rev_resp.text
        assert disp_rev_resp.json()["status"] == "PICKED"

        async with GoldenSessionLocal() as session:
            db_ret2 = await session.get(PickupRequest, uuid.UUID(return2_id))
            assert db_ret2 is not None
            assert db_ret2.status == PickupStatus.IN_TRANSIT

        ret2_otp = await read_otp_as_merchant(client, accounts, CUSTOMER_B2C_EMAIL, return2_id)
        STATE[f"otp_{return2_id}"] = ret2_otp

        comp_ret2_resp = await client.patch(
            f"/api/v1/shipments/{return2_id}",
            headers=_headers(accounts, OPERATIONS_EMAIL),
            json={
                "status": PickupStatus.COMPLETED.value,
                "delivery_otp": ret2_otp,
                "pod_received_by": "Gurugram Hub Returns Desk",
                "comment": "Return delivered to merchant warehouse after passing doorstep QC",
                "is_public": True,
            },
        )
        assert comp_ret2_resp.status_code == 200, comp_ret2_resp.text
        ret2_completed = comp_ret2_resp.json()
        assert ret2_completed["status"] == PickupStatus.COMPLETED.value
        assert ret2_completed["pod_received_by"] == "Gurugram Hub Returns Desk"

        # Timeline records "Doorstep QC Failed — Return Rejected at Pickup" on Return #1
        tl1_resp = await client.get(
            f"/api/v1/shipments/{return1_id}/timeline",
            headers=_headers(accounts, ADMIN_EMAIL),
        )
        assert tl1_resp.status_code == 200, tl1_resp.text
        summaries1 = [a.get("summary") or "" for a in tl1_resp.json()]
        assert any(
            "Doorstep QC Failed — Return Rejected at Pickup" in s for s in summaries1
        ), f"Expected Doorstep QC Failed summary in {summaries1}"

        # 4. Orders #1 and #3 are still IN_TRANSIT with COD intact for Batch 4 (J32)
        for oid, expected_cod in (
            (STATE["order1_id"], 1500.0),
            (STATE["order3_id"], 2000.0),
        ):
            ord_chk = await _get_shipment(client, accounts, oid)
            assert ord_chk["status"] == PickupStatus.IN_TRANSIT.value
            assert ord_chk["payment_details"]["is_cod"] is True
            assert (
                round(float(ord_chk["payment_details"]["shipment_total_value"]), 2)
                == expected_cod
            )
            assert round(float(ord_chk["payment_details"]["cod_amount"]), 2) >= expected_cod

        # 5. Persist Batch 3 state (namespaced by slug) for Batch 4 (J27-J36)
        save_state(BATCH3_STATE, STATE)

        # 6. Verify System & Wallet Ledger Integrity Audit
        audit_resp = await client.get(
            "/api/v1/wallet/audit-integrity",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert audit_resp.status_code == 200, audit_resp.text
        audit_body = audit_resp.json()
        assert audit_body["passed"] is True, audit_body
        assert audit_body["discrepancy_count"] == 0, audit_body
        assert audit_body["discrepancies"] == []
