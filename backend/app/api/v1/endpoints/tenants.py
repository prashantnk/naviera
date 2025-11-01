# backend/app/api/v1/endpoints/tenants.py
import uuid
from typing import List

from app.core.dependencies import get_current_active_user
from app.models.tenants import User
from app.schemas.v1.tenants import TenantRead, UserRead
from app.services.tenants import TenantService, get_tenant_service
from fastapi import APIRouter, Depends

router = APIRouter()


@router.get("/", response_model=List[TenantRead])
async def list_tenants(
    *,
    tenant_service: TenantService = Depends(get_tenant_service),
    user: User = Depends(get_current_active_user)
):
    """
    List all tenants in the system.
    """
    # if user.role != UserRole.owner:
    #     raise HTTPException(status_code=403, detail="Forbidden")
    tenants = await tenant_service.list_tenants()
    return tenants


@router.get("/{tenant_id}/users/", response_model=List[UserRead])
async def list_users_for_tenant(
    *,
    tenant_id: uuid.UUID,
    tenant_service: TenantService = Depends(get_tenant_service),
    user: User = Depends(get_current_active_user)
):
    """
    List all users for a specific tenant (administrative).
    """
    # if user.role != UserRole.owner:
    #     raise HTTPException(status_code=403, detail="Forbidden")

    users = await tenant_service.list_users_for_tenant(tenant_id=tenant_id)
    return users
