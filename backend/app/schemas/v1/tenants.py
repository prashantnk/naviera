import uuid
from datetime import datetime
from typing import List, Optional

from sqlmodel import Field, SQLModel

from app.models.tenants import ServiceScope, UserRole


class TenantRead(SQLModel):
    id: uuid.UUID
    name: str
    slug: str
    settings: dict = {}


class UserRead(SQLModel):
    id: uuid.UUID
    email: str
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    role: UserRole
    service_scope: ServiceScope = ServiceScope.B2C
    tenant_id: uuid.UUID
    created_at: Optional[datetime] = None
    b2b_request_status: Optional[str] = None
    company_name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    b2b_requested_at: Optional[str] = None
    account_type: Optional[str] = None
    same_as_tenant_gstin: Optional[bool] = False
    billing_address: Optional[str] = None
    gstin_status: Optional[str] = None
    company_details_locked: bool = False


class TenantUpdate(SQLModel):
    name: Optional[str] = Field(default=None, max_length=255)
    settings: Optional[dict] = None


class UserUpdate(SQLModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None
    service_scope: Optional[ServiceScope] = None
    company_name: Optional[str] = None
    gstin: Optional[str] = None
    pan: Optional[str] = None
    account_type: Optional[str] = None
    same_as_tenant_gstin: Optional[bool] = False


class SellerCompanyDetailsSubmit(SQLModel):
    """
    A seller's "Company details" printed as "Bill To" on their GST documents (audit C-01).
    Submitted once from My profile; afterwards view-only, changes via a support ticket
    (Delhivery One `profile`: company details cannot be edited).
    """

    legal_name: str = Field(min_length=2, max_length=160)
    billing_address: str = Field(min_length=10, max_length=300)
    gstin: Optional[str] = Field(
        default=None,
        max_length=15,
        description="Optional 15-character GSTIN; checksum-verified and never the tenant's own GSTIN",
    )


class UserSelfUpdate(SQLModel):
    """Self-service profile edit (any signed-in user): display name, phone, company details."""

    full_name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=24)
    company_details: Optional[SellerCompanyDetailsSubmit] = None


class B2BAccessRequestCreate(SQLModel):
    company_name: Optional[str] = Field(default=None, max_length=160)
    gstin: Optional[str] = Field(default=None, max_length=15)
    pan: Optional[str] = Field(default=None, max_length=10)
    notes: Optional[str] = Field(default=None, max_length=500)


class B2BAccessReviewRequest(SQLModel):
    approve: bool = True
    service_scope: ServiceScope = ServiceScope.BOTH


class TenantSettingsHistoryRead(SQLModel):
    """One restorable settings version (the settings JSON itself is not sent)."""

    id: uuid.UUID
    version: int
    created_at: datetime
    changed_by_email: Optional[str] = None
    changed_sections: List[str] = []


class PasswordSignupRequest(SQLModel):
    """Request payload for creating an account with Email & Password.

    `terms_accepted` is the signup consent checkbox ("I agree to the Terms and
    Privacy Policy and will not ship prohibited items"); the service rejects a
    new account without it and stamps the accepted version server-side.
    """

    email: str
    password: str
    full_name: Optional[str] = None
    terms_accepted: bool = False


class PasswordLoginRequest(SQLModel):
    """Request payload for signing in with Email & Password."""

    email: str
    password: str


class PasswordAuthResponse(SQLModel):
    """Supabase-compatible session + synced Naviera user profile."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    expires_at: int
    supabase_user_id: str
    user: UserRead
