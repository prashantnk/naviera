# backend/app/api/v1/endpoints/tenants.py
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException

from app.core.dependencies import get_current_active_user, get_tenant_from_header
from app.models.tenants import Tenant, User, UserRole
from app.schemas.v1.tenants import (
    TenantRead,
    TenantSettingsHistoryRead,
    TenantUpdate,
    UserRead,
)
from app.services.tenants import TenantService, get_tenant_service

router = APIRouter()


@router.get("", response_model=List[TenantRead])
async def list_tenants(
    *,
    tenant_service: TenantService = Depends(get_tenant_service),
    user: User = Depends(get_current_active_user)
):
    """
    The caller's own workspace (Admin/Owner only). Other tenants are never listed.
    """
    return await tenant_service.list_tenants(user)


@router.get("/config", response_model=TenantRead)
async def get_tenant_config(
    *,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
):
    """
    Public tenant branding/config for the X-Tenant-Slug header (no auth).
    Only allow-listed settings keys are returned; admins load the full
    settings from `GET /tenants/settings`.
    """
    return tenant_service.to_public_tenant(current_tenant)


@router.get("/settings", response_model=TenantRead)
async def get_current_tenant_settings(
    *,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(get_current_active_user),
):
    """Full tenant settings for the Settings editor. Admin/Owner only (403 otherwise)."""
    return await tenant_service.get_admin_tenant_settings(
        current_tenant.id, current_user
    )


@router.patch("/settings", response_model=TenantRead)
async def update_current_tenant_settings(
    *,
    payload: Dict[str, Any] = Body(...),
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(get_current_active_user),
):
    """
    Additively updates current tenant settings via recursive deep-merge (resolved from X-Tenant-Slug header).
    Preserves all existing tenant.settings keys that are not in the incoming payload.
    Requires Admin or Owner privileges (returns 403 for Customers).
    """
    settings_payload: Dict[str, Any] = {}
    if "settings" in payload and isinstance(payload["settings"], dict):
        settings_payload.update(payload["settings"])
        for key, value in payload.items():
            if key != "settings":
                settings_payload[key] = value
    else:
        settings_payload = dict(payload)

    if not settings_payload:
        raise HTTPException(status_code=400, detail="Settings payload is required.")

    return await tenant_service.update_tenant_settings(
        tenant_id=current_tenant.id,
        user=current_user,
        settings_payload=settings_payload,
    )


@router.get("/settings/history", response_model=List[TenantSettingsHistoryRead])
async def get_settings_history(
    *,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(get_current_active_user),
):
    """Restorable settings versions (newest first, max 20). Admin/Owner only."""
    return await tenant_service.list_settings_history(current_tenant.id, current_user)


@router.post("/settings/restore/{version_id}", response_model=TenantRead)
async def restore_settings_version(
    *,
    version_id: uuid.UUID,
    current_tenant: Tenant = Depends(get_tenant_from_header),
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(get_current_active_user),
):
    """
    Restores the settings stored in history entry `version_id` (its `id`).
    The current settings are snapshotted first, so the restore can be undone.
    """
    return await tenant_service.restore_settings_version(
        current_tenant.id, version_id, current_user
    )


@router.get("/{tenant_id}/users", response_model=List[UserRead])
async def list_users_for_tenant(
    *,
    tenant_id: uuid.UUID,
    tenant_service: TenantService = Depends(get_tenant_service),
    user: User = Depends(get_current_active_user)
):
    """
    List all users for a specific tenant (administrative: Admin/Owner only).
    Enforces strict multi-tenant boundary so users cannot query another workspace.
    """
    if user.tenant_id != tenant_id:
        raise HTTPException(
            status_code=403,
            detail="You cannot view users for a different workspace.",
        )
    if user.role not in (UserRole.admin, UserRole.owner):
        raise HTTPException(
            status_code=403, detail="Only Admins or Owners can view the team list."
        )
    users = await tenant_service.list_users_for_tenant(tenant_id=tenant_id)
    return users


@router.get("/{slug}/public", response_model=TenantRead)
async def get_public_tenant(
    *, slug: str, tenant_service: TenantService = Depends(get_tenant_service)
):
    """
    Public endpoint to fetch tenant branding and landing page config.
    No authentication required, so only allow-listed settings keys are returned.
    """
    tenant = await tenant_service.get_public_tenant_by_slug(slug=slug)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.patch("/{tenant_id}", response_model=TenantRead)
async def update_tenant(
    *,
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    tenant_service: TenantService = Depends(get_tenant_service),
    current_user: User = Depends(get_current_active_user)
):
    """
    Update tenant details (specifically the settings JSON).
    Requires Admin privileges.
    """
    if payload.settings is None:
        raise HTTPException(status_code=400, detail="Settings payload is required.")

    updated_tenant = await tenant_service.update_tenant_settings(
        tenant_id=tenant_id, user=current_user, settings_payload=payload.settings
    )
    return updated_tenant
