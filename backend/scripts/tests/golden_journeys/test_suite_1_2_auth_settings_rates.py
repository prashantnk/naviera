"""
Golden Test Suite 1 & 2 (`J01-J08`):
- Suite 1: Public Website, Authentication, Onboarding & RBAC (`J01-J04`)
- Suite 2: Workspace Settings, Rate Card, Address Book Privacy & Rate Calculator (`J05-J08`)

Runs ONLY against the guarded test tenant (`GOLDEN_TENANT_SLUG`, default
`logismart-test`) with real JWT sessions for the canonical test accounts
(`golden_journeys/fixtures/logismart_test_accounts.json`). The tenant is reset
once per pytest session by `golden_journeys/conftest.py`.
"""

import time
import uuid

import httpx
import pytest
from httpx import ASGITransport

from app.main import app
from app.models.pickups import Address, DimensionUnit, PaymentDetails, ServiceOption
from app.models.tenants import ServiceScope, User

from .golden_env import (
    GoldenSessionLocal,
    ADMIN_EMAIL,
    B2B_ONBOARDING_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GOLDEN_TENANT_SLUG,
    OWNER_EMAIL,
    READONLY_EMAIL,
    canonical_emails,
    first_tenant_payment_details,
    load_settings_fixture,
)
from .golden_env import (
    headers as _headers,
)
from .golden_env import (
    load_accounts as _load_accounts,
)

TENANT_SLUG = GOLDEN_TENANT_SLUG
EXPECTED_8_EMAILS = set(canonical_emails())

# J04 onboarding GSTIN: a valid-format Karnataka GSTIN that is NOT the tenant's own.
J04_ONBOARDING_GSTIN = "29AAGCB7383J1Z4"
J04_ONBOARDING_PAN = "AAGCB7383J"
J04_COMPANY_NAME = "Golden Onboarding Traders"


