import uuid
from enum import Enum

from sqlmodel import Field, Relationship, SQLModel

# 1. Import Column and JSON from sqlalchemy
from sqlalchemy import Column, JSON

# Define Enums first, as they are used in the models below
class UserRole(str, Enum):
    owner = "owner"
    admin = "admin"
    customer = "customer"


# The Tenant model: Represents a single logistics company in our system.
# We have removed the `users` relationship field to avoid performance issues.
class Tenant(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    settings: dict = Field(default={}, sa_column=Column(JSON))


# The User model: Represents a user account, which must belong to a Tenant.
class User(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    email: str = Field(unique=True, index=True)
    is_active: bool = Field(default=True)
    role: UserRole = Field(default=UserRole.customer)

    # The foreign key relationship to the Tenant model
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id")

    # Define the relationship to the Tenant.
    # It is no longer bidirectional ("back-populating") from the Tenant's side.
    tenant: Tenant | None = Relationship()
