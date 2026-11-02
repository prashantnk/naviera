"""
Platform Settings version history + validation (Phase O.7, S1) and tenant
endpoint security (own-tenant scoping, owner protection).
All writes happen inside the per-test transaction from conftest (rolled back).
"""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import func, select

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.main import app
from app.models.tenants import ServiceScope, Tenant, TenantSettingsHistory, User, UserRole
from app.services.tenants import SETTINGS_HISTORY_LIMIT

HEADERS = {"X-Tenant-Slug": "naviera"}
TENANTS_URL = f"{settings.API_V1_STR}/tenants"
SETTINGS_URL = f"{TENANTS_URL}/settings"
HISTORY_URL = f"{SETTINGS_URL}/history"
USERS_URL = f"{settings.API_V1_STR}/users"


async def _tenant() -> Tenant:
    return await app.dependency_overrides[get_tenant_from_header]()


async def _tenant_admin() -> User:
    """The cached admin, pinned to the cached tenant (settings are tenant-scoped)."""
    admin = await app.dependency_overrides[get_current_active_user]()
    tenant = await _tenant()
    return User(**{**admin.model_dump(), "tenant_id": tenant.id, "role": UserRole.admin})


def _as_user(user: User) -> None:
    async def _override():
        return user

    app.dependency_overrides[get_current_active_user] = _override


async def _patch(client: AsyncClient, body: dict, expected: int = 200) -> dict:
    res = await client.patch(SETTINGS_URL, json=body, headers=HEADERS)
    assert res.status_code == expected, res.text
    return res.json()


