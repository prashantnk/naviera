import uuid
from typing import Optional

from sqlmodel import SQLModel, Field

from app.models.tenants import UserRole

# This is a Pydantic model, not a table model.
# It inherits from SQLModel but we do not set `table=True`.
# It defines the shape of the data we want to send back in the API.


class TenantRead(SQLModel):
    id: uuid.UUID
    name: str
    slug: str
    settings: dict = {}


class UserRead(SQLModel):
    id: uuid.UUID
    email: str
    is_active: bool
    role: UserRole
    tenant_id: uuid.UUID


class TenantUpdate(SQLModel):
    name: Optional[str] = Field(default=None, max_length=255)
    settings: Optional[dict] = None


class UserUpdate(SQLModel):
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
