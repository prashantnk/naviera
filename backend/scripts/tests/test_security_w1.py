"""
Wave W1 security regressions (go-live S1, S3, S5b).

- S1: `/users/auth/signup` never overwrites an existing `auth.users` password.
- S3: unauthenticated tenant endpoints only expose allow-listed settings; the
  full settings are admin-only; restoring a version keeps `b2b_access_requests`.
- S5b: a pickup request (manifest) can only hold one customer's shipments, and a
  customer needs to own ALL linked shipments to access it.

Every write happens inside the per-test transaction from conftest (rolled back),
including the `auth.users` rows, so nothing is left behind in the shared DB.
"""

import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import text

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.main import app
from app.models.manifests import Manifest
from app.models.pickups import PickupRequest
from app.models.tenants import (
    ServiceScope,
    Tenant,
    TenantSettingsHistory,
    User,
    UserRole,
)
from app.repositories.tenants import TenantRepository
from app.services.manifests import ERR_MIXED_CUSTOMERS
from app.services.tenants import PUBLIC_WALLET_CONFIG_KEYS, SIGNUP_EMAIL_EXISTS_DETAIL

HEADERS = {"X-Tenant-Slug": "naviera"}
USERS_URL = f"{settings.API_V1_STR}/users"
SIGNUP_URL = f"{USERS_URL}/auth/signup"
LOGIN_URL = f"{USERS_URL}/auth/login"
TENANTS_URL = f"{settings.API_V1_STR}/tenants"
SETTINGS_URL = f"{TENANTS_URL}/settings"
MANIFESTS_URL = f"{settings.API_V1_STR}/manifests"
SHIPMENTS_URL = f"{settings.API_V1_STR}/shipments"

ORIGINAL_PASSWORD = "Original-Pass-123"
ATTACKER_PASSWORD = "Attacker-Pass-456"
KYC_GSTIN = "27AAPFU0939F1ZV"
KYC_PAN = "AAPFU0939F"
SECRET_VPA = "w1-secret-vpa@okaxis"
STAFF_ROLES_DENIED = (
    UserRole.customer,
    UserRole.operations_user,
    UserRole.support_user,
    UserRole.read_only_user,
)


# --------------------------------------------------------------------------- helpers


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _unique_email(tag: str) -> str:
    return f"w1-sec-{tag}-{uuid.uuid4().hex[:8]}@example.com"


async def _cached_tenant() -> Tenant:
    return await app.dependency_overrides[get_tenant_from_header]()


async def _acting_user(role: UserRole) -> User:
    """The conftest actor re-cast to `role`, pinned to the cached tenant."""
    actor = await app.dependency_overrides[get_current_active_user]()
    tenant = await _cached_tenant()
    return User(**{**actor.model_dump(), "tenant_id": tenant.id, "role": role})


def _act_as(user: User) -> None:
    async def _override() -> User:
        return user

    app.dependency_overrides[get_current_active_user] = _override


def _serve_tenant(tenant: Tenant) -> None:
    async def _override() -> Tenant:
        return tenant

    app.dependency_overrides[get_tenant_from_header] = _override


async def _password_hash(db_session, email: str) -> str:
    row = (
        await db_session.execute(
            text("SELECT encrypted_password FROM auth.users WHERE lower(email) = :email"),
            {"email": email.lower()},
        )
    ).first()
    assert row is not None
    return row[0]


async def _persisted_tenant(db_session) -> Tenant:
    cached = await _cached_tenant()
    tenant = await db_session.get(Tenant, cached.id)
    assert tenant is not None
    return tenant


async def _seed_private_settings(db_session, b2b_requests: dict) -> Tenant:
    """Adds KYC requests, a secret VPA and a rate card to the persisted tenant settings."""
    tenant = await _persisted_tenant(db_session)
    current = dict(tenant.settings or {})
    wallet = dict(current.get("wallet_config") or {})
    wallet.update({"merchant_vpa": SECRET_VPA, "merchant_name": "W1 Merchant", "strict_finlock": True})
    pricing = dict(current.get("pricing_policy") or {})
    pricing.setdefault("delhivery_markup_percent", 0.0)
    current.update(
        {
            "b2b_access_requests": b2b_requests,
            "wallet_config": wallet,
            "pricing_policy": pricing,
            "brand": dict(current.get("brand") or {}, primary_color="#112233"),
        }
    )
    tenant.settings = current
    flag_modified(tenant, "settings")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


def _kyc_request(company: str) -> dict:
    return {
        str(uuid.uuid4()): {
            "status": "PENDING",
            "company_name": company,
            "gstin": KYC_GSTIN,
            "pan": KYC_PAN,
            "notes": "w1 private note",
        }
    }


