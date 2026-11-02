"""
B2B Manage Appointments API (`GET /api/v1/appointments`).

Rows are inserted inside the per-test transaction from `conftest.db_session`
(rolled back afterwards), so nothing is left in the shared database.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.main import app
from app.models.pickups import (
    Address,
    NdrExceptionReason,
    PickupRequest,
    PickupStatus,
    PickupStrategy,
    ProductCategory,
)
from app.models.tenants import User, UserRole
from app.repositories.appointments import AppointmentFilters, AppointmentsRepository
from app.schemas.v1.appointments import AppointmentTab
from app.services.appointments import AppointmentsService

HEADERS = {"X-Tenant-Slug": "naviera"}
APPOINTMENTS_URL = f"{settings.API_V1_STR}/appointments"


_ACTOR: dict = {}


@pytest.fixture(autouse=True)
async def _resolve_actor(global_dependency_overrides):
    """Capture the staff actor / tenant that conftest injects into every request."""
    _ACTOR["user"] = await app.dependency_overrides[get_current_active_user]()
    _ACTOR["tenant"] = await app.dependency_overrides[get_tenant_from_header]()
    assert _ACTOR["user"] is not None and _ACTOR["tenant"] is not None
    yield
    _ACTOR.clear()


def _actor() -> User:
    """The staff user every request is authenticated as (see conftest)."""
    return _ACTOR["user"]


def _tenant_id() -> uuid.UUID:
    return _ACTOR["tenant"].id


async def _address(session, tag: str, city: str) -> Address:
    """Snapshot address row inside the test transaction."""
    address = Address(
        tenant_id=_tenant_id(),
        name=f"Appt {tag}",
        phone="9000000000",
        company_name=f"Appt Co {tag}",
        address_line1=f"Road {tag}",
        city=city,
        state="GJ",
        pincode="382421",
    )
    session.add(address)
    await session.flush()
    return address


async def _shipment(
    session,
    tag: str,
    *,
    b2b: bool = True,
    status: PickupStatus = PickupStatus.IN_TRANSIT,
    ndr_reason: NdrExceptionReason | None = None,
    appointment_id: str | None = None,
    appointment_start: datetime | None = None,
    po_number: str | None = None,
    po_expiry_date: date | None = None,
    created_by: uuid.UUID | None = None,
    city: str = "Gandhinagar",
) -> PickupRequest:
    """Insert one shipment (B2B via the `pickup_strategy` marker unless `b2b=False`)."""
    pickup = await _address(session, f"{tag}-p", "Delhi")
    delivery = await _address(session, f"{tag}-d", city)
    shipment = PickupRequest(
        tenant_id=_tenant_id(),
        created_by_user_id=created_by or _actor().id,
        order_reference_id=f"APPT-{tag}",
        tracking_id=f"APPT{tag}",
        status=status,
        ndr_reason=ndr_reason,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=date.today(),
        pickup_address_id=pickup.id,
        delivery_address_id=delivery.id,
        pickup_strategy=PickupStrategy.DEFAULT if b2b else None,
        appointment_id=appointment_id,
        appointment_start=appointment_start,
        appointment_end=(appointment_start + timedelta(hours=4)) if appointment_start else None,
        po_number=po_number,
        po_expiry_date=po_expiry_date,
    )
    session.add(shipment)
    await session.flush()
    return shipment


async def _list(client: AsyncClient, **params) -> dict:
    res = await client.get(APPOINTMENTS_URL, params=params, headers=HEADERS)
    assert res.status_code == 200, res.text
    return res.json()


def _ids(body: dict) -> set[str]:
    return {row["shipment_id"] for row in body["items"]}


@pytest.mark.asyncio
async def test_tabs_follow_dashboard_definitions(db_session):
    tag = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)
    pending_exception = await _shipment(
        db_session,
        f"{tag}a",
        status=PickupStatus.EXCEPTION,
        ndr_reason=NdrExceptionReason.APPOINTMENT_NEEDED,
    )
    pending_no_slot = await _shipment(db_session, f"{tag}b", appointment_id=f"AP-{tag}")
    at_risk = await _shipment(
        db_session, f"{tag}c", appointment_start=now + timedelta(hours=5), po_number="PO1"
    )
    booked_later = await _shipment(
        db_session, f"{tag}d", appointment_start=now + timedelta(days=3), po_number="PO2"
    )
    delivered = await _shipment(
        db_session,
        f"{tag}e",
        status=PickupStatus.COMPLETED,
        appointment_start=now + timedelta(hours=2),
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        pending = await _list(client, tab="pending", search=tag, size=100)
        risk = await _list(client, tab="at_risk", search=tag, size=100)
        booked = await _list(client, tab="booked", search=tag, size=100)

    assert _ids(pending) == {str(pending_exception.id), str(pending_no_slot.id)}
    assert _ids(risk) == {str(at_risk.id)}
    assert _ids(booked) == {str(at_risk.id), str(booked_later.id)}
    assert str(delivered.id) not in _ids(booked) | _ids(risk) | _ids(pending)

    # Tab counts ignore filters but include our rows.
    assert pending["counts"]["pending"] >= 2
    assert risk["counts"]["at_risk"] >= 1
    assert booked["counts"]["booked"] >= 2

    row = next(r for r in pending["items"] if r["shipment_id"] == str(pending_exception.id))
    assert row["po_missing"] is True
    assert row["po_expired"] is False
    assert row["consignee_city"] == "Gandhinagar"
    assert row["consignee_pincode"] == "382421"
    assert row["delivery_by"] is None

    booked_row = next(r for r in booked["items"] if r["shipment_id"] == str(booked_later.id))
    assert booked_row["po_missing"] is False
    assert booked_row["delivery_by"] == (now + timedelta(days=3)).date().isoformat()


@pytest.mark.asyncio
async def test_b2c_shipments_are_excluded(db_session):
    tag = uuid.uuid4().hex[:6]
    b2c = await _shipment(
        db_session,
        tag,
        b2b=False,
        status=PickupStatus.EXCEPTION,
        ndr_reason=NdrExceptionReason.APPOINTMENT_NEEDED,
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = await _list(client, tab="pending", search=tag)
    assert str(b2c.id) not in _ids(body)


@pytest.mark.asyncio
async def test_filters_city_status_expired_po_and_delivery_range(db_session):
    tag = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)
    yesterday = date.today() - timedelta(days=1)
    expired = await _shipment(
        db_session,
        f"{tag}x",
        status=PickupStatus.EXCEPTION,
        ndr_reason=NdrExceptionReason.APPOINTMENT_NEEDED,
        po_number="PO-OLD",
        po_expiry_date=yesterday,
        city="Surat",
    )
    fresh = await _shipment(
        db_session,
        f"{tag}y",
        appointment_id=f"AP-{tag}",
        po_number="PO-NEW",
        po_expiry_date=date.today() + timedelta(days=10),
    )
    soon = await _shipment(db_session, f"{tag}z", appointment_start=now + timedelta(days=2))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        expired_only = await _list(client, tab="pending", search=tag, expired_po_only=True)
        by_city = await _list(client, tab="pending", search=tag, city="sura")
        by_status = await _list(client, tab="pending", search=tag, status="IN_TRANSIT")
        in_range = await _list(
            client,
            tab="booked",
            search=tag,
            pdd_from=(now + timedelta(days=1)).date().isoformat(),
            pdd_to=(now + timedelta(days=3)).date().isoformat(),
        )
        out_of_range = await _list(
            client, tab="booked", search=tag, pdd_to=date.today().isoformat()
        )

    assert _ids(expired_only) == {str(expired.id)}
    assert expired_only["items"][0]["po_expired"] is True
    assert _ids(by_city) == {str(expired.id)}
    assert _ids(by_status) == {str(fresh.id)}
    assert _ids(in_range) == {str(soon.id)}
    assert str(soon.id) not in _ids(out_of_range)


@pytest.mark.asyncio
async def test_customers_only_see_their_own_lrs(db_session):
    tag = uuid.uuid4().hex[:6]
    customer = User(
        id=uuid.uuid4(),
        tenant_id=_tenant_id(),
        email=f"appt-{tag}@example.com",
        supabase_user_id=f"test-{tag}",
        role=UserRole.customer,
    )
    mine = await _shipment(
        db_session,
        f"{tag}m",
        status=PickupStatus.EXCEPTION,
        ndr_reason=NdrExceptionReason.APPOINTMENT_NEEDED,
        created_by=customer.id,
    )
    theirs = await _shipment(
        db_session,
        f"{tag}t",
        status=PickupStatus.EXCEPTION,
        ndr_reason=NdrExceptionReason.APPOINTMENT_NEEDED,
    )
    service = AppointmentsService(AppointmentsRepository(db_session))

    as_customer = await service.list_appointments(
        tenant_id=_tenant_id(),
        user=customer,
        tab=AppointmentTab.pending,
        filters=AppointmentFilters(search=tag),
        page=1,
        size=50,
    )
    as_staff = await service.list_appointments(
        tenant_id=_tenant_id(),
        user=_actor(),
        tab=AppointmentTab.pending,
        filters=AppointmentFilters(search=tag),
        page=1,
        size=50,
    )

    assert {row.shipment_id for row in as_customer.items} == {mine.id}
    assert as_customer.counts.pending == 1
    assert {row.shipment_id for row in as_staff.items} == {mine.id, theirs.id}


@pytest.mark.asyncio
async def test_pagination_and_validation(db_session):
    tag = uuid.uuid4().hex[:6]
    for index in range(3):
        await _shipment(
            db_session,
            f"{tag}{index}",
            status=PickupStatus.EXCEPTION,
            ndr_reason=NdrExceptionReason.APPOINTMENT_NEEDED,
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await _list(client, tab="pending", search=tag, size=2, page=1)
        second = await _list(client, tab="pending", search=tag, size=2, page=2)
        bad_tab = await client.get(APPOINTMENTS_URL, params={"tab": "nope"}, headers=HEADERS)

    assert first["total"] == 3
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert not (_ids(first) & _ids(second))
    assert bad_tab.status_code == 422
