# backend/app/services/addresses.py
import re
import uuid
from typing import List, Optional

from fastapi import Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.pickups import Address, AddressCategory, AddressScope
from app.models.tenants import Tenant, User, UserRole
from app.repositories.addresses import AddressRepository
from app.schemas.v1.pickups import AddressCreate, AddressUpdate


def normalize_address_text(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    abbreviations = {
        r"\bflat\b": "ft",
        r"\bapartment\b": "apt",
        r"\bhouse\b": "h",
        r"\bnumber\b": "num",
        r"\bno\b": "num",
        r"\bstreet\b": "st",
        r"\broad\b": "rd",
        r"\bfloor\b": "fl",
        r"\bsector\b": "sec",
        r"\bphase\b": "ph",
        r"\bnear\b": "nr",
        r"\bopposite\b": "opp",
        r"\bhospital\b": "hosp",
    }
    for pattern, replacement in abbreviations.items():
        text = re.sub(pattern, replacement, text)
    return re.sub(r"[^a-z0-9]", "", text)


def generate_address_signature(
    name: str, phone: str, pincode: str, line1: str, line2: Optional[str] = None
) -> str:
    norm_name = normalize_address_text(name)
    clean_phone = re.sub(r"^(\+91|91|0)", "", phone.strip())
    clean_phone = re.sub(r"[^0-9]", "", clean_phone)
    clean_pincode = re.sub(r"[\s-]", "", pincode.strip())
    norm_line1 = normalize_address_text(line1)
    norm_line2 = normalize_address_text(line2 or "")
    return f"{norm_name}|{clean_phone}|{clean_pincode}|{norm_line1}|{norm_line2}"


class AddressService:
    """
    Handles the business logic for Address Book management.
    """

    def __init__(self, address_repo: AddressRepository):
        self.address_repo = address_repo

    async def list_saved_addresses(
        self, user: User, tenant: Tenant, category: Optional[AddressCategory] = None
    ) -> List[Address]:

        return await self.address_repo.list_saved_addresses(
            tenant_id=tenant.id, user_id=user.id, category=category
        )

    async def create_saved_address(
        self, payload: AddressCreate, user: User, tenant: Tenant
    ) -> Address:
        """
        Business Logic to add a new address to the address book.
        Forces the 'is_saved' flag to True.
        Checks for duplicates via the Deduplication Engine.
        """
        # Rule 3: Customers can only create private level addresses
        if user.role == UserRole.customer and payload.scope == AddressScope.TENANT:
            raise HTTPException(
                status_code=403,
                detail="Standard customers are not allowed to create B2B team shared addresses."
            )
        sig = generate_address_signature(
            name=payload.name,
            phone=payload.phone,
            pincode=payload.pincode,
            line1=payload.address_line1,
            line2=payload.address_line2,
        )

        # Query DB for a matching signature under this tenant
        existing = await self.address_repo.get_address_by_signature(tenant.id, sig)
        if existing:
            if existing.is_saved:
                # Active duplicate found: Reuse and return the existing Address
                return existing
            else:
                # Soft-deleted duplicate found: Reactivate it by setting is_saved = True
                existing.is_saved = True
                # Update fields with new values
                address_data = payload.model_dump(exclude={"is_saved"})
                for key, value in address_data.items():
                    setattr(existing, key, value)
                existing.user_id = user.id  # Track who reactivated/claims it
                return await self.address_repo.create_address(existing)

        address_data = payload.model_dump(exclude={"is_saved"})
        # Convert the Pydantic schema to the SQLModel database object
        new_address = Address(
            **address_data,
            tenant_id=tenant.id,
            user_id=user.id,
            is_saved=True,  # Force it to be a permanent address book entry
            address_signature=sig,
        )
        return await self.address_repo.create_address(new_address)

    async def update_saved_address(
        self, address_id: uuid.UUID, payload: AddressUpdate, user: User, tenant: Tenant
    ) -> Address:
        address = await self.address_repo.get_address_by_id(address_id)
        if not address or address.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Address not found")

        # Role-Based Access Control:
        # - Admins/Owners can edit any address in their tenant.
        # - Customers can only edit PRIVATE addresses that they created.
        is_admin = user.role in (UserRole.admin, UserRole.owner)
        if not is_admin:
            if address.scope == AddressScope.TENANT:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have permission to edit team shared addresses."
                )
            if address.user_id != user.id:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have permission to edit this address."
                )
            if payload.scope == AddressScope.TENANT:
                raise HTTPException(
                    status_code=403,
                    detail="Standard customers are not allowed to share addresses with the B2B team."
                )

        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(address, key, value)

        # Compute signature
        sig = generate_address_signature(
            name=address.name,
            phone=address.phone,
            pincode=address.pincode,
            line1=address.address_line1,
            line2=address.address_line2,
        )
        address.address_signature = sig

        # Check if another duplicate exists in the DB under this tenant (excluding current address ID)
        existing = await self.address_repo.get_address_by_signature(tenant.id, sig)
        if existing and existing.id != address.id:
            if existing.is_saved:
                # Soft delete current one, return existing active duplicate
                address.is_saved = False
                await self.address_repo.create_address(address)
                return existing
            else:
                # Reactivate soft-deleted duplicate, update it with current values, soft delete current
                existing.is_saved = True
                for key in ["name", "phone", "alternate_phone", "gstin", "email", "company_name", "address_line1", "address_line2", "landmark", "city", "state", "pincode", "country", "category", "scope"]:
                    setattr(existing, key, getattr(address, key))
                existing.user_id = user.id
                await self.address_repo.create_address(existing)

                address.is_saved = False
                await self.address_repo.create_address(address)
                return existing

        return await self.address_repo.create_address(address)  # Reuses add/commit

    async def delete_saved_address(
        self, address_id: uuid.UUID, user: User, tenant: Tenant
    ) -> dict:
        address = await self.address_repo.get_address_by_id(address_id)
        if not address or address.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Address not found")

        # Role-Based Access Control:
        # - Admins/Owners can delete any address in their tenant.
        # - Customers can only delete PRIVATE addresses they created.
        is_admin = user.role in (UserRole.admin, UserRole.owner)
        if not is_admin:
            if address.scope == AddressScope.TENANT:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have permission to delete team shared addresses."
                )
            if address.user_id != user.id:
                raise HTTPException(
                    status_code=403,
                    detail="You do not have permission to delete this address."
                )

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
