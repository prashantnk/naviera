"""
Production-readiness Job C: money / correctness guards.

1. Maker-checker: nobody approves their own wallet recharge.
2. COD settlement ledger category uses the shared B2B classifier.
3. No invoice for CANCELLED / TO_PAY shipments; no label for CANCELLED ones.
4. Bookings require payment details and a serviceable, non-zero quote.
5. Customer `service_scope` is enforced on booking (admins exempt).
All writes happen inside the per-test transaction from conftest (rolled back).
"""

import uuid
from datetime import date

import pytest
from golden_journeys.golden_env import allow_to_pay_bookings, make_utr
from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.main import app
from app.models.pickups import PickupRequest, PickupStatus, ServiceOption
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.models.wallet import WalletTransaction, WalletTxnType
from app.schemas.v1.pricing import PricingPolicy
from app.services.pricing.quote_service import OPTION_DISABLED_REASON

HEADERS = {"X-Tenant-Slug": "naviera"}
API = settings.API_V1_STR
SHIPMENTS_URL = f"{API}/shipments"
PIN_ENDING_IN_NINE = "400009"
"""Ends in 9 (refused by the retired stub, D8); serviceable under FakeDelhiveryApi."""
UNSERVICEABLE_PIN = "999999"


def _without_express(tenant: Tenant) -> Tenant:
    """A detached copy of the tenant whose pricing policy disables DELHIVERY_EXPRESS."""
    tenant_settings = dict(tenant.settings or {})
    policy = PricingPolicy(enabled_options=[ServiceOption.DELHIVERY_SURFACE, ServiceOption.PRIME_SURFACE])
    tenant_settings["pricing_policy"] = policy.model_dump(mode="json")
    return Tenant(**dict(tenant.model_dump(), settings=tenant_settings))


def _with_tenant(tenant: Tenant) -> None:
    async def _override():
        return tenant

    app.dependency_overrides[get_tenant_from_header] = _override


def _payload(*, b2b: bool = False, cod: bool = False, freight_mode: str = "PREPAID",
             service_type: str = "SURFACE_ROAD", delivery_pincode: str = "400001") -> dict:
    tag = uuid.uuid4().hex[:8]
    return {
        "order_reference_id": f"JOBC-{tag}",
        "shipment_type": "FORWARD",
        "service_type": service_type,
        "requested_pickup_date": str(date.today()),
        "product_category": "ELECTRONICS",
        "is_carriers_risk": b2b,
        "new_pickup_address": {
            "name": f"Job C WH {tag}", "phone": "9000000005", "address_line1": f"Unit {tag}",
            "city": "Gurugram", "state": "HR", "pincode": "122001",
        },
        "new_delivery_address": {
            "name": "Job C Consignee", "phone": "8888888888", "address_line1": "Road 4",
            "city": "Mumbai", "state": "MH", "pincode": delivery_pincode,
        },
        "packages": [{"length": 10.0, "breadth": 10.0, "height": 10.0, "weight": 1.0, "box_count": 1}],
        "payment_details": {
            "freight_payment_mode": freight_mode,
            "is_cod": cod,
            "cod_amount": 700.0 if cod else 0.0,
            "shipment_total_value": 1000.0,
        },
    }


async def _real_user(db_session, role: UserRole, scope: ServiceScope = ServiceScope.BOTH) -> User:
    tenant = await app.dependency_overrides[get_tenant_from_header]()
    tag = uuid.uuid4().hex[:10]
    user = User(
        supabase_user_id=f"jobc-{role.value}-{tag}",
        email=f"jobc-{role.value}-{tag}@example.com",
        role=role,
        service_scope=scope,
        tenant_id=tenant.id,
    )
    db_session.add(user)
    await db_session.flush()
    return user


def _as_user(user: User) -> None:
    async def _override():
        return user

    app.dependency_overrides[get_current_active_user] = _override


@pytest.fixture
async def restore_user_override():
    original = app.dependency_overrides[get_current_active_user]
    yield
    app.dependency_overrides[get_current_active_user] = original


