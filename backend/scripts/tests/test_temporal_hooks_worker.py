"""
Consolidated unit and edge-case test suite for the Temporal Hooks Worker
(`scripts/temporal_hooks_worker.py`), covering:
1. Overdue appointment transitions (`IN_TRANSIT`/`OUT_FOR_DELIVERY` -> `EXCEPTION` with
   `APPOINTMENT_NEEDED`; parcels not yet picked up are never flagged, D-04c)
2. E-Way bill expiry transitions (`IN_TRANSIT` > 7 days -> `EXCEPTION` with `DOCUMENT_NEEDED`)
3. Null/empty boundary conditions (`appointment_end=None`, `eway_bill_numbers=None` or `[]`)
4. Batch pagination stress testing (1,000 overdue appointments processed without OOM)
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select

from app.api.v1.endpoints import internal as internal_endpoint
from app.core.config import settings
from app.models.manifests import Manifest
from app.models.pickups import (
    ActivityType,
    Address,
    NdrExceptionReason,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    PickupStatus,
    ProductCategory,
    ServiceType,
    ShipmentActivity,
    ShipmentType,
)
from app.models.tenants import Tenant, User
from scripts import temporal_hooks_worker
from scripts.temporal_hooks_worker import check_appointments, check_eway_bills

DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# Only the tables the worker reads/writes (plus their FK parents). Creating the
# whole Postgres schema in SQLite fails on Postgres-only server defaults
# (e.g. `'[]'::jsonb`) of unrelated tables.
WORKER_TABLES = [
    Tenant.__table__,
    User.__table__,
    Address.__table__,
    Manifest.__table__,
    PickupRequest.__table__,
    PaymentDetails.__table__,
    PackageDetails.__table__,
    PickupDocument.__table__,
    ShipmentActivity.__table__,
]


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw) -> str:
    """Lets the full Postgres schema (JSONB columns) be created in the SQLite test DB."""
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(type_, compiler, **kw) -> str:
    """SQLite has no ARRAY type; store it as JSON text for these tests."""
    return "JSON"


@pytest_asyncio.fixture
async def sqlite_engine():
    """Creates an isolated in-memory SQLite engine for fast temporal worker tests."""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.create_all(sync_conn, tables=WORKER_TABLES))
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(lambda sync_conn: SQLModel.metadata.drop_all(sync_conn, tables=WORKER_TABLES))
    await engine.dispose()


@pytest_asyncio.fixture
async def sqlite_session(sqlite_engine):
    """Provides an AsyncSession bound to the in-memory SQLite test engine."""
    async_session = sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


async def _seed_test_address(session: AsyncSession, tenant_id: uuid.UUID) -> Address:
    """Seeds a baseline Address record for foreign-key integrity."""
    address = Address(
        name="Test Contact",
        phone="1234567890",
        address_line1="123 Main St",
        city="Test City",
        state="Test State",
        pincode="123456",
        tenant_id=tenant_id,
    )
    session.add(address)
    await session.commit()
    await session.refresh(address)
    return address


@pytest.mark.asyncio
async def test_check_appointments_transitions_overdue_only(
    sqlite_session: AsyncSession,
) -> None:
    """Overdue IN_TRANSIT / OFD appointments move to EXCEPTION; pre-pickup ones never do (D-04c)."""
    now_utc = datetime.now(timezone.utc)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    address = await _seed_test_address(sqlite_session, tenant_id)

    req_past_assigned = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.IN_TRANSIT,
        appointment_end=now_utc - timedelta(hours=1),
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )
    req_future_assigned = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.IN_TRANSIT,
        appointment_end=now_utc + timedelta(hours=1),
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )
    req_past_open = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.OUT_FOR_DELIVERY,
        appointment_end=now_utc - timedelta(hours=1),
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )

    req_past_not_picked = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.ASSIGNED,
        appointment_end=now_utc - timedelta(hours=1),
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )

    sqlite_session.add_all(
        [req_past_assigned, req_future_assigned, req_past_open, req_past_not_picked]
    )
    await sqlite_session.commit()

    count = await check_appointments(sqlite_session)
    await sqlite_session.commit()
    assert count == 2

    r1 = await sqlite_session.get(PickupRequest, req_past_assigned.id)
    r2 = await sqlite_session.get(PickupRequest, req_future_assigned.id)
    r3 = await sqlite_session.get(PickupRequest, req_past_open.id)

    assert r1 is not None and r1.status == PickupStatus.EXCEPTION
    assert r1.ndr_reason == NdrExceptionReason.APPOINTMENT_NEEDED
    assert r2 is not None and r2.status == PickupStatus.IN_TRANSIT
    assert r3 is not None and r3.status == PickupStatus.EXCEPTION
    assert r3.ndr_reason == NdrExceptionReason.APPOINTMENT_NEEDED

    activities = (
        await sqlite_session.execute(select(ShipmentActivity))
    ).scalars().all()
    assert len(activities) == 2
    for act in activities:
        assert act.pickup_id in (req_past_assigned.id, req_past_open.id)
        assert act.activity_type == ActivityType.STATUS_CHANGE
        assert act.user_id == user_id
        assert act.diff["status"]["new"] == PickupStatus.EXCEPTION.value
        assert act.diff["ndr_raise"]["held_from"] in (
            PickupStatus.IN_TRANSIT.value,
            PickupStatus.OUT_FOR_DELIVERY.value,
        )

    r4 = await sqlite_session.get(PickupRequest, req_past_not_picked.id)
    assert r4 is not None and r4.status == PickupStatus.ASSIGNED


@pytest.mark.asyncio
async def test_check_eway_bills_transitions_stale_in_transit_only(
    sqlite_session: AsyncSession,
) -> None:
    """Verifies IN_TRANSIT shipments > 7 days old with E-Way bills move to EXCEPTION (DOCUMENT_NEEDED)."""
    now_utc = datetime.now(timezone.utc)
    eight_days_ago = now_utc - timedelta(days=8)
    six_days_ago = now_utc - timedelta(days=6)

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    address = await _seed_test_address(sqlite_session, tenant_id)

    req_stale_with_ewb = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.IN_TRANSIT,
        updated_at=eight_days_ago,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )
    req_stale_empty_ewb = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.IN_TRANSIT,
        updated_at=eight_days_ago,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )
    req_recent_with_ewb = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.IN_TRANSIT,
        updated_at=six_days_ago,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )

    sqlite_session.add_all(
        [req_stale_with_ewb, req_stale_empty_ewb, req_recent_with_ewb]
    )
    await sqlite_session.commit()
    for req in (req_stale_with_ewb, req_stale_empty_ewb, req_recent_with_ewb):
        await sqlite_session.refresh(req)

    sqlite_session.add_all(
        [
            PaymentDetails(
                pickup_id=req_stale_with_ewb.id, eway_bill_numbers=["123456789012"]
            ),
            PaymentDetails(pickup_id=req_stale_empty_ewb.id, eway_bill_numbers=[]),
            PaymentDetails(
                pickup_id=req_recent_with_ewb.id, eway_bill_numbers=["987654321098"]
            ),
        ]
    )
    await sqlite_session.commit()

    count = await check_eway_bills(sqlite_session)
    await sqlite_session.commit()
    assert count == 1

    r1 = await sqlite_session.get(PickupRequest, req_stale_with_ewb.id)
    r2 = await sqlite_session.get(PickupRequest, req_stale_empty_ewb.id)
    r3 = await sqlite_session.get(PickupRequest, req_recent_with_ewb.id)

    assert r1 is not None and r1.status == PickupStatus.EXCEPTION
    assert r1.ndr_reason == NdrExceptionReason.DOCUMENT_NEEDED
    assert r2 is not None and r2.status == PickupStatus.IN_TRANSIT
    assert r3 is not None and r3.status == PickupStatus.IN_TRANSIT


@pytest.mark.asyncio
async def test_null_appointment_and_null_eway_bill_edge_cases(
    sqlite_session: AsyncSession,
) -> None:
    """Verifies null `appointment_end` and null `eway_bill_numbers` are safely ignored."""
    now_utc = datetime.now(timezone.utc)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    address = await _seed_test_address(sqlite_session, tenant_id)

    req_no_appt = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.OPEN,
        appointment_end=None,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )
    req_null_ewb = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.IN_TRANSIT,
        updated_at=now_utc - timedelta(days=8),
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )
    sqlite_session.add_all([req_no_appt, req_null_ewb])
    await sqlite_session.commit()
    await sqlite_session.refresh(req_null_ewb)

    sqlite_session.add(
        PaymentDetails(pickup_id=req_null_ewb.id, eway_bill_numbers=None)
    )
    await sqlite_session.commit()

    assert await check_appointments(sqlite_session) == 0
    assert await check_eway_bills(sqlite_session) == 0


@pytest.mark.asyncio
async def test_check_eway_bills_sets_document_needed_reason_with_mock() -> None:
    """Adversarial unit test verifying `ndr_reason` is set to `DOCUMENT_NEEDED`."""
    session_mock = AsyncMock()
    session_mock.add = MagicMock()
    session_mock.expunge_all = MagicMock()
    now_utc = datetime.now(timezone.utc)

    req1 = PickupRequest(
        tenant_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        status=PickupStatus.IN_TRANSIT,
        updated_at=now_utc - timedelta(days=8),
    )
    req1.payment_details = PaymentDetails(
        pickup_id=req1.id, eway_bill_numbers=["123456789012"]
    )

    call_count = 0

    async def mock_execute(statement):
        nonlocal call_count
        call_count += 1
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [req1] if call_count == 1 else []
        mock_result.scalars.return_value = mock_scalars
        return mock_result

    session_mock.execute = mock_execute
    await check_eway_bills(session_mock)

    assert req1.status == PickupStatus.EXCEPTION
    assert req1.ndr_reason == NdrExceptionReason.DOCUMENT_NEEDED


@pytest.mark.asyncio
async def test_batch_pagination_stress_1000_appointments(
    sqlite_session: AsyncSession,
) -> None:
    """Verifies batch pagination processes 1,000 overdue appointments cleanly."""
    now_utc = datetime.now(timezone.utc)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    address = await _seed_test_address(sqlite_session, tenant_id)

    reqs = [
        PickupRequest(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            status=PickupStatus.IN_TRANSIT,
            appointment_end=now_utc - timedelta(hours=1),
            product_category=ProductCategory.ELECTRONICS,
            requested_pickup_date=now_utc.date(),
            pickup_address_id=address.id,
            delivery_address_id=address.id,
        )
        for _ in range(1000)
    ]
    sqlite_session.add_all(reqs)
    await sqlite_session.commit()

    count = await check_appointments(sqlite_session)
    await sqlite_session.commit()
    assert count == 1000


def _build_internal_test_app() -> FastAPI:
    """Minimal FastAPI app mounting `/api/v1/internal` for cron auth tests."""
    test_app = FastAPI()
    test_app.include_router(internal_endpoint.router, prefix="/api/v1/internal")
    return test_app


@pytest.mark.asyncio
async def test_temporal_hooks_cron_endpoint_auth_and_idempotency(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    sqlite_session: AsyncSession,
) -> None:
    """
    Verifies `POST /api/v1/internal/temporal-hooks/run`:
    - returns 403 when `CRON_SECRET` is unset (endpoint disabled);
    - returns 403 when `X-Cron-Secret` is missing or wrong;
    - returns 200 with the right secret, logs a single searchable INFO line, and executes
      `run_temporal_hooks_iteration()` idempotently.
    """
    now_utc = datetime.now(timezone.utc)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    address = await _seed_test_address(sqlite_session, tenant_id)
    overdue_req = PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=PickupStatus.IN_TRANSIT,
        appointment_end=now_utc - timedelta(hours=2),
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=now_utc.date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
    )
    sqlite_session.add(overdue_req)
    await sqlite_session.commit()

    @asynccontextmanager
    async def _fake_session_local():
        yield sqlite_session

    monkeypatch.setattr(temporal_hooks_worker, "AsyncSessionLocal", _fake_session_local)

    test_app = _build_internal_test_app()
    transport = ASGITransport(app=test_app)
    url = "/api/v1/internal/temporal-hooks/run"

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Endpoint disabled when CRON_SECRET is unset
        monkeypatch.setattr(settings, "CRON_SECRET", "")
        resp_unset = await client.post(url, headers={"X-Cron-Secret": "any-secret"})
        assert resp_unset.status_code == 403

        # 2. Missing or wrong X-Cron-Secret rejected with 403
        monkeypatch.setattr(settings, "CRON_SECRET", "super-secret-cron-token")
        resp_missing = await client.post(url)
        assert resp_missing.status_code == 403

        resp_wrong = await client.post(url, headers={"X-Cron-Secret": "wrong-token"})
        assert resp_wrong.status_code == 403

        # 3. Valid X-Cron-Secret runs one iteration (holds 1 overdue appointment)
        with caplog.at_level("INFO", logger="app.api.v1.endpoints.internal"):
            resp_ok_1 = await client.post(
                url, headers={"X-Cron-Secret": "super-secret-cron-token"}
            )
        assert resp_ok_1.status_code == 200
        assert resp_ok_1.json() == {
            "status": "ok",
            "appointments_held": 1,
            "eway_bills_held": 0,
        }
        assert any(
            "temporal_hooks_run expired_appointments=1 stale_eway_holds=0 duration_ms="
            in rec.getMessage()
            for rec in caplog.records
        )

        # 4. Second run is idempotent (holds 0 rows because already in EXCEPTION)
        caplog.clear()
        with caplog.at_level("INFO", logger="app.api.v1.endpoints.internal"):
            resp_ok_2 = await client.post(
                url, headers={"X-Cron-Secret": "super-secret-cron-token"}
            )
        assert resp_ok_2.status_code == 200
        assert resp_ok_2.json() == {
            "status": "ok",
            "appointments_held": 0,
            "eway_bills_held": 0,
        }
        assert any(
            "temporal_hooks_run expired_appointments=0 stale_eway_holds=0 duration_ms="
            in rec.getMessage()
            for rec in caplog.records
        )

