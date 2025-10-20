import uuid

from app.models.tenants import UserRole
from sqlmodel import SQLModel

# This is a Pydantic model, not a table model.
# It inherits from SQLModel but we do not set `table=True`.
# It defines the shape of the data we want to send back in the API.


class TenantRead(SQLModel):
    id: uuid.UUID
    name: str
    slug: str


class UserRead(SQLModel):
    id: uuid.UUID
    email: str
    is_active: bool
    role: UserRole
    tenant_id: uuid.UUID
