import copy
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import Depends, HTTPException
from jose import jwt
from pydantic import ValidationError
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings as app_settings
from app.core.db import get_session
from app.core.dependencies import (
    cache_tenant,
    cache_user,
    get_cached_tenant_by_id,
    get_cached_tenant_by_slug,
    invalidate_auth_cache,
)
from app.core.permissions import STAFF_USER_ROLES, is_tenant_admin, is_tenant_staff
from app.core.security import TokenPayload
from app.exceptions.definitions import TenantNotFoundException
from app.models.tenants import (
    ServiceScope,
    Tenant,
    TenantSettingsHistory,
    User,
    UserRole,
)
from app.repositories.tenants import TenantRepository
from app.schemas.v1.tenant_settings import TenantSettingsUpdate
from app.schemas.v1.tenants import (
    B2BAccessRequestCreate,
    B2BAccessReviewRequest,
    PasswordAuthResponse,
    PasswordLoginRequest,
    PasswordSignupRequest,
    SellerCompanyDetailsSubmit,
    TenantRead,
    TenantSettingsHistoryRead,
    UserRead,
    UserSelfUpdate,
    UserUpdate,
)
from app.services.delhivery_modules import resolve_supplier_gst_profile
from app.services.gst_documents import (
    BILLING_ADDRESS_KEY,
    COMPANY_DETAILS_SUBMITTED_AT_KEY,
    GSTIN_STATUS_KEY,
    KYC_APPROVED_STATUS,
    KYC_REQUESTS_SETTINGS_KEY,
    VERIFIED_GSTIN_KEY,
    company_details_locked,
    is_checksum_valid_gstin,
    pan_from_gstin,
)

SETTINGS_HISTORY_LIMIT = 20
"""Snapshots kept per tenant; older versions are pruned on insert."""
SHOW_LOGO_DEFAULT = True
"""`brand.show_logo` defaults to ON (admins can toggle the logo off)."""
GSTIN_PATTERN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")
PAN_PATTERN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]{1}$")
MIN_PASSWORD_LENGTH = 8
PROFILE_PHONE_RE = re.compile(r"^\+?[0-9]{10,15}$")
"""Self-service profile phone: optional leading +, 10-15 digits."""
AUTH_TOKEN_TTL_SECONDS = 86400
INVITED_SUPABASE_ID_PREFIX = "invited:"
"""Placeholder `supabase_user_id` prefix of pre-invited users who never signed in."""

SIGNUP_EMAIL_EXISTS_DETAIL = (
    "An account with this email already exists. Sign in with your password, "
    "or use Email OTP / Forgot password."
)
"""409 detail for `/auth/signup` when `auth.users` already has the email (any tenant)."""
TERMS_VERSION = "2026-10-30-draft"
"""
Version of the published Terms / Privacy Policy (`/terms`, `/privacy`) that a
new signup accepts; stored in the Supabase user metadata with the timestamp.
Bump it whenever the legal text changes materially.
"""
TERMS_CONSENT_REQUIRED_DETAIL = (
    "Please accept the Terms of Service and Privacy Policy, and confirm you will "
    "not ship prohibited items, to create an account."
)
"""400 detail for `/auth/signup` without the consent checkbox."""
INVITED_LOGIN_CREATE_ACCOUNT_DETAIL = (
    "Your account was invited by an administrator. Click the 'Create Account' tab "
    "above to set your password and activate your account."
)
INVITED_LOGIN_EXISTING_ACCOUNT_DETAIL = (
    "Your account was invited by an administrator. Sign in with the password you "
    "already use, or use Email OTP / Forgot password."
)
INVALID_LOGIN_DETAIL = (
    "Invalid email or password. If you don't have an account yet, click the "
    "'Create Account' tab above."
)

PUBLIC_SETTINGS_KEYS = frozenset(
    {
        "brand",
        "announcement_bar",
        "contact",
        "landing_page",
        "about_page",
        "services_page",
        "escalation_matrix",
        "support",
        "oAuthSignInEnabled",
        "gstin",
    }
)
"""
Allow-list of `tenant.settings` keys that unauthenticated callers may read
(marketing site, login page, app shell). Everything else (B2B KYC requests,
rate card, UPI/wallet config, unknown keys) stays admin-only.
"""
PUBLIC_WALLET_CONFIG_KEYS = ("merchant_name", "gstin")
"""Non-secret `wallet_config` display fields (GST invoice header on shipment details)."""
RUNTIME_SETTINGS_KEYS = ("b2b_access_requests",)
"""
Non-config data that lives inside `tenant.settings` but is written by other
flows (B2B access requests/KYC). It is never snapshotted, and a restore keeps
the CURRENT value so approvals and pending requests are not reverted.
"""
RETIRED_SETTINGS_KEYS = ("pricing_config",)
"""Legacy settings keys stripped on snapshot/restore after the D2 pricing redesign."""
RESTORE_KEEPS_CURRENT_KEYS = ("pricing_policy",)
"""
Sections a Settings "Restore" never rolls back: the pricing policy has its own editor
(`PUT /pricing/policy`, with a confirm-diff dialog), so restoring branding or contacts must
not silently change what customers are charged.
"""
HISTORY_HIDDEN_SECTIONS = frozenset({"user_roles", "pricing_policy"})
"""
`changed_sections` the Settings history list does not show: role changes and pricing edits
are snapshotted for the audit trail, but a Settings restore can't undo them, so rows that
only touched these are hidden (and the labels are dropped from mixed rows).
"""
INVOICE_PREFIX_LOCKED_DETAIL = (
    "Invoice prefix is locked and cannot be changed mid-financial-year once configured."
)


