from typing import List

from app.core.dependencies import (
    get_current_active_user,
    get_supabase_user_from_token,
    get_tenant_from_header,
)
from app.core.security import TokenPayload
from app.models.tenants import Tenant, User
from app.schemas.v1.tenants import UserRead
from app.services.tenants import TenantService, get_tenant_service
from fastapi import APIRouter, Depends, status

router = APIRouter()


@router.post("/onboard", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def onboard_new_user(
    *,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    token_data: TokenPayload = Depends(get_supabase_user_from_token),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Onboarding endpoint for new and existing users.
    Delegates the core "get or create" logic to the TenantService.
    """
    user = await tenant_service.get_or_create_user(
        token_data=token_data, tenant=current_tenant
    )
    return user


@router.get("/", response_model=List[UserRead])
async def list_users_in_tenant(
    *,
    current_user: User = Depends(get_current_active_user),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    List all users for the current authenticated user's tenant.
    (This will be refactored to use the service layer fully next).
    """
    users = await tenant_service.list_users_for_tenant(tenant_id=current_user.tenant_id)
    return users
