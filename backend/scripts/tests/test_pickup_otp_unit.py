"""
Pure unit tests for Delhivery-parity Pickup Handover OTP (`rel8:pickup-otp`).

Runs against an in-memory SQLite database (`sqlite+aiosqlite:///:memory:`), never touching
the shared Postgres database, so it executes in milliseconds inside `PURE_UNIT_SUITES`
(`bash backend/scripts/run_golden.sh --quick`).

Covers:
1. Cryptographically random 6-digit OTP generation (`secrets.randbelow`, never `random`).
2. Automatic OTP generation on `ManifestService.create_manifest()` (B2C + B2B + blind pickups).
3. Lazy OTP generation on legacy open (`SCHEDULED` / `OUT_FOR_PICKUP`) manifests with
   `pickup_otp=None` (and NO lazy generation on terminal `PICKED` / `NOT_PICKED` / `CANCELED`).
4. Role-based visibility matrix across `owner`, `admin`, `customer` (owning vs non-owning),
   `operations_user`, `support_user`, `read_only_user`, and `None`, including warm reads
   from `manifest_list_cache`.
5. `dispatch_manifest()` OTP verification (`secrets.compare_digest`), partial pickup
   (`picked_shipment_ids`), 5-attempt lockout (`429 Too Many Requests` with `Retry-After`),
   Owner/Admin override with mandatory `pickup_otp_override_reason` recorded on the manifest
   and in `ShipmentActivity`, and `manifest_list_cache` / `eligible_shipments_cache` eviction.
"""

import uuid
from datetime import date
from typing import Any, AsyncIterator, List

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from response_audit import ResponseAuditMiddleware
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.v1.endpoints.manifests import router as manifests_router
from app.api.v1.endpoints.shipments import router as shipments_router
from app.core import logging as app_logging
from app.core.db import get_session
from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.core.ttl_cache import set_caches_enabled_for_tests
from app.models.manifests import Manifest, ManifestStatus, ServiceFlow
from app.models.pickups import (
    Address,
    AddressCategory,
    AddressScope,
    PackageDetails,
    PaymentDetails,
    PickupDocument,
    PickupRequest,
    PickupStatus,
    ProductCategory,
    ServiceOption,
    ServiceType,
    ShipmentActivity,
    ShipmentType,
)
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.repositories.manifests import eligible_shipments_cache, manifest_list_cache
from app.schemas.v1.manifests import ManifestCreate
from app.schemas.v1.pickups import PickupRead
from app.services.manifests import (
    ERR_PICKUP_OTP_OVERRIDE_FORBIDDEN,
    ERR_PICKUP_OTP_OVERRIDE_REASON_REQUIRED,
    ERR_PICKUP_OTP_REQUIRED,
    PICKUP_OTP_LOCKOUT_SECONDS,
    PICKUP_OTP_MAX_ATTEMPTS,
    ManifestService,
    reset_pickup_otp_attempts,
)

