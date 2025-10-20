from typing import List
from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.models.tenants import User
from app.schemas.v1.tenants import UserRead

router = APIRouter()

@router.get("/", response_model=List[UserRead])
async def list_users_in_tenant(
    session: AsyncSession = Depends(get_session)
):
    """
    List all users.

    (In the future, this will be restricted to the current user's tenant).
    """
    result = await session.exec(select(User))
    users = result.all()
    return users