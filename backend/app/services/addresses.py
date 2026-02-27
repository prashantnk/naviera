# backend/app/services/addresses.py
from typing import List, Optional

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.pickups import Address, AddressType
from app.models.tenants import Tenant, User
from app.repositories.addresses import AddressRepository
from app.schemas.v1.pickups import AddressCreate


class AddressService:
    """
    Handles the business logic for Address Book management.
    """

    def __init__(self, address_repo: AddressRepository):
        self.address_repo = address_repo

    async def list_saved_addresses(
        self, user: User, tenant: Tenant, address_type: Optional[AddressType] = None
    ) -> List[Address]:

        return await self.address_repo.list_saved_addresses(
            tenant_id=tenant.id, user_id=user.id, address_type=address_type
        )

    async def create_saved_address(
        self, payload: AddressCreate, user: User, tenant: Tenant
    ) -> Address:
        """
        Business Logic to add a new address to the address book.
        Forces the 'is_saved' flag to True.
        """
        address_data = payload.model_dump(exclude={"is_saved"})
        # Convert the Pydantic schema to the SQLModel database object
        new_address = Address(
            **address_data,
            tenant_id=tenant.id,
            user_id=user.id,
            is_saved=True,  # Force it to be a permanent address book entry
        )
        return await self.address_repo.create_address(new_address)


# --- Factory for Dependency Injection ---
def get_address_service(
    session: AsyncSession = Depends(get_session),
) -> AddressService:
    """
    Factory function to create the AddressService with its required Repository.
    """
    repo = AddressRepository(session)
    return AddressService(repo)
