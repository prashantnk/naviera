"""
Launch onboarding flow: everyone signs up themselves, then Owner/Admin promote them.

- `PATCH /api/v1/users/me` lets any signed-in user change their own name / phone.
- The invite endpoint (`POST /api/v1/users/invite`) is gone.
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


async def _signed_up_customer(db_session) -> User:
    """A freshly self-signed-up customer in the conftest actor's tenant."""
    admin_user = await app.dependency_overrides[get_current_active_user]()
    customer = User(
        tenant_id=admin_user.tenant_id,
        email=f"self-{uuid.uuid4().hex[:8]}@example.com",
        supabase_user_id=f"test-signup:{uuid.uuid4()}",
        role=UserRole.customer,
        service_scope=ServiceScope.B2C,
        is_active=True,
    )
    db_session.add(customer)
    await db_session.flush()
    return customer


async def test_any_user_can_edit_own_name_and_phone(db_session):
    admin_override = app.dependency_overrides[get_current_active_user]
    customer = await _signed_up_customer(db_session)

    async def _as_customer():
        return customer

    app.dependency_overrides[get_current_active_user] = _as_customer
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            ok = await client.patch(
                f"{settings.API_V1_STR}/users/me",
                json={"full_name": "  Ravi Kumar  ", "phone": "98765-43210"},
                headers=HEADERS,
            )
            assert ok.status_code == 200, ok.text
            assert ok.json()["full_name"] == "Ravi Kumar"
            assert ok.json()["phone"] == "9876543210"
            # Self-edit can never change role / scope (fields are ignored).
            assert ok.json()["role"] == "customer"

            blank = await client.patch(
                f"{settings.API_V1_STR}/users/me", json={"full_name": "   "}, headers=HEADERS
            )
            assert blank.status_code == 400, blank.text

            bad_phone = await client.patch(
                f"{settings.API_V1_STR}/users/me", json={"phone": "12ab"}, headers=HEADERS
            )
            assert bad_phone.status_code == 400, bad_phone.text

            cleared = await client.patch(
                f"{settings.API_V1_STR}/users/me", json={"phone": ""}, headers=HEADERS
            )
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["phone"] is None
    finally:
        app.dependency_overrides[get_current_active_user] = admin_override


async def test_owner_admin_promote_a_signed_up_customer(db_session):
    customer = await _signed_up_customer(db_session)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        promoted = await client.patch(
            f"{settings.API_V1_STR}/users/{customer.id}",
            json={"role": "operations_user", "account_type": "TENANT_STAFF", "service_scope": "BOTH"},
            headers=HEADERS,
        )
        assert promoted.status_code == 200, promoted.text
        assert promoted.json()["role"] == "operations_user"
        assert promoted.json()["service_scope"] == "BOTH"


async def test_invite_endpoint_is_removed(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            f"{settings.API_V1_STR}/users/invite",
            json={"full_name": "X", "email": "x@example.com"},
            headers=HEADERS,
        )
        assert res.status_code in (404, 405), res.text
