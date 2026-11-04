"""
Consolidated unit and edge-case test suite for the Temporal Hooks Worker
(`scripts/temporal_hooks_worker.py`), covering:
1. Overdue appointment transitions (`IN_TRANSIT`/`OUT_FOR_DELIVERY` -> `EXCEPTION` with
   `APPOINTMENT_NEEDED`; parcels not yet picked up are never flagged, D-04c)
2. E-Way bill expiry transitions (`IN_TRANSIT` > 72 hours with goods value >= ₹50,000 ->
   `EXCEPTION` with `EWAY_BILL_MISSING`)
3. Null/empty boundary conditions (`appointment_end=None`, `eway_bill_numbers=None` or `[]`)
4. Batch pagination stress testing (1,000 overdue appointments processed without OOM)
5. Lifecycle guards (terminal / RTO / pre-pickup rows untouched, invalid transitions rolled
   back), the audit activity, tenant-scoped actor fallback and the cron endpoint contract
"""

import importlib.util
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import ARRAY
from sqlalchemy import text as sql_text
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
async def test_check_eway_bills_holds_stale_high_value_in_transit_only(
    sqlite_session: AsyncSession,
) -> None:
    """
    IN_TRANSIT parcels worth >= ₹50,000 with no update for 72 hours move to EXCEPTION
    (EWAY_BILL_MISSING), whether the e-way bill was given as numbers or as a document
    (`eway_bill_numbers` JSON null). Fresh or low-value parcels stay In transit.
    """
    now_utc = datetime.now(timezone.utc)
    stale = now_utc - timedelta(hours=73)
    fresh = now_utc - timedelta(hours=71)

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    address = await _seed_test_address(sqlite_session, tenant_id)

    def _in_transit(updated_at: datetime) -> PickupRequest:
        return PickupRequest(
            tenant_id=tenant_id,
            created_by_user_id=user_id,
            status=PickupStatus.IN_TRANSIT,
            updated_at=updated_at,
            product_category=ProductCategory.ELECTRONICS,
            requested_pickup_date=now_utc.date(),
            pickup_address_id=address.id,
            delivery_address_id=address.id,
            shipment_type=ShipmentType.FORWARD,
            service_type=ServiceType.SURFACE_ROAD,
        )

    req_stale_numbers = _in_transit(stale)
    req_stale_document = _in_transit(stale)
    req_stale_low_value = _in_transit(stale)
    req_fresh_high_value = _in_transit(fresh)
    reqs = [req_stale_numbers, req_stale_document, req_stale_low_value, req_fresh_high_value]
    sqlite_session.add_all(reqs)
    await sqlite_session.commit()
    for req in reqs:
        await sqlite_session.refresh(req)

    sqlite_session.add_all(
        [
            PaymentDetails(
                pickup_id=req_stale_numbers.id,
                shipment_total_value=50000,
                eway_bill_numbers=["123456789012"],
            ),
            PaymentDetails(
                pickup_id=req_stale_document.id,
                shipment_total_value=120000,
                eway_bill_numbers=None,
            ),
            PaymentDetails(
                pickup_id=req_stale_low_value.id,
                shipment_total_value=49999.99,
                eway_bill_numbers=["111122223333"],
            ),
            PaymentDetails(
                pickup_id=req_fresh_high_value.id,
                shipment_total_value=90000,
                eway_bill_numbers=["987654321098"],
            ),
        ]
    )
    await sqlite_session.commit()

    count = await check_eway_bills(sqlite_session)
    assert count == 2

    for req in (req_stale_numbers, req_stale_document):
        held = await sqlite_session.get(PickupRequest, req.id)
        assert held is not None and held.status == PickupStatus.EXCEPTION
        assert held.ndr_reason == NdrExceptionReason.EWAY_BILL_MISSING
        assert held.ndr_remark == temporal_hooks_worker.EWAY_BILL_STALE_REMARK
    for req in (req_stale_low_value, req_fresh_high_value):
        untouched = await sqlite_session.get(PickupRequest, req.id)
        assert untouched is not None and untouched.status == PickupStatus.IN_TRANSIT
        assert untouched.ndr_reason is None

    assert await check_eway_bills(sqlite_session) == 0


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
async def test_check_eway_bills_sets_eway_bill_missing_reason_with_mock() -> None:
    """Adversarial unit test verifying `ndr_reason` is set to `EWAY_BILL_MISSING`."""
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
    assert req1.ndr_reason == NdrExceptionReason.EWAY_BILL_MISSING


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
            "temporal_hooks_run appointments_held=1 eway_bills_held=0 duration_ms="
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
            "temporal_hooks_run appointments_held=0 eway_bills_held=0 duration_ms="
            in rec.getMessage()
            for rec in caplog.records
        )



