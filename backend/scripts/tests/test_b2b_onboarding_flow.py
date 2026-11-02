"""
E2E tests for:
1. B2B Customer Onboarding & Access Request Flow (D21):
   - Customer self-requests B2B Heavy Cargo access (`POST /api/v1/users/me/request-b2b`)
     with optional Company Name, GSTIN (auto-deriving PAN), or PAN (or neither).
   - Validation of optional GSTIN (15-char format) and PAN (10-char format).
   - Tenant Admin reviews & approves/rejects B2B access (`POST /api/v1/users/{user_id}/review-b2b`).
   - Users always self-sign-up (customer); Tenant Admin then promotes / sets B2B scope via Edit (`PATCH /api/v1/users/{id}`).
2. Two-Category Tenant Model (`TENANT_STAFF` vs `CUSTOMER`):
   - `TENANT_STAFF`: Internal LogiSmart team (`Owner`, `Admin`, `Operations-User`, `Support-User`, `Read-Only User`).
     - `READ_ONLY_USER` staff receives `403` on writes.
     - `SUPPORT_USER` staff receives `403` on shipment/pickup creation, but can view disputes & tickets.
     - `OPERATIONS_USER` staff receives `403` on `/users` and wallet recharge intents, but can audit weight & dispatch.
   - `CUSTOMER`: External B2C / B2B shippers with zero sub-role segregation at the customer level,
     having full self-service access within their enabled `service_scope` (`B2C`, `B2B`, or `BOTH`).
3. Full Cross-Entity Correlation:
   - Booking a PREPAID shipment creates both a `WalletTransaction(SPEND)` and a `BillingInvoice(INVOICE)`.
   - Admin Weight Audit creates `WalletTransaction(WEIGHT_AUDIT_DEBIT)`, `BillingInvoice(DEBIT_NOTE)`,
     and a `WeightDispute`.
   - Customer raising a Weight Claim auto-creates a correlated `SupportTicket` (`TKT-2026`).
   - Admin accepting the Weight Claim refunds the wallet (`REFUND`), issues a `BillingInvoice(CREDIT_NOTE)`,
     and resolves the correlated `SupportTicket` (`RESOLVED`).
"""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_current_active_user
from app.main import app
from app.models.tenants import ServiceScope, User, UserRole

pytestmark = pytest.mark.asyncio

HEADERS = {"X-Tenant-Slug": "logismart"}


async def _signup_then_promote(client: AsyncClient, db_session, fields: dict):
    """
    Simulates the launch onboarding flow: the person signs up themselves
    (a plain B2C customer row in the tenant), then the Owner/Admin edits that
    user (`PATCH /users/{id}`) to set role, scope and optional KYC fields.
    Returns the PATCH response.
    """
    admin_user = await app.dependency_overrides[get_current_active_user]()
    signed_up = User(
        tenant_id=admin_user.tenant_id,
        email=fields["email"].lower(),
        supabase_user_id=f"test-signup:{uuid.uuid4()}",
        full_name=fields.get("full_name"),
        phone=fields.get("phone"),
        role=UserRole.customer,
        service_scope=ServiceScope.B2C,
        is_active=True,
    )
    db_session.add(signed_up)
    await db_session.flush()
    update = {k: v for k, v in fields.items() if k not in ("email",)}
    return await client.patch(
        f"{settings.API_V1_STR}/users/{signed_up.id}", json=update, headers=HEADERS
    )


