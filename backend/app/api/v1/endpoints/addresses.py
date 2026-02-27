# backend/app/api/v1/endpoints/addresses.py
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.pickups import AddressType
from app.models.tenants import Tenant, User
from app.schemas.v1.pickups import AddressCreate, AddressRead
from app.services.addresses import AddressService, get_address_service

router = APIRouter()


@router.get("", response_model=List[AddressRead])
async def list_saved_addresses(
    address_type: Optional[AddressType] = Query(
        None, description="Filter by WAREHOUSE or CUSTOMER"
    ),
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    address_service: AddressService = Depends(get_address_service),
):
    """
    Fetch all SAVED addresses for the current user in this tenant.
    """
    return await address_service.list_saved_addresses(
        user=current_user, tenant=current_tenant, address_type=address_type
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
