# backend/app/repositories/addresses.py
import sys
import threading
import time
import uuid
from typing import Dict, List, Optional, Tuple

from sqlalchemy import exists, func, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.manifests import Manifest
from app.models.pickups import Address, AddressCategory, AddressScope, PickupRequest
from app.repositories.manifests import invalidate_manifests_cache

# --- Short-Lived Tenant-Scoped Address List Cache (30s TTL) ---
_ADDRESS_CACHE_TTL_SECONDS: float = 30.0
_ADDRESS_CACHE_MAX_SIZE: int = 512
_ADDRESS_CACHE_FORCE_ENABLED: bool = False
_address_cache_lock = threading.Lock()
_AddressCacheKey = Tuple[
    uuid.UUID,
    Optional[uuid.UUID],
    Optional[bool],
    Optional[str],
    str,
    int,
    Optional[int],
]
_address_list_cache: Dict[_AddressCacheKey, Tuple[float, List[Address], int]] = {}


def _is_address_cache_enabled() -> bool:
    if _ADDRESS_CACHE_FORCE_ENABLED:
        return True
    return "pytest" not in sys.modules


def set_address_cache_enabled_for_tests(enabled: bool) -> None:
    """Explicitly enables or disables the address list cache inside unit tests."""
    global _ADDRESS_CACHE_FORCE_ENABLED
    _ADDRESS_CACHE_FORCE_ENABLED = enabled
    if not enabled:
        clear_address_cache()


def _clone_address(addr: Address) -> Address:
    """Returns a detached Address clone safe to use across async sessions."""
    if not isinstance(addr, Address):
        return addr
    cloned = Address(
        id=addr.id,
        tenant_id=addr.tenant_id,
        user_id=addr.user_id,
        category=addr.category,
        scope=addr.scope,
        alternate_phone=addr.alternate_phone,
        gstin=addr.gstin,
        address_signature=addr.address_signature,
        is_saved=addr.is_saved,
        name=addr.name,
        phone=addr.phone,
        email=addr.email,
        company_name=addr.company_name,
        address_line1=addr.address_line1,
        address_line2=addr.address_line2,
        landmark=addr.landmark,
        city=addr.city,
        state=addr.state,
        pincode=addr.pincode,
        country=addr.country,
    )
    total_count = getattr(addr, "_total_count", None)
    if total_count is not None:
        object.__setattr__(cloned, "_total_count", int(total_count))
    return cloned


def _build_address_cache_key(
    *,
    tenant_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
    is_saved: Optional[bool] = True,
    address_type: Optional[AddressCategory] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: Optional[int] = None,
) -> _AddressCacheKey:
    cat_val = (
        address_type.value
        if hasattr(address_type, "value")
        else (str(address_type) if address_type is not None else None)
    )
    norm_search = (search or "").strip().lower()
    return (tenant_id, user_id, is_saved, cat_val, norm_search, int(skip), limit)


def get_cached_address_list(
    *,
    tenant_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
    is_saved: Optional[bool] = True,
    address_type: Optional[AddressCategory] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: Optional[int] = None,
) -> Optional[Tuple[List[Address], int]]:
    """Returns detached clones of cached Address rows and total count on hit."""
    if not _is_address_cache_enabled():
        return None
    key = _build_address_cache_key(
        tenant_id=tenant_id,
        user_id=user_id,
        is_saved=is_saved,
        address_type=address_type,
        search=search,
        skip=skip,
        limit=limit,
    )
    now = time.monotonic()
    with _address_cache_lock:
        entry = _address_list_cache.get(key)
        if entry is None:
            return None
        expires_at, cached_items, cached_total = entry
        if now >= expires_at:
            _address_list_cache.pop(key, None)
            return None
        return [_clone_address(a) for a in cached_items], cached_total


def get_cached_address_by_id(
    tenant_id: uuid.UUID, address_id: uuid.UUID
) -> Optional[Address]:
    """Returns a detached Address clone from any non-expired tenant cache entry on hit."""
    if not _is_address_cache_enabled():
        return None
    now = time.monotonic()
    with _address_cache_lock:
        for key, (expires_at, cached_items, _) in list(_address_list_cache.items()):
            if key[0] != tenant_id:
                continue
            if now >= expires_at:
                _address_list_cache.pop(key, None)
                continue
            for addr in cached_items:
                if addr.id == address_id:
                    return _clone_address(addr)
    return None


def cache_address_list(
    items: List[Address],
    total: int,
    *,
    tenant_id: uuid.UUID,
    user_id: Optional[uuid.UUID] = None,
    is_saved: Optional[bool] = True,
    address_type: Optional[AddressCategory] = None,
    search: Optional[str] = None,
    skip: int = 0,
    limit: Optional[int] = None,
) -> List[Address]:
    """Stores detached Address clones in the 30s TTL cache and returns detached clones."""
    detached = [_clone_address(a) for a in items]
    if not _is_address_cache_enabled():
        return detached
    key = _build_address_cache_key(
        tenant_id=tenant_id,
        user_id=user_id,
        is_saved=is_saved,
        address_type=address_type,
        search=search,
        skip=skip,
        limit=limit,
    )
    expires_at = time.monotonic() + _ADDRESS_CACHE_TTL_SECONDS
    with _address_cache_lock:
        if len(_address_list_cache) >= _ADDRESS_CACHE_MAX_SIZE:
            _address_list_cache.clear()
        _address_list_cache[key] = (expires_at, detached, int(total))
    return [_clone_address(a) for a in detached]


