# backend/app/repositories/addresses.py
import uuid
from typing import List, Optional, Tuple

from sqlalchemy import exists, or_
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.ttl_cache import TTLCache
from app.models.manifests import Manifest
from app.models.pickups import Address, AddressCategory, AddressScope, PickupRequest

# --- Short-lived address book cache (30s TTL, evicted on every committed Address write) ---
ADDRESS_CACHE_TTL_SECONDS: float = 30.0
ADDRESS_LIST_CACHE_MAX_ENTRIES: int = 64
ADDRESS_BY_ID_CACHE_MAX_ENTRIES: int = 2048
ADDRESS_LIST_CACHE_MAX_ROWS: int = 100
"""Address books longer than this are served from the database, never pinned in memory."""


def _clone_address(addr: Address) -> Address:
    """A detached Address copy (every column, no relationships)."""
    return Address.model_validate(addr.model_dump())


def _clone_addresses(addresses: List[Address]) -> List[Address]:
    return [_clone_address(a) for a in addresses]


AddressListKey = Tuple[uuid.UUID, uuid.UUID, Optional[str]]
"""(tenant_id, viewer user_id, category): a list is scoped to what that viewer may see."""

_address_list_cache: TTLCache[AddressListKey, List[Address]] = TTLCache(
    "address_list",
    ttl_seconds=ADDRESS_CACHE_TTL_SECONDS,
    max_entries=ADDRESS_LIST_CACHE_MAX_ENTRIES,
    clone=_clone_addresses,
    invalidated_by={Address: "tenant_id"},
    max_items_per_entry=ADDRESS_LIST_CACHE_MAX_ROWS,
)
_address_by_id_cache: TTLCache[Tuple[uuid.UUID, uuid.UUID], Address] = TTLCache(
    "address_by_id",
    ttl_seconds=ADDRESS_CACHE_TTL_SECONDS,
    max_entries=ADDRESS_BY_ID_CACHE_MAX_ENTRIES,
    clone=_clone_address,
    invalidated_by={Address: "tenant_id"},
)


def get_cached_address_by_id(
    tenant_id: uuid.UUID, address_id: uuid.UUID
) -> Optional[Address]:
    """
    A detached copy of a tenant address seen in a recently listed address book, or None.
    NOT viewer-scoped: callers must still apply their own ownership check.
    """
    return _address_by_id_cache.get((tenant_id, address_id))


def invalidate_address_cache(tenant_id: Optional[uuid.UUID] = None) -> None:
    """Evicts one tenant's (or every) cached address. Committed writes do this automatically."""
    _address_list_cache.invalidate(tenant_id)
    _address_by_id_cache.invalidate(tenant_id)


class AddressRepository:
    """
    Handles all database operations for the Address model.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_saved_addresses(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        category: Optional[AddressCategory] = None,
    ) -> List[Address]:
        """
        Saved addresses visible to `user_id` (tenant-shared + their own), served from a
        30s cache keyed by (tenant, viewer, category). Returns detached copies.
        """
        key: AddressListKey = (tenant_id, user_id, category.value if category else None)
        cached = _address_list_cache.get(key)
        if cached is not None:
            return cached
        generation = _address_list_cache.generation()

        statement = select(Address).where(
            Address.tenant_id == tenant_id,
            Address.is_saved,
            (Address.scope == AddressScope.TENANT) | (Address.user_id == user_id),
        )
        if category:
            statement = statement.where(Address.category == category)
        statement = statement.order_by(col(Address.name).asc(), col(Address.id).asc())
        addresses = list((await self.session.exec(statement)).all())
        for addr in addresses:
            _address_by_id_cache.set((tenant_id, addr.id), addr, generation=generation)
        return _address_list_cache.set(key, addresses, generation=generation)

    async def create_address(self, address: Address) -> Address:
        """
        Persists a new or updated Address object to the database.
        """
        self.session.add(address)
        await self.session.commit()
        await self.session.refresh(address)
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
