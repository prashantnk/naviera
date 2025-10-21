from typing import List

from app.core.db import get_session
from app.core.dependencies import (
    get_current_active_user,
    get_supabase_user_from_token,
    get_tenant_from_header,
)
from app.core.security import TokenPayload
from app.models.tenants import Tenant, User, UserRole
from app.schemas.v1.tenants import UserRead
from fastapi import APIRouter, Depends, status
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


@router.post("/onboard", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def onboard_new_user(
    *,
    session: AsyncSession = Depends(get_session),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    token_data: TokenPayload = Depends(get_supabase_user_from_token),
):
    """
    Onboarding endpoint for new and existing users.
    Called by the frontend after a successful Supabase login.
    It's idempotent: it gets or creates the user profile in our database.
    """
    supabase_user_id = token_data.sub

    # Check if the user profile already exists for this tenant
    statement = select(User).where(
        User.supabase_user_id == supabase_user_id,
        User.tenant_id == current_tenant.id,
    )
    result = await session.exec(statement)
    user = result.first()

    if user:
        # If user exists, we're done. Return a 200 OK.
        # We can't directly change the status code here, but the frontend can handle it.
        return user

    # If user does not exist, create a new user profile
    # We need the user's email, which is in the token payload but not our schema yet.

    new_user = User(
        email=token_data.email,
        supabase_user_id=supabase_user_id,
        tenant_id=current_tenant.id,
        role=UserRole.customer,  # New users default to 'customer'
        is_active=True,
    )
    session.add(new_user)
    await session.commit()
    await session.refresh(new_user)

    return new_user


@router.get("/", response_model=List[UserRead])
async def list_users_in_tenant(
    *,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    """
    List all users for the current authenticated user's tenant.
    (Requires user to be already onboarded).
    """
    statement = select(User).where(User.tenant_id == current_user.tenant_id)
    result = await session.exec(statement)
    users = result.all()
    return users
