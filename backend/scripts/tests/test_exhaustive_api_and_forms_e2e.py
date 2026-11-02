"""
Exhaustive E2E API, Database Lifecycle & Form Payload Verification Suite.

Exercises every API endpoint and form payload contract under the Admin and
Customer JWT identities of the guarded TEST tenant (`GOLDEN_TENANT_SLUG`,
default `logismart-test`; plan item A7). It never targets the live
`logismart` tenant: identities, tokens and the slug come from
`golden_journeys.golden_env`, which refuses non-test slugs, non-test tenants
and protected live identities. Requests go through the in-process
`ASGITransport` (no running server needed).
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Set, Tuple

import httpx
import pytest
from golden_journeys.golden_env import (
    ADMIN_EMAIL,
    CUSTOMER_B2B_EMAIL,
    CUSTOMER_B2C_EMAIL,
    GOLDEN_TENANT_SLUG,
    OWNER_EMAIL,
    acquire_run_lock,
    load_accounts,
    load_test_tenant,
    make_utr,
    mint_jwt,
    release_run_lock,
)
from httpx import ASGITransport

from app.core.db import AsyncSessionLocal
from app.main import app
from app.models.pickups import (
    Address,
)
from app.models.pricing import DelhiveryPriceCache
from app.models.prime import PrimeLane
from app.models.tenants import Tenant
from app.repositories.prime_rates import PrimeRatesRepository
from scripts.seed_prime_zones import apply_test_fixture
from scripts.tenant_data_core import assert_test_tenant_slug, require_tenant, reset_test_tenant
from sqlalchemy import delete

# --- Module-Level Constants ---
ASGI_BASE_URL = "http://test"
HTTP_TIMEOUT_SECONDS = 30.0
TENANT_SLUGS: List[str] = [GOLDEN_TENANT_SLUG]
# A different tenant used only for read-only isolation probes (never written to).
CROSS_TENANT_PROBE_SLUG = "naviera"


def _e2e_client() -> httpx.AsyncClient:
    """Returns an in-process ASGI client bound to the FastAPI app."""
    return httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url=ASGI_BASE_URL, timeout=HTTP_TIMEOUT_SECONDS
    )


async def _resolve_test_identities() -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Resolves the canonical Admin and B2C Customer of the guarded test tenant
    (tenant-checked lookup; refuses protected live identities).
    """
    accounts = await load_accounts()
    admin = accounts[ADMIN_EMAIL]
    customer = accounts[CUSTOMER_B2C_EMAIL]
    admin_identity = {
        "email": admin["email"],
        "sub": admin["sub"],
        "expected_role": admin["role"],
    }
    customer_identity = {
        "email": customer["email"],
        "sub": customer["sub"],
        "expected_role": customer["role"],
    }
    return admin_identity, customer_identity


EXPECTED_PRICING_BREAKDOWN_KEYS: Set[str] = {
    "service_option",
    "base_charge",
    "cod_fee",
    "rto_surcharge",
    "total_actual_weight",
    "total_volumetric_weight",
    "raw_chargeable_weight",
    "subtotal",
    "gst_total",
    "sell_lines",
    "total_customer_pays",
    "sender_net_remittance",
    "shipping_paid_by",
}


def _mint_supabase_jwt(sub: str, email: str) -> str:
    """Mints a test JWT through the guarded golden harness (canonical test actors only)."""
    return mint_jwt(str(sub), email)


def _build_headers(tenant_slug: str, token: str | None = None) -> Dict[str, str]:
    """Constructs request headers with X-Tenant-Slug and optional Bearer JWT."""
    headers = {"X-Tenant-Slug": tenant_slug}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def _ensure_wallet_funded(
    client: httpx.AsyncClient,
    slug: str,
    user_token: str,
    admin_token: str,
    min_balance: float = 10000.0,
) -> None:
    """
    Ensures the target user's wallet has at least `min_balance` using the Maker-Checker
    UPI Recharge flow (`upi-intent` -> `confirm` 'I Have Paid' -> Admin `approve`).
    """
    res_w = await client.get(
        "/api/v1/wallet", headers=_build_headers(slug, user_token)
    )
    assert res_w.status_code == 200, res_w.text
    cur_bal = float(res_w.json().get("balance", 0.0))
    if cur_bal >= min_balance:
        return

    topup_amt = round(max(1000.0, min_balance - cur_bal + 1000.0), 2)
    # Maker-checker forbids approving your own recharge: the owner approves the
    # admin's top-up, so every balance change has a ledger row.
    approver_token = (
        await _owner_token() if user_token == admin_token else admin_token
    )

    res_intent = await client.post(
        "/api/v1/wallet/recharge/upi-intent",
        headers=_build_headers(slug, user_token),
        json={"amount": topup_amt},
    )
    assert res_intent.status_code == 200, res_intent.text
    txn_id = res_intent.json()["transaction_id"]

    # User clicks "I Have Paid" with a 12-digit UTR -> status stays PENDING
    res_confirm = await client.post(
        f"/api/v1/wallet/recharge/{txn_id}/confirm",
        headers=_build_headers(slug, user_token),
        json={"utr_number": make_utr()},
    )
    assert res_confirm.status_code == 200, res_confirm.text
    assert res_confirm.json()["status"] == "PENDING"

    # Admin approves & merges the pending recharge into the user's main balance
    res_approve = await client.post(
        f"/api/v1/wallet/recharge/{txn_id}/approve",
        headers=_build_headers(slug, approver_token),
    )
    assert res_approve.status_code == 200, res_approve.text
    assert res_approve.json()["status"] == "COMPLETED"


async def _owner_token() -> str:
    """Returns the canonical test-tenant owner's JWT (guarded harness)."""
    accounts = await load_accounts()
    return str(accounts[OWNER_EMAIL]["access_token"])