def invalidate_address_cache(tenant_id: Optional[uuid.UUID] = None) -> None:
    """
    Evicts cached Address list entries for `tenant_id` (or all tenants when None)
    immediately on any address create, update, or soft-delete mutation.
    Also invalidates that tenant's manifest list cache so warehouse names/addresses stay fresh.
    """
    with _address_cache_lock:
        if tenant_id is None:
            _address_list_cache.clear()
        else:
            for key in list(_address_list_cache.keys()):
                if key[0] == tenant_id:
                    _address_list_cache.pop(key, None)
    invalidate_manifests_cache(tenant_id)


def clear_address_cache() -> None:
    """Clears the entire address cache."""
    invalidate_address_cache(None)


class AddressRepository:
    """
    Handles all database operations for the Address model.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_saved_addresses(
        self,
        tenant_id: uuid.UUID,
        user_id: Optional[uuid.UUID] = None,
        category: Optional[AddressCategory] = None,
        *,
        is_saved: Optional[bool] = True,
        search: Optional[str] = None,
        skip: int = 0,
        limit: Optional[int] = None,
    ) -> List[Address]:
        """
        Retrieves saved addresses in a single SQL round-trip (`func.count().over()`),
        backed by a 30s TTL tenant-scoped in-memory cache with 0ms mutation invalidation.
        """
        cached = get_cached_address_list(
            tenant_id=tenant_id,
            user_id=user_id,
            is_saved=is_saved,
            address_type=category,
            search=search,
            skip=skip,
            limit=limit,
        )
        if cached is not None:
            return cached[0]

        filters = [Address.tenant_id == tenant_id]
        if is_saved is not None:
            filters.append(Address.is_saved == is_saved)
        if user_id is not None:
            filters.append(
                (Address.scope == AddressScope.TENANT) | (Address.user_id == user_id)
            )
        if category:
            filters.append(Address.category == category)

        search_term = (search or "").strip()
        if search_term:
            pattern = f"%{search_term}%"
            filters.append(
                or_(
                    col(Address.name).ilike(pattern),
                    col(Address.company_name).ilike(pattern),
                    col(Address.city).ilike(pattern),
                    col(Address.pincode).ilike(pattern),
                    col(Address.phone).ilike(pattern),
                )
            )

        statement = (
            select(
                Address,
                func.count().over().label("_total_count"),
            )
            .where(*filters)
            .order_by(col(Address.name).asc(), col(Address.id).asc())
        )
        if skip > 0:
            statement = statement.offset(skip)
        if limit is not None:
            statement = statement.limit(limit)

        raw_rows = (await self.session.exec(statement)).all()
        items: List[Address] = []
        total = 0
        if raw_rows:
            first = raw_rows[0]
            if isinstance(first, Address):
                items = list(raw_rows)  # type: ignore[arg-type]
                total = len(items)
            else:
                total = int(first[1] or 0)
                items = [r[0] for r in raw_rows]
            for addr in items:
                object.__setattr__(addr, "_total_count", total)
        elif skip > 0:
            count_stmt = select(func.count(col(Address.id))).where(*filters)
            total = int((await self.session.exec(count_stmt)).one() or 0)

        return cache_address_list(
            items,
            total,
            tenant_id=tenant_id,
            user_id=user_id,
            is_saved=is_saved,
            address_type=category,
            search=search,
            skip=skip,
            limit=limit,
        )

    async def create_address(self, address: Address) -> Address:
        """
        Persists a new or updated Address object to the database and invalidates
        the tenant's address & manifest caches immediately.
        """
        self.session.add(address)
        await self.session.commit()
        await self.session.refresh(address)
        invalidate_address_cache(address.tenant_id)
        return address

    async def get_address_by_id(self, address_id: uuid.UUID) -> Address | None:
        """Retrieves a single address by ID."""
        return await self.session.get(Address, address_id)

    async def get_address_by_signature(
        self,
        tenant_id: uuid.UUID,
        signature: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> Address | None:
        """Retrieves a single address by its signature within a tenant."""
        statement = select(Address).where(
            Address.tenant_id == tenant_id,
            Address.address_signature == signature,
        )
        if user_id is not None:
            statement = statement.where(
                (Address.scope == AddressScope.TENANT) | (Address.user_id == user_id)
            )
        result = await self.session.exec(statement)
        return result.first()

    async def is_address_referenced(
        self,
        tenant_id: uuid.UUID,
        address_id: uuid.UUID,
    ) -> bool:
        """
        Returns True if the address row is referenced by any shipment (PickupRequest)
        or pickup request (Manifest) within the tenant (D-03) in a single SQL round-trip.
        """
        shipment_exists = exists(
            select(PickupRequest.id).where(
                PickupRequest.tenant_id == tenant_id,
                (PickupRequest.pickup_address_id == address_id)
                | (PickupRequest.delivery_address_id == address_id),
            )
        )
        manifest_exists = exists(
            select(Manifest.id).where(
                Manifest.tenant_id == tenant_id,
                Manifest.pickup_address_id == address_id,
            )
        )
        stmt = select(or_(shipment_exists, manifest_exists))
        return bool((await self.session.exec(stmt)).one())
