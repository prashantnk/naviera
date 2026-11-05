"""
End-to-End API & Database Invariant Suite for Wallet Ledger, Finlock, UPI Maker-Checker,
and 6-Digit OTP Proof of Delivery (POD) on `logismart-test` (rolled back via savepoint).
"""

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.main import app
from app.models.tenants import Tenant, User, UserRole
from app.services.wallet import indian_financial_year_label, today_ist

TEST_MERCHANT_VPA = "wallet-e2e@okaxis"
"""Neutral test UPI ID; a tenant without one has no recharge (no code default)."""
FY = indian_financial_year_label(today_ist())
"""Receipt numbers carry the Indian financial-year code (e.g. `REC-2627-...`)."""


@pytest.mark.asyncio
async def test_wallet_and_otp_e2e_suite(db_session):
    """
    Comprehensive End-to-End API & Database Invariant Suite (T-01 through T-09)
    verifying:
    - T-01: Initial ₹0.00 User Wallet & Multi-User Isolation
    - T-02: DB-Driven Tenant Configuration (wallet_config & pricing_config)
    - T-03: Delhivery-Style Minimum Balance Gate (Finlock)
    - T-04: Zero-Fee UPI Intent/QR Generation & 12-Digit UTR Recharge
    - T-05: UTR Replay / Duplicate Protection (HTTP 409 Conflict)
    - T-06: Automatic Shipment Spend Deduction (SPEND)
    - T-07: Automatic Cancellation Refund (REFUND / Credit Note)
    - T-08: Printable PDF Receipt, GST Freight Invoice, Manifest Run-Sheet & CSV Exports
    - T-09: 6-Digit OTP Proof of Delivery (POD) Verification & Manifest Dispatch
    """
    # Use the pinned `logismart-test` tenant inside the savepoint session (rolled back after test).
    cached_tenant = await app.dependency_overrides[get_tenant_from_header]()
    test_tenant = await db_session.get(Tenant, cached_tenant.id)
    assert test_tenant is not None and test_tenant.slug == "logismart-test"
    test_tenant.settings = {}
    db_session.add(test_tenant)
    await db_session.flush()

    user_owner = User(
        id=uuid.uuid4(),
        supabase_user_id=f"sub-owner-{uuid.uuid4().hex[:8]}",
        email=f"owner_{uuid.uuid4().hex[:6]}@logismart.in",
        role=UserRole.owner,
        is_active=True,
        tenant_id=test_tenant.id,
    )
    user_a = User(
        id=uuid.uuid4(),
        supabase_user_id=f"sub-a-{uuid.uuid4().hex[:8]}",
        email=f"shipper_a_{uuid.uuid4().hex[:6]}@logismart.in",
        role=UserRole.admin,
        is_active=True,
        tenant_id=test_tenant.id,
    )
    user_b = User(
        id=uuid.uuid4(),
        supabase_user_id=f"sub-b-{uuid.uuid4().hex[:8]}",
        email=f"shipper_b_{uuid.uuid4().hex[:6]}@logismart.in",
        role=UserRole.customer,
        is_active=True,
        tenant_id=test_tenant.id,
    )
    db_session.add(user_owner)
    db_session.add(user_a)
    db_session.add(user_b)
    await db_session.flush()

    active_user_ref = {"user": user_a}

    async def override_user():
        return active_user_ref["user"]

    async def override_tenant():
        return test_tenant

    app.dependency_overrides[get_current_active_user] = override_user
    app.dependency_overrides[get_tenant_from_header] = override_tenant

    headers = {"X-Tenant-Slug": test_tenant.slug}

    try:
      async with AsyncClient(
          transport=ASGITransport(app=app), base_url="http://test"
      ) as client:
        # =====================================================================
        # T-01: Initial ₹0.00 User Wallet, No Default VPA (recharge 409) & Multi-User Isolation
        # =====================================================================
        active_user_ref["user"] = user_a
        res_a = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        assert res_a.status_code == 200, res_a.text
        wallet_a = res_a.json()
        assert wallet_a["balance"] == 0.0
        assert wallet_a["wallet_config"]["merchant_vpa"] == ""
        assert wallet_a["wallet_config"]["auto_detect_upi"] is False
        res_no_upi = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/upi-intent",
            json={"amount": 100.0},
            headers=headers,
        )
        assert res_no_upi.status_code == 409, res_no_upi.text
        assert "UPI recharge is not configured" in res_no_upi.json()["detail"]

        # Verify cross-tenant user list isolation (HTTP 403 for random other tenant_id)
        res_cross_tenant = await client.get(
            f"{settings.API_V1_STR}/tenants/{uuid.uuid4()}/users",
            headers=headers,
        )
        assert res_cross_tenant.status_code == 403, res_cross_tenant.text

        active_user_ref["user"] = user_b
        res_b = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        assert res_b.status_code == 200, res_b.text
        wallet_b = res_b.json()
        assert wallet_b["balance"] == 0.0

        # =====================================================================
        # T-02: DB-Driven Tenant Configuration (Tenant.settings)
        # =====================================================================
        active_user_ref["user"] = user_a
        settings_payload = {
            "settings": {
                "wallet_config": {
                    "merchant_vpa": TEST_MERCHANT_VPA,
                    "merchant_name": "Logismart Freight",
                    "min_wallet_balance_b2c": 0.0,
                    "min_wallet_balance_b2b": 500.0,
                    "strict_finlock": True,
                    "auto_detect_upi": True,
                    "auto_detect_delay_seconds": 5,
                    "gstin": "27AABCL9999F1Z2",
                },
                "pricing_policy": {
                    "delhivery_markup_percent": 0.0,
                    "prime_default_markup_percent": 20.0,
                    "cod_fee_percent": 2.0,
                    "cod_fee_min": 1.0,
                    "enabled_options": [
                        "DELHIVERY_SURFACE",
                        "DELHIVERY_EXPRESS",
                        "PRIME_SURFACE",
                    ],
                },
            }
        }
        res_cfg = await client.patch(
            f"{settings.API_V1_STR}/tenants/settings",
            json=settings_payload,
            headers=headers,
        )
        assert res_cfg.status_code == 200, res_cfg.text
        updated_tenant_json = res_cfg.json()
        assert (
            updated_tenant_json["settings"]["wallet_config"]["merchant_vpa"]
            == TEST_MERCHANT_VPA
        )
        assert (
            updated_tenant_json["settings"]["pricing_policy"][
                "delhivery_markup_percent"
            ]
            == 0.0
        )

        # Verify QuoteService honors the new DB pricing_policy
        rate_req = {
            "service_flow": "B2C",
            "pickup_pincode": "400001",
            "delivery_pincode": "411001",
            "shipment_type": "FORWARD",
            "packages": [
                {
                    "length": 20.0,
                    "breadth": 20.0,
                    "height": 20.0,
                    "weight": 2.0,
                    "box_count": 1,
                }
            ],
            "is_cod": False,
            "cod_amount": 0.0,
            "shipment_value": 5000.0,
        }
        res_rate = await client.post(
            f"{settings.API_V1_STR}/quotes",
            json=rate_req,
            headers=headers,
        )
        assert res_rate.status_code == 200, res_rate.text
        opts = {
            o["service_option"]: o for o in res_rate.json()["options"]
        }
        rate_data = opts["DELHIVERY_SURFACE"]
        assert rate_data["freight_amount"] == 135.0
        assert rate_data["tax_amount"] == 24.3
        assert rate_data["total_amount"] == 159.3

        # =====================================================================
        # T-03: Delhivery-Style Minimum Balance Gate (Finlock)
        # =====================================================================
        shipment_payload = {
            "order_reference_id": f"ORD-{uuid.uuid4().hex[:6].upper()}",
            "shipment_type": "FORWARD",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "10:00 - 14:00",
            "product_category": "ELECTRONICS",
            "new_pickup_address": {
                "name": "Mumbai Hub",
                "phone": "9876543210",
                "address_line1": "Andheri East",
                "city": "Mumbai",
                "state": "MH",
                "pincode": "400001",
            },
            "new_delivery_address": {
                "name": "Pune Consignee",
                "phone": "9123456780",
                "address_line1": "Hinjewadi Phase 1",
                "city": "Pune",
                "state": "MH",
                "pincode": "411001",
            },
            "packages": [
                {
                    "length": 20.0,
                    "breadth": 20.0,
                    "height": 20.0,
                    "weight": 2.0,
                    "box_count": 1,
                    "description": "Laptop",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "PREPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_total_value": 5000.0,
            },
        }

        res_finlock = await client.post(
            f"{settings.API_V1_STR}/shipments",
            json=shipment_payload,
            headers=headers,
        )
        assert res_finlock.status_code == 400, res_finlock.text
        assert "Insufficient wallet balance" in res_finlock.text

        # =====================================================================
        # T-04: Zero-Fee UPI Intent/QR Generation, Auto-Detection & Manual UTR
        # =====================================================================
        res_upi = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/upi-intent",
            json={"amount": 1000.0},
            headers=headers,
        )
        assert res_upi.status_code == 200, res_upi.text
        upi_data = res_upi.json()
        assert upi_data["merchant_vpa"] == TEST_MERCHANT_VPA
        assert upi_data["upi_uri"].startswith("upi://pay?pa=wallet-e2e%40okaxis")
        assert f"&tr=REC-{FY}-" in upi_data["upi_uri"]
        assert upi_data["qr_svg_data_url"].startswith(
            "data:image/svg+xml;base64,"
        )
        txn_id = upi_data["transaction_id"]

        # Verify passive status poll (even with ?auto_complete=true) stays PENDING
        res_pending = await client.get(
            f"{settings.API_V1_STR}/wallet/recharge/{txn_id}/status?auto_complete=true",
            headers=headers,
        )
        assert res_pending.status_code == 200, res_pending.text
        assert res_pending.json()["status"] == "PENDING"

        # Verify unpaid PENDING intent cannot generate an official Receipt PDF (HTTP 400)
        res_unpaid_pdf = await client.get(
            f"{settings.API_V1_STR}/wallet/transactions/{txn_id}/receipt-pdf",
            headers=headers,
        )
        assert res_unpaid_pdf.status_code == 400, res_unpaid_pdf.text

        # Verify maker-checker: user_a (Admin) cannot self-verify their own QR intent (403)
        tamper_utr = str(uuid.uuid4().int)[:12]
        res_self_verify = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/verify-utr",
            json={
                "transaction_id": txn_id,
                "amount": 1000.0,
                "utr_number": tamper_utr,
            },
            headers=headers,
        )
        assert res_self_verify.status_code == 403, res_self_verify.text

        # Switch to Owner (`user_owner`) to verify amount tampering and complete `user_a`'s intent
        active_user_ref["user"] = user_owner
        res_tamper = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/verify-utr",
            json={
                "transaction_id": txn_id,
                "amount": 50000.0,
                "utr_number": tamper_utr,
            },
            headers=headers,
        )
        assert res_tamper.status_code == 400, res_tamper.text
        assert "mismatch" in res_tamper.text.lower()

        # Verify 12-Digit UTR verification by Owner completes `user_a`'s ₹1,000.00 QR intent
        unique_utr_1 = str(uuid.uuid4().int)[:12]
        res_utr_1 = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/verify-utr",
            json={
                "transaction_id": txn_id,
                "amount": 1000.0,
                "utr_number": unique_utr_1,
            },
            headers=headers,
        )
        assert res_utr_1.status_code == 200, res_utr_1.text
        auto_data = res_utr_1.json()
        assert auto_data["balance"] == 1000.0
        assert auto_data["transaction"]["status"] == "COMPLETED"
        assert auto_data["transaction"]["utr_number"] == unique_utr_1

        # Also test second recharge (₹500.0 -> total ₹1500.0)
        active_user_ref["user"] = user_a
        res_upi_2 = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/upi-intent",
            json={"amount": 500.0},
            headers=headers,
        )
        assert res_upi_2.status_code == 200, res_upi_2.text
        txn_id_2 = res_upi_2.json()["transaction_id"]

        active_user_ref["user"] = user_owner
        unique_utr = str(uuid.uuid4().int)[:12]
        res_utr = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/verify-utr",
            json={
                "transaction_id": txn_id_2,
                "amount": 500.0,
                "utr_number": unique_utr,
            },
            headers=headers,
        )
        assert res_utr.status_code == 200, res_utr.text
        utr_data = res_utr.json()
        assert utr_data["balance"] == 1500.0
        assert utr_data["transaction"]["status"] == "COMPLETED"
        assert utr_data["transaction"]["receipt_number"].startswith(f"REC-{FY}-")

        # Verify User B's wallet is still ₹0.00 (Multi-User Isolation) and test Maker-Checker flow:
        # 1. User B generates QR intent -> skipping UTR returns 400 (A-14) -> submitting 12-digit UTR stays PENDING (pending_recharge = ₹100.00)
        # 2. Customer cannot self-approve (HTTP 403)
        # 3. Admin sees it in GET /wallet/admin/pending-recharges and approves it -> merges ₹100.00 into User B's main balance!
        active_user_ref["user"] = user_b
        res_b_after = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        assert res_b_after.json()["balance"] == 0.0
        assert res_b_after.json()["summary"]["pending_recharge"] == 0.0

        res_b_intent = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/upi-intent",
            json={"amount": 100.0},
            headers=headers,
        )
        b_txn_id = res_b_intent.json()["transaction_id"]

        # Before clicking "I Have Paid", abandoned QR intent does not count as pending_recharge
        res_b_before_paid = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        assert res_b_before_paid.json()["summary"]["pending_recharge"] == 0.0

        # A-14: User B clicking "I Have Paid" without a 12-digit UTR is rejected (400)
        res_b_no_utr = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/{b_txn_id}/confirm",
            json={},
            headers=headers,
        )
        assert res_b_no_utr.status_code == 400, res_b_no_utr.text

        b_utr = str(uuid.uuid4().int)[:12]
        res_b_paid = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/{b_txn_id}/confirm",
            json={"utr_number": b_utr},
            headers=headers,
        )
        assert res_b_paid.status_code == 200, res_b_paid.text
        b_paid_json = res_b_paid.json()
        assert b_paid_json["status"] == "PENDING"
        assert b_paid_json["balance"] == 0.0
        assert b_paid_json["transaction"]["utr_number"] == b_utr

        # User B now sees ₹100.00 in Pending Approval while main balance remains ₹0.00
        res_b_pending = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        assert res_b_pending.json()["balance"] == 0.0
        assert res_b_pending.json()["summary"]["pending_recharge"] == 100.0

        # Customer cannot self-approve their pending recharge (HTTP 403)
        res_b_self_approve = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/{b_txn_id}/approve",
            headers=headers,
        )
        assert res_b_self_approve.status_code == 403, res_b_self_approve.text

        # Switch to Admin (user_a) -> inspect pending queue and approve User B's ₹100.00 recharge
        active_user_ref["user"] = user_a
        res_admin_queue = await client.get(
            f"{settings.API_V1_STR}/wallet/admin/pending-recharges",
            headers=headers,
        )
        assert res_admin_queue.status_code == 200, res_admin_queue.text
        queue_items = res_admin_queue.json()
        assert any(
            item["id"] == b_txn_id and item["user_email"] == user_b.email
            for item in queue_items
        )

        res_admin_approve = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/{b_txn_id}/approve",
            headers=headers,
        )
        assert res_admin_approve.status_code == 200, res_admin_approve.text
        approved_json = res_admin_approve.json()
        assert approved_json["status"] == "COMPLETED"
        assert approved_json["balance"] == 100.0

        # Verify User B's pending ₹100.00 is now merged into main balance (balance = ₹100.00, pending = ₹0.00)
        active_user_ref["user"] = user_b
        res_b_merged = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        assert res_b_merged.json()["balance"] == 100.0
        assert res_b_merged.json()["summary"]["pending_recharge"] == 0.0
        active_user_ref["user"] = user_a

        # =====================================================================
        # T-05: UTR Replay / Duplicate Protection (HTTP 409 Conflict)
        # =====================================================================
        res_dup = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/verify-utr",
            json={"amount": 500.0, "utr_number": unique_utr},
            headers=headers,
        )
        assert res_dup.status_code == 409, res_dup.text

        # =====================================================================
        # T-06: Automatic Shipment Spend Deduction (SPEND)
        # =====================================================================
        res_book = await client.post(
            f"{settings.API_V1_STR}/shipments",
            json=shipment_payload,
            headers=headers,
        )
        assert res_book.status_code == 201, res_book.text
        booked_shipment = res_book.json()
        booked_id = booked_shipment["id"]
        logistics_cost = booked_shipment["payment_details"][
            "total_logistics_cost"
        ]
        assert logistics_cost == 159.3  # 135.0 base * 1.18 = 159.30

        res_wallet_after_book = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        expected_balance = round(1500.0 - logistics_cost, 2)
        assert res_wallet_after_book.json()["balance"] == expected_balance

        res_spends = await client.get(
            f"{settings.API_V1_STR}/wallet/transactions?tab=spends&user_id={user_a.id}",
            headers=headers,
        )
        assert res_spends.status_code == 200
        spend_items = res_spends.json()["items"]
        assert len(spend_items) == 1
        assert spend_items[0]["txn_type"] == "SPEND"
        assert spend_items[0]["shipment_id"] == booked_id

        # =====================================================================
        # T-07: Automatic Cancellation Refund (REFUND / Credit Note)
        # =====================================================================
        res_cancel = await client.post(
            f"{settings.API_V1_STR}/shipments/{booked_id}/cancel",
            headers=headers,
        )
        assert res_cancel.status_code == 200, res_cancel.text
        assert res_cancel.json()["status"] == "CANCELLED"

        res_wallet_after_cancel = await client.get(
            f"{settings.API_V1_STR}/wallet", headers=headers
        )
        assert res_wallet_after_cancel.json()["balance"] == 1500.0

        res_spends_after = await client.get(
            f"{settings.API_V1_STR}/wallet/transactions?tab=spends&user_id={user_a.id}",
            headers=headers,
        )
        txns_after = res_spends_after.json()["items"]
        assert any(
            t["txn_type"] == "REFUND"
            and t["receipt_number"].startswith(f"CN-{FY}-")
            for t in txns_after
        )

        # =====================================================================
        # T-08: Printable PDF Receipt, Freight Invoice & CSV Exports
        # =====================================================================
        res_rec_pdf = await client.get(
            f"{settings.API_V1_STR}/wallet/transactions/{txn_id}/receipt-pdf",
            headers=headers,
        )
        assert res_rec_pdf.status_code == 200
        assert res_rec_pdf.content.startswith(b"%PDF-1.")

        # The shipment is CANCELLED at this point: no GST invoice is issued
        # (the refund credit-note receipt above is the merchant's document).
        res_inv_pdf = await client.get(
            f"{settings.API_V1_STR}/shipments/{booked_id}/invoice-pdf",
            headers=headers,
        )
        assert res_inv_pdf.status_code == 400, res_inv_pdf.text

        res_csv = await client.get(
            f"{settings.API_V1_STR}/wallet/export/csv",
            headers=headers,
        )
        assert res_csv.status_code == 200
        assert "Receipt / Invoice No" in res_csv.text

        # =====================================================================
        # T-09: 6-Digit OTP Proof of Delivery (POD) & Manifest Dispatch
        # =====================================================================
        shipment_payload["order_reference_id"] = f"POD-{uuid.uuid4().hex[:6]}"
        res_pod_ship = await client.post(
            f"{settings.API_V1_STR}/shipments",
            json=shipment_payload,
            headers=headers,
        )
        assert res_pod_ship.status_code == 201, res_pod_ship.text
        pod_ship = res_pod_ship.json()
        pod_ship_id = pod_ship["id"]
        pickup_addr_id = pod_ship["pickup_address"]["id"]

        # Move DRAFT -> OPEN
        res_open = await client.patch(
            f"{settings.API_V1_STR}/shipments/{pod_ship_id}",
            json={"status": "OPEN", "comment": "Ready for pickup"},
            headers=headers,
        )
        assert res_open.status_code == 200

        # Create Manifest & Dispatch ("Mark Picked Up")
        res_man = await client.post(
            f"{settings.API_V1_STR}/manifests",
            json={
                "pickup_address_id": pickup_addr_id,
                "scheduled_date": str(date.today()),
                "time_slot": "10:00 - 14:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "total_boxes": 1,
                "shipment_ids": [pod_ship_id],
            },
            headers=headers,
        )
        assert res_man.status_code == 201, res_man.text
        manifest_json = res_man.json()
        manifest_id = manifest_json["id"]
        manifest_otp = manifest_json["pickup_otp"]
        assert manifest_otp is not None and len(manifest_otp) == 6 and manifest_otp.isdigit()

        # Download Manifest Run-Sheet PDF
        res_man_pdf = await client.get(
            f"{settings.API_V1_STR}/manifests/{manifest_id}/pdf",
            headers=headers,
        )
        assert res_man_pdf.status_code == 200
        assert res_man_pdf.content.startswith(b"%PDF-1.")

        # Verify Customer (User B) cannot see User A's manifest or dispatch fleet pickup trucks (HTTP 403)
        active_user_ref["user"] = user_b
        res_b_manifests = await client.get(
            f"{settings.API_V1_STR}/manifests",
            headers=headers,
        )
        assert res_b_manifests.status_code == 200, res_b_manifests.text
        assert all(m["id"] != manifest_id for m in res_b_manifests.json())

        res_b_disp_forbidden = await client.post(
            f"{settings.API_V1_STR}/manifests/{manifest_id}/dispatch",
            headers=headers,
        )
        assert res_b_disp_forbidden.status_code == 403, res_b_disp_forbidden.text

        # Switch back to Admin (User A) to Dispatch Manifest -> transitions shipment to IN_TRANSIT and generates 6-digit delivery_otp
        active_user_ref["user"] = user_a
        res_disp = await client.post(
            f"{settings.API_V1_STR}/manifests/{manifest_id}/dispatch",
            json={"pickup_otp": manifest_otp},
            headers=headers,
        )
        assert res_disp.status_code == 200, res_disp.text
        assert res_disp.json()["status"] in ("PICKED", "COMPLETED")

        # Fetch shipment to inspect generated 6-digit delivery_otp
        res_detail = await client.get(
            f"{settings.API_V1_STR}/shipments/{pod_ship_id}",
            headers=headers,
        )
        assert res_detail.status_code == 200
        detail_json = res_detail.json()
        assert detail_json["status"] == "IN_TRANSIT"
        generated_otp = detail_json["delivery_otp"]
        assert generated_otp is not None and len(generated_otp) == 6 and generated_otp.isdigit()

        # Attempt COMPLETED with WRONG OTP -> must fail with HTTP 400
        wrong_otp = "000000" if generated_otp != "000000" else "999999"
        res_wrong_otp = await client.patch(
            f"{settings.API_V1_STR}/shipments/{pod_ship_id}",
            json={
                "status": "COMPLETED",
                "delivery_otp": wrong_otp,
                "pod_received_by": "Rahul Sharma",
                "comment": "Delivered at reception",
            },
            headers=headers,
        )
        assert res_wrong_otp.status_code == 400, res_wrong_otp.text
        assert "Invalid 6-digit Delivery OTP" in res_wrong_otp.text

        # Submit VALID 6-digit OTP -> succeeds with 200 and records OTP Verified POD
        res_valid_otp = await client.patch(
            f"{settings.API_V1_STR}/shipments/{pod_ship_id}",
            json={
                "status": "COMPLETED",
                "delivery_otp": generated_otp,
                "pod_received_by": "Rahul Sharma",
                "comment": "Handed over to receiver",
                "is_public": True,
            },
            headers=headers,
        )
        assert res_valid_otp.status_code == 200, res_valid_otp.text
        completed_json = res_valid_otp.json()
        assert completed_json["status"] == "COMPLETED"
        assert completed_json["pod_received_by"] == "Rahul Sharma"

        # Verify public tracking timeline shows OTP Verified
        res_track = await client.get(
            f"{settings.API_V1_STR}/tracking/{completed_json['tracking_id']}",
            headers=headers,
        )
        assert res_track.status_code == 200, res_track.text
        track_json = res_track.json()
        assert track_json["pod_received_by"] == "R*** S***"  # masked on the public page
        assert any(
            "OTP Verified" in (ev.get("status_title") or "")
            for ev in track_json["timeline"]
        )

        # =====================================================================
        # T-10: Delhivery ServiceScope Segmentation & B2C Reverse (DTO) Flow
        # =====================================================================
        # 1. Verify User B defaults to ServiceScope.B2C
        active_user_ref["user"] = user_b
        res_me_b = await client.get(
            f"{settings.API_V1_STR}/users/me",
            headers=headers,
        )
        assert res_me_b.status_code == 200, res_me_b.text
        assert res_me_b.json()["service_scope"] == "B2C"

        # 2. Admin (User A) updates User B's service_scope -> B2B -> BOTH -> B2C
        active_user_ref["user"] = user_a
        for target_scope in ("B2B", "BOTH", "B2C"):
            res_scope = await client.patch(
                f"{settings.API_V1_STR}/users/{user_b.id}",
                json={"service_scope": target_scope},
                headers=headers,
            )
            assert res_scope.status_code == 200, res_scope.text
            assert res_scope.json()["service_scope"] == target_scope

        # 3. Book a B2C Reverse Return (DTO) Shipment with Doorstep QC enabled
        reverse_payload = {
            "order_reference_id": f"RET-{uuid.uuid4().hex[:6].upper()}",
            "shipment_type": "REVERSE",
            "service_type": "SURFACE_ROAD",
            "requested_pickup_date": str(date.today()),
            "pickup_time_slot": "10:00 - 14:00",
            "product_category": "ELECTRONICS",
            "reason_for_return": "Defective / Damaged Item",
            "qc_required": True,
            "qc_notes": "Check serial number and unbroken brand seal",
            "new_pickup_address": {
                "name": "Pune Customer Return",
                "phone": "9123456780",
                "address_line1": "Hinjewadi Phase 1",
                "city": "Pune",
                "state": "MH",
                "pincode": "411001",
            },
            "new_delivery_address": {
                "name": "Mumbai Origin Warehouse",
                "phone": "9876543210",
                "address_line1": "Andheri East",
                "city": "Mumbai",
                "state": "MH",
                "pincode": "400001",
            },
            "packages": [
                {
                    "length": 20.0,
                    "breadth": 20.0,
                    "height": 20.0,
                    "weight": 2.0,
                    "box_count": 1,
                    "description": "Returned Laptop",
                }
            ],
            "payment_details": {
                "freight_payment_mode": "PREPAID",
                "is_cod": False,
                "cod_amount": 0.0,
                "shipment_total_value": 5000.0,
            },
        }
        res_rev = await client.post(
            f"{settings.API_V1_STR}/shipments",
            json=reverse_payload,
            headers=headers,
        )
        assert res_rev.status_code == 201, res_rev.text
        rev_json = res_rev.json()
        rev_id = rev_json["id"]
        assert rev_json["shipment_type"] == "REVERSE"
        assert rev_json["reason_for_return"] == "Defective / Damaged Item"
        assert rev_json["qc_required"] is True
        assert rev_json["qc_notes"] == "Check serial number and unbroken brand seal"

        # 4. Verify B2C list filter (is_b2b=false) includes the Reverse shipment
        res_b2c_list = await client.get(
            f"{settings.API_V1_STR}/shipments?page=1&size=50&is_b2b=false",
            headers=headers,
        )
        assert res_b2c_list.status_code == 200, res_b2c_list.text
        b2c_ids = [item["id"] for item in res_b2c_list.json()["items"]]
        assert rev_id in b2c_ids

        # 5. Cancel Reverse shipment and verify automatic wallet refund
        res_rev_cancel = await client.post(
            f"{settings.API_V1_STR}/shipments/{rev_id}/cancel",
            headers=headers,
        )
        assert res_rev_cancel.status_code == 200, res_rev_cancel.text
        assert res_rev_cancel.json()["status"] == "CANCELLED"
    finally:
        pass