@pytest.fixture(scope="module", autouse=True)
async def e2e_test_tenant_reset():
    """
    Guards and resets the TEST tenant once before this module (plan A3/A7).

    Replaces the old cross-tenant "stale prefix" sweep and the all-tenant wallet
    rewrite: cleanup is now the shared FK-ordered `reset_test_tenant`, scoped by
    the test tenant's id, under the same run lock as the golden suites. Data is
    left in place afterwards for inspection; the next run resets it.
    """
    assert_test_tenant_slug(GOLDEN_TENANT_SLUG)
    await load_test_tenant(GOLDEN_TENANT_SLUG)
    lock_handle = acquire_run_lock()
    try:
        async with AsyncSessionLocal() as session:
            counts = await reset_test_tenant(session, GOLDEN_TENANT_SLUG, commit=False)
            tenant = await require_tenant(session, GOLDEN_TENANT_SLUG)
            await session.exec(
                delete(DelhiveryPriceCache).where(DelhiveryPriceCache.tenant_id == tenant.id)
            )
            await session.exec(delete(PrimeLane).where(PrimeLane.tenant_id == tenant.id))
            await apply_test_fixture(PrimeRatesRepository(session), tenant.id)
            await session.commit()
        print(f"[e2e] reset tenant {GOLDEN_TENANT_SLUG!r}: {counts}")
        yield
    finally:
        release_run_lock(lock_handle)


@pytest.mark.asyncio
async def test_01_tenant_config_branding_and_rbac() -> None:
    """
    Verifies Tenant Config, JIT Onboarding, User Profile (/users/me), and
    Settings Update RBAC (Admin 200 vs Customer 403) on the guarded test tenant.
    """
    admin_identity, customer_identity = await _resolve_test_identities()
    admin_token = _mint_supabase_jwt(admin_identity["sub"], admin_identity["email"])
    customer_token = _mint_supabase_jwt(
        customer_identity["sub"], customer_identity["email"]
    )

    async with _e2e_client() as client:
        for slug in TENANT_SLUGS:
            # 1. Ensure both Admin and Customer are onboarded in the tenant
            res_onboard_admin = await client.post(
                "/api/v1/users/onboard",
                headers=_build_headers(slug, admin_token),
            )
            assert res_onboard_admin.status_code == 201, res_onboard_admin.text

            res_onboard_cust = await client.post(
                "/api/v1/users/onboard",
                headers=_build_headers(slug, customer_token),
            )
            assert res_onboard_cust.status_code == 201, res_onboard_cust.text

            # 2. Verify GET /api/v1/tenants/config and GET /api/v1/tenants/{slug}/public
            res_config = await client.get(
                "/api/v1/tenants/config",
                headers=_build_headers(slug),
            )
            assert res_config.status_code == 200, res_config.text
            config_data = res_config.json()
            assert config_data["slug"] == slug
            assert "settings" in config_data
            tenant_id = config_data["id"]

            res_public = await client.get(f"/api/v1/tenants/{slug}/public")
            assert res_public.status_code == 200, res_public.text
            assert res_public.json()["id"] == tenant_id

            # 3. Verify GET /api/v1/users/me for Admin and Customer
            res_me_admin = await client.get(
                "/api/v1/users/me",
                headers=_build_headers(slug, admin_token),
            )
            assert res_me_admin.status_code == 200, res_me_admin.text
            assert res_me_admin.json()["email"] == admin_identity["email"]
            assert res_me_admin.json()["role"] == admin_identity["expected_role"]

            res_me_cust = await client.get(
                "/api/v1/users/me",
                headers=_build_headers(slug, customer_token),
            )
            assert res_me_cust.status_code == 200, res_me_cust.text
            assert res_me_cust.json()["email"] == customer_identity["email"]
            assert res_me_cust.json()["role"] == customer_identity["expected_role"]

            # 4. Verify PATCH /api/v1/tenants/settings (Customer -> 403 Forbidden)
            res_patch_cust = await client.patch(
                "/api/v1/tenants/settings",
                headers=_build_headers(slug, customer_token),
                json={"settings": {"e2e_rbac_probe": "blocked"}},
            )
            assert res_patch_cust.status_code == 403, res_patch_cust.text

            # 5. Verify PATCH /api/v1/tenants/settings (Admin -> 200 OK) is strictly ADDITIVE & restore.
            # The baseline is the FULL admin settings (not the public config, which withholds
            # private sections such as pricing_config and the test `environment` flag).
            res_full = await client.get(
                "/api/v1/tenants/settings",
                headers=_build_headers(slug, admin_token),
            )
            assert res_full.status_code == 200, res_full.text
            original_settings = res_full.json().get("settings") or {}
            res_patch_admin = await client.patch(
                "/api/v1/tenants/settings",
                headers=_build_headers(slug, admin_token),
                json={"settings": {"announcement_bar": {"text": "E2E Verified Notice"}}},
            )
            assert res_patch_admin.status_code == 200, res_patch_admin.text
            patched_settings = res_patch_admin.json()["settings"]
            assert (
                patched_settings.get("announcement_bar", {}).get("text")
                == "E2E Verified Notice"
            )
            for existing_key, existing_val in original_settings.items():
                if existing_key != "announcement_bar":
                    assert patched_settings.get(existing_key) == existing_val, (
                        f"Additive settings merge lost or altered key '{existing_key}'"
                    )

            # Restore the full original settings of the TEST tenant
            async with AsyncSessionLocal() as session:
                tenant_obj = await session.get(Tenant, uuid.UUID(tenant_id))
                assert tenant_obj is not None and tenant_obj.slug == GOLDEN_TENANT_SLUG
                tenant_obj.settings = dict(original_settings)
                session.add(tenant_obj)
                await session.commit()