def _shipment(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    address: Address,
    status: PickupStatus,
    **fields,
) -> PickupRequest:
    """A minimal shipment row for the lifecycle-guard tests."""
    return PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        status=status,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=datetime.now(timezone.utc).date(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
        **fields,
    )


@pytest.mark.asyncio
async def test_terminal_rto_and_held_rows_are_never_touched(
    sqlite_session: AsyncSession,
) -> None:
    """Terminal, RTO, LOST and already-held rows stay as they are, however overdue or stale."""
    now_utc = datetime.now(timezone.utc)
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    address = await _seed_test_address(sqlite_session, tenant_id)
    guarded_statuses = [
        PickupStatus.COMPLETED,
        PickupStatus.CANCELLED,
        PickupStatus.RTO_INITIATED,
        PickupStatus.RTO_IN_TRANSIT,
        PickupStatus.RTO_DELIVERED,
        PickupStatus.LOST,
        PickupStatus.EXCEPTION,
        PickupStatus.OPEN,
    ]
    reqs = [
        _shipment(
            tenant_id,
            user_id,
            address,
            status,
            appointment_end=now_utc - timedelta(days=1),
            updated_at=now_utc - timedelta(days=10),
        )
        for status in guarded_statuses
    ]
    sqlite_session.add_all(reqs)
    await sqlite_session.commit()
    for req in reqs:
        await sqlite_session.refresh(req)
    sqlite_session.add_all(
        [PaymentDetails(pickup_id=req.id, shipment_total_value=200000) for req in reqs]
    )
    await sqlite_session.commit()

    assert await check_appointments(sqlite_session) == 0
    assert await check_eway_bills(sqlite_session) == 0
    for req, status in zip(reqs, guarded_statuses):
        row = await sqlite_session.get(PickupRequest, req.id)
        assert row is not None and row.status == status
    activities = (await sqlite_session.execute(select(ShipmentActivity))).scalars().all()
    assert activities == []


@pytest.mark.asyncio
async def test_hold_writes_merchant_visible_audit_and_clears_stale_exception_fields(
    sqlite_session: AsyncSession,
) -> None:
    """
    The hold records remark, held_from and source, shows on the merchant's timeline
    (`is_public`), clears a previous exception's charge and keeps the attempt count.
    The actor of an orphaned shipment is an active user of the SAME tenant.
    """
    now_utc = datetime.now(timezone.utc)
    tenant = Tenant(name="Acme", slug="acme")
    other_tenant = Tenant(name="Other", slug="other")
    sqlite_session.add_all([tenant, other_tenant])
    await sqlite_session.commit()
    other_user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="ops@other.in",
        tenant_id=other_tenant.id,
        is_active=True,
    )
    tenant_user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="ops@acme.in",
        tenant_id=tenant.id,
        is_active=True,
    )
    sqlite_session.add_all([other_user, tenant_user])
    await sqlite_session.commit()
    address = await _seed_test_address(sqlite_session, tenant.id)
    req = _shipment(
        tenant.id,
        uuid.uuid4(),  # creator no longer exists
        address,
        PickupStatus.OUT_FOR_DELIVERY,
        appointment_end=now_utc - timedelta(minutes=5),
        charge_amount=250.0,
        ndr_attempt_count=1,
        ndr_remark="Old remark from a previous exception",
    )
    sqlite_session.add(req)
    await sqlite_session.commit()

    assert await check_appointments(sqlite_session) == 1

    held = await sqlite_session.get(PickupRequest, req.id)
    assert held is not None
    assert held.status == PickupStatus.EXCEPTION
    assert held.ndr_remark == temporal_hooks_worker.APPOINTMENT_EXPIRED_REMARK
    assert held.charge_amount is None
    assert held.ndr_attempt_count == 1
    assert held.exception_raised_at is not None and held.exception_raised_at.tzinfo is None
    activity = (await sqlite_session.execute(select(ShipmentActivity))).scalars().one()
    assert activity.user_id == tenant_user.id
    assert activity.is_public is True
    assert activity.comment == temporal_hooks_worker.APPOINTMENT_EXPIRED_REMARK
    assert activity.diff["status"] == {"old": "OUT_FOR_DELIVERY", "new": "EXCEPTION"}
    assert activity.diff["ndr_raise"] == {
        "reason": NdrExceptionReason.APPOINTMENT_NEEDED.value,
        "attempt": 1,
        "remark": temporal_hooks_worker.APPOINTMENT_EXPIRED_REMARK,
        "held_from": "OUT_FOR_DELIVERY",
        "source": temporal_hooks_worker.WORKER_SOURCE,
    }