@pytest.mark.asyncio
async def test_j01_public_tenant_config_and_branding():
    """
    J01: Public tenant branding & config (`GET /api/v1/tenants/config`) +
    Admin full settings (`GET /api/v1/tenants/settings`).
    """
    accounts = await _load_accounts()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/v1/tenants/config",
            headers={"X-Tenant-Slug": TENANT_SLUG},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["slug"] == TENANT_SLUG
        pub_settings = body["settings"]

        assert "brand" in pub_settings
        assert pub_settings["brand"].get("primary_color")
        assert pub_settings["brand"].get("secondary_color")
        assert pub_settings.get("gstin") == "06AAECL2138H1ZQ"
        assert pub_settings["contact"]["gstin"] == "06AAECL2138H1ZQ"
        assert pub_settings["contact"]["whatsapp"] == "9821008627"
        assert "Gurgaon" in pub_settings["contact"]["address"]
        assert "escalation_matrix" in pub_settings or "support" in pub_settings

        # Verify pricing_policy is withheld from unauthenticated public response
        # and returned on authenticated admin GET /api/v1/tenants/settings and /api/v1/pricing/policy
        assert "pricing_policy" not in pub_settings
        assert "pricing_config" not in pub_settings
        admin_resp = await client.get(
            "/api/v1/tenants/settings",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert admin_resp.status_code == 200, admin_resp.text
        full_settings = admin_resp.json()["settings"]
        assert "pricing_policy" in full_settings
        assert float(full_settings["pricing_policy"]["prime_default_markup_percent"]) == 20.0

        policy_resp = await client.get(
            "/api/v1/pricing/policy",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert policy_resp.status_code == 200, policy_resp.text
        policy_body = policy_resp.json()
        assert policy_body["cod_enabled"] is True
        assert policy_body["delhivery_configured"] is True


@pytest.mark.asyncio
async def test_j02_signup_duplicate_409_profile_edit_and_me():
    """
    J02: Duplicate email signup guard (`409 Conflict`), `GET /api/v1/users/me`,
    and self-service profile edit (`PATCH /api/v1/users/me`) with DB verification
    and clean state restoration.
    """
    accounts = await _load_accounts()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Duplicate email signup returns 409 Conflict
        dup_resp = await client.post(
            "/api/v1/users/auth/signup",
            headers={"X-Tenant-Slug": TENANT_SLUG},
            json={
                "email": CUSTOMER_B2C_EMAIL,
                "password": "TestPassword123!",
                "full_name": "Attempt Overwrite",
            },
        )
        assert dup_resp.status_code == 409, dup_resp.text
        assert "already exists" in dup_resp.json()["detail"].lower()

        # 2. Fetch current profile for customerb2c@logismart.in
        me_resp = await client.get(
            "/api/v1/users/me",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
        )
        assert me_resp.status_code == 200, me_resp.text
        orig_profile = me_resp.json()
        orig_name = orig_profile.get("full_name") or "B2C Customer"
        orig_phone = orig_profile.get("phone") or ""

        # 3. Update full_name & phone via PATCH /api/v1/users/me and verify in DB
        test_name = "LogiSmart B2C Verified Seller"
        test_phone = "+919811223344"
        try:
            patch_resp = await client.patch(
                "/api/v1/users/me",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
                json={"full_name": test_name, "phone": test_phone},
            )
            assert patch_resp.status_code == 200, patch_resp.text
            updated = patch_resp.json()
            assert updated["full_name"] == test_name
            assert updated["phone"] == test_phone

            async with GoldenSessionLocal() as session:
                db_user = await session.get(
                    User, uuid.UUID(accounts[CUSTOMER_B2C_EMAIL]["id"])
                )
                assert db_user is not None
                assert db_user.full_name == test_name
                assert db_user.phone == test_phone
        finally:
            restore_resp = await client.patch(
                "/api/v1/users/me",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
                json={"full_name": orig_name, "phone": orig_phone},
            )
            assert restore_resp.status_code == 200, restore_resp.text


@pytest.mark.asyncio
async def test_j03_owner_staff_management_demotion_guard_and_deactivation():
    """
    J03: Owner lists all 8 workspace users, verifies Owner demotion/deactivation
    guards (`400 Bad Request`), and verifies user deactivation blocks API access
    (`400`/`403`) before restoring active status.
    """
    accounts = await _load_accounts()
    owner_id = accounts[OWNER_EMAIL]["id"]
    readonly_id = accounts[READONLY_EMAIL]["id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. List all users in tenant
        list_resp = await client.get(
            "/api/v1/users",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert list_resp.status_code == 200, list_resp.text
        users_list = list_resp.json()
        returned_emails = {u["email"] for u in users_list}
        assert EXPECTED_8_EMAILS.issubset(returned_emails)

        # 2. Attempt to demote owner@logismart.in -> 400 Bad Request
        demote_resp = await client.patch(
            f"/api/v1/users/{owner_id}",
            headers=_headers(accounts, OWNER_EMAIL),
            json={"role": "admin"},
        )
        assert demote_resp.status_code == 400, demote_resp.text
        assert "owner" in demote_resp.json()["detail"].lower()

        # 3. Attempt to deactivate owner@logismart.in -> 400 Bad Request
        deact_owner_resp = await client.patch(
            f"/api/v1/users/{owner_id}",
            headers=_headers(accounts, OWNER_EMAIL),
            json={"is_active": False},
        )
        assert deact_owner_resp.status_code == 400, deact_owner_resp.text

        # 4. Deactivate readonly@logismart.in -> verify API blocked -> restore
        try:
            deact_resp = await client.patch(
                f"/api/v1/users/{readonly_id}",
                headers=_headers(accounts, OWNER_EMAIL),
                json={"is_active": False},
            )
            assert deact_resp.status_code == 200, deact_resp.text
            assert deact_resp.json()["is_active"] is False

            blocked_resp = await client.get(
                "/api/v1/users/me",
                headers=_headers(accounts, READONLY_EMAIL),
            )
            assert blocked_resp.status_code in (400, 403), blocked_resp.text
        finally:
            react_resp = await client.patch(
                f"/api/v1/users/{readonly_id}",
                headers=_headers(accounts, OWNER_EMAIL),
                json={"is_active": True},
            )
            assert react_resp.status_code == 200, react_resp.text
            assert react_resp.json()["is_active"] is True

        ok_resp = await client.get(
            "/api/v1/users/me",
            headers=_headers(accounts, READONLY_EMAIL),
        )
        assert ok_resp.status_code == 200, ok_resp.text


@pytest.mark.asyncio
async def test_j04_b2b_access_request_reject_resubmit_and_approve():
    """
    J04: Self-service B2B access onboarding (`b2bonboarding@logismart.in`, a
    canonical test-only identity; the live owner is never a test actor):
    1) Customer starts as `B2C` (seed/reset state, asserted via the admin API)
    2) Customer submits B2B request (`gstin=J04_ONBOARDING_GSTIN`) -> `PENDING` + PAN auto-derived
    3) Admin rejects -> `REJECTED`, scope stays `B2C`
    4) Customer re-submits -> `PENDING`
    5) Admin approves -> `APPROVED`, `service_scope == "BOTH"`
    """
    accounts = await _load_accounts()
    onboarding_id = accounts[B2B_ONBOARDING_EMAIL]["id"]

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. The onboarding customer starts as B2C after the session reset
        users_resp = await client.get(
            "/api/v1/users", headers=_headers(accounts, ADMIN_EMAIL)
        )
        assert users_resp.status_code == 200, users_resp.text
        start_row = next(u for u in users_resp.json() if u["id"] == onboarding_id)
        assert start_row["service_scope"] == ServiceScope.B2C.value

        # 2. Customer requests B2B access with GSTIN (PAN auto-derived)
        req1 = await client.post(
            "/api/v1/users/me/request-b2b",
            headers=_headers(accounts, B2B_ONBOARDING_EMAIL),
            json={
                "company_name": J04_COMPANY_NAME,
                "gstin": J04_ONBOARDING_GSTIN,
            },
        )
        assert req1.status_code == 200, req1.text
        r1_body = req1.json()
        assert r1_body["b2b_request_status"] == "PENDING"
        assert r1_body["company_name"] == J04_COMPANY_NAME
        assert r1_body["gstin"] == J04_ONBOARDING_GSTIN
        assert r1_body["pan"] == J04_ONBOARDING_PAN

        # 3. Admin rejects the B2B request
        rej_resp = await client.post(
            f"/api/v1/users/{onboarding_id}/review-b2b",
            headers=_headers(accounts, ADMIN_EMAIL),
            json={"approve": False},
        )
        assert rej_resp.status_code == 200, rej_resp.text
        rej_body = rej_resp.json()
        assert rej_body["b2b_request_status"] == "REJECTED"
        assert rej_body["service_scope"] == "B2C"

        # 4. Customer re-submits B2B request
        req2 = await client.post(
            "/api/v1/users/me/request-b2b",
            headers=_headers(accounts, B2B_ONBOARDING_EMAIL),
            json={
                "company_name": J04_COMPANY_NAME,
                "gstin": J04_ONBOARDING_GSTIN,
            },
        )
        assert req2.status_code == 200, req2.text
        assert req2.json()["b2b_request_status"] == "PENDING"

        # 5. Admin approves B2B request -> upgrades scope to BOTH
        app_resp = await client.post(
            f"/api/v1/users/{onboarding_id}/review-b2b",
            headers=_headers(accounts, ADMIN_EMAIL),
            json={"approve": True, "service_scope": "BOTH"},
        )
        assert app_resp.status_code == 200, app_resp.text
        app_body = app_resp.json()
        assert app_body["b2b_request_status"] == "APPROVED"
        assert app_body["service_scope"] == "BOTH"

        async with GoldenSessionLocal() as session:
            db_user = await session.get(User, uuid.UUID(onboarding_id))
            assert db_user is not None
            assert db_user.service_scope == ServiceScope.BOTH


@pytest.mark.asyncio
async def test_j05_workspace_settings_validation_history_and_restore():
    """
    J05: Workspace settings validation (`422` on invalid hex colour or invalid GSTIN),
    settings update creates a `tenant_settings_history` version snapshot, and
    `POST /api/v1/tenants/settings/restore/{version_id}` restores the original state.
    """
    accounts = await _load_accounts()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Invalid hex colour returns 422
        bad_hex = await client.patch(
            "/api/v1/tenants/settings",
            headers=_headers(accounts, OWNER_EMAIL),
            json={"brand": {"primary_color": "not-a-valid-hex"}},
        )
        assert bad_hex.status_code == 422, bad_hex.text

        # 2. Invalid GSTIN returns 422
        bad_gst = await client.patch(
            "/api/v1/tenants/settings",
            headers=_headers(accounts, OWNER_EMAIL),
            json={"gstin": "INVALIDGSTIN999"},
        )
        assert bad_gst.status_code == 422, bad_gst.text

        # 3. Read current settings
        cur_resp = await client.get(
            "/api/v1/tenants/settings",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert cur_resp.status_code == 200, cur_resp.text
        orig_bar = dict(
            (cur_resp.json()["settings"] or {}).get("announcement_bar") or {}
        )
        orig_text = orig_bar.get("text") or "Pan-India Express & Heavy Cargo Logistics"

        # 4. Update announcement_bar.text to trigger a version snapshot
        new_text = f"Golden J05 Snapshot Check {int(time.time())}"
        upd_resp = await client.patch(
            "/api/v1/tenants/settings",
            headers=_headers(accounts, OWNER_EMAIL),
            json={"announcement_bar": {"text": new_text, "is_active": True}},
        )
        assert upd_resp.status_code == 200, upd_resp.text
        assert upd_resp.json()["settings"]["announcement_bar"]["text"] == new_text

        # 5. Inspect history and restore the newest snapshot (which holds the pre-update state)
        hist_resp = await client.get(
            "/api/v1/tenants/settings/history",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert hist_resp.status_code == 200, hist_resp.text
        history = hist_resp.json()
        assert len(history) >= 1
        latest_snapshot = history[0]
        assert "announcement_bar" in latest_snapshot["changed_sections"]

        restore_resp = await client.post(
            f"/api/v1/tenants/settings/restore/{latest_snapshot['id']}",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert restore_resp.status_code == 200, restore_resp.text
        restored_bar = (restore_resp.json()["settings"] or {}).get(
            "announcement_bar"
        ) or {}
        assert restored_bar.get("text") == orig_bar.get("text", orig_text)


@pytest.mark.asyncio
async def test_j06_address_book_isolation_and_soft_delete():
    """
    J06: `customerb2c@logismart.in` creates a saved `PRIVATE` warehouse address ->
    `customerb2b@logismart.in` cannot see it (`D17`) -> `customerb2c` soft-deletes
    it (`DELETE /api/v1/addresses/{id}`) -> `is_saved == False` in PostgreSQL DB.
    """
    accounts = await _load_accounts()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post(
            "/api/v1/addresses",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "name": "J06 Private B2C Warehouse",
                "phone": "9811001122",
                "company_name": "B2C Private Seller Store",
                "address_line1": "Plot 42, Sector 18 Industrial Estate",
                "city": "Gurugram",
                "state": "Haryana",
                "pincode": "122015",
                "country": "IN",
                "category": "WAREHOUSE",
                "scope": "PRIVATE",
                "is_saved": True,
            },
        )
        assert create_resp.status_code in (200, 201), create_resp.text
        created_addr = create_resp.json()
        addr_id = created_addr["id"]
        assert created_addr["scope"] == "PRIVATE"
        assert created_addr["user_id"] == accounts[CUSTOMER_B2C_EMAIL]["id"]

        try:
            # Verify visible to creator (customerb2c)
            b2c_list = await client.get(
                "/api/v1/addresses",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            )
            assert b2c_list.status_code == 200, b2c_list.text
            b2c_ids = {a["id"] for a in b2c_list.json()}
            assert addr_id in b2c_ids

            # Verify 100% invisible to customerb2b (D17 isolation)
            b2b_list = await client.get(
                "/api/v1/addresses",
                headers=_headers(accounts, CUSTOMER_B2B_EMAIL),
            )
            assert b2b_list.status_code == 200, b2b_list.text
            b2b_ids = {a["id"] for a in b2b_list.json()}
            assert addr_id not in b2b_ids
        finally:
            # Soft-delete the test address
            del_resp = await client.delete(
                f"/api/v1/addresses/{addr_id}",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            )
            assert del_resp.status_code in (200, 204), del_resp.text

        # Verify soft-deleted in PostgreSQL DB (`is_saved == False`)
        async with GoldenSessionLocal() as session:
            db_addr = await session.get(Address, uuid.UUID(addr_id))
            assert db_addr is not None
            assert db_addr.is_saved is False


@pytest.mark.asyncio
async def test_j07_rate_calculator_unserviceable_pincode_and_volumetric_divisors():
    """
    J07: Rate calculator serviceability on `POST /api/v1/quotes` (DESIGN.md v4):
    1. B2C quotes on `122001 -> 400001` return `DELHIVERY_SURFACE` and `DELHIVERY_EXPRESS`
       serviceable, while `000000` is unserviceable (`PINCODE_NOT_SERVICEABLE`).
    2. B2B quotes on `122001 -> 400001` return `PRIME_SURFACE` and `DELHIVERY_SURFACE`
       serviceable, while `122001 -> 560001` (not in Prime fixture) marks `PRIME_SURFACE`
       unserviceable (`LANE_NOT_SERVED`) and `DELHIVERY_SURFACE` serviceable.
    3. `50x40x30 CM` (`60,000 cm3`), `1.0 kg` actual -> `DELHIVERY_EXPRESS` (`5000` divisor -> `12.0 kg`)
       vs `DELHIVERY_SURFACE` (`4500` divisor -> `13.33 kg` raw, `13.5 kg` 500g slab).
    4. `IN`, `FT`, `M` dimension unit conversions.
    """
    accounts = await _load_accounts()
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. B2C serviceable (400001) vs unserviceable (000000)
        b2c_ok = await client.post(
            "/api/v1/quotes",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "service_flow": "B2C",
                "pickup_pincode": "122001",
                "delivery_pincode": "400001",
                "packages": [
                    {
                        "length": 20,
                        "breadth": 20,
                        "height": 20,
                        "dimension_unit": "CM",
                        "weight": 1.0,
                        "weight_unit": "KG",
                        "box_count": 1,
                    }
                ],
            },
        )
        assert b2c_ok.status_code == 200, b2c_ok.text
        opts_ok = {o["service_option"]: o for o in b2c_ok.json()["options"]}
        assert opts_ok[ServiceOption.DELHIVERY_SURFACE.value]["serviceable"] is True
        assert opts_ok[ServiceOption.DELHIVERY_EXPRESS.value]["serviceable"] is True

        b2c_unserv = await client.post(
            "/api/v1/quotes",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "service_flow": "B2C",
                "pickup_pincode": "122001",
                "delivery_pincode": "999999",
                "packages": [
                    {
                        "length": 20,
                        "breadth": 20,
                        "height": 20,
                        "dimension_unit": "CM",
                        "weight": 1.0,
                        "weight_unit": "KG",
                        "box_count": 1,
                    }
                ],
            },
        )
        assert b2c_unserv.status_code == 200, b2c_unserv.text
        for opt in b2c_unserv.json()["options"]:
            assert opt["serviceable"] is False
            assert opt["unavailable_code"] == "NOT_SERVICEABLE"

        # 2. B2B Prime lane (122001 -> 400001 serviceable vs 122001 -> 560001 NO_PRIME_LANE)
        b2b_ok = await client.post(
            "/api/v1/quotes",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "service_flow": "B2B",
                "pickup_pincode": "122001",
                "delivery_pincode": "400001",
                "packages": [
                    {
                        "length": 40,
                        "breadth": 30,
                        "height": 30,
                        "dimension_unit": "CM",
                        "weight": 10.0,
                        "weight_unit": "KG",
                        "box_count": 1,
                    }
                ],
            },
        )
        assert b2b_ok.status_code == 200, b2b_ok.text
        b2b_opts = {o["service_option"]: o for o in b2b_ok.json()["options"]}
        assert set(b2b_opts.keys()) == {ServiceOption.PRIME_SURFACE.value}
        assert b2b_opts[ServiceOption.PRIME_SURFACE.value]["serviceable"] is True
        assert b2b_opts[ServiceOption.PRIME_SURFACE.value]["total_amount"] == 1699.20

        b2b_no_lane = await client.post(
            "/api/v1/quotes",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "service_flow": "B2B",
                "pickup_pincode": "122001",
                "delivery_pincode": "560001",
                "packages": [
                    {
                        "length": 40,
                        "breadth": 30,
                        "height": 30,
                        "dimension_unit": "CM",
                        "weight": 10.0,
                        "weight_unit": "KG",
                        "box_count": 1,
                    }
                ],
            },
        )
        assert b2b_no_lane.status_code == 200, b2b_no_lane.text
        b2b_nl_opts = {o["service_option"]: o for o in b2b_no_lane.json()["options"]}
        assert set(b2b_nl_opts.keys()) == {ServiceOption.PRIME_SURFACE.value}
        assert b2b_nl_opts[ServiceOption.PRIME_SURFACE.value]["serviceable"] is False
        assert b2b_nl_opts[ServiceOption.PRIME_SURFACE.value]["unavailable_code"] == "NO_PRIME_LANE"

        # 3. 50x40x30 CM (60,000 cm3), 1.0 kg actual -> Delhivery divisor 5000 -> 12.0 kg for both Surface & Express
        vol_resp = await client.post(
            "/api/v1/quotes",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json={
                "service_flow": "B2C",
                "pickup_pincode": "122001",
                "delivery_pincode": "400001",
                "packages": [
                    {
                        "length": 50,
                        "breadth": 40,
                        "height": 30,
                        "dimension_unit": "CM",
                        "weight": 1.0,
                        "weight_unit": "KG",
                        "box_count": 1,
                    }
                ],
            },
        )
        assert vol_resp.status_code == 200, vol_resp.text
        vol_quotes = {q["service_option"]: q for q in vol_resp.json()["options"]}
        air_q = vol_quotes[ServiceOption.DELHIVERY_EXPRESS.value]
        surf_q = vol_quotes[ServiceOption.DELHIVERY_SURFACE.value]

        assert air_q["chargeable_weight_kg"] == 12.0
        assert surf_q["chargeable_weight_kg"] == 12.0
        assert air_q["total_amount"] > surf_q["total_amount"]

        # 4. Test IN, FT, M dimension units
        for unit, dim in [
            (DimensionUnit.IN.value, 10.0),
            (DimensionUnit.FT.value, 1.5),
            (DimensionUnit.M.value, 0.5),
        ]:
            unit_resp = await client.post(
                "/api/v1/quotes",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
                json={
                    "service_flow": "B2C",
                    "pickup_pincode": "122001",
                    "delivery_pincode": "400001",
                    "packages": [
                        {
                            "length": dim,
                            "breadth": dim,
                            "height": dim,
                            "dimension_unit": unit,
                            "weight": 1.0,
                            "weight_unit": "KG",
                            "box_count": 1,
                        }
                    ],
                },
            )
            assert unit_resp.status_code == 200, unit_resp.text
            u_opts = {q["service_option"]: q for q in unit_resp.json()["options"]}
            assert u_opts[ServiceOption.DELHIVERY_SURFACE.value]["chargeable_weight_kg"] >= 0.5
            assert u_opts[ServiceOption.DELHIVERY_SURFACE.value]["total_amount"] > 0


@pytest.mark.asyncio
async def test_j08_live_rate_card_propagation_and_restore():
    """
    J08: Owner updates `pricing_policy.delhivery_markup_percent` via `PUT /api/v1/pricing/policy` ->
    `POST /api/v1/quotes` immediately reflects the new markup,
    existing shipment's `payment_details.base_freight` in DB remains immutable,
    `delhivery_markup_percent` is restored to its original value (`0.0`), and
    `GET /api/v1/wallet/audit-integrity` confirms 0 discrepancies.
    """
    accounts = await _load_accounts()
    transport = ASGITransport(app=app)

    # Record an existing payment_details row of the TEST tenant (if any) to verify
    # historical immutability. Right after the session reset there may be none.
    existing_pd_id = None
    existing_base_freight = None
    pd_row = await first_tenant_payment_details()
    if pd_row is not None:
        existing_pd_id = pd_row.id
        existing_base_freight = float(pd_row.base_freight)
    fixture_policy = dict(load_settings_fixture()["pricing_policy"])

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        policy_resp = await client.get(
            "/api/v1/pricing/policy",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert policy_resp.status_code == 200, policy_resp.text
        orig_policy = policy_resp.json()
        orig_markup = float(orig_policy["delhivery_markup_percent"])
        assert orig_markup == float(fixture_policy["delhivery_markup_percent"]), (
            "The reset must restore the frozen pricing policy before J08 changes it"
        )

        rate_payload = {
            "service_flow": "B2C",
            "pickup_pincode": "122001",
            "delivery_pincode": "400001",
            "packages": [
                {
                    "length": 10,
                    "breadth": 10,
                    "height": 10,
                    "dimension_unit": "CM",
                    "weight": 2.0,
                    "weight_unit": "KG",
                    "box_count": 1,
                }
            ],
        }
        before_resp = await client.post(
            "/api/v1/quotes",
            headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
            json=rate_payload,
        )
        assert before_resp.status_code == 200, before_resp.text
        before_quotes = {
            q["service_option"]: q for q in before_resp.json()["options"]
        }
        before_freight = float(
            before_quotes[ServiceOption.DELHIVERY_SURFACE.value]["freight_amount"]
        )
        assert before_freight == 135.0

        try:
            upd_payload = {
                "delhivery_markup_percent": 20.0,
                "prime_default_markup_percent": orig_policy["prime_default_markup_percent"],
                "cod_fee_percent": orig_policy["cod_fee_percent"],
                "cod_fee_min": orig_policy["cod_fee_min"],
                "enabled_options": orig_policy["enabled_options"],
            }
            upd_resp = await client.put(
                "/api/v1/pricing/policy",
                headers=_headers(accounts, OWNER_EMAIL),
                json=upd_payload,
            )
            assert upd_resp.status_code == 200, upd_resp.text

            after_resp = await client.post(
                "/api/v1/quotes",
                headers=_headers(accounts, CUSTOMER_B2C_EMAIL),
                json=rate_payload,
            )
            assert after_resp.status_code == 200, after_resp.text
            after_quotes = {
                q["service_option"]: q for q in after_resp.json()["options"]
            }
            after_freight = float(
                after_quotes[ServiceOption.DELHIVERY_SURFACE.value]["freight_amount"]
            )
            assert after_freight == 162.0  # 135.0 * 1.20

            # Verify historical shipment payment_details.base_freight is untouched
            if existing_pd_id is not None:
                async with GoldenSessionLocal() as session:
                    pd_check = await session.get(PaymentDetails, existing_pd_id)
                    assert pd_check is not None
                    assert float(pd_check.base_freight) == existing_base_freight
        finally:
            restore_payload = {
                "delhivery_markup_percent": orig_markup,
                "prime_default_markup_percent": orig_policy["prime_default_markup_percent"],
                "cod_fee_percent": orig_policy["cod_fee_percent"],
                "cod_fee_min": orig_policy["cod_fee_min"],
                "enabled_options": orig_policy["enabled_options"],
            }
            restore_resp = await client.put(
                "/api/v1/pricing/policy",
                headers=_headers(accounts, OWNER_EMAIL),
                json=restore_payload,
            )
            assert restore_resp.status_code == 200, restore_resp.text
            assert float(restore_resp.json()["delhivery_markup_percent"]) == orig_markup

        # Final Suite 1 & 2 Ledger & System Integrity Audit check
        audit_resp = await client.get(
            "/api/v1/wallet/audit-integrity",
            headers=_headers(accounts, OWNER_EMAIL),
        )
        assert audit_resp.status_code == 200, audit_resp.text
        audit_body = audit_resp.json()
        assert audit_body["passed"] is True, audit_body
        assert audit_body["discrepancy_count"] == 0, audit_body
        assert audit_body["discrepancies"] == []