TABLES = [
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
def _jsonb_as_json(type_, compiler, **kw) -> str:
    return "JSON"


@compiles(ARRAY, "sqlite")
def _array_as_json(type_, compiler, **kw) -> str:
    return "JSON"


@pytest.fixture(autouse=True)
def _clean_otp_and_cache_state():
    set_caches_enabled_for_tests(True)
    reset_pickup_otp_attempts()
    yield
    reset_pickup_otp_attempts()
    set_caches_enabled_for_tests(None)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _user(tenant_id: uuid.UUID, role: UserRole, email_prefix: str = "u") -> User:
    uid = uuid.uuid4()
    return User(
        id=uid,
        supabase_user_id=str(uid),
        email=f"{email_prefix}-{uid.hex[:6]}@logismart-test.in",
        role=role,
        service_scope=ServiceScope.BOTH,
        tenant_id=tenant_id,
    )


def _address(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    name: str = "Bhiwandi Hub",
    scope: AddressScope = AddressScope.TENANT,
) -> Address:
    return Address(
        tenant_id=tenant_id,
        user_id=user_id,
        scope=scope,
        category=AddressCategory.WAREHOUSE,
        is_saved=True,
        name=name,
        phone="9876543210",
        address_line1="Plot 12, MIDC",
        city="Bhiwandi",
        state="Maharashtra",
        pincode="421302",
    )


def _shipment(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    address: Address,
    *,
    is_b2b: bool = False,
    is_blind_pickup: bool = False,
    status: PickupStatus = PickupStatus.OPEN,
    **kw: Any,
) -> PickupRequest:
    return PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=date.today(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
        service_option=ServiceOption.PRIME_SURFACE if is_b2b else ServiceOption.DELHIVERY_SURFACE,
        is_blind_pickup=is_blind_pickup,
        status=status,
        tracking_id=f"AWB-{uuid.uuid4().hex[:8].upper()}",
        **kw,
    )


# --------------------------------------------------------------------------- 1. Pure OTP generator


def test_generate_pickup_otp_returns_6_digit_numeric_string() -> None:
    samples = {ManifestService.generate_pickup_otp() for _ in range(50)}
    assert len(samples) > 1
    for otp in samples:
        assert len(otp) == 6
        assert otp.isdigit()
        assert 100_000 <= int(otp) <= 999_999


# --------------------------------------------------------------------------- 2. Creation & lazy generation


@pytest.mark.asyncio
async def test_create_manifest_generates_otp_for_b2c_and_b2b_blind(session_factory) -> None:
    tenant_id = uuid.uuid4()
    merchant = _user(tenant_id, UserRole.customer, "merchant")
    hub = _address(tenant_id, merchant.id)

    async with session_factory() as session:
        session.add_all([merchant, hub])
        await session.flush()
        b2c_lr = _shipment(tenant_id, merchant.id, hub, is_b2b=False)
        b2b_blind_lr = _shipment(
            tenant_id, merchant.id, hub, is_b2b=True, is_blind_pickup=True, estimated_box_count=5
        )
        session.add_all([b2c_lr, b2b_blind_lr])
        await session.commit()

    async with session_factory() as session:
        svc = ManifestService(session)
        b2c_resp = await svc.create_manifest(
            ManifestCreate(
                pickup_address_id=hub.id,
                scheduled_date=date.today(),
                time_slot="14:00 - 18:00",
                service_flow=ServiceFlow.B2C,
                shipment_ids=[b2c_lr.id],
            ),
            tenant_id=tenant_id,
            current_user=merchant,
        )
        b2b_resp = await svc.create_manifest(
            ManifestCreate(
                pickup_address_id=hub.id,
                scheduled_date=date.today(),
                time_slot="14:00 - 18:00",
                service_flow=ServiceFlow.B2B,
                is_blind_pickup=True,
                total_boxes=5,
                shipment_ids=[b2b_blind_lr.id],
            ),
            tenant_id=tenant_id,
            current_user=merchant,
        )

    assert b2c_resp["pickup_otp"] is not None and len(b2c_resp["pickup_otp"]) == 6
    assert b2b_resp["pickup_otp"] is not None and len(b2b_resp["pickup_otp"]) == 6
    assert b2c_resp["pickup_otp"].isdigit() and b2b_resp["pickup_otp"].isdigit()


@pytest.mark.asyncio
async def test_lazy_otp_generation_only_for_open_manifests(session_factory) -> None:
    tenant_id = uuid.uuid4()
    admin = _user(tenant_id, UserRole.admin, "admin")
    hub = _address(tenant_id, admin.id)

    async with session_factory() as session:
        session.add_all([admin, hub])
        await session.flush()
        open_legacy = Manifest(
            tenant_id=tenant_id,
            pickup_address_id=hub.id,
            scheduled_date=date.today(),
            time_slot="10:00 - 14:00",
            service_flow=ServiceFlow.B2C,
            status=ManifestStatus.SCHEDULED,
            pickup_otp=None,
        )
        closed_legacy = Manifest(
            tenant_id=tenant_id,
            pickup_address_id=hub.id,
            scheduled_date=date.today(),
            time_slot="14:00 - 18:00",
            service_flow=ServiceFlow.B2C,
            status=ManifestStatus.CANCELED,
            pickup_otp=None,
        )
        session.add_all([open_legacy, closed_legacy])
        await session.commit()

    async with session_factory() as session:
        rows = await ManifestService(session).list_manifests(tenant_id, current_user=admin)
    by_id = {r["id"]: r for r in rows}
    assert by_id[open_legacy.id]["pickup_otp"] is not None
    assert len(by_id[open_legacy.id]["pickup_otp"]) == 6
    assert by_id[closed_legacy.id]["pickup_otp"] is None


# --------------------------------------------------------------------------- 3. Role visibility + cache safety


@pytest.mark.asyncio
async def test_role_visibility_matrix_and_warm_cache_stripping(session_factory) -> None:
    tenant_id = uuid.uuid4()
    owner = _user(tenant_id, UserRole.owner, "owner")
    admin = _user(tenant_id, UserRole.admin, "admin")
    ops = _user(tenant_id, UserRole.operations_user, "ops")
    support = _user(tenant_id, UserRole.support_user, "support")
    readonly = _user(tenant_id, UserRole.read_only_user, "readonly")
    alice = _user(tenant_id, UserRole.customer, "alice")
    bob = _user(tenant_id, UserRole.customer, "bob")
    hub = _address(tenant_id, alice.id)

    async with session_factory() as session:
        session.add_all([owner, admin, ops, support, readonly, alice, bob, hub])
        await session.flush()
        alice_lr = _shipment(tenant_id, alice.id, hub)
        session.add(alice_lr)
        await session.commit()

    async with session_factory() as session:
        created = await ManifestService(session).create_manifest(
            ManifestCreate(
                pickup_address_id=hub.id,
                scheduled_date=date.today(),
                time_slot="14:00 - 18:00",
                service_flow=ServiceFlow.B2C,
                shipment_ids=[alice_lr.id],
            ),
            tenant_id=tenant_id,
            current_user=alice,
        )
    expected_otp = created["pickup_otp"]
    manifest_id = created["id"]
    assert expected_otp is not None and len(expected_otp) == 6

    async def list_as(viewer: User | None) -> List[dict]:
        async with session_factory() as session:
            return await ManifestService(session).list_manifests(tenant_id, current_user=viewer)

    async def get_as(viewer: User | None) -> dict:
        async with session_factory() as session:
            return await ManifestService(session).get_manifest(
                manifest_id, tenant_id, current_user=viewer
            )

    # 1. Admin populates warm staff cache -> sees OTP
    admin_rows = await list_as(admin)
    assert admin_rows[0]["pickup_otp"] == expected_otp

    # 2. Operations, Support, Read-Only, and None read from the WARM staff cache -> OTP stripped!
    for restricted_viewer in (ops, support, readonly, None):
        rows = await list_as(restricted_viewer)
        assert rows[0]["pickup_otp"] is None
        detail = await get_as(restricted_viewer)
        assert detail["pickup_otp"] is None

    # 3. Owner reads from the same warm staff cache -> still sees OTP (cache entry was not mutated)
    owner_rows = await list_as(owner)
    assert owner_rows[0]["pickup_otp"] == expected_otp
    assert (await get_as(owner))["pickup_otp"] == expected_otp
    assert manifest_list_cache.stats()["hits"] >= 5

    # 4. Owning customer (Alice) sees OTP; another customer (Bob) gets empty list / 403 on detail
    alice_rows = await list_as(alice)
    assert len(alice_rows) == 1 and alice_rows[0]["pickup_otp"] == expected_otp
    assert (await get_as(alice))["pickup_otp"] == expected_otp
    assert await list_as(bob) == []
    with pytest.raises(HTTPException) as exc_info:
        await get_as(bob)
    assert exc_info.value.status_code == 403


# --------------------------------------------------------------------------- 4. Dispatch verification, lockout & override


@pytest.mark.asyncio
async def test_dispatch_requires_otp_locks_out_after_5_attempts_and_records_verification(
    session_factory,
) -> None:
    tenant_id = uuid.uuid4()
    alice = _user(tenant_id, UserRole.customer, "alice")
    ops = _user(tenant_id, UserRole.operations_user, "ops")
    admin = _user(tenant_id, UserRole.admin, "admin")
    hub = _address(tenant_id, alice.id)

    async with session_factory() as session:
        session.add_all([alice, ops, admin, hub])
        await session.flush()
        lr1 = _shipment(tenant_id, alice.id, hub)
        lr2 = _shipment(tenant_id, alice.id, hub)
        session.add_all([lr1, lr2])
        await session.commit()

    async with session_factory() as session:
        created = await ManifestService(session).create_manifest(
            ManifestCreate(
                pickup_address_id=hub.id,
                scheduled_date=date.today(),
                time_slot="14:00 - 18:00",
                service_flow=ServiceFlow.B2C,
                shipment_ids=[lr1.id, lr2.id],
            ),
            tenant_id=tenant_id,
            current_user=alice,
        )
    manifest_id = created["id"]
    real_otp = created["pickup_otp"]
    wrong_otp = "000000" if real_otp != "000000" else "999999"

    # Warm both manifest_list_cache and eligible_shipments_cache before dispatch
    async with session_factory() as session:
        await ManifestService(session).list_manifests(tenant_id, current_user=admin)
        await ManifestService(session).list_eligible_shipments(
            tenant_id, ServiceFlow.B2C, hub.id, current_user=admin
        )
    assert manifest_list_cache.stats()["size"] > 0
    assert eligible_shipments_cache.stats()["size"] > 0

    # 1. Missing OTP -> 400 Bad Request
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await ManifestService(session).dispatch_manifest(
                manifest_id, tenant_id, current_user=ops, pickup_otp=None
            )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == ERR_PICKUP_OTP_REQUIRED
    assert real_otp not in exc_info.value.detail

    # 2. First 4 wrong attempts -> 400 Bad Request with countdown
    for attempt in range(1, PICKUP_OTP_MAX_ATTEMPTS):
        async with session_factory() as session:
            with pytest.raises(HTTPException) as exc_info:
                await ManifestService(session).dispatch_manifest(
                    manifest_id, tenant_id, current_user=ops, pickup_otp=wrong_otp
                )
        assert exc_info.value.status_code == 400
        remaining = PICKUP_OTP_MAX_ATTEMPTS - attempt
        assert f"{remaining} attempt(s) remaining" in exc_info.value.detail
        assert real_otp not in exc_info.value.detail

    # 3. 5th wrong attempt -> 429 Too Many Requests with Retry-After header
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await ManifestService(session).dispatch_manifest(
                manifest_id, tenant_id, current_user=ops, pickup_otp=wrong_otp
            )
    assert exc_info.value.status_code == 429
    assert exc_info.value.headers is not None
    assert int(exc_info.value.headers["Retry-After"]) == PICKUP_OTP_LOCKOUT_SECONDS

    # 4. Even the CORRECT OTP is rejected with 429 while locked out
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await ManifestService(session).dispatch_manifest(
                manifest_id, tenant_id, current_user=ops, pickup_otp=real_otp
            )
    assert exc_info.value.status_code == 429

    # 5. Reset lockout (simulating lockout expiry) and verify partial pickup with correct OTP
    reset_pickup_otp_attempts(manifest_id)
    async with session_factory() as session:
        dispatched = await ManifestService(session).dispatch_manifest(
            manifest_id,
            tenant_id,
            current_user=ops,
            picked_shipment_ids=[lr1.id],
            pickup_otp=real_otp,
        )

    assert dispatched["status"] == ManifestStatus.PICKED
    assert dispatched["pickup_otp"] is None  # stripped for operations_user
    assert dispatched["pickup_otp_verified_at"] is not None
    assert dispatched["pickup_otp_verified_by"] == ops.id
    assert dispatched["pickup_otp_override_reason"] is None
    assert manifest_list_cache.stats()["size"] == 0  # cache invalidated on dispatch
    assert eligible_shipments_cache.stats()["size"] == 0  # cache invalidated on dispatch

    # Verify DB state & ShipmentActivity audit trail
    async with session_factory() as session:
        lr1_row = await session.get(PickupRequest, lr1.id)
        lr2_row = await session.get(PickupRequest, lr2.id)
        activities = (
            await session.exec(
                select(ShipmentActivity).where(ShipmentActivity.pickup_id == lr1.id)
            )
        ).all()
    assert lr1_row.status == PickupStatus.IN_TRANSIT
    assert lr2_row.status == PickupStatus.OPEN and lr2_row.manifest_id is None
    dispatch_acts = [
        a for a in activities if a.diff and a.diff.get("status", {}).get("new") == "IN_TRANSIT"
    ]
    assert len(dispatch_acts) == 1
    assert dispatch_acts[0].diff["pickup_otp_verified"] is True


@pytest.mark.asyncio
async def test_owner_admin_override_with_mandatory_reason_and_audit_trail(session_factory) -> None:
    tenant_id = uuid.uuid4()
    alice = _user(tenant_id, UserRole.customer, "alice")
    ops = _user(tenant_id, UserRole.operations_user, "ops")
    admin = _user(tenant_id, UserRole.admin, "admin")
    hub = _address(tenant_id, alice.id)

    async with session_factory() as session:
        session.add_all([alice, ops, admin, hub])
        await session.flush()
        lr = _shipment(tenant_id, alice.id, hub)
        session.add(lr)
        await session.commit()

    async with session_factory() as session:
        created = await ManifestService(session).create_manifest(
            ManifestCreate(
                pickup_address_id=hub.id,
                scheduled_date=date.today(),
                time_slot="14:00 - 18:00",
                service_flow=ServiceFlow.B2C,
                shipment_ids=[lr.id],
            ),
            tenant_id=tenant_id,
            current_user=alice,
        )
    manifest_id = created["id"]

    # 1. Operations user cannot override OTP even with a reason -> 403 Forbidden
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await ManifestService(session).dispatch_manifest(
                manifest_id,
                tenant_id,
                current_user=ops,
                pickup_otp_override_reason="Seller phone unreachable at warehouse",
            )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == ERR_PICKUP_OTP_OVERRIDE_FORBIDDEN

    # 2. Admin with blank/whitespace override reason -> 400 Bad Request
    async with session_factory() as session:
        with pytest.raises(HTTPException) as exc_info:
            await ManifestService(session).dispatch_manifest(
                manifest_id,
                tenant_id,
                current_user=admin,
                pickup_otp_override_reason="   ",
            )
    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == ERR_PICKUP_OTP_OVERRIDE_REASON_REQUIRED

    # 3. Admin with valid mandatory reason succeeds and records override reason in DB + activity log
    reason = "Seller phone unreachable; physical dock sign-off verified by hub manager"
    async with session_factory() as session:
        dispatched = await ManifestService(session).dispatch_manifest(
            manifest_id,
            tenant_id,
            current_user=admin,
            pickup_otp_override_reason=reason,
        )

    assert dispatched["status"] == ManifestStatus.PICKED
    assert dispatched["pickup_otp_verified_at"] is not None
    assert dispatched["pickup_otp_verified_by"] == admin.id
    assert dispatched["pickup_otp_override_reason"] == reason

    async with session_factory() as session:
        activities = (
            await session.exec(
                select(ShipmentActivity).where(ShipmentActivity.pickup_id == lr.id)
            )
        ).all()
    dispatch_acts = [
        a for a in activities if a.diff and a.diff.get("status", {}).get("new") == "IN_TRANSIT"
    ]
    assert len(dispatch_acts) == 1
    assert dispatch_acts[0].diff["pickup_otp_override"] is True
    assert dispatch_acts[0].diff["pickup_otp_override_reason"] == reason
    assert reason in (dispatch_acts[0].comment or "")


@pytest.mark.asyncio
async def test_manifests_http_endpoints_and_response_audit(session_factory) -> None:
    tenant = Tenant(
        id=uuid.uuid4(),
        name="Logismart Test",
        slug="logismart-test",
        settings={"environment": "test"},
    )
    alice = _user(tenant.id, UserRole.customer, "alice")
    ops = _user(tenant.id, UserRole.operations_user, "ops")
    support = _user(tenant.id, UserRole.support_user, "support")
    readonly = _user(tenant.id, UserRole.read_only_user, "readonly")
    admin = _user(tenant.id, UserRole.admin, "admin")
    hub = _address(tenant.id, alice.id)

    async with session_factory() as session:
        session.add_all([tenant, alice, ops, support, readonly, admin, hub])
        await session.flush()
        lr = _shipment(tenant.id, alice.id, hub)
        session.add(lr)
        await session.flush()
        session.add(
            PackageDetails(
                pickup_id=lr.id, box_count=1, length=20, breadth=15, height=10, weight=1.0
            )
        )
        await session.commit()

    active_user_box = {"user": alice}

    async def _override_session():
        async with session_factory() as s:
            yield s

    test_app = FastAPI()
    test_app.add_middleware(ResponseAuditMiddleware)
    test_app.include_router(manifests_router, prefix="/api/v1/manifests")
    test_app.include_router(shipments_router, prefix="/api/v1/shipments")
    test_app.dependency_overrides[get_session] = _override_session
    test_app.dependency_overrides[get_tenant_from_header] = lambda: tenant
    test_app.dependency_overrides[get_current_active_user] = lambda: active_user_box["user"]

    transport = httpx.ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. POST /api/v1/manifests as customer -> 201 with 6-digit pickup_otp
        r_create = await client.post(
            "/api/v1/manifests",
            json={
                "pickup_address_id": str(hub.id),
                "scheduled_date": date.today().isoformat(),
                "time_slot": "14:00 - 18:00",
                "service_flow": "B2C",
                "is_blind_pickup": False,
                "total_boxes": 1,
                "shipment_ids": [str(lr.id)],
            },
        )
        assert r_create.status_code == 201
        created = r_create.json()
        manifest_id = created["id"]
        otp = created["pickup_otp"]
        assert isinstance(otp, str) and len(otp) == 6 and otp.isdigit()

        # 2. Bypass prevention: PATCH /api/v1/shipments/{id} {status: IN_TRANSIT} on a manifested
        #    ASSIGNED shipment is rejected with 400 (must go through POST /manifests/{id}/dispatch).
        active_user_box["user"] = ops
        r_bypass = await client.patch(
            f"/api/v1/shipments/{lr.id}",
            json={"status": "IN_TRANSIT", "comment": "Attempt direct bypass without OTP"},
        )
        assert r_bypass.status_code == 400
        assert "Cannot mark a manifested shipment In Transit directly" in r_bypass.json()["detail"]

        # 3. GET /api/v1/manifests/{id} across roles
        for restricted in (ops, support, readonly):
            active_user_box["user"] = restricted
            r_get = await client.get(f"/api/v1/manifests/{manifest_id}")
            assert r_get.status_code == 200
            assert r_get.json()["pickup_otp"] is None

        active_user_box["user"] = admin
        r_get_admin = await client.get(f"/api/v1/manifests/{manifest_id}")
        assert r_get_admin.status_code == 200
        assert r_get_admin.json()["pickup_otp"] == otp

        # 4. POST /api/v1/manifests/{id}/dispatch as operations_user with valid OTP -> 200
        active_user_box["user"] = ops
        r_bad = await client.post(
            f"/api/v1/manifests/{manifest_id}/dispatch",
            json={"pickup_otp": "000000" if otp != "000000" else "999999"},
        )
        assert r_bad.status_code == 400

        r_ok = await client.post(
            f"/api/v1/manifests/{manifest_id}/dispatch",
            json={"pickup_otp": otp},
        )
        assert r_ok.status_code == 200
        body = r_ok.json()
        assert body["status"] == "PICKED"
        assert body["pickup_otp"] is None
        assert body["pickup_otp_verified_at"] is not None
        assert body["pickup_otp_verified_by"] == str(ops.id)


def test_allowed_next_statuses_drops_in_transit_when_manifested() -> None:
    unmanifested = PickupRead.model_construct(
        status=PickupStatus.ASSIGNED, manifest_id=None
    )
    assert PickupStatus.IN_TRANSIT in unmanifested.allowed_next_statuses

    manifested = PickupRead.model_construct(
        status=PickupStatus.ASSIGNED, manifest_id=uuid.uuid4()
    )
    assert PickupStatus.IN_TRANSIT not in manifested.allowed_next_statuses


def test_logfire_scrubbing_includes_otp_pattern(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_kwargs: dict[str, Any] = {}

    def _fake_configure(**kwargs: Any) -> None:
        captured_kwargs.update(kwargs)

    monkeypatch.setattr(app_logging.settings, "LOGFIRE_TOKEN", "test-token")
    monkeypatch.setattr(app_logging.logfire, "configure", _fake_configure)
    monkeypatch.setattr(app_logging.logfire, "install_auto_tracing", lambda **kw: None)
    monkeypatch.setattr(app_logging.logfire, "LogfireLoggingHandler", logging_dummy_handler)

    app_logging.setup_logging()
    scrubbing = captured_kwargs.get("scrubbing")
    assert scrubbing is not None
    assert "otp" in (scrubbing.extra_patterns or [])


class logging_dummy_handler(app_logging.logging.Handler):
    def emit(self, record: Any) -> None:
        pass


