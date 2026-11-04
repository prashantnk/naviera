import copy
import sys
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple, Union

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.security import TokenPayload, decode_access_token
from app.models.tenants import Tenant, User

oauth2_scheme = HTTPBearer(scheme_name="JWT")

# --- Short-Lived Auth & Tenant Context Cache ---
# Avoids redundant sequential SQL round-trips to remote PgBouncer on parallel
# frontend page-load bursts while guaranteeing 0ms staleness via explicit
# invalidation on every Tenant / User write in TenantService.
_AUTH_CACHE_TTL_SECONDS: float = 30.0
_AUTH_CACHE_MAX_SIZE: int = 512
_AUTH_CACHE_FORCE_ENABLED: bool = False
_auth_cache_lock = threading.Lock()
_tenant_by_slug_cache: Dict[str, Tuple[float, Tenant]] = {}
_tenant_by_id_cache: Dict[uuid.UUID, Tuple[float, Tenant]] = {}
_user_by_tenant_sub_cache: Dict[Tuple[uuid.UUID, str], Tuple[float, User]] = {}


def _is_auth_cache_enabled() -> bool:
    if _AUTH_CACHE_FORCE_ENABLED:
        return True
    return "pytest" not in sys.modules


def set_auth_cache_enabled_for_tests(enabled: bool) -> None:
    """Explicitly enables or disables the auth/tenant cache inside unit tests."""
    global _AUTH_CACHE_FORCE_ENABLED
    _AUTH_CACHE_FORCE_ENABLED = enabled
    if not enabled:
        clear_auth_cache()


def _clone_tenant(tenant: Tenant) -> Tenant:
    """Returns a detached Tenant instance safe to read across async sessions."""
    if not isinstance(tenant, Tenant):
        return tenant
    return Tenant(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        settings=copy.deepcopy(tenant.settings or {}),
    )


def _clone_user(user: Any) -> Any:
    """Returns a detached User instance safe to read across async sessions."""
    if not isinstance(user, User):
        return user
    return User(
        id=user.id,
        supabase_user_id=str(user.supabase_user_id),
        email=user.email,
        full_name=user.full_name,
        phone=user.phone,
        is_active=user.is_active,
        role=user.role,
        service_scope=user.service_scope,
        tenant_id=user.tenant_id,
        created_at=user.created_at,
    )


def get_cached_tenant_by_slug(slug: str) -> Optional[Tenant]:
    if not _is_auth_cache_enabled():
        return None
    now = time.monotonic()
    with _auth_cache_lock:
        entry = _tenant_by_slug_cache.get(slug)
        if entry is None:
            return None
        expires_at, cached = entry
        if now >= expires_at:
            _tenant_by_slug_cache.pop(slug, None)
            _tenant_by_id_cache.pop(cached.id, None)
            return None
        return _clone_tenant(cached)


def get_cached_tenant_by_id(tenant_id: uuid.UUID) -> Optional[Tenant]:
    if not _is_auth_cache_enabled():
        return None
    now = time.monotonic()
    with _auth_cache_lock:
        entry = _tenant_by_id_cache.get(tenant_id)
        if entry is None:
            return None
        expires_at, cached = entry
        if now >= expires_at:
            _tenant_by_id_cache.pop(tenant_id, None)
            _tenant_by_slug_cache.pop(cached.slug, None)
            return None
        return _clone_tenant(cached)


def cache_tenant(tenant: Tenant) -> Tenant:
    detached = _clone_tenant(tenant)
    if not _is_auth_cache_enabled():
        return detached
    expires_at = time.monotonic() + _AUTH_CACHE_TTL_SECONDS
    with _auth_cache_lock:
        if len(_tenant_by_slug_cache) >= _AUTH_CACHE_MAX_SIZE:
            _tenant_by_slug_cache.clear()
            _tenant_by_id_cache.clear()
        _tenant_by_slug_cache[detached.slug] = (expires_at, detached)
        _tenant_by_id_cache[detached.id] = (expires_at, detached)
    return _clone_tenant(detached)


def get_cached_user(
    tenant_id: uuid.UUID, supabase_user_id: Union[str, uuid.UUID]
) -> Optional[User]:
    if not _is_auth_cache_enabled():
        return None
    now = time.monotonic()
    key = (tenant_id, str(supabase_user_id))
    with _auth_cache_lock:
        entry = _user_by_tenant_sub_cache.get(key)
        if entry is None:
            return None
        expires_at, cached = entry
        if now >= expires_at:
            _user_by_tenant_sub_cache.pop(key, None)
            return None
        return _clone_user(cached)


def cache_user(user: Any) -> Any:
    if not isinstance(user, User):
        return user
    detached = _clone_user(user)
    if not _is_auth_cache_enabled():
        return detached
    expires_at = time.monotonic() + _AUTH_CACHE_TTL_SECONDS
    key = (detached.tenant_id, str(detached.supabase_user_id))
    with _auth_cache_lock:
        if len(_user_by_tenant_sub_cache) >= _AUTH_CACHE_MAX_SIZE:
            _user_by_tenant_sub_cache.clear()
        _user_by_tenant_sub_cache[key] = (expires_at, detached)
    return _clone_user(detached)


def invalidate_auth_cache(
    *,
    tenant_id: Optional[uuid.UUID] = None,
    slug: Optional[str] = None,
    supabase_user_id: Optional[Union[str, uuid.UUID]] = None,
) -> None:
    """
    Evicts cached Tenant and/or User entries immediately on any mutation.
    When called with no arguments, clears the entire auth/tenant cache.
    """
    sub_str = str(supabase_user_id) if supabase_user_id is not None else None
    with _auth_cache_lock:
        if tenant_id is None and slug is None and sub_str is None:
            _tenant_by_slug_cache.clear()
            _tenant_by_id_cache.clear()
            _user_by_tenant_sub_cache.clear()
            return

        if slug is not None:
            popped = _tenant_by_slug_cache.pop(slug, None)
            if popped is not None:
                _tenant_by_id_cache.pop(popped[1].id, None)

        if tenant_id is not None:
            popped_id = _tenant_by_id_cache.pop(tenant_id, None)
            if popped_id is not None:
                _tenant_by_slug_cache.pop(popped_id[1].slug, None)
            for s, (_, t_obj) in list(_tenant_by_slug_cache.items()):
                if t_obj.id == tenant_id:
                    _tenant_by_slug_cache.pop(s, None)

        if sub_str is not None and tenant_id is not None:
            _user_by_tenant_sub_cache.pop((tenant_id, sub_str), None)
        elif sub_str is not None:
            for k in list(_user_by_tenant_sub_cache.keys()):
                if k[1] == sub_str:
                    _user_by_tenant_sub_cache.pop(k, None)
        elif tenant_id is not None:
            for k in list(_user_by_tenant_sub_cache.keys()):
                if k[0] == tenant_id:
                    _user_by_tenant_sub_cache.pop(k, None)


def clear_auth_cache() -> None:
    """Alias for full auth & tenant cache reset."""
    invalidate_auth_cache()


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

    cached_tenant = get_cached_tenant_by_slug(x_tenant_slug)
    if cached_tenant is not None:
        return cached_tenant

    statement = select(Tenant).where(Tenant.slug == x_tenant_slug)
    result = await session.exec(statement)
    tenant = result.first()

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found.",
        )

    return cache_tenant(tenant)


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

    cached_user = get_cached_user(current_tenant.id, supabase_user_id)
    if cached_user is not None:
        if not cached_user.is_active:
            raise HTTPException(status_code=400, detail="Inactive user")
        return cached_user

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

    return cache_user(user)