@pytest.mark.asyncio
async def test_02_address_book_crud_and_isolation() -> None:
    """
    Verifies Address Book CRUD, Multi-Tenant Isolation, Private vs Shared B2B Scope
    Isolation, PUT/PATCH updates, and Soft-Delete (`is_saved=False`) across both tenants.
    """
    admin_identity, customer_identity = await _resolve_test_identities()
    admin_token = _mint_supabase_jwt(admin_identity["sub"], admin_identity["email"])
    customer_token = _mint_supabase_jwt(
        customer_identity["sub"], customer_identity["email"]
    )
    run_tag = uuid.uuid4().hex[:6].upper()

    created_by_tenant: Dict[str, Dict[str, str]] = {}

    async with _e2e_client() as client:
        for slug in TENANT_SLUGS:
            # 1. Customer attempting to create TENANT-shared B2B Warehouse must fail (403)
            res_cust_forbidden = await client.post(
                "/api/v1/addresses",
                headers=_build_headers(slug, customer_token),
                json={
                    "name": f"Forbidden Shared Hub {run_tag}",
                    "phone": "+919811112222",
                    "address_line1": f"Plot 99 Industrial Area {run_tag}",
                    "city": "Pune",
                    "state": "Maharashtra",
                    "pincode": "411001",
                    "country": "IN",
                    "category": "WAREHOUSE",
                    "scope": "TENANT",
                },
            )
            assert res_cust_forbidden.status_code == 403, res_cust_forbidden.text

            # 2. Customer creates Personal (PRIVATE) Address -> 200 OK
            res_cust_priv = await client.post(
                "/api/v1/addresses",
                headers=_build_headers(slug, customer_token),
                json={
                    "name": f"Cust Personal {slug} {run_tag}",
                    "phone": "+919822223333",
                    "address_line1": f"Flat 12B Green Park {slug} {run_tag}",
                    "city": "Bangalore",
                    "state": "Karnataka",
                    "pincode": "560001",
                    "country": "IN",
                    "category": "HOME",
                    "scope": "PRIVATE",
                },
            )
            assert res_cust_priv.status_code == 200, res_cust_priv.text
            cust_priv_id = res_cust_priv.json()["id"]
            assert res_cust_priv.json()["is_saved"] is True
            assert res_cust_priv.json()["scope"] == "PRIVATE"

            # 3. Admin creates PRIVATE Office Address AND Shared B2B Warehouse (TENANT) Address
            res_admin_priv = await client.post(
                "/api/v1/addresses",
                headers=_build_headers(slug, admin_token),
                json={
                    "name": f"Admin Private Office {slug} {run_tag}",
                    "phone": "+919833334444",
                    "address_line1": f"Suite 400 Cyber Tower {slug} {run_tag}",
                    "city": "Hyderabad",
                    "state": "Telangana",
                    "pincode": "500081",
                    "country": "IN",
                    "category": "OFFICE",
                    "scope": "PRIVATE",
                },
            )
            assert res_admin_priv.status_code == 200, res_admin_priv.text
            admin_priv_id = res_admin_priv.json()["id"]

            res_admin_shared = await client.post(
                "/api/v1/addresses",
                headers=_build_headers(slug, admin_token),
                json={
                    "name": f"Shared B2B Hub {slug} {run_tag}",
                    "phone": "+919844445555",
                    "company_name": f"{slug.upper()} Central Logistics",
                    "gstin": "27AABCU9603R1ZM",
                    "address_line1": f"Dock 7 MIDC Hub {slug} {run_tag}",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                    "country": "IN",
                    "category": "WAREHOUSE",
                    "scope": "TENANT",
                },
            )
            assert res_admin_shared.status_code == 200, res_admin_shared.text
            admin_shared_id = res_admin_shared.json()["id"]
            assert res_admin_shared.json()["scope"] == "TENANT"

            created_by_tenant[slug] = {
                "cust_priv_id": cust_priv_id,
                "admin_priv_id": admin_priv_id,
                "admin_shared_id": admin_shared_id,
            }

            # 4. Verify GET /api/v1/addresses scope isolation within tenant
            res_list_cust = await client.get(
                "/api/v1/addresses",
                headers=_build_headers(slug, customer_token),
            )
            assert res_list_cust.status_code == 200
            cust_visible_ids = {a["id"] for a in res_list_cust.json()}
            assert cust_priv_id in cust_visible_ids
            assert admin_shared_id in cust_visible_ids
            assert (
                admin_priv_id not in cust_visible_ids
            ), "Customer must NOT see Admin PRIVATE address"

            res_list_admin = await client.get(
                "/api/v1/addresses",
                headers=_build_headers(slug, admin_token),
            )
            assert res_list_admin.status_code == 200
            admin_visible_ids = {a["id"] for a in res_list_admin.json()}
            assert admin_priv_id in admin_visible_ids
            assert admin_shared_id in admin_visible_ids
            assert (
                cust_priv_id not in admin_visible_ids
            ), "Admin list_saved_addresses must NOT leak Customer PRIVATE address"

            # 5. Verify PUT /api/v1/addresses/{id}
            res_put_cust = await client.put(
                f"/api/v1/addresses/{cust_priv_id}",
                headers=_build_headers(slug, customer_token),
                json={
                    "landmark": "Near Metro Station Gate 2",
                    "city": "Bengaluru",
                },
            )
            assert res_put_cust.status_code == 200, res_put_cust.text
            assert res_put_cust.json()["city"] == "Bengaluru"
            assert res_put_cust.json()["landmark"] == "Near Metro Station Gate 2"

            # Customer cannot PUT Admin's TENANT shared warehouse -> 403
            res_put_forbidden = await client.put(
                f"/api/v1/addresses/{admin_shared_id}",
                headers=_build_headers(slug, customer_token),
                json={"landmark": "Unauthorized Edit"},
            )
            assert res_put_forbidden.status_code == 403

            # 6. Verify DELETE /api/v1/addresses/{id} soft-delete (`is_saved=False`)
            res_del_cust = await client.delete(
                f"/api/v1/addresses/{cust_priv_id}",
                headers=_build_headers(slug, customer_token),
            )
            assert res_del_cust.status_code == 200, res_del_cust.text

            # Verify soft-deleted row in DB still exists with is_saved == False
            async with AsyncSessionLocal() as session:
                db_addr = await session.get(Address, uuid.UUID(cust_priv_id))
                assert db_addr is not None
                assert db_addr.is_saved is False

            # And no longer appears in GET /api/v1/addresses
            res_list_after_del = await client.get(
                "/api/v1/addresses",
                headers=_build_headers(slug, customer_token),
            )
            assert cust_priv_id not in {a["id"] for a in res_list_after_del.json()}

        # 7. Verify strict Cross-Tenant Isolation: the test tenant's shared address is never
        # visible through another tenant's slug (read-only probe; 403 = no membership there).
        test_shared_id = created_by_tenant[GOLDEN_TENANT_SLUG]["admin_shared_id"]
        probe_list = await client.get(
            "/api/v1/addresses",
            headers=_build_headers(CROSS_TENANT_PROBE_SLUG, admin_token),
        )
        assert probe_list.status_code in (200, 403, 404), probe_list.text
        probe_ids = (
            {a["id"] for a in probe_list.json()} if probe_list.status_code == 200 else set()
        )
        assert test_shared_id not in probe_ids, "Cross-tenant address leak detected!"