@pytest.mark.asyncio
async def test_invalid_transition_fails_the_check_and_rolls_back() -> None:
    """A row the lifecycle machine refuses (terminal) fails the check; nothing is committed."""
    session_mock = AsyncMock()
    session_mock.add = MagicMock()
    completed = PickupRequest(
        tenant_id=uuid.uuid4(),
        created_by_user_id=uuid.uuid4(),
        status=PickupStatus.COMPLETED,
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [completed]
    result.all.return_value = []
    session_mock.execute = AsyncMock(return_value=result)

    held = await temporal_hooks_worker._run_check(
        session_mock, "check_appointments", check_appointments
    )

    assert held is None
    assert completed.status == PickupStatus.COMPLETED
    session_mock.commit.assert_not_awaited()
    session_mock.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_appointment_cutoff_is_timezone_aware() -> None:
    """`appointment_end` is TIMESTAMPTZ: the cutoff must be an aware UTC instant."""
    captured = []

    async def _capture(statement):
        captured.append(statement)
        result = MagicMock()
        result.scalars.return_value.all.return_value = []
        return result

    session_mock = AsyncMock()
    session_mock.execute = _capture
    assert await check_appointments(session_mock) == 0

    params = captured[0].compile().params
    cutoffs = [value for value in params.values() if isinstance(value, datetime)]
    assert len(cutoffs) == 1
    assert cutoffs[0].utcoffset() == timedelta(0)


@pytest.mark.asyncio
async def test_run_iteration_reports_failed_check_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One failing check is reported as None and never stops the other one (G-08)."""

    @asynccontextmanager
    async def _fake_session_local():
        yield AsyncMock()

    async def _boom(session):
        raise RuntimeError("db down")

    async def _three(session):
        return 3

    monkeypatch.setattr(temporal_hooks_worker, "AsyncSessionLocal", _fake_session_local)
    monkeypatch.setattr(temporal_hooks_worker, "check_appointments", _boom)
    monkeypatch.setattr(temporal_hooks_worker, "check_eway_bills", _three)

    assert await temporal_hooks_worker.run_temporal_hooks_iteration() == {
        "appointments_held": None,
        "eway_bills_held": 3,
    }


@pytest.mark.asyncio
async def test_cron_endpoint_returns_500_with_failed_checks(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed check yields HTTP 500 (scheduler sees the failure) instead of a TypeError."""

    async def _partial_iteration():
        return {"appointments_held": 2, "eway_bills_held": None}

    monkeypatch.setattr(
        temporal_hooks_worker, "run_temporal_hooks_iteration", _partial_iteration
    )
    monkeypatch.setattr(settings, "CRON_SECRET", "super-secret-cron-token")
    transport = ASGITransport(app=_build_internal_test_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        with caplog.at_level("INFO", logger="app.api.v1.endpoints.internal"):
            resp = await client.post(
                "/api/v1/internal/temporal-hooks/run",
                headers={"X-Cron-Secret": "super-secret-cron-token"},
            )

    assert resp.status_code == 500
    assert resp.json() == {
        "status": "error",
        "appointments_held": 2,
        "eway_bills_held": None,
        "failed_checks": ["eway_bills_held"],
    }
    assert any(
        rec.levelname == "ERROR"
        and "temporal_hooks_run appointments_held=2 eway_bills_held=None" in rec.getMessage()
        for rec in caplog.records
    )


def _load_pg_cron_revision() -> ModuleType:
    """Imports migration `f9a0b1c2d3e4` (pg_cron schedule) without running it."""
    (path,) = (Path(__file__).resolve().parents[2] / "alembic" / "versions").glob(
        "f9a0b1c2d3e4_*.py"
    )
    spec = importlib.util.spec_from_file_location("rev_f9a0b1c2d3e4", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_pg_cron_migration_schedules_vault_backed_call_every_14_minutes() -> None:
    """
    The DB-side scheduler calls the cron endpoint every 14 minutes, reads URL and secret from
    Vault (nothing secret in git or `cron.job`), is a no-op until both exist, survives a
    Render cold start, and has no accidental SQLAlchemy bind parameters.
    """
    revision = _load_pg_cron_revision()
    assert revision.down_revision == "e8f9a0b1c2d3"
    schedule_sql = revision.UPGRADE_STATEMENTS[-1]
    assert schedule_sql.startswith("SELECT cron.schedule('naviera-temporal-hooks', '*/14 * * * *'")
    assert internal_endpoint.CRON_SECRET_HEADER in revision.JOB_COMMAND
    assert revision.JOB_COMMAND.count("vault.decrypted_secrets") == 4
    assert "WHERE EXISTS" in revision.JOB_COMMAND
    assert "onrender.com" not in revision.JOB_COMMAND
    assert revision.HTTP_TIMEOUT_MS >= 60_000
    for statement in revision.UPGRADE_STATEMENTS + revision.DOWNGRADE_STATEMENTS:
        assert sql_text(statement).compile().params == {}
