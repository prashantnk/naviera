import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

import sqlalchemy as sa
from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlmodel import Field, Relationship, SQLModel


def _utc_now_naive() -> datetime:
    """Current UTC time as a naive datetime (TIMESTAMP WITHOUT TIME ZONE)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# Define Enums first, as they are used in the models below
class UserRole(str, Enum):
    owner = "owner"
    admin = "admin"
    operations_user = "operations_user"
    support_user = "support_user"
    read_only_user = "read_only_user"
    customer = "customer"


class ServiceScope(str, Enum):
    B2C = "B2C"
    B2B = "B2B"
    BOTH = "BOTH"


# The Tenant model: Represents a single logistics company in our system.
# We have removed the `users` relationship field to avoid performance issues.
class Tenant(SQLModel, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    slug: str = Field(unique=True, index=True)
    name: str
    settings: dict = Field(default={}, sa_column=Column(JSON))


# The User model: Represents a user account, which must belong to a Tenant.
class User(SQLModel, table=True):
    __table_args__ = (
        UniqueConstraint("supabase_user_id", "tenant_id", name="unique_user_tenant"),
        UniqueConstraint("email", "tenant_id", name="unique_email_tenant"),
        # Add the new composite index for performance
        Index("ix_user_supabase_tenant", "supabase_user_id", "tenant_id"),
    )
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    # This new field links our user profile to the Supabase Auth user identity.
    supabase_user_id: str = Field(index=True)
    email: str = Field(index=True)
    full_name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=24)
    is_active: bool = Field(default=True)
    role: UserRole = Field(default=UserRole.customer)
    service_scope: ServiceScope = Field(
        default=ServiceScope.B2C,
        sa_column=Column(
            SAEnum(ServiceScope, native_enum=False, length=32),
            nullable=False,
            server_default="B2C",
        ),
    )
    created_at: Optional[datetime] = Field(
        default_factory=_utc_now_naive,
        sa_column=Column(
            sa.DateTime(timezone=False),
            nullable=True,
            server_default=sa.func.now(),
        ),
    )

    # The foreign key relationship to the Tenant model
    tenant_id: uuid.UUID = Field(foreign_key="tenant.id")

    # Define the relationship to the Tenant.
    # It is no longer bidirectional ("back-populating") from the Tenant's side.
    tenant: Tenant | None = Relationship()


class TenantSettingsHistory(SQLModel, table=True):
    """
    Immutable snapshot of `Tenant.settings` taken BEFORE every successful
    settings update (and before every restore), so admins can undo changes.
    Only the latest `SETTINGS_HISTORY_LIMIT` versions per tenant are kept.

    Spring Boot Equivalent: an '@Entity' audit/envers-style revision table.
    """

    __tablename__ = "tenant_settings_history"  # type: ignore
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_tenant_settings_history_version"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tenant_id: uuid.UUID = Field(
        sa_column=Column(
            sa.Uuid,
            sa.ForeignKey("tenant.id", ondelete="CASCADE"),
            index=True,
            nullable=False,
        )
    )
    version: int = Field(sa_column=Column(sa.Integer, nullable=False))
    settings: dict = Field(default_factory=dict, sa_column=Column(JSONB, nullable=False))
    changed_by_user_id: Optional[uuid.UUID] = Field(
        default=None,
        sa_column=Column(
            sa.Uuid, sa.ForeignKey("user.id", ondelete="SET NULL"), nullable=True
        ),
    )
    changed_sections: List[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(sa.Text), nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=_utc_now_naive,
        sa_column=Column(sa.DateTime(timezone=False), nullable=False, server_default=sa.func.now()),
    )
