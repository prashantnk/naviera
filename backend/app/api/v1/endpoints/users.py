import uuid
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.dependencies import (
    get_current_active_user,
    get_supabase_user_from_token,
    get_tenant_from_header,
)
from app.core.permissions import is_tenant_admin
from app.core.rate_limit import guard_login, guard_signup
from app.core.security import TokenPayload
from app.models.tenants import Tenant, User
from app.schemas.v1.tenants import (
    B2BAccessRequestCreate,
    B2BAccessReviewRequest,
    PasswordAuthResponse,
    PasswordLoginRequest,
    PasswordSignupRequest,
    UserRead,
    UserSelfUpdate,
    UserUpdate,
)
from app.services.tenants import TenantService, get_tenant_service

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


@router.post(
    "/auth/signup",
    response_model=PasswordAuthResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(guard_signup)],
)
async def signup_with_email_and_password(
    payload: PasswordSignupRequest,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Creates or activates a user account with Email & Password in `auth.users`,
    provisions their `public.\"user\"` profile in the current tenant (bootstrapping
    the first tenant user as OWNER), and returns a Supabase-compatible JWT session.
    Rate-limited per IP (B-05).
    """
    return await tenant_service.signup_with_password(
        tenant=current_tenant, payload=payload
    )


@router.post(
    "/auth/login",
    response_model=PasswordAuthResponse,
    dependencies=[Depends(guard_login)],
)
async def login_with_email_and_password(
    payload: PasswordLoginRequest,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Authenticates a user with Email & Password against `auth.users` and returns
    a Supabase-compatible JWT session + synced tenant profile. Rate-limited per
    account and per IP (B-05).
    """
    return await tenant_service.login_with_password(
        tenant=current_tenant, payload=payload
    )


@router.get("", response_model=List[UserRead])
async def list_users_in_tenant(
    *,
    current_user: User = Depends(get_current_active_user),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    List users for the current workspace:
    - LogiSmart Platform Admins / Owners see all tenant users.
    - B2B Merchant Owners / Admins see only their own Merchant Organization's sub-team.
    - Individual B2C customers or non-admin roles receive 403 Forbidden.
    """
    if not is_tenant_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Tenant Admins or Owners can list workspace users.",
        )
    users = await tenant_service.list_users_for_tenant(
        tenant_id=current_user.tenant_id, current_user=current_user
    )
    return users


@router.get("/me", response_model=UserRead)
async def get_my_profile(
    current_user: User = Depends(get_current_active_user),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Returns the currently authenticated user's profile (including their role,
    account_type, merchant_org_id, and B2B access request status).
    """
    return await tenant_service.enrich_user_profile(
        current_user, tenant=current_tenant
    )


@router.patch("/me", response_model=UserRead)
async def update_my_profile(
    payload: UserSelfUpdate,
    current_user: User = Depends(get_current_active_user),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Lets any signed-in user change their own display name and phone.
    Declared before `PATCH /{user_id}` so `/me` is not parsed as a user id.
    """
    return await tenant_service.update_my_profile(
        current_user=current_user, payload=payload
    )


@router.post("/me/request-b2b", response_model=UserRead)
async def request_b2b_access_for_current_user(
    payload: B2BAccessRequestCreate,
    current_user: User = Depends(get_current_active_user),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Allows an authenticated customer to request B2B Cargo access,
    optionally providing their Company Name, 15-digit GSTIN, or 10-digit PAN.
    """
    return await tenant_service.request_b2b_access(
        current_user=current_user, payload=payload
    )


@router.post("/{user_id}/review-b2b", response_model=UserRead)
async def review_user_b2b_access_request(
    user_id: uuid.UUID,
    payload: B2BAccessReviewRequest,
    current_user: User = Depends(get_current_active_user),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Allows a Tenant Admin / Owner to approve or reject a customer's B2B access request.
    """
    return await tenant_service.review_b2b_access(
        user_id=user_id,
        payload=payload,
        current_user=current_user,
        tenant_id=current_user.tenant_id,
    )


@router.patch("/{user_id}", response_model=UserRead)
async def update_user_role(
    user_id: uuid.UUID,
    payload: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """Update a user's role or active status (Platform Admin or B2B Merchant Admin)."""
    return await tenant_service.update_user(
        user_id, payload, current_user, current_user.tenant_id
    )