@pytest.mark.asyncio
async def test_03_rate_calculator_b2c_and_b2b_math() -> None:
    """
    Verifies POST /api/v1/quotes across B2C (0.5 kg, 2.5 kg, PREPAID vs COD)
    and B2B Heavy Cargo (60 kg multi-box, Prime vs Delhivery options, Door Delivery)
    under both roles & tenants, and verifies retired /rates/calculate returns 404.
    """
    admin_identity, customer_identity = await _resolve_test_identities()
    admin_token = _mint_supabase_jwt(admin_identity["sub"], admin_identity["email"])
    customer_token = _mint_supabase_jwt(
        customer_identity["sub"], customer_identity["email"]
    )

    async with _e2e_client() as client:
        for slug in TENANT_SLUGS:
            for token in (admin_token, customer_token):
                headers = _build_headers(slug, token)

                # Retired endpoints must 404
                res_retired = await client.post(
                    "/api/v1/rates/calculate", headers=headers, json={}
                )
                assert res_retired.status_code == 404

                # 1. B2C: 0.5 kg Prepaid
                res_b2c_half = await client.post(
                    "/api/v1/quotes",
                    headers=headers,
                    json={
                        "service_flow": "B2C",
                        "pickup_pincode": "500081",
                        "delivery_pincode": "560001",
                        "shipment_type": "FORWARD",
                        "packages": [
                            {
                                "length": 10.0,
                                "breadth": 10.0,
                                "height": 10.0,
                                "weight": 0.5,
                                "box_count": 1,
                            }
                        ],
                        "is_cod": False,
                        "cod_amount": 0.0,
                        "shipment_value": 1200.0,
                    },
                )
                assert res_b2c_half.status_code == 200, res_b2c_half.text
                opts_half = {
                    o["service_option"]: o for o in res_b2c_half.json()["options"]
                }
                q_half = opts_half["DELHIVERY_SURFACE"]
                assert q_half["serviceable"] is True
                assert q_half["chargeable_weight_kg"] == 0.5
                assert q_half["freight_amount"] == 52.5
                assert q_half["tax_amount"] == 9.45
                assert q_half["total_amount"] == 61.95

                # 2. B2C: 2.5 kg COD
                res_b2c_cod = await client.post(
                    "/api/v1/quotes",
                    headers=headers,
                    json={
                        "service_flow": "B2C",
                        "pickup_pincode": "500081",
                        "delivery_pincode": "560001",
                        "shipment_type": "FORWARD",
                        "packages": [
                            {
                                "length": 30.0,
                                "breadth": 20.0,
                                "height": 15.0,
                                "weight": 2.5,
                                "box_count": 1,
                            }
                        ],
                        "is_cod": True,
                        "cod_amount": 2000.0,
                        "add_shipping_to_cod": True,
                        "shipment_value": 2000.0,
                    },
                )
                assert res_b2c_cod.status_code == 200, res_b2c_cod.text
                opts_cod = {
                    o["service_option"]: o for o in res_b2c_cod.json()["options"]
                }
                q_cod = opts_cod["DELHIVERY_SURFACE"]
                assert q_cod["chargeable_weight_kg"] == 2.5
                assert q_cod["freight_amount"] == 162.5
                assert q_cod["cod_fee"] == 40.0  # 2% of 2000
                assert q_cod["tax_amount"] == 36.45
                assert q_cod["total_amount"] == 238.95

                # 3. B2B Heavy Cargo: 60 kg actual, 100 kg Prime volumetric (122001 -> 400001)
                b2b_packages = [
                    {
                        "length": 125.0,
                        "breadth": 40.0,
                        "height": 30.0,
                        "weight": 20.0,
                        "box_count": 3,
                    }
                ]
                res_b2b_godown = await client.post(
                    "/api/v1/quotes",
                    headers=headers,
                    json={
                        "service_flow": "B2B",
                        "pickup_pincode": "122001",
                        "delivery_pincode": "400001",
                        "shipment_type": "FORWARD",
                        "packages": b2b_packages,
                        "is_cod": False,
                        "cod_amount": 0.0,
                        "shipment_value": 75000.0,
                        "door_delivery": False,
                    },
                )
                assert res_b2b_godown.status_code == 200, res_b2b_godown.text
                opts_b2b = {
                    o["service_option"]: o for o in res_b2b_godown.json()["options"]
                }
                q_prime = opts_b2b["PRIME_SURFACE"]
                assert q_prime["serviceable"] is True
                assert q_prime["chargeable_weight_kg"] == 100.0
                assert q_prime["freight_amount"] == 2040.0
                assert q_prime["total_amount"] == 2407.2

                res_b2b_door = await client.post(
                    "/api/v1/quotes",
                    headers=headers,
                    json={
                        "service_flow": "B2B",
                        "pickup_pincode": "122001",
                        "delivery_pincode": "400001",
                        "shipment_type": "FORWARD",
                        "packages": b2b_packages,
                        "is_cod": False,
                        "cod_amount": 0.0,
                        "shipment_value": 75000.0,
                        "door_delivery": True,
                    },
                )
                assert res_b2b_door.status_code == 200, res_b2b_door.text
                opts_door = {
                    o["service_option"]: o for o in res_b2b_door.json()["options"]
                }
                q_prime_door = opts_door["PRIME_SURFACE"]
                assert q_prime_door["freight_amount"] == 2760.0
                assert q_prime_door["total_amount"] == 3256.8


