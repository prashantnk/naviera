# backend/app/api/v1/endpoints/addresses.py
import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.pickups import AddressCategory
from app.models.tenants import Tenant, User
from app.schemas.v1.pickups import AddressCreate, AddressRead, AddressUpdate
from app.services.addresses import AddressService, get_address_service

router = APIRouter()


@router.get("", response_model=List[AddressRead])
async def list_saved_addresses(
    category: Optional[AddressCategory] = Query(
        None, description="Filter by HOME, OFFICE, WAREHOUSE, STOREFRONT, or OTHER"
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    address_service: AddressService = Depends(get_address_service),
):
    """
    Fetch all SAVED addresses for the current user in this tenant.
    """
    return await address_service.list_saved_addresses(
        user=current_user, tenant=current_tenant, category=category
    )


@router.post("", response_model=AddressRead)
async def create_saved_address(
    payload: AddressCreate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    address_service: AddressService = Depends(get_address_service),
):
    """
    Add a new address to the user's Address Book.
    """
    return await address_service.create_saved_address(
        payload=payload, user=current_user, tenant=current_tenant
    )


@router.patch("/{address_id}", response_model=AddressRead)
async def update_saved_address(
    address_id: uuid.UUID,
    payload: AddressUpdate,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    address_service: AddressService = Depends(get_address_service),
):
    """Edit an existing address."""
    return await address_service.update_saved_address(
        address_id, payload, current_user, current_tenant
    )


@router.delete("/{address_id}")
async def delete_saved_address(
    address_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    address_service: AddressService = Depends(get_address_service),
):
    """Remove an address from the Address Book."""
    return await address_service.delete_saved_address(
        address_id, current_user, current_tenant
    )