class TenantService:
    """
    This class handles the business logic for tenants and users.
    It depends on the TenantRepository for data access.
    """

    def __init__(self, tenant_repo: TenantRepository):
        self.tenant_repo = tenant_repo

    def _deep_merge(self, base_dict: dict, update_dict: dict) -> dict:
        """
        Recursively merges update_dict into base_dict.
        Preserves existing keys in base_dict that are not present in update_dict.
        """
        merged = copy.deepcopy(base_dict)
        for key, value in update_dict.items():
            if (
                isinstance(value, dict)
                and key in merged
                and isinstance(merged[key], dict)
            ):
                merged[key] = self._deep_merge(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    @staticmethod
    def _validate_optional_gstin_and_pan(
        gstin: Optional[str], pan: Optional[str]
    ) -> tuple[Optional[str], Optional[str]]:
        """
        Validates optional 15-character GSTIN and 10-character PAN.
        If GSTIN is provided without PAN, derives the 10-character PAN from
        characters 3 to 12 of the GSTIN.
        """
        clean_gstin = gstin.strip().upper() if gstin and gstin.strip() else None
        clean_pan = pan.strip().upper() if pan and pan.strip() else None

        if clean_gstin and not GSTIN_PATTERN.match(clean_gstin):
            raise HTTPException(
                status_code=422,
                detail="Invalid GSTIN format. Must be a valid 15-character Indian GSTIN (e.g. 06AAECL2138H1ZQ).",
            )
        if clean_pan and not PAN_PATTERN.match(clean_pan):
            raise HTTPException(
                status_code=422,
                detail="Invalid PAN format. Must be a valid 10-character Indian PAN (e.g. AAECL2138H).",
            )
        if clean_gstin and clean_pan and clean_gstin[2:12] != clean_pan:
            raise HTTPException(
                status_code=422,
                detail="GSTIN and PAN mismatch: characters 3 to 12 of the GSTIN must match the PAN number.",
            )
        if clean_gstin and not clean_pan:
            clean_pan = clean_gstin[2:12]
        return clean_gstin, clean_pan

    @staticmethod
    def _enrich_user_with_b2b_metadata(
        user: User, tenant_settings: Optional[dict]
    ) -> User:
        """
        Attaches transient B2B request, KYC, and `account_type` (`TENANT_STAFF`
        vs `CUSTOMER`) fields from `tenant.settings['b2b_access_requests']`
        onto the `User` entity using `object.__setattr__` so Pydantic/SQLModel
        serialization populates `UserRead`.
        """
        requests_map = (
            (tenant_settings or {}).get("b2b_access_requests")
            if isinstance(tenant_settings, dict)
            else None
        )
        entry = (
            requests_map.get(str(user.id))
            if isinstance(requests_map, dict)
            else None
        )

        account_type = (
            "TENANT_STAFF"
            if is_tenant_staff(user)
            else "CUSTOMER"
        )
        object.__setattr__(user, "account_type", account_type)

        source_entry = entry if isinstance(entry, dict) else {}

        default_status = (
            "APPROVED"
            if user.service_scope in (ServiceScope.B2B, ServiceScope.BOTH)
            else "NONE"
        )
        object.__setattr__(
            user,
            "b2b_request_status",
            source_entry.get("status") or default_status,
        )
        object.__setattr__(user, "company_name", source_entry.get("company_name"))
        object.__setattr__(user, "gstin", source_entry.get("gstin"))
        object.__setattr__(user, "pan", source_entry.get("pan"))
        object.__setattr__(
            user, "b2b_requested_at", source_entry.get("requested_at")
        )
        object.__setattr__(user, "same_as_tenant_gstin", source_entry.get("same_as_tenant_gstin", False))
        object.__setattr__(user, "billing_address", source_entry.get(BILLING_ADDRESS_KEY))
        object.__setattr__(user, "gstin_status", source_entry.get(GSTIN_STATUS_KEY))
        object.__setattr__(user, "company_details_locked", company_details_locked(source_entry))
        return user

    async def enrich_user_profile(
        self, user: User, tenant: Optional[Tenant] = None
    ) -> User:
        """Loads the user's tenant settings and enriches transient B2B & org fields."""
        if tenant is None:
            tenant = get_cached_tenant_by_id(user.tenant_id)
        if tenant is None:
            tenant = await self.tenant_repo.get_tenant_by_id(user.tenant_id)
            if tenant is not None:
                cache_tenant(tenant)
        settings = tenant.settings if tenant else {}
        return self._enrich_user_with_b2b_metadata(user, settings)

    @staticmethod
    def _is_token_email_verified(token_data: TokenPayload) -> bool:
        """
        True unless the token explicitly marks the email as unverified (B-04).
        Prevents an unverified OAuth/email identity from claiming an `invited:`
        staff or admin placeholder row.
        """
        if token_data.email_verified is False:
            return False
        user_meta = token_data.user_metadata
        if isinstance(user_meta, dict) and user_meta.get("email_verified") is False:
            return False
        return True

    async def get_or_create_user(
        self,
        *,
        token_data: TokenPayload,
        tenant: Tenant,
        full_name: Optional[str] = None,
    ) -> User:
        """
        Gets a user profile if it exists, or creates a new one if it does not.
        This is the core "Just-in-Time" provisioning logic.
        """
        clean_full_name = full_name.strip() if full_name and full_name.strip() else None
        user = await self.tenant_repo.get_user_by_supabase_id_and_tenant_id(
            supabase_user_id=token_data.sub, tenant_id=tenant.id
        )

        if user:
            needs_save = False
            if clean_full_name and not user.full_name:
                user.full_name = clean_full_name
                needs_save = True
            if user.role != UserRole.owner and getattr(user, "is_active", True):
                existing_users = await self.tenant_repo.list_users_for_tenant(tenant.id)
                has_active_owner = any(
                    u.role == UserRole.owner and getattr(u, "is_active", True)
                    for u in existing_users
                )
                if not has_active_owner and len(existing_users) == 1:
                    user.role = UserRole.owner
                    user.service_scope = ServiceScope.BOTH
                    needs_save = True
            if needs_save:
                user = await self.tenant_repo.create_user(user)
            return self._enrich_user_with_b2b_metadata(user, tenant.settings)

        if token_data.email:
            invited_user = await self.tenant_repo.get_user_by_email_and_tenant_id(
                email=token_data.email, tenant_id=tenant.id
            )
            if invited_user:
                existing_sub = str(invited_user.supabase_user_id or "")
                if not existing_sub.startswith(INVITED_SUPABASE_ID_PREFIX) and existing_sub != token_data.sub:
                    raise HTTPException(
                        status_code=403,
                        detail="This email is already linked to another account in this workspace.",
                    )
                if not self._is_token_email_verified(token_data):
                    raise HTTPException(
                        status_code=403,
                        detail="Please verify your email address before claiming an invited workspace account.",
                    )
                invited_user.supabase_user_id = token_data.sub
                if clean_full_name and not invited_user.full_name:
                    invited_user.full_name = clean_full_name
                saved_invited = await self.tenant_repo.create_user(invited_user)
                return self._enrich_user_with_b2b_metadata(
                    saved_invited, tenant.settings
                )

        existing_users = await self.tenant_repo.list_users_for_tenant(tenant.id)
        has_active_owner = any(
            u.role == UserRole.owner and getattr(u, "is_active", True)
            for u in existing_users
        )
        is_first_tenant_user = len(existing_users) == 0 or not has_active_owner

        new_user = User(
            email=token_data.email,
            supabase_user_id=token_data.sub,
            tenant_id=tenant.id,
            full_name=clean_full_name,
            role=UserRole.owner if is_first_tenant_user else UserRole.customer,
            service_scope=(
                ServiceScope.BOTH if is_first_tenant_user else ServiceScope.B2C
            ),
            is_active=True,
        )
        created = await self.tenant_repo.create_user(new_user)
        cache_user(created)
        return self._enrich_user_with_b2b_metadata(created, tenant.settings)

    def _mint_supabase_session(
        self, supabase_user_id: str, email: str, user: User
    ) -> PasswordAuthResponse:
        """Mints a Supabase-compatible JWT and returns the session + user profile."""
        now_ts = int(time.time())
        exp_ts = now_ts + AUTH_TOKEN_TTL_SECONDS
        claims = {
            "sub": str(supabase_user_id),
            "email": email,
            "aud": "authenticated",
            "role": "authenticated",
            "iss": app_settings.JWT_ISSUER,
            "iat": now_ts,
            "exp": exp_ts,
        }
        token = jwt.encode(
            claims, app_settings.SECRET_KEY, algorithm=app_settings.ALGORITHM
        )
        return PasswordAuthResponse(
            access_token=token,
            refresh_token=f"naviera-rt-{uuid.uuid4().hex}",
            token_type="bearer",
            expires_in=AUTH_TOKEN_TTL_SECONDS,
            expires_at=exp_ts,
            supabase_user_id=str(supabase_user_id),
            user=UserRead.model_validate(user),
        )

    @staticmethod
    def _signup_consent_metadata(
        payload: PasswordSignupRequest, now: Optional[datetime] = None
    ) -> dict[str, str]:
        """
        Enforces the signup consent checkbox and builds its audit record.

        Args:
            payload: The signup request (must carry `terms_accepted=True`).
            now: Acceptance time (injectable for tests; defaults to UTC now).

        Returns:
            `{"terms_accepted_at": <ISO-8601 UTC>, "terms_version": TERMS_VERSION}`,
            merged into the Supabase `raw_user_meta_data` of the new account.

        Raises:
            HTTPException(400): consent was not given.
        """
        if payload.terms_accepted is not True:
            raise HTTPException(status_code=400, detail=TERMS_CONSENT_REQUIRED_DETAIL)
        accepted_at = now or datetime.now(timezone.utc)
        return {
            "terms_accepted_at": accepted_at.isoformat(),
            "terms_version": TERMS_VERSION,
        }

    async def signup_with_password(
        self, *, tenant: Tenant, payload: PasswordSignupRequest
    ) -> PasswordAuthResponse:
        """
        Creates a NEW Email & Password account in `auth.users` and provisions or
        links the `public."user"` profile in the current tenant (an `invited:`
        row is linked by email; the first tenant user becomes OWNER).

        `auth.users` is shared by every tenant, so if the email already has an
        auth account (in ANY tenant) its password is never touched: 409 tells
        the caller to sign in (which JIT-provisions them in this tenant) or use
        Email OTP / Forgot password.
        """
        normalized_email = (payload.email or "").strip().lower()
        if not normalized_email or "@" not in normalized_email:
            raise HTTPException(
                status_code=400, detail="Please enter a valid email address."
            )
        if len(payload.password or "") < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            )

        if await self.tenant_repo.get_auth_user_by_email(normalized_email) is not None:
            raise HTTPException(status_code=409, detail=SIGNUP_EMAIL_EXISTS_DETAIL)

        # Consent is checked only when a NEW auth account would be created, so an
        # existing email still gets the 409 "sign in instead" guidance above.
        consent_metadata = self._signup_consent_metadata(payload)

        auth_user_id = await self.tenant_repo.create_auth_user_with_password(
            email=normalized_email,
            password=payload.password,
            full_name=payload.full_name,
            extra_user_metadata=consent_metadata,
        )
        if auth_user_id is None:
            # Lost a race with a concurrent signup for the same email.
            raise HTTPException(status_code=409, detail=SIGNUP_EMAIL_EXISTS_DETAIL)

        token_data = TokenPayload(
            sub=auth_user_id, email=normalized_email, aud="authenticated"
        )
        user = await self.get_or_create_user(
            token_data=token_data, tenant=tenant, full_name=payload.full_name
        )

        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Your account has been deactivated by the workspace administrator.",
            )

        return self._mint_supabase_session(auth_user_id, normalized_email, user)

    async def _login_failure_detail(self, tenant: Tenant, email: str) -> str:
        """
        401 message for a failed password login. Invited users who have no auth
        account yet are pointed to 'Create Account'; invited users who already
        have one (e.g. from another tenant) are told to use that password or OTP.
        """
        tenant_user = await self.tenant_repo.get_user_by_email_and_tenant_id(
            email=email, tenant_id=tenant.id
        )
        is_pending_invite = tenant_user is not None and str(
            tenant_user.supabase_user_id
        ).startswith(INVITED_SUPABASE_ID_PREFIX)
        if not is_pending_invite:
            return INVALID_LOGIN_DETAIL
        if await self.tenant_repo.get_auth_user_by_email(email) is None:
            return INVITED_LOGIN_CREATE_ACCOUNT_DETAIL
        return INVITED_LOGIN_EXISTING_ACCOUNT_DETAIL

    async def login_with_password(
        self, *, tenant: Tenant, payload: PasswordLoginRequest
    ) -> PasswordAuthResponse:
        """
        Authenticates a user with Email & Password against `auth.users` and returns
        a Supabase-compatible JWT session + synced tenant profile. A valid password
        from another tenant JIT-provisions (or links an invite in) this tenant.
        """
        normalized_email = (payload.email or "").strip().lower()
        if not normalized_email or "@" not in normalized_email:
            raise HTTPException(
                status_code=400, detail="Please enter a valid email address."
            )

        verified = await self.tenant_repo.verify_auth_user_password(
            normalized_email, payload.password or ""
        )
        if not verified:
            raise HTTPException(
                status_code=401,
                detail=await self._login_failure_detail(tenant, normalized_email),
            )

        auth_user_id = str(verified["id"])
        token_data = TokenPayload(
            sub=auth_user_id, email=normalized_email, aud="authenticated"
        )
        user = await self.get_or_create_user(token_data=token_data, tenant=tenant)
        if not user.is_active:
            raise HTTPException(
                status_code=403,
                detail="Your account has been deactivated by the workspace administrator.",
            )

        return self._mint_supabase_session(auth_user_id, normalized_email, user)

    async def get_tenant_by_slug(self, slug: str) -> Tenant | None:
        """
        Retrieves a tenant by slug for public-facing endpoints.
        """
        cached = get_cached_tenant_by_slug(slug)
        if cached is not None:
            return cached
        tenant = await self.tenant_repo.get_tenant_by_slug(slug)
        if tenant is not None:
            cache_tenant(tenant)
        return tenant

    @staticmethod
    def _public_wallet_config(wallet_config: Any) -> dict:
        """Only the non-secret `wallet_config` display fields (no VPA, limits or flags)."""
        if not isinstance(wallet_config, dict):
            return {}
        return {
            key: wallet_config[key]
            for key in PUBLIC_WALLET_CONFIG_KEYS
            if wallet_config.get(key) is not None
        }

    @classmethod
    def build_public_settings(cls, settings: Optional[dict]) -> dict:
        """
        Projects `tenant.settings` onto the public allow-list
        (`PUBLIC_SETTINGS_KEYS` + a sanitized `wallet_config`).

        Args:
            settings: The raw tenant settings JSON (may be None / malformed).

        Returns:
            A deep-copied dict that is safe to serve without authentication.
        """
        source = settings if isinstance(settings, dict) else {}
        public = {
            key: copy.deepcopy(value)
            for key, value in source.items()
            if key in PUBLIC_SETTINGS_KEYS
        }
        wallet_display = cls._public_wallet_config(source.get("wallet_config"))
        if wallet_display:
            public["wallet_config"] = wallet_display
        return public

    @classmethod
    def to_public_tenant(cls, tenant: Tenant) -> TenantRead:
        """Tenant identity + allow-listed settings for unauthenticated responses."""
        return TenantRead(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            settings=cls.build_public_settings(tenant.settings),
        )

    async def get_public_tenant_by_slug(self, slug: str) -> Optional[TenantRead]:
        """Public (sanitized) tenant config by slug, or None when the slug is unknown."""
        tenant = await self.get_tenant_by_slug(slug)
        return self.to_public_tenant(tenant) if tenant else None

    async def list_tenants(self, user: User) -> list[Tenant]:
        """
        Workspaces visible to the caller: only their OWN tenant (Admin/Owner).
        Customers get 403; nobody can enumerate other tenants' settings.
        """
        if user.role not in [UserRole.admin, UserRole.owner]:
            raise HTTPException(
                status_code=403, detail="Only Admins or Owners can view workspace details."
            )
        tenant = get_cached_tenant_by_id(user.tenant_id)
        if tenant is None:
            tenant = await self.tenant_repo.get_tenant_by_id(user.tenant_id)
            if tenant is not None:
                cache_tenant(tenant)
        return [tenant] if tenant else []

    async def list_users_for_tenant(
        self, tenant_id: uuid.UUID, current_user: Optional[User] = None
    ) -> list[User]:
        """
        Retrieves all users for a tenant (both `TENANT_STAFF` and `CUSTOMER` accounts).
        Strictly restricted to Tenant Staff Admins / Owners (`is_tenant_admin`).
        """
        if current_user is not None and not is_tenant_admin(current_user):
            raise HTTPException(
                status_code=403,
                detail="Only Tenant Admins or Owners can list workspace users.",
            )

        tenant = get_cached_tenant_by_id(tenant_id)
        if tenant is None:
            tenant = await self.tenant_repo.get_tenant_by_id(tenant_id)
            if tenant is not None:
                cache_tenant(tenant)
        if not tenant:
            raise TenantNotFoundException()
        users = await self.tenant_repo.list_users_for_tenant(tenant_id=tenant_id)
        return [
            self._enrich_user_with_b2b_metadata(u, tenant.settings) for u in users
        ]

    # ------------------------------------------------------------ settings

    @staticmethod
    def _assert_settings_admin(
        user: User, tenant_id: uuid.UUID, *, action: str = "update"
    ) -> None:
        """Tenant Admin/Owner of the SAME tenant only (`action` words the 403)."""
        if not is_tenant_admin(user):
            raise HTTPException(
                status_code=403,
                detail=f"Only Tenant Admins or Owners can {action} platform settings.",
            )
        if user.tenant_id != tenant_id:
            raise HTTPException(
                status_code=403,
                detail=f"You cannot {action} settings for a different workspace.",
            )

    @staticmethod
    def _validate_settings_payload(settings_payload: dict) -> dict:
        """
        Validates known sections (unknown keys pass through) and returns the
        normalised patch (e.g. canonical icon keys, blank formatted fields -> None).
        """
        try:
            validated = TenantSettingsUpdate.model_validate(settings_payload)
        except ValidationError as exc:
            errors = [
                {
                    "loc": ["body", "settings", *error["loc"]],
                    "msg": error["msg"],
                    "type": error["type"],
                }
                for error in exc.errors(include_url=False, include_context=False)
            ]
            raise HTTPException(status_code=422, detail=errors)
        return validated.model_dump(mode="json", exclude_unset=True)

    @staticmethod
    def _apply_settings_defaults(settings: dict) -> dict:
        """Server-side defaults for known toggles (brand.show_logo defaults to True)."""
        brand = settings.get("brand")
        brand = dict(brand) if isinstance(brand, dict) else {}
        if brand.get("show_logo") is None:
            brand["show_logo"] = SHOW_LOGO_DEFAULT
        settings["brand"] = brand
        return settings

    @staticmethod
    def _changed_sections(before: dict, after: dict) -> List[str]:
        """Top-level settings keys whose value differs between two snapshots."""
        keys = set(before) | set(after)
        return sorted(key for key in keys if before.get(key) != after.get(key))

    async def _snapshot_settings(
        self,
        tenant: Tenant,
        *,
        changed_by: User,
        changed_sections: List[str],
    ) -> TenantSettingsHistory:
        """
        Stores the tenant's CURRENT config settings as the next version and prunes
        old ones. `RUNTIME_SETTINGS_KEYS` (B2B KYC requests) are not copied.
        """
        snapshot = TenantSettingsHistory(
            tenant_id=tenant.id,
            version=await self.tenant_repo.next_settings_version(tenant.id),
            settings=self._without_runtime_keys(tenant.settings),
            changed_by_user_id=changed_by.id,
            changed_sections=changed_sections,
        )
        await self.tenant_repo.add_settings_snapshot(snapshot)
        await self.tenant_repo.prune_settings_history(tenant.id, SETTINGS_HISTORY_LIMIT)
        return snapshot

    @staticmethod
    def _without_runtime_keys(settings: Optional[dict]) -> dict:
        """Deep copy of `settings` minus `RUNTIME_SETTINGS_KEYS` and `RETIRED_SETTINGS_KEYS`."""
        excluded = set(RUNTIME_SETTINGS_KEYS) | set(RETIRED_SETTINGS_KEYS)
        return {
            key: copy.deepcopy(value)
            for key, value in (settings or {}).items()
            if key not in excluded
        }

    @staticmethod
    def _carry_forward_runtime_keys(restored: dict, current: Optional[dict]) -> dict:
        """
        Replaces `RUNTIME_SETTINGS_KEYS` and `RESTORE_KEEPS_CURRENT_KEYS` (pricing policy)
        in a restored snapshot with the tenant's CURRENT values (dropping them when the
        tenant has none), strips retired keys (`pricing_config`), and preserves a configured
        `company.invoice_prefix`, so a restore never reverts KYC approvals, never changes
        what customers are charged and never changes the GST series mid-FY (A4-33).
        """
        current_settings = current or {}
        for key in RETIRED_SETTINGS_KEYS:
            restored.pop(key, None)
        for key in RUNTIME_SETTINGS_KEYS + RESTORE_KEEPS_CURRENT_KEYS:
            if key in current_settings:
                restored[key] = copy.deepcopy(current_settings[key])
            else:
                restored.pop(key, None)
        current_company = current_settings.get("company")
        current_prefix = (
            str(current_company.get("invoice_prefix") or "").strip().upper()
            if isinstance(current_company, dict)
            else ""
        )
        if current_prefix:
            restored_company = (
                dict(restored["company"])
                if isinstance(restored.get("company"), dict)
                else {}
            )
            restored_company["invoice_prefix"] = current_prefix
            restored["company"] = restored_company
        return restored

    @staticmethod
    def _assert_invoice_prefix_locked(
        current_settings: Optional[dict], normalized_patch: dict
    ) -> None:
        """Rejects mid-FY changes to `company.invoice_prefix` once configured (A4-33)."""
        patch_company = normalized_patch.get("company")
        if not isinstance(patch_company, dict) or "invoice_prefix" not in patch_company:
            return
        current_company = (
            (current_settings or {}).get("company")
            if isinstance(current_settings, dict)
            else None
        )
        existing_prefix = (
            str(current_company.get("invoice_prefix") or "").strip().upper()
            if isinstance(current_company, dict)
            else ""
        )
        incoming_prefix = str(patch_company.get("invoice_prefix") or "").strip().upper()
        if existing_prefix and incoming_prefix != existing_prefix:
            raise HTTPException(status_code=422, detail=INVOICE_PREFIX_LOCKED_DETAIL)

    async def _replace_settings(
        self, tenant: Tenant, new_settings: dict, user: User
    ) -> Tenant:
        """Snapshots the previous settings (when something changed), then saves."""
        previous = copy.deepcopy(tenant.settings or {})
        changed = self._changed_sections(previous, new_settings)
        if changed:
            await self._snapshot_settings(tenant, changed_by=user, changed_sections=changed)
        tenant.settings = new_settings
        flag_modified(tenant, "settings")
        await self.tenant_repo.save_tenant(tenant)
        saved = await self.tenant_repo.commit_and_refresh(tenant)
        invalidate_auth_cache(tenant_id=saved.id, slug=saved.slug)
        cache_tenant(saved)
        return saved

    async def get_admin_tenant_settings(
        self, tenant_id: uuid.UUID, user: User
    ) -> Tenant:
        """
        Full (unfiltered) tenant settings for the Settings page editor.
        Tenant Admin/Owner of the same tenant only; public callers get
        `to_public_tenant` instead.
        """
        self._assert_settings_admin(user, tenant_id, action="view")
        tenant = get_cached_tenant_by_id(tenant_id)
        if tenant is None:
            tenant = await self.tenant_repo.get_tenant_by_id(tenant_id)
            if tenant is not None:
                cache_tenant(tenant)
        if not tenant:
            raise TenantNotFoundException()
        return tenant

    async def update_tenant_settings(
        self, tenant_id: uuid.UUID, user: User, settings_payload: dict
    ) -> Tenant:
        """
        Validates, deep-merges and saves tenant settings, snapshotting the
        previous version first. Strictly requires Platform Admin or Owner privileges.
        Supports optional `expected_version` optimistic concurrency check (G-10).
        """
        self._assert_settings_admin(user, tenant_id)
        payload_copy = dict(settings_payload or {})
        expected_version = payload_copy.pop("expected_version", None)
        normalized_patch = self._validate_settings_payload(payload_copy)

        tenant = await self.tenant_repo.get_tenant_for_update(tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        if expected_version is not None:
            current_version = (await self.tenant_repo.next_settings_version(tenant_id)) - 1
            if int(expected_version) != current_version:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Settings were modified by another administrator "
                        f"(expected v{expected_version}, current v{current_version}). "
                        "Please reload and try again."
                    ),
                )
        self._assert_invoice_prefix_locked(tenant.settings, normalized_patch)

        merged = self._deep_merge(tenant.settings or {}, normalized_patch)
        return await self._replace_settings(
            tenant, self._apply_settings_defaults(merged), user
        )

    async def replace_settings_section(
        self, tenant_id: uuid.UUID, user: User, key: str, value: Any
    ) -> Tenant:
        """
        Replaces ONE top-level settings section wholesale (no deep merge), row-locked and
        snapshotted like every settings save. Used by typed editors such as the pricing
        policy (`services/pricing/policy.py`), whose caller already validated `value`.

        Raises:
            TenantNotFoundException: unknown tenant.
        """
        tenant = await self.tenant_repo.get_tenant_for_update(tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        new_settings = copy.deepcopy(tenant.settings or {})
        new_settings[key] = value
        return await self._replace_settings(tenant, new_settings, user)

    async def list_settings_history(
        self, tenant_id: uuid.UUID, user: User
    ) -> List[TenantSettingsHistoryRead]:
        """
        Restorable versions (newest first) for the settings History panel. Admin only.
        Rows that only changed `HISTORY_HIDDEN_SECTIONS` are left out (see that constant).
        """
        self._assert_settings_admin(user, tenant_id, action="view")
        rows = await self.tenant_repo.list_settings_history(tenant_id)
        entries: List[TenantSettingsHistoryRead] = []
        for entry, email in rows:
            sections = list(entry.changed_sections or [])
            visible = self._visible_history_sections(sections)
            if sections and not visible:
                continue
            entries.append(
                TenantSettingsHistoryRead(
                    id=entry.id,
                    version=entry.version,
                    created_at=entry.created_at,
                    changed_by_email=email,
                    changed_sections=visible,
                )
            )
        return entries

    @staticmethod
    def _visible_history_sections(sections: List[str]) -> List[str]:
        """`sections` minus the ones a Settings restore can't undo (`HISTORY_HIDDEN_SECTIONS`)."""
        return [section for section in sections if section not in HISTORY_HIDDEN_SECTIONS]

    async def restore_settings_version(
        self, tenant_id: uuid.UUID, version_id: uuid.UUID, user: User
    ) -> Tenant:
        """
        Restores a stored snapshot. The current settings are snapshotted first,
        so a restore can itself be undone. `RUNTIME_SETTINGS_KEYS` keep their
        current values. Admin only.
        """
        self._assert_settings_admin(user, tenant_id)
        tenant = await self.tenant_repo.get_tenant_for_update(tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        snapshot = await self.tenant_repo.get_settings_snapshot(version_id, tenant_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Settings version not found")
        restored = self._carry_forward_runtime_keys(
            copy.deepcopy(snapshot.settings or {}), tenant.settings
        )
        return await self._replace_settings(
            tenant, self._apply_settings_defaults(restored), user
        )

    # --------------------------------------------------------------- users

    @staticmethod
    def _assert_owner_rules(
        current_user: User, target_user: User, payload: UserUpdate
    ) -> None:
        """
        Ownership guard rails: only the Owner can grant the owner role
        (transfer ownership); the Owner can't be demoted or deactivated.
        B-06 (DO1 `users`): only the Owner can make someone an Admin or change an existing
        Admin, so a second approver can never be minted by the first; and nobody can change
        their own role or deactivate themselves.
        """
        is_self = target_user.id == current_user.id
        changes_role = payload.role is not None and payload.role != target_user.role
        if is_self and (changes_role or payload.is_active is False):
            raise HTTPException(
                status_code=400,
                detail="You can't change your own role or deactivate yourself. Ask the Tenant Owner.",
            )
        if current_user.role != UserRole.owner and (
            (changes_role and payload.role == UserRole.admin)
            or (target_user.role == UserRole.admin and (changes_role or payload.is_active is False))
        ):
            raise HTTPException(
                status_code=403,
                detail="Only the Tenant Owner can add, change or remove an Admin.",
            )
        if payload.role == UserRole.owner and target_user.role != UserRole.owner:
            if current_user.role != UserRole.owner:
                raise HTTPException(
                    status_code=403,
                    detail="Only the Tenant Owner can transfer ownership.",
                )
        if target_user.role == UserRole.owner:
            if payload.role is not None and payload.role != UserRole.owner:
                raise HTTPException(status_code=400, detail="Cannot demote the Tenant Owner")
            if payload.is_active is False:
                raise HTTPException(
                    status_code=400, detail="Cannot deactivate the Tenant Owner"
                )

    async def _save_user_b2b_metadata(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        status_val: Optional[str] = None,
        company_name: Optional[str] = None,
        gstin: Optional[str] = None,
        pan: Optional[str] = None,
        notes: Optional[str] = None,
        requested_at: Optional[str] = None,
        reviewed_by: Optional[str] = None,
        same_as_tenant_gstin: Optional[bool] = None,
    ) -> dict:
        """Persists per-user B2B access request & optional KYC details inside `tenant.settings['b2b_access_requests']`."""
        tenant = await self.tenant_repo.get_tenant_for_update(tenant_id)
        if not tenant:
            raise TenantNotFoundException()

        settings = copy.deepcopy(tenant.settings or {})
        requests_map = settings.get("b2b_access_requests")
        if not isinstance(requests_map, dict):
            requests_map = {}

        uid_str = str(user_id)
        existing = requests_map.get(uid_str)
        entry = dict(existing) if isinstance(existing, dict) else {}

        if status_val is not None:
            entry["status"] = status_val
        if company_name is not None:
            entry["company_name"] = company_name.strip() if company_name.strip() else None
        if gstin is not None:
            entry["gstin"] = gstin
        if pan is not None:
            entry["pan"] = pan
        if notes is not None:
            entry["notes"] = notes.strip() if notes.strip() else None
        if requested_at is not None:
            entry["requested_at"] = requested_at
        if reviewed_by is not None:
            entry["reviewed_by"] = reviewed_by
            entry["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        if same_as_tenant_gstin is not None:
            entry["same_as_tenant_gstin"] = same_as_tenant_gstin

        requests_map[uid_str] = entry
        settings["b2b_access_requests"] = requests_map
        tenant.settings = settings
        flag_modified(tenant, "settings")
        await self.tenant_repo.save_tenant(tenant)
        await self.tenant_repo.commit_and_refresh(tenant)
        invalidate_auth_cache(tenant_id=tenant.id, slug=tenant.slug)
        cache_tenant(tenant)
        return settings

    async def request_b2b_access(
        self, current_user: User, payload: B2BAccessRequestCreate
    ) -> User:
        """
        Allows an authenticated B2C customer to request B2B Cargo access,
        optionally providing their Company Name, 15-digit GSTIN, or 10-digit PAN.
        """
        clean_gstin, clean_pan = self._validate_optional_gstin_and_pan(
            payload.gstin, payload.pan
        )
        now_iso = datetime.now(timezone.utc).isoformat()
        next_status = (
            "APPROVED"
            if current_user.service_scope in (ServiceScope.B2B, ServiceScope.BOTH)
            else "PENDING"
        )
        tenant = get_cached_tenant_by_id(current_user.tenant_id)
        if tenant is None:
            tenant = await self.tenant_repo.get_tenant_by_id(current_user.tenant_id)
            if tenant is not None:
                cache_tenant(tenant)
        tenant_gstin = None
        if tenant and tenant.settings:
            tenant_gstin = tenant.settings.get("gstin")
        
        is_same_gstin = False
        if clean_gstin and tenant_gstin and clean_gstin == tenant_gstin:
            is_same_gstin = True
            
        settings = await self._save_user_b2b_metadata(
            current_user.tenant_id,
            current_user.id,
            status_val=next_status,
            company_name=payload.company_name,
            gstin=clean_gstin,
            pan=clean_pan,
            notes=payload.notes,
            requested_at=now_iso,
            same_as_tenant_gstin=is_same_gstin,
        )
        return self._enrich_user_with_b2b_metadata(current_user, settings)

    async def review_b2b_access(
        self,
        user_id: uuid.UUID,
        payload: B2BAccessReviewRequest,
        current_user: User,
        tenant_id: uuid.UUID,
    ) -> User:
        """
        Allows a Tenant Staff Admin / Owner to approve or reject a customer's
        B2B access request. On approval, upgrades `service_scope` (default `BOTH`).
        """
        if not is_tenant_admin(current_user):
            raise HTTPException(
                status_code=403,
                detail="Only Tenant Admins or Owners can review B2B access requests",
            )

        target_user = await self.tenant_repo.get_user_by_id(user_id)
        if not target_user or target_user.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="User not found")

        if payload.approve:
            target_user.service_scope = (
                payload.service_scope
                if payload.service_scope in (ServiceScope.B2B, ServiceScope.BOTH)
                else ServiceScope.BOTH
            )
            target_user = await self.tenant_repo.create_user(target_user)

        settings = await self._save_user_b2b_metadata(
            tenant_id,
            target_user.id,
            status_val="APPROVED" if payload.approve else "REJECTED",
            reviewed_by=current_user.email,
        )
        return self._enrich_user_with_b2b_metadata(target_user, settings)

    def _normalize_admin_user_edits(self, update_data: dict, target_user: User) -> None:
        """
        Cleans an Owner/Admin edit of another user in place (Users page, PATCH /users/{id}):
        - a blank `full_name` is ignored (the name is never wiped from this form);
        - `phone` is validated like the self-service profile (blank clears it);
        - team members always keep both flows (`service_scope = BOTH`); the B2C / B2B
          scope only restricts customers, so it can't lock a staff member out of B2B.

        Raises:
            HTTPException(400): invalid phone number.
        """
        if "full_name" in update_data:
            clean_name = (update_data["full_name"] or "").strip()
            if clean_name:
                update_data["full_name"] = clean_name
            else:
                update_data.pop("full_name")
        if "phone" in update_data:
            update_data["phone"] = self._normalize_profile_phone(update_data["phone"])
        resulting_role = update_data.get("role") or target_user.role
        if resulting_role in STAFF_USER_ROLES:
            update_data["service_scope"] = ServiceScope.BOTH

    async def update_user(
        self,
        user_id: uuid.UUID,
        payload: UserUpdate,
        current_user: User,
        tenant_id: uuid.UUID,
    ) -> User:
        """
        Updates a user's category (`TENANT_STAFF` vs `CUSTOMER`), staff role,
        status, or B2C/B2B service scope. Restricted to Tenant Admins / Owners.
        """
        if not is_tenant_admin(current_user):
            raise HTTPException(
                status_code=403,
                detail="Only Tenant Admins or Owners can modify users",
            )

        target_user = await self.tenant_repo.get_user_by_id(user_id)
        if not target_user or target_user.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="User not found")

        update_data = payload.model_dump(exclude_unset=True)
        company_name = update_data.pop("company_name", None)
        raw_gstin = update_data.pop("gstin", None)
        raw_pan = update_data.pop("pan", None)
        account_type = update_data.pop("account_type", None)
        clean_gstin, clean_pan = self._validate_optional_gstin_and_pan(
            raw_gstin, raw_pan
        )

        if account_type and "role" not in update_data:
            normalized_type = account_type.strip().upper()
            if normalized_type in ("CUSTOMER", "MERCHANT_TEAM"):
                payload.role = UserRole.customer
                update_data["role"] = UserRole.customer
            elif (
                normalized_type in ("TENANT_STAFF", "LOGISMART_STAFF")
                and target_user.role != UserRole.owner
            ):
                payload.role = UserRole.admin
                update_data["role"] = UserRole.admin

        self._assert_owner_rules(current_user, target_user, payload)
        self._normalize_admin_user_edits(update_data, target_user)
        role_or_status_changed = any(
            key in update_data and getattr(target_user, key, None) != update_data[key]
            for key in ("role", "service_scope", "is_active")
        )
        is_transfer = (
            payload.role == UserRole.owner
            and target_user.role != UserRole.owner
            and target_user.id != current_user.id
        )

        for key, value in update_data.items():
            setattr(target_user, key, value)

        if is_transfer:
            previous_owner = await self.tenant_repo.get_user_by_id(current_user.id)
            if previous_owner is not None:
                previous_owner.role = UserRole.admin
                self.tenant_repo.session.add(previous_owner)

        if role_or_status_changed:
            tenant_row = await self.tenant_repo.get_tenant_by_id(tenant_id)
            if tenant_row is not None:
                await self._snapshot_settings(
                    tenant_row,
                    changed_by=current_user,
                    changed_sections=["user_roles"],
                )

        saved_user = await self.tenant_repo.create_user(target_user)
        invalidate_auth_cache(tenant_id=tenant_id)
        cache_user(saved_user)
        new_b2b_status = (
            "APPROVED"
            if saved_user.service_scope in (ServiceScope.B2B, ServiceScope.BOTH)
            else None
        )
        if any(
            v is not None
            for v in (company_name, clean_gstin, clean_pan, new_b2b_status)
        ):
            settings = await self._save_user_b2b_metadata(
                tenant_id,
                saved_user.id,
                status_val=new_b2b_status,
                company_name=company_name,
                gstin=clean_gstin,
                pan=clean_pan,
                reviewed_by=current_user.email if new_b2b_status else None,
            )
            return self._enrich_user_with_b2b_metadata(saved_user, settings)

        return await self.enrich_user_profile(saved_user)

    async def update_my_profile(
        self, current_user: User, payload: UserSelfUpdate
    ) -> User:
        """
        Lets any signed-in user change their own display name and phone.
        Role, scope and status stay Owner/Admin-only (`update_user`).

        Raises:
            HTTPException(400): blank name or an invalid phone number.
        """
        update_data = payload.model_dump(exclude_unset=True)
        if payload.company_details is not None:
            await self._submit_company_details(current_user, payload.company_details)
        target_user = current_user
        session = getattr(self.tenant_repo, "session", None)
        if session is not None and current_user not in session:
            db_user = await self.tenant_repo.get_user_by_id(current_user.id)
            if db_user is not None:
                target_user = db_user
        if "full_name" in update_data:
            clean_name = (update_data["full_name"] or "").strip()
            if not clean_name:
                raise HTTPException(status_code=400, detail="Name cannot be empty.")
            target_user.full_name = clean_name
        if "phone" in update_data:
            target_user.phone = self._normalize_profile_phone(update_data["phone"])
        saved_user = await self.tenant_repo.create_user(target_user)
        invalidate_auth_cache(
            tenant_id=getattr(saved_user, "tenant_id", None),
            supabase_user_id=getattr(saved_user, "supabase_user_id", None),
        )
        cache_user(saved_user)
        return await self.enrich_user_profile(saved_user)

    @staticmethod
    def _validate_seller_gstin(raw_gstin: Optional[str], tenant: Tenant) -> Optional[str]:
        """
        A seller's self-submitted GSTIN (C-01): blank = unregistered; otherwise it must
        pass the GSTN checksum (which also checks the embedded PAN format and state code)
        and must not be the tenant's own GSTIN.

        Raises:
            HTTPException(422): malformed / checksum mismatch / the tenant's own GSTIN.
        """
        gstin = (raw_gstin or "").strip().upper()
        if not gstin:
            return None
        if not is_checksum_valid_gstin(gstin):
            raise HTTPException(
                status_code=422,
                detail="Enter a valid 15-character GSTIN (please check it against your GST certificate).",
            )
        if gstin == resolve_supplier_gst_profile(tenant).gstin:
            raise HTTPException(
                status_code=422,
                detail=f"This is {tenant.name}'s own GSTIN. Enter your company's GSTIN, or leave it blank.",
            )
        return gstin

    async def _submit_company_details(
        self, current_user: User, details: SellerCompanyDetailsSubmit
    ) -> None:
        """
        Saves a seller's one-time "Company details" into
        `tenant.settings['b2b_access_requests'][user_id]` (C-01). The tenant row is locked
        (`SELECT ... FOR UPDATE`) and re-read first, so a concurrent settings save is
        never overwritten. Once on file they are view-only (Delhivery One `profile`).

        Raises:
            HTTPException(409): company details are already on file.
            HTTPException(422): blank name / address or an invalid GSTIN.
        """
        tenant = await self.tenant_repo.get_tenant_for_update(current_user.tenant_id)
        if not tenant:
            raise TenantNotFoundException()
        settings = copy.deepcopy(tenant.settings or {})
        requests_map = settings.get(KYC_REQUESTS_SETTINGS_KEY)
        if not isinstance(requests_map, dict):
            requests_map = {}
        uid = str(current_user.id)
        entry = dict(requests_map.get(uid) or {})
        if company_details_locked(entry):
            raise HTTPException(
                status_code=409,
                detail="Your company details are already on file. To change them, raise a support ticket.",
            )
        legal_name = details.legal_name.strip()
        billing_address = details.billing_address.strip()
        if not legal_name or not billing_address:
            raise HTTPException(status_code=422, detail="Company name and billing address are required.")
        gstin = self._validate_seller_gstin(details.gstin, tenant)
        entry.update(
            {
                "company_name": legal_name,
                BILLING_ADDRESS_KEY: billing_address,
                "gstin": gstin,
                "pan": pan_from_gstin(gstin) if gstin else entry.get("pan"),
                GSTIN_STATUS_KEY: KYC_APPROVED_STATUS if gstin else None,
                VERIFIED_GSTIN_KEY: gstin,
                "same_as_tenant_gstin": False,
                COMPANY_DETAILS_SUBMITTED_AT_KEY: datetime.now(timezone.utc).isoformat(),
            }
        )
        requests_map[uid] = entry
        settings[KYC_REQUESTS_SETTINGS_KEY] = requests_map
        tenant.settings = settings
        flag_modified(tenant, "settings")
        await self.tenant_repo.save_tenant(tenant)
        await self.tenant_repo.commit_and_refresh(tenant)
        invalidate_auth_cache(tenant_id=tenant.id, slug=tenant.slug)
        cache_tenant(tenant)

    @staticmethod
    def _normalize_profile_phone(raw_phone: Optional[str]) -> Optional[str]:
        """
        Blank clears the phone; otherwise keeps digits (optional leading +) and
        requires 10-15 digits.
        """
        cleaned = re.sub(r"[\s-]", "", raw_phone or "")
        if not cleaned:
            return None
        if not PROFILE_PHONE_RE.match(cleaned):
            raise HTTPException(
                status_code=400,
                detail="Enter a valid phone number (10 to 15 digits).",
            )
        return cleaned

def get_tenant_service(session: AsyncSession = Depends(get_session)) -> TenantService:
    """
    Factory for creating a TenantService instance with its dependencies.
    """
    tenant_repo = TenantRepository(session)
    return TenantService(tenant_repo)