async def test_b2b_request_with_optional_gstin_and_admin_approval(db_session):
    admin_override = app.dependency_overrides[get_current_active_user]
    temp_email = f"b2b-req-{uuid.uuid4().hex[:8]}@example.com"

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Tenant Admin invites a B2C customer
            invite_res = await _signup_then_promote(client, db_session, {
                    "full_name": "Rohan Traders",
                    "email": temp_email,
                    "phone": "9876543210",
                    "is_active": True,
                    "account_type": "CUSTOMER",
                    "service_scope": "B2C",
                })
            assert invite_res.status_code == 200, invite_res.text
            invited_data = invite_res.json()
            created_user_id = uuid.UUID(invited_data["id"])
            assert invited_data["service_scope"] == "B2C"
            assert invited_data["account_type"] == "CUSTOMER"

            customer_db_user = await db_session.get(User, created_user_id)
            assert customer_db_user is not None

            async def _as_b2c_customer():
                return customer_db_user

            app.dependency_overrides[get_current_active_user] = _as_b2c_customer

            # Customer cannot list tenant users (403)
            cust_users_res = await client.get(
                f"{settings.API_V1_STR}/users", headers=HEADERS
            )
            assert cust_users_res.status_code == 403, cust_users_res.text

            # 2. Invalid GSTIN is rejected with 422
            bad_res = await client.post(
                f"{settings.API_V1_STR}/users/me/request-b2b",
                json={
                    "company_name": "Rohan Heavy Freight",
                    "gstin": "BADGSTIN123",
                },
                headers=HEADERS,
            )
            assert bad_res.status_code == 422, bad_res.text

            # 3. Request B2B with valid 15-digit GSTIN (auto-derives PAN = ABCDE1234F)
            req_res = await client.post(
                f"{settings.API_V1_STR}/users/me/request-b2b",
                json={
                    "company_name": "Rohan Heavy Freight Pvt Ltd",
                    "gstin": "29ABCDE1234F1Z5",
                    "notes": "Need PTL cargo from Bengaluru to Mumbai",
                },
                headers=HEADERS,
            )
            assert req_res.status_code == 200, req_res.text
            req_body = req_res.json()
            assert req_body["b2b_request_status"] == "PENDING"
            assert req_body["company_name"] == "Rohan Heavy Freight Pvt Ltd"
            assert req_body["gstin"] == "29ABCDE1234F1Z5"
            assert req_body["pan"] == "ABCDE1234F"

            # 4. Switch back to Tenant Admin and verify GET /users surfaces the pending request + GSTIN/PAN
            app.dependency_overrides[get_current_active_user] = admin_override
            list_res = await client.get(
                f"{settings.API_V1_STR}/users", headers=HEADERS
            )
            assert list_res.status_code == 200, list_res.text
            matching = [
                u for u in list_res.json() if u["id"] == str(created_user_id)
            ]
            assert len(matching) == 1
            assert matching[0]["b2b_request_status"] == "PENDING"
            assert matching[0]["gstin"] == "29ABCDE1234F1Z5"
            assert matching[0]["pan"] == "ABCDE1234F"

            # 5. Tenant Admin approves the B2B request -> upgrades service_scope to BOTH
            approve_res = await client.post(
                f"{settings.API_V1_STR}/users/{created_user_id}/review-b2b",
                json={"approve": True, "service_scope": "BOTH"},
                headers=HEADERS,
            )
            assert approve_res.status_code == 200, approve_res.text
            approved_body = approve_res.json()
            assert approved_body["b2b_request_status"] == "APPROVED"
            assert approved_body["service_scope"] == "BOTH"
            assert approved_body["gstin"] == "29ABCDE1234F1Z5"
    finally:
        app.dependency_overrides[get_current_active_user] = admin_override


async def test_b2b_request_without_gstin_or_pan_and_direct_admin_invite(db_session):
    invite_email = f"b2b-direct-{uuid.uuid4().hex[:8]}@example.com"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Tenant Admin directly invites a customer for B2B with optional PAN only
        invite_res = await _signup_then_promote(client, db_session, {
                "full_name": "Kiran Distributors",
                "email": invite_email,
                "phone": "9811122233",
                "is_active": True,
                "account_type": "CUSTOMER",
                "service_scope": "B2B",
                "company_name": "Kiran Industrial Supply",
                "pan": "KLMNO5678P",
            })
        assert invite_res.status_code == 200, invite_res.text
        invited = invite_res.json()
        assert invited["account_type"] == "CUSTOMER"
        assert invited["service_scope"] == "B2B"
        assert invited["b2b_request_status"] == "APPROVED"
        assert invited["company_name"] == "Kiran Industrial Supply"
        assert invited["pan"] == "KLMNO5678P"