def _assert_public_payload(payload: dict) -> None:
    public_settings = payload["settings"]
    assert "b2b_access_requests" not in public_settings
    assert "pricing_policy" not in public_settings
    assert "company" not in public_settings
    assert set(public_settings.get("wallet_config", {})) <= set(PUBLIC_WALLET_CONFIG_KEYS)
    assert public_settings["brand"]["primary_color"] == "#112233"


# --------------------------------------------------------------------------- S1


@pytest.mark.asyncio
async def test_signup_with_existing_email_returns_409_and_keeps_password(db_session):
    email = _unique_email("existing")
    repo = TenantRepository(db_session)
    assert await repo.create_auth_user_with_password(email, ORIGINAL_PASSWORD) is not None
    original_hash = await _password_hash(db_session, email)

    async with _client() as client:
        for candidate in (email, email.upper()):
            res = await client.post(
                SIGNUP_URL,
                json={"email": candidate, "password": ATTACKER_PASSWORD},
                headers=HEADERS,
            )
            assert res.status_code == 409, res.text
            assert res.json()["detail"] == SIGNUP_EMAIL_EXISTS_DETAIL

        assert await _password_hash(db_session, email) == original_hash
        assert await repo.verify_auth_user_password(email, ATTACKER_PASSWORD) is None

        # Signing in with the existing password JIT-provisions a customer here.
        res = await client.post(
            LOGIN_URL, json={"email": email, "password": ORIGINAL_PASSWORD}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        assert res.json()["user"]["role"] == UserRole.customer.value
        assert res.json()["user"]["email"] == email

        res = await client.post(
            LOGIN_URL, json={"email": email, "password": ATTACKER_PASSWORD}, headers=HEADERS
        )
        assert res.status_code == 401


@pytest.mark.asyncio
async def test_create_auth_user_is_conflict_safe(db_session):
    email = _unique_email("dup")
    repo = TenantRepository(db_session)
    assert await repo.create_auth_user_with_password(email, ORIGINAL_PASSWORD) is not None
    original_hash = await _password_hash(db_session, email)
    assert await repo.create_auth_user_with_password(email, ATTACKER_PASSWORD) is None
    assert await _password_hash(db_session, email) == original_hash


@pytest.mark.asyncio
async def test_invited_unregistered_email_can_still_sign_up(db_session):
    tenant = await _cached_tenant()
    email = _unique_email("invited")
    invited = User(
        email=email,
        supabase_user_id=f"invited:{email}",
        tenant_id=tenant.id,
        full_name="Invited Ops",
        role=UserRole.operations_user,
        service_scope=ServiceScope.BOTH,
        is_active=True,
    )
    db_session.add(invited)
    await db_session.flush()

    async with _client() as client:
        res = await client.post(
            SIGNUP_URL,
            json={"email": email, "password": ORIGINAL_PASSWORD, "terms_accepted": True},
            headers=HEADERS,
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["user"]["id"] == str(invited.id)
    assert body["user"]["role"] == UserRole.operations_user.value
    assert not body["supabase_user_id"].startswith("invited:")
    assert await TenantRepository(db_session).verify_auth_user_password(email, ORIGINAL_PASSWORD)


# --------------------------------------------------------------------------- S3


@pytest.mark.asyncio
async def test_public_tenant_endpoints_hide_private_settings(db_session):
    tenant = await _seed_private_settings(db_session, _kyc_request("W1 Public Leak Co"))
    _serve_tenant(tenant)

    async with _client() as client:
        public_res = await client.get(f"{TENANTS_URL}/{tenant.slug}/public")
        config_res = await client.get(f"{TENANTS_URL}/config", headers=HEADERS)

    for res in (public_res, config_res):
        assert res.status_code == 200, res.text
        _assert_public_payload(res.json())
        for secret in (KYC_GSTIN, KYC_PAN, "W1 Public Leak Co", SECRET_VPA, "strict_finlock"):
            assert secret not in res.text
    assert public_res.json()["settings"]["wallet_config"]["merchant_name"] == "W1 Merchant"


@pytest.mark.asyncio
async def test_admin_settings_endpoint_is_owner_admin_only(db_session):
    tenant = await _seed_private_settings(db_session, _kyc_request("W1 Admin View Co"))
    _serve_tenant(tenant)

    async with _client() as client:
        for role in STAFF_ROLES_DENIED:
            _act_as(await _acting_user(role))
            res = await client.get(SETTINGS_URL, headers=HEADERS)
            assert res.status_code == 403, (role, res.text)

        for role in (UserRole.owner, UserRole.admin):
            _act_as(await _acting_user(role))
            res = await client.get(SETTINGS_URL, headers=HEADERS)
            assert res.status_code == 200, (role, res.text)
            full = res.json()["settings"]
            assert full["wallet_config"]["merchant_vpa"] == SECRET_VPA
            assert "pricing_policy" in full
            assert any(
                entry.get("gstin") == KYC_GSTIN
                for entry in full["b2b_access_requests"].values()
            )


@pytest.mark.asyncio
async def test_team_kyc_listing_stays_admin_only(db_session):
    async with _client() as client:
        for role in STAFF_ROLES_DENIED:
            _act_as(await _acting_user(role))
            res = await client.get(USERS_URL, headers=HEADERS)
            assert res.status_code == 403, (role, res.text)
        _act_as(await _acting_user(UserRole.admin))
        res = await client.get(USERS_URL, headers=HEADERS)
        assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_restore_keeps_current_b2b_access_requests(db_session):
    _act_as(await _acting_user(UserRole.admin))
    old_requests = _kyc_request("W1 Old Request Co")
    await _seed_private_settings(db_session, old_requests)
    tag = uuid.uuid4().hex[:6]

    async with _client() as client:
        for text_value in (f"v1 {tag}", f"v2 {tag}"):
            res = await client.patch(
                SETTINGS_URL, json={"announcement_bar": {"text": text_value}}, headers=HEADERS
            )
            assert res.status_code == 200, res.text
        history = (await client.get(f"{SETTINGS_URL}/history", headers=HEADERS)).json()
        v1_snapshot_id = history[0]["id"]

        snapshot = await db_session.get(TenantSettingsHistory, uuid.UUID(v1_snapshot_id))
        assert "b2b_access_requests" not in (snapshot.settings or {})

        # A new B2B request arrives after the snapshot was taken.
        tenant = await _persisted_tenant(db_session)
        new_requests = dict(old_requests, **_kyc_request("W1 New Request Co"))
        tenant.settings = dict(tenant.settings, b2b_access_requests=new_requests)
        flag_modified(tenant, "settings")
        db_session.add(tenant)
        await db_session.flush()

        res = await client.post(f"{SETTINGS_URL}/restore/{v1_snapshot_id}", headers=HEADERS)
        assert res.status_code == 200, res.text
        restored = res.json()["settings"]
        assert restored["announcement_bar"]["text"] == f"v1 {tag}"
        assert restored["b2b_access_requests"] == new_requests


# --------------------------------------------------------------------------- S5b


def _pickup_location(tag: str) -> dict:
    return {
        "name": f"W1 Warehouse {tag}",
        "phone": "9000000001",
        "address_line1": f"Plot W1-{tag}, Koramangala",
        "city": "Bengaluru",
        "state": "KA",
        "pincode": "560034",
    }


def _shipment_payload(pickup: dict) -> dict:
    return {
        "order_reference_id": f"W1-{uuid.uuid4().hex[:6]}",
        "shipment_type": "FORWARD",
        "service_type": "SURFACE_ROAD",
        "requested_pickup_date": str(date.today()),
        "pickup_time_slot": "10:00 - 14:00",
        "product_category": "ELECTRONICS",
        "is_carriers_risk": False,
        "new_pickup_address": dict(pickup),
        "new_delivery_address": {
            "name": "Consignee",
            "phone": "8888888888",
            "address_line1": "Road 2",
            "city": "Mumbai",
            "state": "MH",
            "pincode": "400001",
        },
        "packages": [
            {"length": 20.0, "breadth": 20.0, "height": 10.0, "weight": 1.0, "box_count": 1, "description": "Box"}
        ],
        "payment_details": {
            "freight_payment_mode": "PREPAID",
            "is_cod": False,
            "cod_amount": 0.0,
            "shipment_total_value": 1000.0,
        },
    }


async def _create_open_shipment(client: AsyncClient, pickup: dict) -> dict:
    res = await client.post(SHIPMENTS_URL, json=_shipment_payload(pickup), headers=HEADERS)
    assert res.status_code == 201, res.text
    shipment = res.json()
    res = await client.patch(
        f"{SHIPMENTS_URL}/{shipment['id']}",
        json={"status": "OPEN", "comment": "Ready to ship"},
        headers=HEADERS,
    )
    assert res.status_code == 200, res.text
    return shipment


async def _create_customer(db_session, tag: str) -> User:
    tenant = await _cached_tenant()
    customer = User(
        email=_unique_email(f"cust-{tag}"),
        supabase_user_id=f"w1-test-{tag}-{uuid.uuid4().hex[:6]}",
        tenant_id=tenant.id,
        role=UserRole.customer,
        service_scope=ServiceScope.B2C,
        is_active=True,
    )
    db_session.add(customer)
    await db_session.flush()
    return customer


async def _reassign_shipment(db_session, shipment_id: str, owner: User) -> PickupRequest:
    shipment = await db_session.get(PickupRequest, uuid.UUID(shipment_id))
    shipment.created_by_user_id = owner.id
    db_session.add(shipment)
    await db_session.flush()
    return shipment


def _pur_body(location_id: str, shipment_ids: list) -> dict:
    return {
        "pickup_address_id": location_id,
        "scheduled_date": str(date.today()),
        "time_slot": "14:00 - 18:00",
        "service_flow": "B2C",
        "is_blind_pickup": False,
        "total_boxes": 0,
        "shipment_ids": shipment_ids,
    }


@pytest.mark.asyncio
async def test_mixed_customer_pickup_request_rejected(db_session):
    tag = uuid.uuid4().hex[:6]
    pickup = _pickup_location(tag)
    _act_as(await _acting_user(UserRole.admin))
    customer_a = await _create_customer(db_session, f"a{tag}")
    customer_b = await _create_customer(db_session, f"b{tag}")

    async with _client() as client:
        ship_a = await _create_open_shipment(client, pickup)
        ship_b = await _create_open_shipment(client, pickup)
        await _reassign_shipment(db_session, ship_a["id"], customer_a)
        await _reassign_shipment(db_session, ship_b["id"], customer_b)
        location_id = ship_a["pickup_address"]["id"]

        res = await client.post(
            MANIFESTS_URL, json=_pur_body(location_id, [ship_a["id"], ship_b["id"]]), headers=HEADERS
        )
        assert res.status_code == 400, res.text
        assert res.json()["detail"] == ERR_MIXED_CUSTOMERS

        res = await client.get(
            f"{MANIFESTS_URL}/pickup-candidates",
            params={"shipment_ids": [ship_a["id"], ship_b["id"]]},
            headers=HEADERS,
        )
        assert res.status_code == 400, res.text

        res = await client.post(MANIFESTS_URL, json=_pur_body(location_id, [ship_a["id"]]), headers=HEADERS)
        assert res.status_code == 201, res.text
        pur_id = res.json()["id"]

        res = await client.post(
            f"{MANIFESTS_URL}/{pur_id}/shipments", json={"shipment_ids": [ship_b["id"]]}, headers=HEADERS
        )
        assert res.status_code == 400, res.text
        assert res.json()["detail"] == ERR_MIXED_CUSTOMERS

        res = await client.get(
            f"{MANIFESTS_URL}/pickup-candidates", params={"shipment_ids": [ship_b["id"]]}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        assert all(c["id"] != pur_id for c in res.json()["candidates"])

        # The owning customer keeps access to their single-customer PUR.
        _act_as(customer_a)
        res = await client.get(MANIFESTS_URL, headers=HEADERS)
        assert any(m["id"] == pur_id for m in res.json())


@pytest.mark.asyncio
async def test_customer_needs_all_linked_shipments_to_access_pickup(db_session):
    """A legacy mixed PUR (forced in the DB) is invisible to both customers."""
    tag = uuid.uuid4().hex[:6]
    pickup = _pickup_location(tag)
    _act_as(await _acting_user(UserRole.admin))
    customer_a = await _create_customer(db_session, f"a{tag}")
    customer_b = await _create_customer(db_session, f"b{tag}")

    async with _client() as client:
        ship_a = await _create_open_shipment(client, pickup)
        ship_b = await _create_open_shipment(client, pickup)
        await _reassign_shipment(db_session, ship_a["id"], customer_a)
        location_id = ship_a["pickup_address"]["id"]
        res = await client.post(MANIFESTS_URL, json=_pur_body(location_id, [ship_a["id"]]), headers=HEADERS)
        assert res.status_code == 201, res.text
        pur_id = res.json()["id"]

        foreign = await _reassign_shipment(db_session, ship_b["id"], customer_b)
        foreign.manifest_id = uuid.UUID(pur_id)
        db_session.add(foreign)
        await db_session.flush()
        manifest = await db_session.get(Manifest, uuid.UUID(pur_id))
        db_session.expire(manifest, ["pickups"])

        for customer in (customer_a, customer_b):
            _act_as(customer)
            res = await client.get(f"{MANIFESTS_URL}/{pur_id}/labels", headers=HEADERS)
            assert res.status_code == 403, res.text
            res = await client.get(f"{MANIFESTS_URL}/{pur_id}/pdf", headers=HEADERS)
            assert res.status_code == 403, res.text
            res = await client.post(f"{MANIFESTS_URL}/{pur_id}/cancel", headers=HEADERS)
            assert res.status_code == 403, res.text
            res = await client.get(MANIFESTS_URL, headers=HEADERS)
            assert all(m["id"] != pur_id for m in res.json())