@pytest.mark.asyncio
async def test_04_b2c_express_shipment_full_lifecycle() -> None:
    """
    Verifies the complete B2C Express Shipment Lifecycle on the guarded test tenant
    under both Admin and Customer identities:
    - Prepaid & COD creation with `add_shipping_to_cod=True` (`cod_amount == 2000.0 + total_logistics_cost`)
    - `GET /api/v1/shipments?is_b2b=false` & `GET /api/v1/shipments/{id}` (multi-tenant + RBAC ownership)
    - `PUT /api/v1/shipments/{id}` (Address snapshot immutability + server price recalculation)
    - `GET /api/v1/shipments/{id}/label?label_format=a4` (`%PDF-` binary verification)
    - `GET /api/v1/shipments/{id}/timeline` & `GET /api/v1/tracking/{tracking_id}` (unauthenticated public tracking)
    - `POST /api/v1/shipments/{id}/cancel` (`CANCELLED` state verification)
    """
    admin_identity, customer_identity = await _resolve_test_identities()
    admin_token = _mint_supabase_jwt(admin_identity["sub"], admin_identity["email"])
    customer_token = _mint_supabase_jwt(
        customer_identity["sub"], customer_identity["email"]
    )
    run_tag = uuid.uuid4().hex[:6].upper()

    async with _e2e_client() as client:
        for slug in TENANT_SLUGS:
            await _ensure_wallet_funded(
                client, slug, customer_token, admin_token, min_balance=2000.0
            )
            await _ensure_wallet_funded(
                client, slug, admin_token, admin_token, min_balance=2000.0
            )
            # 1. Customer creates B2C COD shipment with add_shipping_to_cod=True
            cust_cod_payload = {
                "order_reference_id": f"B2C-COD-{slug.upper()}-{run_tag}",
                "shipment_type": "FORWARD",
                "service_type": "SURFACE_ROAD",
                "requested_pickup_date": str(date.today() + timedelta(days=1)),
                "pickup_time_slot": "10:00 - 14:00",
                "product_category": "ELECTRONICS",
                "new_pickup_address": {
                    "name": "B2C Sender Hub",
                    "phone": "+919876500001",
                    "address_line1": "Plot 12 HSR Layout",
                    "city": "Bangalore",
                    "state": "Karnataka",
                    "pincode": "560001",
                    "country": "IN",
                },
                "new_delivery_address": {
                    "name": "B2C Consignee",
                    "phone": "+919876500002",
                    "address_line1": "Flat 402 Banjara Hills",
                    "city": "Hyderabad",
                    "state": "Telangana",
                    "pincode": "500081",
                    "country": "IN",
                },
                "packages": [
                    {
                        "length": 25.0,
                        "breadth": 20.0,
                        "height": 10.0,
                        "weight": 1.5,
                        "box_count": 1,
                        "description": "Wireless Headphones",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": True,
                    "cod_amount": 2000.0,
                    "add_shipping_to_cod": True,
                    "shipment_value": 1800.0,
                    "shipment_tax_value": 200.0,
                    "shipment_total_value": 2000.0,
                },
            }
            res_create_cod = await client.post(
                "/api/v1/shipments",
                headers=_build_headers(slug, customer_token),
                json=cust_cod_payload,
            )
            assert res_create_cod.status_code == 201, res_create_cod.text
            cod_shipment = res_create_cod.json()

            pay = cod_shipment["payment_details"]
            expected_cod = round(2000.0 + pay["total_logistics_cost"], 2)
            assert pay["cod_amount"] == expected_cod, (
                f"Expected cod_amount={expected_cod}, got {pay['cod_amount']}"
            )

            # 2. Admin creates B2C Prepaid shipment
            admin_prepaid_payload = {
                **cust_cod_payload,
                "order_reference_id": f"B2C-PRE-{slug.upper()}-{run_tag}",
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": False,
                    "cod_amount": 0.0,
                    "add_shipping_to_cod": False,
                    "shipment_value": 1500.0,
                    "shipment_tax_value": 0.0,
                    "shipment_total_value": 1500.0,
                },
            }
            res_create_pre = await client.post(
                "/api/v1/shipments",
                headers=_build_headers(slug, admin_token),
                json=admin_prepaid_payload,
            )
            assert res_create_pre.status_code == 201, res_create_pre.text
            pre_shipment = res_create_pre.json()

            # 3. Verify GET /api/v1/shipments?is_b2b=false & RBAC visibility
            res_list_cust = await client.get(
                "/api/v1/shipments?is_b2b=false&page=1&size=50",
                headers=_build_headers(slug, customer_token),
            )
            assert res_list_cust.status_code == 200
            cust_shipment_ids = {s["id"] for s in res_list_cust.json()["items"]}
            assert cod_shipment["id"] in cust_shipment_ids
            assert (
                pre_shipment["id"] not in cust_shipment_ids
            ), "Customer must NOT see Admin's shipment"

            # Customer GET /api/v1/shipments/{admin_shipment_id} -> 404
            res_detail_forbidden = await client.get(
                f"/api/v1/shipments/{pre_shipment['id']}",
                headers=_build_headers(slug, customer_token),
            )
            assert res_detail_forbidden.status_code == 404

            # 4. Verify PUT /api/v1/shipments/{id} (Admin edits dimensions & delivery address -> new Address snapshot + recalculated cost)
            original_delivery_addr_id = pre_shipment["delivery_address"]["id"]
            original_cost = pre_shipment["payment_details"]["total_logistics_cost"]
            pkg_id = pre_shipment["packages"][0]["id"]

            res_put = await client.put(
                f"/api/v1/shipments/{pre_shipment['id']}",
                headers=_build_headers(slug, admin_token),
                json={
                    "status": "OPEN",
                    "comment": "Confirmed and upgraded weight + address snapshot",
                    "is_public": True,
                    "new_delivery_address": {
                        "name": "B2C Consignee Updated",
                        "phone": "+919876599999",
                        "address_line1": "Tower 9 Mindspace",
                        "city": "Hyderabad",
                        "state": "Telangana",
                        "pincode": "500081",
                        "country": "IN",
                    },
                    "packages": [
                        {
                            "id": pkg_id,
                            "length": 40.0,
                            "breadth": 30.0,
                            "height": 20.0,
                            "weight": 4.5,
                            "box_count": 1,
                            "description": "Upgraded Package",
                        }
                    ],
                },
            )
            assert res_put.status_code == 200, res_put.text
            updated_pre = res_put.json()
            assert updated_pre["delivery_address"]["id"] != original_delivery_addr_id
            assert (
                updated_pre["payment_details"]["total_logistics_cost"] > original_cost
            )
            assert updated_pre["payment_details"]["chargeable_weight"] == 5.0

            # 5. Verify GET /api/v1/shipments/{id}/label?label_format=a4
            res_label = await client.get(
                f"/api/v1/shipments/{updated_pre['id']}/label?label_format=a4",
                headers=_build_headers(slug, admin_token),
            )
            assert res_label.status_code == 200
            assert res_label.headers["content-type"] == "application/pdf"
            assert res_label.content.startswith(b"%PDF-")

            # 6. Verify GET /api/v1/shipments/{id}/timeline & unauthenticated GET /api/v1/tracking/{tracking_id}
            res_timeline = await client.get(
                f"/api/v1/shipments/{updated_pre['id']}/timeline",
                headers=_build_headers(slug, admin_token),
            )
            assert res_timeline.status_code == 200
            assert len(res_timeline.json()) >= 2

            res_public_track = await client.get(
                f"/api/v1/tracking/{updated_pre['tracking_id']}",
                headers=_build_headers(slug),  # No Authorization header!
            )
            assert res_public_track.status_code == 200, res_public_track.text
            assert res_public_track.json()["tracking_id"] == updated_pre["tracking_id"]
            assert len(res_public_track.json()["timeline"]) >= 1

            # 7. Verify POST /api/v1/shipments/{id}/cancel for both Customer and Admin
            res_cancel_cust = await client.post(
                f"/api/v1/shipments/{cod_shipment['id']}/cancel",
                headers=_build_headers(slug, customer_token),
            )
            assert res_cancel_cust.status_code == 200, res_cancel_cust.text
            assert res_cancel_cust.json()["status"] in ("CANCELLED", "CANCELED")

            res_cancel_admin = await client.post(
                f"/api/v1/shipments/{updated_pre['id']}/cancel",
                headers=_build_headers(slug, admin_token),
            )
            assert res_cancel_admin.status_code == 200, res_cancel_admin.text
            assert res_cancel_admin.json()["status"] in ("CANCELLED", "CANCELED")


