"""
Pure unit tests for the shared in-process cache (`app/core/ttl_cache.py`) and every
cache built on it (auth Tenant/User, address book, pickup-request lists).

Proves: hard size bound under 10k distinct keys, TTL expiry purge, misses / unknown slugs
never cached, detached copies, the load-vs-invalidate race guard, and automatic eviction on
every committed (or rolled back) ORM write, incl. user deactivation / demotion, tenant
settings, address edits, new shipments, shipment status changes from the temporal-hooks
worker, package edits and pickup-request writes. Runs on an in-memory SQLite database,
never the shared Postgres.
"""

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, AsyncIterator, List, Optional

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import ttl_cache
from app.core.dependencies import (
    USER_CACHE_MAX_ENTRIES,
    _user_by_tenant_sub,
    get_current_active_user,
    get_tenant_from_header,
    load_tenant_by_id,
)
from app.core.ttl_cache import (
    ALL_TENANTS,
    TTLCache,
    all_cache_stats,
    pending_invalidations,
    set_caches_enabled_for_tests,
)
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
    ServiceType,
    ShipmentActivity,
    ShipmentType,
)
from app.models.tenants import ServiceScope, Tenant, User, UserRole
from app.repositories.addresses import (
    AddressRepository,
    _address_by_id_cache,
    _address_list_cache,
    get_cached_address_by_id,
)
from app.repositories.manifests import eligible_shipments_cache, manifest_list_cache
from app.repositories.tenants import TenantRepository
from app.services.manifests import ManifestService
from app.services.tenants import TenantService
from scripts.temporal_hooks_worker import check_appointments

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
DISTINCT_KEYS = 10_000


@compiles(JSONB, "sqlite")
def _jsonb_as_json(type_, compiler, **kw) -> str:
    return "JSON"


@compiles(ARRAY, "sqlite")
def _array_as_json(type_, compiler, **kw) -> str:
    return "JSON"


