# backend/app/api/v1/endpoints/tenants.py
import uuid
from typing import List

from app.core.db import get_session
from app.models.tenants import Tenant, User
from app.schemas.v1.tenants import TenantRead, UserRead
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

router = APIRouter()


@router.get("/", response_model=List[TenantRead])
async def list_tenants(*, session: AsyncSession = Depends(get_session)):
    """
    List all tenants in the system.
    """
    result = await session.exec(select(Tenant))
    tenants = result.all()
    return tenants


@router.get("/{tenant_id}/users/", response_model=List[UserRead])
async def list_users_for_tenant(
    tenant_id: uuid.UUID, *, session: AsyncSession = Depends(get_session)
):
    """
    List all users for a specific tenant.
    (This is an administrative endpoint).
    """
    tenant = await session.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    statement = select(User).where(User.tenant_id == tenant_id)
    result = await session.exec(statement)
    users = result.all()
    return users