@pytest.mark.asyncio
async def test_05_06_07_b2b_cargo_manifests_and_ndr_resolution_lifecycle() -> None:
    """
    Verifies:
    - B2B Heavy Cargo Forward (multi-box, PO number, E-Way bill > 50k validation, Carrier's Risk)
    - B2B Heavy Cargo Reverse Return refused with 400 (MVP scope)
    - `GET /api/v1/shipments?is_b2b=true`
    - `PATCH /api/v1/shipments/{id}/appointment`
    - `GET /api/v1/shipments/{id}/label?label_format=thermal_4x2` (`%PDF-` thermal 4x2 box label)
    - B2B Fleet Pickup / Manifest Lifecycle (`POST /api/v1/manifests` manifested & blind,
      `GET /api/v1/manifests`, `POST /api/v1/manifests/{id}/cancel` resetting shipment to `OPEN`)
    - NDR Delivery Exception Resolution (`DELIVER_WITHOUT_APPOINTMENT` & `UPDATE_CONSIGNEE_DETAILS`)
    on the guarded test tenant.
    """
    admin_identity, customer_identity = await _resolve_test_identities()
    admin_token = _mint_supabase_jwt(admin_identity["sub"], admin_identity["email"])
    customer_token = _mint_supabase_jwt(
        customer_identity["sub"], customer_identity["email"]
    )
    b2b_customer = (await load_accounts())[CUSTOMER_B2B_EMAIL]
    b2b_customer_token = _mint_supabase_jwt(b2b_customer["sub"], b2b_customer["email"])
    run_tag = uuid.uuid4().hex[:6].upper()

    async with _e2e_client() as client:
        for slug in TENANT_SLUGS:
            await _ensure_wallet_funded(
                client, slug, admin_token, admin_token, min_balance=12000.0
            )
            await _ensure_wallet_funded(
                client, slug, customer_token, admin_token, min_balance=8000.0
            )
            # 1. Verify E-Way Bill > 50,000 INR validation rejects missing E-Way Bill
            invalid_b2b_payload = {
                "order_reference_id": f"B2B-NOEWB-{slug.upper()}-{run_tag}",
                "shipment_type": "FORWARD",
                "service_type": "SURFACE_ROAD",
                "requested_pickup_date": str(date.today() + timedelta(days=1)),
                "pickup_time_slot": "06:00 - 10:00",
                "product_category": "COMMERCIAL",
                "po_number": f"PO-{run_tag}",
                "is_carriers_risk": True,
                "new_pickup_address": {
                    "name": "Origin Factory",
                    "phone": "+919900011111",
                    "address_line1": "Plot 10 Udyog Vihar",
                    "city": "Gurugram",
                    "state": "Haryana",
                    "pincode": "122001",
                    "country": "IN",
                },
                "new_delivery_address": {
                    "name": "Regional Distribution Center",
                    "phone": "+919900022222",
                    "address_line1": "Unit 14 Ballard Estate",
                    "city": "Mumbai",
                    "state": "Maharashtra",
                    "pincode": "400001",
                    "country": "IN",
                },
                "packages": [
                    {
                        "length": 60.0,
                        "breadth": 40.0,
                        "height": 40.0,
                        "weight": 30.0,
                        "box_count": 2,
                        "description": "Industrial Valves",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": False,
                    "cod_amount": 0.0,
                    "shipment_value": 55000.0,
                    "shipment_tax_value": 9900.0,
                    "shipment_total_value": 64900.0,
                    "eway_bill_numbers": [],
                },
            }
            res_missing_ewb = await client.post(
                "/api/v1/shipments",
                headers=_build_headers(slug, admin_token),
                json=invalid_b2b_payload,
            )
            assert res_missing_ewb.status_code in (400, 422), res_missing_ewb.text

            # 2. Create valid B2B Forward Heavy Cargo Shipment with 12-digit E-Way Bill
            valid_b2b_fwd_payload = {
                **invalid_b2b_payload,
                "order_reference_id": f"B2B-FWD-{slug.upper()}-{run_tag}",
                "payment_details": {
                    **invalid_b2b_payload["payment_details"],
                    "invoice_numbers": [f"INV-{run_tag}-1"],
                    "eway_bill_numbers": ["123456789012"],
                },
            }
            res_b2b_fwd = await client.post(
                "/api/v1/shipments",
                headers=_build_headers(slug, admin_token),
                json=valid_b2b_fwd_payload,
            )
            assert res_b2b_fwd.status_code == 201, res_b2b_fwd.text
            b2b_fwd = res_b2b_fwd.json()
            assert b2b_fwd["total_box_count"] == 2
            pb_fwd = b2b_fwd["payment_details"]["pricing_breakdown"]
            assert pb_fwd["service_option"] == "PRIME_SURFACE"
            assert pb_fwd["base_charge"] == 1560.0
            assert "DOCKET" in [line["code"] for line in (pb_fwd.get("sell_lines") or [])]

            # 2b. Verify Track B Carrier's Risk fallback: shipment_value=45000, shipment_tax_value=0, shipment_total_value=0, is_carriers_risk=True -> 201 Created
            carriers_risk_fallback_payload = {
                **invalid_b2b_payload,
                "order_reference_id": f"B2B-CR45K-{slug.upper()}-{run_tag}",
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": False,
                    "cod_amount": 0.0,
                    "shipment_value": 45000.0,
                    "shipment_tax_value": 0.0,
                    "shipment_total_value": 0.0,
                },
            }
            res_cr_fallback = await client.post(
                "/api/v1/shipments",
                headers=_build_headers(slug, admin_token),
                json=carriers_risk_fallback_payload,
            )
            assert res_cr_fallback.status_code == 201, res_cr_fallback.text
            b2b_cr45k = res_cr_fallback.json()
            assert b2b_cr45k["payment_details"]["shipment_total_value"] == 45000.0
            assert b2b_cr45k["is_carriers_risk"] is True

            # 3. MVP Scope (DESIGN.md v4 §9): B2B Reverse LR bookings are refused with 400
            b2b_rev_payload = {
                "order_reference_id": f"B2B-REV-{slug.upper()}-{run_tag}",
                "shipment_type": "REVERSE",
                "service_type": "SURFACE_ROAD",
                "requested_pickup_date": str(date.today() + timedelta(days=1)),
                "pickup_time_slot": "14:00 - 18:00",
                "product_category": "COMMERCIAL",
                "po_number": f"PO-REV-{run_tag}",
                "reason_for_return": "Damaged outer carton on arrival",
                "pickup_qc_params": {
                    "verify_seal": True,
                    "qc_notes": "Verify serial barcode and inner foam intact",
                },
                "is_carriers_risk": True,
                "new_pickup_address": valid_b2b_fwd_payload["new_delivery_address"],
                "new_delivery_address": valid_b2b_fwd_payload["new_pickup_address"],
                "packages": [
                    {
                        "length": 50.0,
                        "breadth": 40.0,
                        "height": 30.0,
                        "weight": 20.0,
                        "box_count": 1,
                        "description": "Returned Industrial Unit",
                    }
                ],
                "payment_details": {
                    "freight_payment_mode": "PREPAID",
                    "is_cod": False,
                    "cod_amount": 0.0,
                    "shipment_total_value": 25000.0,
                },
            }
            res_b2b_rev = await client.post(
                "/api/v1/shipments",
                headers=_build_headers(slug, b2b_customer_token),
                json=b2b_rev_payload,
            )
            assert res_b2b_rev.status_code == 400, res_b2b_rev.text
            assert "reverse" in res_b2b_rev.json()["detail"].lower()

            # 4. Verify GET /api/v1/shipments?is_b2b=true includes the B2B shipments
            res_b2b_list = await client.get(
                "/api/v1/shipments?is_b2b=true&page=1&size=50",
                headers=_build_headers(slug, admin_token),
            )
            assert res_b2b_list.status_code == 200
            b2b_ids = {s["id"] for s in res_b2b_list.json()["items"]}
            assert b2b_fwd["id"] in b2b_ids
            assert b2b_cr45k["id"] in b2b_ids

            # 5. Verify PATCH /api/v1/shipments/{id}/appointment
            appt_start = (
                datetime.now(timezone.utc) + timedelta(days=2)
            ).replace(microsecond=0)
            appt_end = appt_start + timedelta(hours=3)
            res_appt = await client.patch(
                f"/api/v1/shipments/{b2b_fwd['id']}/appointment",
                headers=_build_headers(slug, admin_token),
                json={
                    "appointment_start": appt_start.isoformat(),
                    "appointment_end": appt_end.isoformat(),
                    "po_number": f"PO-UPD-{run_tag}",
                },
            )
            assert res_appt.status_code == 200, res_appt.text
            assert res_appt.json()["po_number"] == f"PO-UPD-{run_tag}"
            assert res_appt.json()["appointment_start"] is not None

            # 6. Verify GET /api/v1/shipments/{id}/label?label_format=thermal_4x2
            res_thermal = await client.get(
                f"/api/v1/shipments/{b2b_fwd['id']}/label?label_format=thermal_4x2",
                headers=_build_headers(slug, admin_token),
            )
            assert res_thermal.status_code == 200
            assert res_thermal.headers["content-type"] == "application/pdf"
            assert res_thermal.content.startswith(b"%PDF-")

            # 7. B2B Fleet Pickup / Manifest Full Lifecycle
            # First transition b2b_fwd from DRAFT -> OPEN so it can be linked to a Manifest
            res_open = await client.patch(
                f"/api/v1/shipments/{b2b_fwd['id']}",
                headers=_build_headers(slug, admin_token),
                json={"status": "OPEN", "comment": "Ready for fleet manifest dispatch"},
            )
            assert res_open.status_code == 200, res_open.text
            assert res_open.json()["status"] == "OPEN"

            # 7a. Create Manifested Pickup linking the OPEN B2B shipment
            res_manifest = await client.post(
                "/api/v1/manifests",
                headers=_build_headers(slug, admin_token),
                json={
                    "pickup_address_id": b2b_fwd["pickup_address"]["id"],
                    "scheduled_date": str(date.today() + timedelta(days=1)),
                    "time_slot": "06:00 - 10:00",
                    "is_blind_pickup": False,
                    "total_boxes": 2,
                    "shipment_ids": [b2b_fwd["id"]],
                },
            )
            assert res_manifest.status_code == 201, res_manifest.text
            manifest_data = res_manifest.json()
            assert manifest_data["status"] == "SCHEDULED"

            # Verify linked shipment transitioned to ASSIGNED with manifest_id set
            res_check_assigned = await client.get(
                f"/api/v1/shipments/{b2b_fwd['id']}",
                headers=_build_headers(slug, admin_token),
            )
            assert res_check_assigned.json()["status"] == "ASSIGNED"
            assert res_check_assigned.json()["manifest_id"] == manifest_data["id"]

            # 7b. Blind Pickup without any LR is refused (D-07: cartons need an AWB + bill)
            res_blind_manifest = await client.post(
                "/api/v1/manifests",
                headers=_build_headers(slug, admin_token),
                json={
                    "pickup_address_id": b2b_fwd["pickup_address"]["id"],
                    "scheduled_date": str(date.today() + timedelta(days=1)),
                    "time_slot": "14:00 - 18:00",
                    "is_blind_pickup": True,
                    "total_boxes": 15,
                    "shipment_ids": [],
                },
            )
            assert res_blind_manifest.status_code == 400, res_blind_manifest.text
            assert "at least one LR" in res_blind_manifest.json()["detail"]

            # 7c. Verify GET /api/v1/manifests lists the manifest
            res_list_manifests = await client.get(
                "/api/v1/manifests",
                headers=_build_headers(slug, admin_token),
            )
            assert res_list_manifests.status_code == 200
            manifest_ids_in_list = {m["id"] for m in res_list_manifests.json()}
            assert manifest_data["id"] in manifest_ids_in_list

            # 7d. Cancel Manifest -> assert CANCELED and linked shipment resets to OPEN with manifest_id=None
            res_cancel_manifest = await client.post(
                f"/api/v1/manifests/{manifest_data['id']}/cancel",
                headers=_build_headers(slug, admin_token),
            )
            assert res_cancel_manifest.status_code == 200, res_cancel_manifest.text
            assert res_cancel_manifest.json()["status"] == "CANCELED"

            res_check_reset = await client.get(
                f"/api/v1/shipments/{b2b_fwd['id']}",
                headers=_build_headers(slug, admin_token),
            )
            assert res_check_reset.json()["status"] == "OPEN"
            assert res_check_reset.json()["manifest_id"] is None

            # 8. NDR Delivery Exception Resolution Lifecycle
            # Transition OPEN -> ASSIGNED -> IN_TRANSIT -> EXCEPTION (APPOINTMENT_NEEDED)
            for next_status, ndr_val in [
                ("ASSIGNED", None),
                ("IN_TRANSIT", None),
                ("EXCEPTION", "APPOINTMENT_NEEDED"),
            ]:
                patch_body: Dict[str, Any] = {
                    "status": next_status,
                    "comment": f"Transition to {next_status}",
                }
                if ndr_val:
                    patch_body["ndr_reason"] = ndr_val
                res_st = await client.patch(
                    f"/api/v1/shipments/{b2b_fwd['id']}",
                    headers=_build_headers(slug, admin_token),
                    json=patch_body,
                )
                assert res_st.status_code == 200, res_st.text

            # 8a. Resolve Exception #1: DELIVER_WITHOUT_APPOINTMENT
            res_resolve_1 = await client.post(
                f"/api/v1/shipments/{b2b_fwd['id']}/resolve-exception",
                headers=_build_headers(slug, admin_token),
                json={
                    "action": "DELIVER_WITHOUT_APPOINTMENT",
                    "notes": "Dock manager approved direct unloading without prior slot",
                },
            )
            assert res_resolve_1.status_code == 200, res_resolve_1.text
            resolved_1 = res_resolve_1.json()
            assert resolved_1["status"] == "IN_TRANSIT"
            assert resolved_1["ndr_reason"] is None

            # 8b. Transition back to EXCEPTION (CONSIGNEE_DETAILS_REQUIRED per Delhivery Cargo
            # b2b-exceptions-management matrix) and Resolve Exception #2: UPDATE_CONSIGNEE_DETAILS
            res_exc_2 = await client.patch(
                f"/api/v1/shipments/{b2b_fwd['id']}",
                headers=_build_headers(slug, admin_token),
                json={
                    "status": "EXCEPTION",
                    "ndr_reason": "CONSIGNEE_DETAILS_REQUIRED",
                    "comment": "Consignee phone unreachable at gate",
                },
            )
            assert res_exc_2.status_code == 200, res_exc_2.text
            prev_deliv_addr_id = res_exc_2.json()["delivery_address"]["id"]

            res_resolve_2 = await client.post(
                f"/api/v1/shipments/{b2b_fwd['id']}/resolve-exception",
                headers=_build_headers(slug, admin_token),
                json={
                    "action": "UPDATE_CONSIGNEE_DETAILS",
                    "consignee_phone": "+919988877766",
                    "consignee_address_line1": "Gate 5 Unloading Bay B, Sector 62",
                    "notes": "Updated alternate receiver phone and dock gate",
                },
            )
            assert res_resolve_2.status_code == 200, res_resolve_2.text
            resolved_2 = res_resolve_2.json()
            assert resolved_2["status"] == "IN_TRANSIT"
            assert resolved_2["ndr_reason"] is None
            assert resolved_2["delivery_address"]["id"] != prev_deliv_addr_id
            assert resolved_2["delivery_address"]["phone"] == "+919988877766"
            assert (
                resolved_2["delivery_address"]["address_line1"]
                == "Gate 5 Unloading Bay B, Sector 62"
            )

            # Verify both resolution activities are logged in the shipment timeline
            res_ndr_timeline = await client.get(
                f"/api/v1/shipments/{b2b_fwd['id']}/timeline",
                headers=_build_headers(slug, admin_token),
            )
            assert res_ndr_timeline.status_code == 200
            summaries = [evt["summary"] for evt in res_ndr_timeline.json()]
            assert (
                "Deliver without appointment authorised (DELIVER_WITHOUT_APPOINTMENT)"
                in summaries
            )
            assert "Consignee details updated (UPDATE_CONSIGNEE)" in summaries
