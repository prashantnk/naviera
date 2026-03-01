# backend/app/repositories/addresses.py
import uuid
from typing import List, Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.pickups import Address, AddressType


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
        address_type: Optional[AddressType] = None,
    ) -> List[Address]:
        """
        Retrieves explicitly saved addresses, optionally filtered by type.
        """
        statement = select(Address).where(
            Address.tenant_id == tenant_id,
            Address.user_id == user_id,
            Address.is_saved == True,
        )

        # APPLY the filter if it was provided
        if address_type:
            statement = statement.where(Address.address_type == address_type)

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
