import copy
import uuid
from typing import Awaitable, Callable, Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_session
from app.core.security import TokenPayload, decode_access_token
from app.core.ttl_cache import TTLCache
from app.models.tenants import Tenant, User

oauth2_scheme = HTTPBearer(scheme_name="JWT")

# --- Short-lived auth & tenant context cache ---
# Saves the Tenant + User round trips to the remote PgBouncer on every request of a
# page-load burst. Any committed Tenant / User write in this process evicts the entry
# (see `app/core/ttl_cache.py`), so a deactivated or demoted user loses access on the
# next request. Writes from another process are seen after at most the TTL.
AUTH_CACHE_TTL_SECONDS: float = 30.0
TENANT_CACHE_MAX_ENTRIES: int = 64
USER_CACHE_MAX_ENTRIES: int = 2048


def _clone_tenant(tenant: Tenant) -> Tenant:
    """A detached Tenant copy (never attached to a session, safe to mutate)."""
    return Tenant(
        id=tenant.id,
        slug=tenant.slug,
        name=tenant.name,
        settings=copy.deepcopy(tenant.settings or {}),
    )


def _clone_user(user: User) -> User:
    """A detached User copy carrying every column (no relationships)."""
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


_tenant_by_slug: TTLCache[str, Tenant] = TTLCache(
    "tenant_by_slug",
    ttl_seconds=AUTH_CACHE_TTL_SECONDS,
    max_entries=TENANT_CACHE_MAX_ENTRIES,
    clone=_clone_tenant,
    invalidated_by={Tenant: "id"},
    tenant_of=lambda _slug, tenant: tenant.id,
)
_tenant_by_id: TTLCache[uuid.UUID, Tenant] = TTLCache(
    "tenant_by_id",
    ttl_seconds=AUTH_CACHE_TTL_SECONDS,
    max_entries=TENANT_CACHE_MAX_ENTRIES,
    clone=_clone_tenant,
    invalidated_by={Tenant: "id"},
    tenant_of=lambda tenant_id, _tenant: tenant_id,
)
_user_by_tenant_sub: TTLCache[tuple, User] = TTLCache(
    "user_by_tenant_sub",
    ttl_seconds=AUTH_CACHE_TTL_SECONDS,
    max_entries=USER_CACHE_MAX_ENTRIES,
    clone=_clone_user,
    invalidated_by={User: "tenant_id"},
)


def get_cached_tenant_by_id(tenant_id: uuid.UUID) -> Optional[Tenant]:
    """A detached copy of a cached tenant, or None."""
    return _tenant_by_id.get(tenant_id)


def cache_tenant(tenant: Tenant) -> Tenant:
    """
    Stores a tenant the caller just read by id and returns it (a detached copy when
    caching is on). Prefer `load_tenant_by_id`: it cannot re-insert a row that a
    concurrent commit replaced while the caller was reading it.
    """
    return _tenant_by_id.set(tenant.id, tenant)


async def load_tenant_by_id(
    tenant_id: uuid.UUID, loader: Callable[[], Awaitable[Optional[Tenant]]]
) -> Optional[Tenant]:
    """Cached tenant by id (detached copy); `loader` reads the row on a miss."""
    return await _tenant_by_id.get_or_load(tenant_id, loader)


async def load_tenant_by_slug(
    slug: str, loader: Callable[[], Awaitable[Optional[Tenant]]]
) -> Optional[Tenant]:
    """Cached tenant by slug (detached copy). Unknown slugs are never cached."""
    return await _tenant_by_slug.get_or_load(slug, loader)


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

    async def _query() -> Optional[Tenant]:
        statement = select(Tenant).where(Tenant.slug == x_tenant_slug)
        return (await session.exec(statement)).first()

    tenant = await load_tenant_by_slug(x_tenant_slug, _query)
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
    supabase_user_id = str(token_data.sub)

    async def _query() -> Optional[User]:
        statement = select(User).where(
            User.supabase_user_id == supabase_user_id,
            User.tenant_id == current_tenant.id,
        )
        return (await session.exec(statement)).first()

    user = await _user_by_tenant_sub.get_or_load(
        (current_tenant.id, supabase_user_id), _query
    )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have access to this tenant.",
        )
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return user
