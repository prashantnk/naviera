# backend/app/services/addresses.py
import uuid
from typing import List, Optional

from fastapi import Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.pickups import Address, AddressType
from app.models.tenants import Tenant, User
from app.repositories.addresses import AddressRepository
from app.schemas.v1.pickups import AddressCreate, AddressUpdate


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

    async def update_saved_address(
        self, address_id: uuid.UUID, payload: AddressUpdate, user: User, tenant: Tenant
    ) -> Address:
        address = await self.address_repo.get_address_by_id(address_id)
        if not address or address.tenant_id != tenant.id or address.user_id != user.id:
            raise HTTPException(status_code=404, detail="Address not found")

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(address, key, value)

        return await self.address_repo.create_address(address)  # Reuses add/commit

    async def delete_saved_address(
        self, address_id: uuid.UUID, user: User, tenant: Tenant
    ) -> dict:
        address = await self.address_repo.get_address_by_id(address_id)
        if not address or address.tenant_id != tenant.id or address.user_id != user.id:
            raise HTTPException(status_code=404, detail="Address not found")

        # Soft delete: Unmark as saved so historical shipments don't break!
        address.is_saved = False
        await self.address_repo.create_address(address)
        return {"detail": "Address removed successfully"}


# --- Factory for Dependency Injection ---
def get_address_service(
    session: AsyncSession = Depends(get_session),
) -> AddressService:
    """
    Factory function to create the AddressService with its required Repository.
    """
    repo = AddressRepository(session)
    return AddressService(repo)