@pytest.mark.asyncio
async def test_recharge_maker_checker(db_session, restore_user_override):
    maker = await _real_user(db_session, UserRole.admin)
    checker = await _real_user(db_session, UserRole.admin)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _as_user(maker)
        res = await client.post(f"{API}/wallet/recharge/upi-intent", json={"amount": 250}, headers=HEADERS)
        assert res.status_code == 200, res.text
        txn_id = res.json()["transaction_id"]
        res = await client.post(
            f"{API}/wallet/recharge/{txn_id}/confirm", json={"utr_number": make_utr()}, headers=HEADERS
        )
        assert res.status_code == 200, res.text
        res = await client.post(f"{API}/wallet/recharge/{txn_id}/approve", headers=HEADERS)
        assert res.status_code == 403, res.text
        assert "Maker-checker" in res.json()["detail"]

        _as_user(checker)
        res = await client.post(f"{API}/wallet/recharge/{txn_id}/approve", headers=HEADERS)
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_settle_cod_uses_shared_b2b_classifier(db_session):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(SHIPMENTS_URL, json=_payload(cod=True), headers=HEADERS)
        assert res.status_code == 201, res.text
        ship = res.json()
        shipment = await db_session.get(PickupRequest, uuid.UUID(ship["id"]))
        shipment.status = PickupStatus.COMPLETED
        db_session.add(shipment)
        await db_session.flush()

        res = await client.post(f"{API}/wallet/settle-cod", headers=HEADERS)
        assert res.status_code == 200, res.text
    txn = (
        await db_session.exec(
            select(WalletTransaction).where(
                WalletTransaction.shipment_id == uuid.UUID(ship["id"]),
                WalletTransaction.txn_type == WalletTxnType.COD_SETTLEMENT.value,
            )
        )
    ).first()
    assert txn is not None
    assert txn.service_category == "B2C"  # has packages, but it's a B2C parcel


@pytest.mark.asyncio
async def test_documents_blocked_for_cancelled_and_to_pay():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(SHIPMENTS_URL, json=_payload(), headers=HEADERS)
        assert res.status_code == 201, res.text
        cancelled = res.json()
        res = await client.post(f"{SHIPMENTS_URL}/{cancelled['id']}/cancel", headers=HEADERS)
        assert res.status_code == 200, res.text
        assert (await client.get(f"{SHIPMENTS_URL}/{cancelled['id']}/label", headers=HEADERS)).status_code == 400
        assert (await client.get(f"{SHIPMENTS_URL}/{cancelled['id']}/invoice-pdf", headers=HEADERS)).status_code == 400

        with allow_to_pay_bookings():
            res = await client.post(SHIPMENTS_URL, json=_payload(freight_mode="TO_PAY"), headers=HEADERS)
        assert res.status_code == 201, res.text
        to_pay = res.json()
        res = await client.get(f"{SHIPMENTS_URL}/{to_pay['id']}/invoice-pdf", headers=HEADERS)
        assert res.status_code == 400
        assert "TO_PAY" in res.json()["detail"]
        res = await client.get(f"{SHIPMENTS_URL}/{to_pay['id']}/label", headers=HEADERS)
        assert res.status_code == 200
        assert res.content.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_booking_requires_payment_details_and_bookable_quote():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = _payload()
        body.pop("payment_details")
        res = await client.post(SHIPMENTS_URL, json=body, headers=HEADERS)
        assert res.status_code == 422
        assert any(err["loc"][-1] == "payment_details" for err in res.json()["detail"])

        # D8: no pin-suffix stub; 400009 is serviceable, unserviceable pin (999999) is 400,
        # and disabled Express option is 400.
        res = await client.post(
            SHIPMENTS_URL, json=_payload(service_type="AIR", delivery_pincode=PIN_ENDING_IN_NINE), headers=HEADERS
        )
        assert res.status_code == 201, res.text
        res = await client.post(
            SHIPMENTS_URL, json=_payload(service_type="AIR", delivery_pincode=UNSERVICEABLE_PIN), headers=HEADERS
        )
        assert res.status_code == 400, res.text
        _with_tenant(_without_express(await app.dependency_overrides[get_tenant_from_header]()))
        res = await client.post(
            SHIPMENTS_URL, json=_payload(service_type="AIR", delivery_pincode=PIN_ENDING_IN_NINE), headers=HEADERS
        )
        assert res.status_code == 400, res.text
        assert res.json()["detail"] == OPTION_DISABLED_REASON


@pytest.mark.asyncio
async def test_customer_service_scope_enforced_on_booking(db_session, restore_user_override):
    b2c_only = await _real_user(db_session, UserRole.customer, ServiceScope.B2C)
    b2b_only = await _real_user(db_session, UserRole.customer, ServiceScope.B2B)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _as_user(b2c_only)
        res = await client.post(SHIPMENTS_URL, json=_payload(b2b=True), headers=HEADERS)
        assert res.status_code == 403, res.text
        res = await client.post(SHIPMENTS_URL, json=_payload(), headers=HEADERS)
        assert res.status_code == 201, res.text

        _as_user(b2b_only)
        res = await client.post(SHIPMENTS_URL, json=_payload(), headers=HEADERS)
        assert res.status_code == 403, res.text
        res = await client.post(SHIPMENTS_URL, json=_payload(b2b=True), headers=HEADERS)
        assert res.status_code == 201, res.text
