# backend/app/services/addresses.py
import re
import uuid
from typing import List, Optional

from fastapi import Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.permissions import assert_not_read_only
from app.models.pickups import Address, AddressCategory, AddressScope
from app.models.tenants import Tenant, User, UserRole
from app.repositories.addresses import AddressRepository, invalidate_address_cache
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
        self,
        user: User,
        tenant: Tenant,
        category: Optional[AddressCategory] = None,
        *,
        is_saved: Optional[bool] = True,
        search: Optional[str] = None,
        skip: int = 0,
        limit: Optional[int] = None,
    ) -> List[Address]:
        return await self.address_repo.list_saved_addresses(
            tenant_id=tenant.id,
            user_id=user.id,
            category=category,
            is_saved=is_saved,
            search=search,
            skip=skip,
            limit=limit,
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
        assert_not_read_only(user, "create saved addresses")
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

        # Query DB for a matching signature under this tenant accessible to this user
        existing = await self.address_repo.get_address_by_signature(
            tenant.id, sig, user_id=user.id
        )
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
                saved = await self.address_repo.create_address(existing)
                invalidate_address_cache(tenant.id)
                return saved

        address_data = payload.model_dump(exclude={"is_saved"})
        # Convert the Pydantic schema to the SQLModel database object
        new_address = Address(
            **address_data,
            tenant_id=tenant.id,
            user_id=user.id,
            is_saved=True,  # Force it to be a permanent address book entry
            address_signature=sig,
        )
        saved = await self.address_repo.create_address(new_address)
        invalidate_address_cache(tenant.id)
        return saved

    async def update_saved_address(
        self, address_id: uuid.UUID, payload: AddressUpdate, user: User, tenant: Tenant
    ) -> Address:
        assert_not_read_only(user, "edit saved addresses")
        address = await self.address_repo.get_address_by_id(address_id)
        if not address or address.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Address not found")
        if not address.is_saved:
            raise HTTPException(
                status_code=400,
                detail="Snapshot addresses cannot be modified.",
            )

        # Role-Based Access Control:
        # - Admins/Owners/Operations can edit any address in their tenant.
        # - Customers can only edit PRIVATE addresses that they created.
        is_admin = user.role in (UserRole.admin, UserRole.owner, UserRole.operations_user)
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

        editable_keys = (
            "name",
            "phone",
            "alternate_phone",
            "gstin",
            "email",
            "company_name",
            "address_line1",
            "address_line2",
            "landmark",
            "city",
            "state",
            "pincode",
            "country",
            "category",
            "scope",
        )
        merged_values = {key: getattr(address, key) for key in editable_keys}
        update_data = payload.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            if key in merged_values:
                merged_values[key] = value

        # Compute signature for the updated values
        sig = generate_address_signature(
            name=merged_values["name"],
            phone=merged_values["phone"],
            pincode=merged_values["pincode"],
            line1=merged_values["address_line1"],
            line2=merged_values["address_line2"],
        )

        # D-03: If this saved address is referenced by any shipment or pickup request,
        # keep the original row untouched with is_saved=False so historical/in-transit
        # shipment snapshots never mutate, and insert a fresh saved Address row.
        if await self.address_repo.is_address_referenced(tenant.id, address.id):
            address.is_saved = False
            await self.address_repo.create_address(address)
            new_address = Address(
                **merged_values,
                tenant_id=tenant.id,
                user_id=address.user_id or user.id,
                is_saved=True,
                address_signature=sig,
            )
            saved = await self.address_repo.create_address(new_address)
            invalidate_address_cache(tenant.id)
            return saved

        for key, value in merged_values.items():
            setattr(address, key, value)
        address.address_signature = sig

        # Check if another duplicate exists in the DB under this tenant (excluding current address ID)
        existing = await self.address_repo.get_address_by_signature(
            tenant.id, sig, user_id=user.id
        )
        if existing and existing.id != address.id:
            if existing.is_saved:
                # Soft delete current one, return existing active duplicate
                address.is_saved = False
                await self.address_repo.create_address(address)
                invalidate_address_cache(tenant.id)
                return existing
            if not await self.address_repo.is_address_referenced(tenant.id, existing.id):
                # Reactivate unreferenced soft-deleted duplicate
                existing.is_saved = True
                for key in editable_keys:
                    setattr(existing, key, getattr(address, key))
                existing.user_id = user.id
                await self.address_repo.create_address(existing)

                address.is_saved = False
                await self.address_repo.create_address(address)
                invalidate_address_cache(tenant.id)
                return existing

        saved = await self.address_repo.create_address(address)  # Reuses add/commit
        invalidate_address_cache(tenant.id)
        return saved

    async def delete_saved_address(
        self, address_id: uuid.UUID, user: User, tenant: Tenant
    ) -> dict:
        assert_not_read_only(user, "delete saved addresses")
        address = await self.address_repo.get_address_by_id(address_id)
        if not address or address.tenant_id != tenant.id:
            raise HTTPException(status_code=404, detail="Address not found")

        # Role-Based Access Control:
        # - Admins/Owners/Operations can delete any address in their tenant.
        # - Customers can only delete PRIVATE addresses they created.
        is_admin = user.role in (UserRole.admin, UserRole.owner, UserRole.operations_user)
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
        invalidate_address_cache(tenant.id)
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
