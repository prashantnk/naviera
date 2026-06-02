# backend/app/repositories/addresses.py
import uuid
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import Address, AddressCategory, AddressScope


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
        Retrieves explicitly saved addresses, optionally filtered by category.
        """
        statement = select(Address).where(
            Address.tenant_id == tenant_id,
            Address.is_saved,
            (Address.scope == AddressScope.TENANT) |
            (Address.user_id == user_id)
        )

        # APPLY the filter if it was provided
        if category:
            statement = statement.where(Address.category == category)

        result = await self.session.exec(statement)
        return list(result.all())

    async def create_address(self, address: Address) -> Address:
        """
        Persists a new Address object to the database.
        """
        self.session.add(address)
        await self.session.commit()
        await self.session.refresh(address)
        return address

    async def get_address_by_id(self, address_id: uuid.UUID) -> Address | None:
        """Retrieves a single address by ID."""
        return await self.session.get(Address, address_id)

    async def get_address_by_signature(self, tenant_id: uuid.UUID, signature: str) -> Address | None:
        """Retrieves a single address by its signature within a tenant."""
        statement = select(Address).where(
            Address.tenant_id == tenant_id,
            Address.address_signature == signature,
        )
        result = await self.session.exec(statement)
        return result.first()
