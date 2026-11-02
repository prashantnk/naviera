"""
Production-readiness permission guards (Phase P).

Covers merchant-facing holes found in the journey audit:
- `POST /wallet/recharge/verify-utr` must not let a customer credit their own wallet.
- `GET /users` must not let a customer enumerate every workspace user's email.
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


def _customer_like(base_user: User) -> User:
    """Builds an in-memory customer that belongs to the cached test tenant."""
    return User(
        id=uuid.uuid4(),
        email="pr-guard-customer@example.com",
        supabase_user_id=f"pr-guard-{uuid.uuid4()}",
        tenant_id=base_user.tenant_id,
        role=UserRole.customer,
        service_scope=ServiceScope.B2C,
        is_active=True,
    )


@pytest.fixture
def as_customer():
    """Overrides the authenticated user with a customer for the test duration."""
    admin_override = app.dependency_overrides[get_current_active_user]
    holder: dict = {}

    async def _customer():
        if "user" not in holder:
            holder["user"] = _customer_like(await admin_override())
        return holder["user"]

    app.dependency_overrides[get_current_active_user] = _customer
    yield
    app.dependency_overrides[get_current_active_user] = admin_override


async def test_customer_cannot_verify_utr(as_customer):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            f"{settings.API_V1_STR}/wallet/recharge/verify-utr",
            json={"amount": 100000.0, "utr_number": str(uuid.uuid4().int)[:12]},
            headers=HEADERS,
        )
    assert res.status_code == 403, res.text


async def test_customer_cannot_list_workspace_users(as_customer):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"{settings.API_V1_STR}/users", headers=HEADERS)
    assert res.status_code == 403, res.text


async def test_admin_can_list_workspace_users():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(f"{settings.API_V1_STR}/users", headers=HEADERS)
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)