async def _history(client: AsyncClient) -> list:
    res = await client.get(HISTORY_URL, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
async def as_tenant_admin():
    """Run the test as an Admin of the cached tenant; restores the original override."""
    original = app.dependency_overrides[get_current_active_user]
    admin = await _tenant_admin()
    _as_user(admin)
    yield admin
    app.dependency_overrides[get_current_active_user] = original


@pytest.mark.asyncio
async def test_snapshot_on_update_records_previous_settings(as_tenant_admin):
    tag = uuid.uuid4().hex[:6]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _patch(client, {"announcement_bar": {"text": f"first {tag}"}})
        before = await _history(client)

        saved = await _patch(client, {"announcement_bar": {"text": f"second {tag}"}})
        assert saved["settings"]["announcement_bar"]["text"] == f"second {tag}"

        after = await _history(client)
        newest = after[0]
        assert newest["changed_sections"] == ["announcement_bar"]
        assert newest["changed_by_email"] == as_tenant_admin.email
        assert newest["version"] == (before[0]["version"] + 1 if before else newest["version"])
        assert set(newest) == {"id", "version", "created_at", "changed_by_email", "changed_sections"}

        # A no-op save doesn't create a version.
        await _patch(client, {"announcement_bar": {"text": f"second {tag}"}})
        assert (await _history(client))[0]["id"] == newest["id"]


@pytest.mark.asyncio
async def test_history_is_capped_at_twenty_versions(db_session, as_tenant_admin):
    tenant = await _tenant()
    max_version = (
        await db_session.exec(
            select(func.max(TenantSettingsHistory.version)).where(
                TenantSettingsHistory.tenant_id == tenant.id
            )
        )
    ).one() or 0
    for offset in range(1, SETTINGS_HISTORY_LIMIT + 5):
        db_session.add(
            TenantSettingsHistory(
                tenant_id=tenant.id,
                version=max_version + offset,
                settings={"seed": offset},
                changed_sections=["seed"],
            )
        )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _patch(client, {"announcement_bar": {"text": f"cap {uuid.uuid4().hex[:6]}"}})
        history = await _history(client)
    assert len(history) == SETTINGS_HISTORY_LIMIT
    versions = [h["version"] for h in history]
    assert versions == sorted(versions, reverse=True)
    assert versions[0] == max_version + SETTINGS_HISTORY_LIMIT + 5


@pytest.mark.asyncio
async def test_restore_round_trip(as_tenant_admin):
    tag = uuid.uuid4().hex[:6]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await _patch(client, {"announcement_bar": {"text": f"v1 {tag}"}})
        await _patch(client, {"announcement_bar": {"text": f"v2 {tag}"}})
        history = await _history(client)
        v1_snapshot = history[0]  # settings as they were BEFORE the v2 save

        res = await client.post(f"{SETTINGS_URL}/restore/{v1_snapshot['id']}", headers=HEADERS)
        assert res.status_code == 200, res.text
        assert res.json()["settings"]["announcement_bar"]["text"] == f"v1 {tag}"

        after = await _history(client)
        assert after[0]["version"] == v1_snapshot["version"] + 1  # v2 was snapshotted first
        assert "announcement_bar" in after[0]["changed_sections"]

        res = await client.post(f"{SETTINGS_URL}/restore/{uuid.uuid4()}", headers=HEADERS)
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_validation_rejects_bad_values_with_field_paths(as_tenant_admin):
    cases = [
        ({"brand": {"primary_color": "blue"}}, ["body", "settings", "brand", "primary_color"]),
        ({"wallet_config": {"merchant_vpa": "not-a-vpa"}}, ["body", "settings", "wallet_config", "merchant_vpa"]),
        (
            {"services_page": {"services": [{"title": "Air", "description": "Fast", "icon": "rocket"}]}},
            ["body", "settings", "services_page", "services", 0, "icon"],
        ),
        ({"pricing_policy": {"cod_fee_percent": 40}}, ["body", "settings", "pricing_policy", "cod_fee_percent"]),
        ({"brand": {"logo_url": "http://insecure.example.com/logo.png"}}, ["body", "settings", "brand", "logo_url"]),
        ({"contact": {"gstin": "12345"}}, ["body", "settings", "contact", "gstin"]),
        ({"contact": {"emails": ["ops@example.com", "nope"]}}, ["body", "settings", "contact", "emails", 1]),
        ({"about_page": {"headline": "x" * 121}}, ["body", "settings", "about_page", "headline"]),
    ]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for body, loc in cases:
            res = await client.patch(SETTINGS_URL, json=body, headers=HEADERS)
            assert res.status_code == 422, (body, res.text)
            assert any(err["loc"] == loc for err in res.json()["detail"]), (loc, res.json())

        # Legacy icon spelling is accepted and normalised; blank optional fields are fine.
        saved = await _patch(
            client,
            {
                "services_page": {"services": [{"title": "Road", "description": "FTL", "icon": "Truck"}]},
                "contact": {"gstin": "", "socials": {"facebook": ""}},
                "wallet_config": {"merchant_vpa": "logismart@okaxis"},
                "pricing_policy": {"cod_fee_percent": 2.0, "cod_fee_min": 30.0},
            },
        )
        assert saved["settings"]["services_page"]["services"][0]["icon"] == "truck"
        assert saved["settings"]["wallet_config"]["merchant_vpa"] == "logismart@okaxis"


@pytest.mark.asyncio
async def test_legacy_unknown_keys_preserved_and_show_logo_default(db_session, as_tenant_admin):
    cached = await _tenant()
    persisted = await db_session.get(Tenant, cached.id)
    before_settings = dict(persisted.settings or {})
    existing_keys = set(before_settings.keys())
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        saved = await _patch(
            client,
            {
                "legacy_widget": {"enabled": True, "nested": {"x": 1}},
                "brand": {"primary_color": "#112233", "legacy_brand_flag": "keep-me"},
            },
        )
        stored = saved["settings"]
        assert stored["legacy_widget"] == {"enabled": True, "nested": {"x": 1}}
        assert stored["brand"]["legacy_brand_flag"] == "keep-me"
        assert stored["brand"]["primary_color"] == "#112233"
        assert existing_keys <= set(stored)  # nothing existing was dropped
        if (before_settings.get("brand") or {}).get("show_logo") is None:
            assert stored["brand"]["show_logo"] is True

        hidden = await _patch(client, {"brand": {"show_logo": False}})
        assert hidden["settings"]["brand"]["show_logo"] is False
        again = await _patch(client, {"announcement_bar": {"text": "still hidden"}})
        assert again["settings"]["brand"]["show_logo"] is False


@pytest.mark.asyncio
async def test_customer_forbidden_on_settings_and_tenant_listing(db_session, as_tenant_admin):
    customer = User(**{**as_tenant_admin.model_dump(), "id": uuid.uuid4(), "role": UserRole.customer})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(TENANTS_URL, headers=HEADERS)
        assert res.status_code == 200
        assert [t["id"] for t in res.json()] == [str(as_tenant_admin.tenant_id)]

        _as_user(customer)
        await _patch(client, {"announcement_bar": {"text": "nope"}}, expected=403)
        assert (await client.get(HISTORY_URL, headers=HEADERS)).status_code == 403
        res = await client.post(f"{SETTINGS_URL}/restore/{uuid.uuid4()}", headers=HEADERS)
        assert res.status_code == 403
        assert (await client.get(TENANTS_URL, headers=HEADERS)).status_code == 403
        res = await client.get(f"{TENANTS_URL}/{as_tenant_admin.tenant_id}/users", headers=HEADERS)
        assert res.status_code == 403


@pytest.mark.asyncio
async def test_owner_protection_rules(db_session, as_tenant_admin):
    tenant = await _tenant()
    tag = uuid.uuid4().hex[:8]
    acting_admin, owner = (
        User(
            supabase_user_id=f"{role.value}-test-{tag}",
            email=f"{role.value}-{tag}@example.com",
            role=role,
            service_scope=ServiceScope.BOTH,
            tenant_id=tenant.id,
        )
        for role in (UserRole.admin, UserRole.owner)
    )
    db_session.add_all([acting_admin, owner])
    await db_session.flush()
    _as_user(acting_admin)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # An admin can't promote themselves to owner.
        res = await client.patch(
            f"{USERS_URL}/{acting_admin.id}", json={"role": "owner"}, headers=HEADERS
        )
        assert res.status_code == 403, res.text
        # An admin can't deactivate or demote the owner.
        res = await client.patch(f"{USERS_URL}/{owner.id}", json={"is_active": False}, headers=HEADERS)
        assert res.status_code == 400, res.text
        res = await client.patch(f"{USERS_URL}/{owner.id}", json={"role": "admin"}, headers=HEADERS)
        assert res.status_code == 400, res.text

        # The owner can transfer ownership; they become an admin.
        _as_user(owner)
        res = await client.patch(
            f"{USERS_URL}/{acting_admin.id}", json={"role": "owner"}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        assert res.json()["role"] == "owner"
        refreshed_owner = await db_session.get(User, owner.id)
        assert refreshed_owner.role == UserRole.admin