class FakeClock:
    """Stands in for `time.monotonic` so TTL tests never sleep."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def caches_on():
    set_caches_enabled_for_tests(True)
    yield
    set_caches_enabled_for_tests(None)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(ttl_cache.time, "monotonic", fake)
    return fake


@pytest.fixture
def cache() -> TTLCache:
    return TTLCache(
        "unit",
        ttl_seconds=30.0,
        max_entries=100,
        invalidated_by={},
        max_items_per_entry=3,
    )


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[sessionmaker]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: SQLModel.metadata.create_all(c, tables=TABLES))
    yield sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


# --------------------------------------------------------------------------- core helper


def test_size_stays_bounded_under_10k_distinct_keys(cache: TTLCache) -> None:
    for i in range(DISTINCT_KEYS):
        cache.set((uuid.uuid4(), f"search-{i}"), [i])
    stats = cache.stats()
    assert stats["size"] == cache.max_entries
    assert stats["evictions"] == DISTINCT_KEYS - cache.max_entries


def test_lru_keeps_recently_read_entries(cache: TTLCache) -> None:
    tenant = uuid.uuid4()
    hot = (tenant, "hot")
    cache.set(hot, [1])
    for i in range(cache.max_entries * 3):
        cache.set((tenant, i), [i])
        assert cache.get(hot) == [1]


def test_expired_entries_are_purged_without_being_read(cache: TTLCache, clock: FakeClock) -> None:
    tenant = uuid.uuid4()
    for i in range(50):
        cache.set((tenant, i), [i])
    clock.now += cache.ttl_seconds + 1
    assert cache.get((tenant, 0)) is None
    cache.set((tenant, "fresh"), [1])  # the periodic purge runs on the next store
    assert cache.stats()["size"] == 1


def test_values_are_detached_copies(cache: TTLCache) -> None:
    key = (uuid.uuid4(), "k")
    original = [{"status": "OPEN"}]
    returned = cache.set(key, original)
    original[0]["status"] = "MUTATED"
    returned[0]["status"] = "MUTATED"
    hit = cache.get(key)
    hit[0]["status"] = "MUTATED"
    assert cache.get(key) == [{"status": "OPEN"}]


def test_over_long_lists_are_served_but_not_stored(cache: TTLCache) -> None:
    key = (uuid.uuid4(), "big")
    assert cache.set(key, [1, 2, 3, 4]) == [1, 2, 3, 4]
    assert cache.get(key) is None


def test_load_that_overlaps_an_invalidation_is_not_stored(cache: TTLCache) -> None:
    key = (uuid.uuid4(), "k")
    generation = cache.generation()
    cache.invalidate(uuid.uuid4())  # any write commits while the reader is querying
    cache.set(key, ["stale"], generation=generation)
    assert cache.get(key) is None
    cache.set(key, ["fresh"], generation=cache.generation())
    assert cache.get(key) == ["fresh"]


def test_invalidate_is_tenant_scoped(cache: TTLCache) -> None:
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    cache.set((tenant_a, 1), [1])
    cache.set((tenant_b, 1), [2])
    cache.invalidate(tenant_a)
    assert cache.get((tenant_a, 1)) is None
    assert cache.get((tenant_b, 1)) == [2]
    cache.invalidate(ALL_TENANTS)
    assert cache.stats()["size"] == 0


@pytest.mark.asyncio
async def test_misses_are_never_cached(cache: TTLCache) -> None:
    async def not_found() -> Optional[list]:
        return None

    for i in range(DISTINCT_KEYS):
        assert await cache.get_or_load((uuid.uuid4(), f"random-slug-{i}"), not_found) is None
    assert cache.stats()["size"] == 0


def test_disabled_cache_is_a_pass_through(cache: TTLCache) -> None:
    set_caches_enabled_for_tests(False)
    value = [1]
    assert cache.set((uuid.uuid4(), "k"), value) is value
    assert cache.stats()["size"] == 0


def test_every_cache_has_a_hard_cap() -> None:
    stats = all_cache_stats()
    assert {s["name"] for s in stats} >= {
        "tenant_by_slug",
        "tenant_by_id",
        "user_by_tenant_sub",
        "address_list",
        "address_by_id",
        "manifest_list",
        "eligible_shipments",
    }
    assert all(0 < s["max_entries"] <= 4096 for s in stats)


def test_written_models_map_to_the_caches_they_feed() -> None:
    tenant_id = uuid.uuid4()

    def caches_for(instance: Any) -> set:
        return {(c.name, t) for c, t in pending_invalidations([instance]) if c.name != "unit"}

    assert caches_for(Tenant(id=tenant_id, slug="x", name="x")) == {
        ("tenant_by_slug", tenant_id),
        ("tenant_by_id", tenant_id),
    }
    assert caches_for(User(supabase_user_id="s", email="e", tenant_id=tenant_id)) == {
        ("user_by_tenant_sub", tenant_id)
    }
    assert caches_for(Address(tenant_id=tenant_id, name="n", phone="p", address_line1="l",
                              city="c", state="s", pincode="1")) == {
        ("address_list", tenant_id),
        ("address_by_id", tenant_id),
        ("manifest_list", tenant_id),
        ("eligible_shipments", tenant_id),
    }
    assert caches_for(PackageDetails(pickup_id=uuid.uuid4())) == {
        ("manifest_list", ALL_TENANTS),
        ("eligible_shipments", ALL_TENANTS),
    }
    for row in (PickupRequest(tenant_id=tenant_id), Manifest(tenant_id=tenant_id)):
        assert caches_for(row) == {
            ("manifest_list", tenant_id),
            ("eligible_shipments", tenant_id),
        }


# --------------------------------------------------------------------- auth dependencies


async def _seed_tenant_and_user(factory: sessionmaker) -> SimpleNamespace:
    tenant = Tenant(slug=f"t-{uuid.uuid4().hex[:8]}", name="T", settings={"brand": {"c": 1}})
    user = User(
        supabase_user_id=str(uuid.uuid4()),
        email="ops@logismart.in",
        role=UserRole.operations_user,
        service_scope=ServiceScope.BOTH,
        tenant_id=tenant.id,
    )
    async with factory() as session:
        session.add_all([tenant, user])
        await session.commit()
    return SimpleNamespace(tenant=tenant, user=user)


async def _authenticate(factory: sessionmaker, slug: str, sub: str) -> User:
    async with factory() as session:
        tenant = await get_tenant_from_header(x_tenant_slug=slug, session=session)
        return await get_current_active_user(
            session=session, current_tenant=tenant, token_data=SimpleNamespace(sub=sub)
        )


async def _update_user(factory: sessionmaker, user_id: uuid.UUID, **changes: Any) -> None:
    async with factory() as session:
        row = await session.get(User, user_id)
        for key, value in changes.items():
            setattr(row, key, value)
        await session.commit()


@pytest.mark.asyncio
async def test_deactivated_user_is_locked_out_on_the_next_request(session_factory) -> None:
    seed = await _seed_tenant_and_user(session_factory)
    first = await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    assert first.role == UserRole.operations_user

    await _update_user(session_factory, seed.user.id, role=UserRole.read_only_user)
    demoted = await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    assert demoted.role == UserRole.read_only_user

    await _update_user(session_factory, seed.user.id, is_active=False)
    with pytest.raises(HTTPException) as exc:
        await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_cached_user_is_a_detached_copy(session_factory) -> None:
    seed = await _seed_tenant_and_user(session_factory)
    await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    hit = await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    hit.role = UserRole.owner  # a caller mutating its copy must not escalate anyone
    again = await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    assert again.role == UserRole.operations_user
    assert again.tenant is None  # no lazy relationship to trip MissingGreenlet


@pytest.mark.asyncio
async def test_rolled_back_write_evicts_and_keeps_db_value(session_factory) -> None:
    seed = await _seed_tenant_and_user(session_factory)
    await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    async with session_factory() as session:
        row = await session.get(User, seed.user.id)
        row.role = UserRole.owner
        await session.flush()
        assert ttl_cache._registry and all_cache_stats()[2]["size"] == 0
        await session.rollback()
    user = await _authenticate(session_factory, seed.tenant.slug, seed.user.supabase_user_id)
    assert user.role == UserRole.operations_user


@pytest.mark.asyncio
async def test_tenant_settings_change_is_visible_immediately(session_factory) -> None:
    seed = await _seed_tenant_and_user(session_factory)
    async with session_factory() as session:
        cached = await get_tenant_from_header(x_tenant_slug=seed.tenant.slug, session=session)
        assert cached.settings == {"brand": {"c": 1}}
        assert await load_tenant_by_id(seed.tenant.id, lambda: session.get(Tenant, seed.tenant.id))
    async with session_factory() as session:
        row = await session.get(Tenant, seed.tenant.id)
        row.settings = {"brand": {"c": 2}}
        await session.commit()
    async with session_factory() as session:
        fresh = await get_tenant_from_header(x_tenant_slug=seed.tenant.slug, session=session)
        by_id = await load_tenant_by_id(seed.tenant.id, lambda: session.get(Tenant, seed.tenant.id))
    assert fresh.settings == by_id.settings == {"brand": {"c": 2}}


@pytest.mark.asyncio
async def test_unknown_tenant_slugs_are_not_cached(session_factory) -> None:
    async with session_factory() as session:
        for i in range(200):
            with pytest.raises(HTTPException):
                await get_tenant_from_header(x_tenant_slug=f"nope-{i}", session=session)
    assert next(s for s in all_cache_stats() if s["name"] == "tenant_by_slug")["size"] == 0


def test_user_cache_is_bounded() -> None:
    tenant_id = uuid.uuid4()
    for i in range(DISTINCT_KEYS):
        _user_by_tenant_sub.set(
            (tenant_id, str(i)),
            User(supabase_user_id=str(i), email=f"{i}@x.in", tenant_id=tenant_id),
        )
    assert _user_by_tenant_sub.stats()["size"] == USER_CACHE_MAX_ENTRIES


# ----------------------------------------------------------------------- address book


def _address(tenant_id: uuid.UUID, user_id: uuid.UUID, name: str, scope: AddressScope) -> Address:
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


@pytest.mark.asyncio
async def test_address_book_is_viewer_scoped_and_refreshed_on_every_write(session_factory) -> None:
    tenant_id, alice, bob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    shared = _address(tenant_id, alice, "Shared Hub", AddressScope.TENANT)
    private = _address(tenant_id, alice, "Alice Home", AddressScope.PRIVATE)
    async with session_factory() as session:
        session.add_all([shared, private])
        await session.commit()

    async def names(viewer: uuid.UUID) -> List[str]:
        async with session_factory() as session:
            rows = await AddressRepository(session).list_saved_addresses(tenant_id, viewer)
            return [a.name for a in rows]

    assert await names(alice) == ["Alice Home", "Shared Hub"]
    assert await names(bob) == ["Shared Hub"]  # Bob never gets Alice's cached private row
    assert get_cached_address_by_id(tenant_id, private.id).name == "Alice Home"

    async with session_factory() as session:  # edit
        row = await session.get(Address, shared.id)
        row.name = "Renamed Hub"
        await AddressRepository(session).create_address(row)
    assert await names(bob) == ["Renamed Hub"]

    async with session_factory() as session:  # soft delete
        row = await session.get(Address, private.id)
        row.is_saved = False
        await AddressRepository(session).create_address(row)
    assert await names(alice) == ["Renamed Hub"]

    async with session_factory() as session:  # create
        await AddressRepository(session).create_address(
            _address(tenant_id, bob, "Bob Shop", AddressScope.PRIVATE)
        )
    assert await names(bob) == ["Bob Shop", "Renamed Hub"]
    assert _address_list_cache.stats()["hits"] == 0  # every read after a write was a miss
    assert _address_by_id_cache.stats()["size"] > 0


# ------------------------------------------------------------------- pickup requests


def _shipment(tenant_id: uuid.UUID, user_id: uuid.UUID, address: Address, **kw: Any) -> PickupRequest:
    return PickupRequest(
        tenant_id=tenant_id,
        created_by_user_id=user_id,
        product_category=ProductCategory.ELECTRONICS,
        requested_pickup_date=date.today(),
        pickup_address_id=address.id,
        delivery_address_id=address.id,
        shipment_type=ShipmentType.FORWARD,
        service_type=ServiceType.SURFACE_ROAD,
        **kw,
    )


def _customer(tenant_id: uuid.UUID, user_id: uuid.UUID) -> User:
    return User(
        id=user_id,
        supabase_user_id=str(user_id),
        email=f"{user_id}@x.in",
        role=UserRole.customer,
        tenant_id=tenant_id,
    )


@pytest.mark.asyncio
async def test_pickup_request_caches_follow_every_write_path(session_factory) -> None:
    tenant_id, alice, bob = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    staff = User(supabase_user_id="s", email="a@x.in", role=UserRole.admin, tenant_id=tenant_id)
    hub = _address(tenant_id, alice, "Hub", AddressScope.TENANT)
    async with session_factory() as session:
        session.add(hub)
        await session.flush()
        alice_lr = _shipment(tenant_id, alice, hub, status=PickupStatus.ASSIGNED,
                             appointment_end=datetime.now(timezone.utc) - timedelta(hours=1))
        bob_lr = _shipment(tenant_id, bob, hub, status=PickupStatus.ASSIGNED)
        alice_pur = Manifest(tenant_id=tenant_id, pickup_address_id=hub.id,
                             scheduled_date=date.today(), time_slot="10:00 - 14:00",
                             service_flow=ServiceFlow.B2C, status=ManifestStatus.SCHEDULED)
        bob_pur = Manifest(tenant_id=tenant_id, pickup_address_id=hub.id,
                           scheduled_date=date.today(), time_slot="14:00 - 18:00",
                           service_flow=ServiceFlow.B2C, status=ManifestStatus.SCHEDULED)
        session.add_all([alice_pur, bob_pur])
        await session.flush()
        alice_lr.manifest_id, bob_lr.manifest_id = alice_pur.id, bob_pur.id
        session.add_all([alice_lr, bob_lr])
        await session.commit()

    async def listed(user: User) -> list:
        async with session_factory() as session:
            return await ManifestService(session).list_manifests(tenant_id, current_user=user)

    async def eligible(user: User) -> list:
        async with session_factory() as session:
            return await ManifestService(session).list_eligible_shipments(
                tenant_id, ServiceFlow.B2C, hub.id, current_user=user
            )

    # Customer scoping (SQL + cache key): each customer sees only their own pickup request.
    assert [m["id"] for m in await listed(_customer(tenant_id, alice))] == [alice_pur.id]
    assert [m["id"] for m in await listed(_customer(tenant_id, bob))] == [bob_pur.id]
    assert len(await listed(staff)) == 2
    assert len(await listed(staff)) == 2 and manifest_list_cache.stats()["hits"] == 1

    # Shipment status change from the temporal-hooks worker (no manual invalidation there).
    async with session_factory() as session:
        alice_row = await session.get(PickupRequest, alice_lr.id)
        alice_row.status = PickupStatus.IN_TRANSIT
        await session.commit()
        assert await check_appointments(session) == 1
        await session.commit()
    statuses = {s["status"] for m in await listed(staff) for s in m["shipments"]}
    assert PickupStatus.EXCEPTION in statuses

    # Pickup address rename shows on the list.
    async with session_factory() as session:
        (await session.get(Address, hub.id)).name = "Hub 2"
        await session.commit()
    assert {m["pickup_location_name"] for m in await listed(staff)} == {"Hub 2"}

    # Package edit (row without tenant_id) refreshes the box count.
    async with session_factory() as session:
        session.add(PackageDetails(pickup_id=bob_lr.id, box_count=4, length=10, breadth=10,
                                   height=10, weight=1))
        await session.commit()
    bob_counts = [s["package_count"] for m in await listed(staff) for s in m["shipments"]
                  if s["id"] == bob_lr.id]
    assert bob_counts == [4]

    # A newly booked OPEN shipment appears in the Create Pickup Request picker at once.
    assert await eligible(staff) == []
    async with session_factory() as session:
        new_lr = _shipment(tenant_id, alice, hub, status=PickupStatus.OPEN)
        session.add(new_lr)
        await session.commit()
    assert [s["id"] for s in await eligible(staff)] == [new_lr.id]
    assert await eligible(_customer(tenant_id, bob)) == []

    # Manifest status write (cancel / dispatch / OTP columns) refreshes the list.
    async with session_factory() as session:
        (await session.get(Manifest, bob_pur.id)).status = ManifestStatus.CANCELED
        await session.commit()
    by_id = {m["id"]: m["status"] for m in await listed(staff)}
    assert by_id[bob_pur.id] == ManifestStatus.CANCELED
    assert eligible_shipments_cache.stats()["size"] == 0  # evicted by the same write


@pytest.mark.asyncio
async def test_get_admin_tenant_settings_fetches_fresh_database_row_without_stale_cache(
    session_factory,
):
    """
    Proves `TenantService.get_admin_tenant_settings` (invoked without tenant override)
    loads the canonical settings from `TenantRepository`, reflecting out-of-band / session
    flushes immediately rather than serving stale header or cached data.
    """
    tenant_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    admin = User(
        id=admin_id,
        supabase_user_id="sb-admin",
        email="admin@example.com",
        tenant_id=tenant_id,
        role=UserRole.admin,
        is_active=True,
    )
    initial_tenant = Tenant(
        id=tenant_id,
        name="Test Tenant",
        slug="test-tenant",
        settings={"wallet_config": {"merchant_name": "Initial"}},
    )

    async with session_factory() as session:
        session.add(initial_tenant)
        session.add(admin)
        await session.commit()

    async with session_factory() as session:
        repo = TenantRepository(session)
        service = TenantService(repo)

        # 1. Fetching admin settings without passing `tenant` loads from repository
        res = await service.get_admin_tenant_settings(tenant_id, admin)
        assert res.settings["wallet_config"]["merchant_name"] == "Initial"

        # 2. Directly update tenant settings in DB (simulating background or transaction write)
        row = await session.get(Tenant, tenant_id)
        row.settings = {
            "wallet_config": {
                "merchant_name": "Updated",
                "merchant_vpa": "secret@vpa",
            }
        }
        await session.commit()

        # 3. get_admin_tenant_settings immediately returns updated DB settings
        fresh = await service.get_admin_tenant_settings(tenant_id, admin)
        assert fresh.settings["wallet_config"]["merchant_name"] == "Updated"
        assert fresh.settings["wallet_config"]["merchant_vpa"] == "secret@vpa"

