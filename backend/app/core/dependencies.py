from typing import Optional

from app.core.db import get_session
from app.core.security import TokenPayload, decode_access_token
from app.models.tenants import Tenant, User
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

oauth2_scheme = HTTPBearer(scheme_name="JWT")


async def get_tenant_from_header(
    *,
    x_tenant_slug: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
) -> Tenant:
    """
    A dependency to identify and return the current tenant based on the
    X-Tenant-Slug header. Raises 404 if the tenant is not found.
    """
    if not x_tenant_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-Slug header is required.",
        )

    statement = select(Tenant).where(Tenant.slug == x_tenant_slug)
    result = await session.exec(statement)
    tenant = result.first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    return tenant


async def get_supabase_user_from_token(*, token=Depends(oauth2_scheme)) -> TokenPayload:
    """
    A dependency that only validates the JWT and returns its payload.
    This is used for the onboarding endpoint where the user might not
    exist in our database yet.
    """
    credentials = token.credentials
    token_data = decode_access_token(credentials)
    return token_data


async def get_current_active_user(
    *,
    session: AsyncSession = Depends(get_session),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    token_data: TokenPayload = Depends(get_supabase_user_from_token),
) -> User:
    """
    A dependency to get the current authenticated user, validate their token,
    and ensure they belong to the correct tenant.
    """
    supabase_user_id = token_data.sub

    statement = select(User).where(
        User.supabase_user_id == supabase_user_id,
        User.tenant_id == current_tenant.id,
    )
    result = await session.exec(statement)
    user = result.first()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have access to this tenant.",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    return user