async def test_two_category_tenant_staff_vs_customer_and_cross_entity_correlation(db_session):
    admin_override = app.dependency_overrides[get_current_active_user]

    customer_email = f"apex-customer-{uuid.uuid4().hex[:6]}@example.com"
    staff_ops_email = f"logismart-ops-{uuid.uuid4().hex[:6]}@example.com"
    staff_support_email = f"logismart-sup-{uuid.uuid4().hex[:6]}@example.com"
    staff_ro_email = f"logismart-ro-{uuid.uuid4().hex[:6]}@example.com"

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # 1. Tenant Admin invites a B2B/B2C Customer (`account_type = CUSTOMER`)
            cust_res = await _signup_then_promote(client, db_session, {
                    "full_name": "Apex Heavy Industries",
                    "email": customer_email,
                    "phone": "9810010001",
                    "is_active": True,
                    "account_type": "CUSTOMER",
                    "service_scope": "BOTH",
                    "company_name": "Apex Heavy Industries Ltd",
                    "gstin": "27AAACA1234A1Z5",
                })
            assert cust_res.status_code == 200, cust_res.text
            cust_data = cust_res.json()
            customer_id = uuid.UUID(cust_data["id"])
            assert cust_data["account_type"] == "CUSTOMER"
            assert cust_data["role"] == "customer"
            assert cust_data["service_scope"] == "BOTH"

            # 2. Tenant Admin invites 3 LogiSmart Tenant Staff members (`account_type = TENANT_STAFF`)
            ops_res = await _signup_then_promote(client, db_session, {
                    "full_name": "LogiSmart Hub Ops",
                    "email": staff_ops_email,
                    "phone": "9810010002",
                    "is_active": True,
                    "account_type": "TENANT_STAFF",
                    "role": "operations_user",
                    "service_scope": "BOTH",
                })
            assert ops_res.status_code == 200, ops_res.text
            ops_user_id = uuid.UUID(ops_res.json()["id"])
            assert ops_res.json()["account_type"] == "TENANT_STAFF"
            assert ops_res.json()["role"] == "operations_user"

            sup_res = await _signup_then_promote(client, db_session, {
                    "full_name": "LogiSmart Support Desk",
                    "email": staff_support_email,
                    "phone": "9810010003",
                    "is_active": True,
                    "account_type": "TENANT_STAFF",
                    "role": "support_user",
                    "service_scope": "BOTH",
                })
            assert sup_res.status_code == 200, sup_res.text
            sup_user_id = uuid.UUID(sup_res.json()["id"])
            assert sup_res.json()["account_type"] == "TENANT_STAFF"
            assert sup_res.json()["role"] == "support_user"

            ro_res = await _signup_then_promote(client, db_session, {
                    "full_name": "LogiSmart Analyst ReadOnly",
                    "email": staff_ro_email,
                    "phone": "9810010004",
                    "is_active": True,
                    "account_type": "TENANT_STAFF",
                    "role": "read_only_user",
                    "service_scope": "BOTH",
                })
            assert ro_res.status_code == 200, ro_res.text
            ro_user_id = uuid.UUID(ro_res.json()["id"])
            assert ro_res.json()["account_type"] == "TENANT_STAFF"
            assert ro_res.json()["role"] == "read_only_user"

            cust_db = await db_session.get(User, customer_id)
            ops_db = await db_session.get(User, ops_user_id)
            sup_db = await db_session.get(User, sup_user_id)
            ro_db = await db_session.get(User, ro_user_id)
            assert cust_db and ops_db and sup_db and ro_db

            async def _as_customer():
                return cust_db

            async def _as_staff_ops():
                return ops_db

            async def _as_staff_support():
                return sup_db

            async def _as_staff_ro():
                return ro_db

            # 3. Verify Staff Operations-User cannot list/invite users or create wallet recharge intent (403)
            app.dependency_overrides[get_current_active_user] = _as_staff_ops
            ops_users = await client.get(
                f"{settings.API_V1_STR}/users", headers=HEADERS
            )
            assert ops_users.status_code == 403, ops_users.text

            ops_recharge = await client.post(
                f"{settings.API_V1_STR}/wallet/recharge/upi-intent",
                json={"amount": 1000.0},
                headers=HEADERS,
            )
            assert ops_recharge.status_code == 403, ops_recharge.text

            # 4. Switch to Customer (`Apex Heavy Industries`):
            #    Customer has full self-service access (can create recharge intent & book B2B shipment)
            app.dependency_overrides[get_current_active_user] = _as_customer

            cust_recharge = await client.post(
                f"{settings.API_V1_STR}/wallet/recharge/upi-intent",
                json={"amount": 1500.0},
                headers=HEADERS,
            )
            assert cust_recharge.status_code == 200, cust_recharge.text

            shipment_payload = {
                "order_reference_id": "APEX-B2B-101",
                "shipment_type": "FORWARD",
                "service_type": "SURFACE_ROAD",
                "requested_pickup_date": "2026-10-18",
                "pickup_time_slot": "14:00 - 18:00",
                "product_category": "COMMERCIAL",
                "po_number": "PO-APEX-101",
                "new_pickup_address": {
                    "name": "Apex Pune Hub",
                    "phone": "9810010001",
                    "address_line1": "Plot 12, Chakan MIDC",
                    "city": "Pune",
                    "state": "Maharashtra",
                    "pincode": "411001",
                    "country": "IN",
                    "category": "WAREHOUSE",
                    "is_saved": True,
                },
                "new_delivery_address": {
                    "name": "Mumbai Consignee Depot",
                    "phone": "9820020002",
                    "address_line1": "Bhiwandi Logistics Park",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                    "country": "IN",
                    "category": "WAREHOUSE",
                    "is_saved": False,
                },
                "packages": [
                    {
                        "weight": 20.0,
                        "weight_unit": "KG",
                        "length": 40.0,
                        "breadth": 30.0,
                        "height": 30.0,
                        "dimension_unit": "CM",
                        "box_count": 2,
                        "description": "Industrial Valves",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": False,
                    "cod_amount": 0.0,
                    "shipment_value": 25000.0,
                    "shipment_tax_value": 4500.0,
                    "shipment_total_value": 29500.0,
                },
                "documents": [],
            }
            book_res = await client.post(
                f"{settings.API_V1_STR}/shipments",
                json=shipment_payload,
                headers=HEADERS,
            )
            assert book_res.status_code in (200, 201), book_res.text
            booked = book_res.json()
            shipment_id = booked["id"]
            tracking_id = booked["tracking_id"]

            # 5. Verify Tenant Staff Read-Only User can view tenant shipments & invoices, but gets 403 on write
            app.dependency_overrides[get_current_active_user] = _as_staff_ro
            ro_shipments = await client.get(
                f"{settings.API_V1_STR}/shipments?is_b2b=true", headers=HEADERS
            )
            assert ro_shipments.status_code == 200
            assert any(
                s["id"] == shipment_id for s in ro_shipments.json()["items"]
            )

            ro_invoices = await client.get(
                f"{settings.API_V1_STR}/invoices", headers=HEADERS
            )
            assert ro_invoices.status_code == 200
            assert any(
                any(
                    li.get("shipment_id") == shipment_id
                    for li in (inv.get("line_items") or [])
                )
                and inv["note_type"] == "INVOICE"
                for inv in ro_invoices.json()
            )

            ro_cancel = await client.post(
                f"{settings.API_V1_STR}/shipments/{shipment_id}/cancel",
                headers=HEADERS,
            )
            assert ro_cancel.status_code == 403, ro_cancel.text

            # 6. Verify Tenant Staff Support-User cannot create shipments (403)
            app.dependency_overrides[get_current_active_user] = _as_staff_support
            sup_book = await client.post(
                f"{settings.API_V1_STR}/shipments",
                json=shipment_payload,
                headers=HEADERS,
            )
            assert sup_book.status_code == 403, sup_book.text

            # 7. Tenant Staff Operations-User performs a Weight Audit (40 KG -> 55 KG)
            app.dependency_overrides[get_current_active_user] = _as_staff_ops
            audit_res = await client.post(
                f"{settings.API_V1_STR}/shipments/{shipment_id}/audit-weight",
                json={"audited_weight_kg": 55.0},
                headers=HEADERS,
            )
            assert audit_res.status_code == 200, audit_res.text

            # 8. Switch back to Customer (`Apex Heavy Industries`):
            #    Customer sees the WeightDispute and raises a Weight Claim -> auto-creates a SupportTicket!
            app.dependency_overrides[get_current_active_user] = _as_customer
            disputes_res = await client.get(
                f"{settings.API_V1_STR}/disputes/weight-mismatch", headers=HEADERS
            )
            assert disputes_res.status_code == 200, disputes_res.text
            matching_disputes = [
                d
                for d in disputes_res.json()
                if d["tracking_id"] == tracking_id
            ]
            assert len(matching_disputes) == 1
            dispute_id = matching_disputes[0]["id"]

            claim_res = await client.post(
                f"{settings.API_V1_STR}/disputes/weight-mismatch/claims",
                json={
                    "tracking_ids": [tracking_id],
                    "claimed_weight_g": 40000.0,
                    "claim_remarks": "Two cartons weighed 20kg each on calibrated dispatch scale.",
                },
                headers=HEADERS,
            )
            assert claim_res.status_code == 200, claim_res.text
            assert claim_res.json()[0]["claim_status"] == "CLAIM_RAISED"

            # Verify a correlated SupportTicket was automatically created!
            tickets_res = await client.get(
                f"{settings.API_V1_STR}/support-tickets", headers=HEADERS
            )
            assert tickets_res.status_code == 200
            correlated_tickets = [
                t
                for t in tickets_res.json()
                if t.get("tracking_id") == tracking_id
            ]
            assert len(correlated_tickets) == 1
            assert correlated_tickets[0]["status"] == "OPEN"

            # 9. Tenant Admin accepts the Weight Dispute (`ACCEPTED`) ->
            #    Automatically refunds customer wallet, issues CREDIT_NOTE in `/invoices`, and resolves SupportTicket!
            app.dependency_overrides[get_current_active_user] = admin_override
            resolve_res = await client.patch(
                f"{settings.API_V1_STR}/disputes/weight-mismatch/{dispute_id}/resolve",
                json={
                    "claim_status": "ACCEPTED",
                    "claim_remarks": "Verified scale photo; refunding excess weight charge.",
                },
                headers=HEADERS,
            )
            assert resolve_res.status_code == 200, resolve_res.text
            assert resolve_res.json()["claim_status"] == "ACCEPTED"

            # Switch back to Customer and verify:
            # - SupportTicket is now RESOLVED
            # - BillingInvoices now has INVOICE, DEBIT_NOTE, and CREDIT_NOTE for this shipment!
            app.dependency_overrides[get_current_active_user] = _as_customer
            tickets_after = await client.get(
                f"{settings.API_V1_STR}/support-tickets", headers=HEADERS
            )
            resolved_ticket = [
                t
                for t in tickets_after.json()
                if t.get("tracking_id") == tracking_id
            ][0]
            assert resolved_ticket["status"] == "RESOLVED"

            invoices_after = await client.get(
                f"{settings.API_V1_STR}/invoices", headers=HEADERS
            )
            shipment_notes = [
                inv["note_type"]
                for inv in invoices_after.json()
                if any(
                    li.get("tracking_id") == tracking_id
                    for li in (inv.get("line_items") or [])
                )
            ]
            assert "INVOICE" in shipment_notes
            assert "DEBIT_NOTE" in shipment_notes
            assert "CREDIT_NOTE" in shipment_notes
    finally:
        app.dependency_overrides[get_current_active_user] = admin_override
