/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { TenantRead } from '../models/TenantRead';
import type { TenantSettingsHistoryRead } from '../models/TenantSettingsHistoryRead';
import type { TenantUpdate } from '../models/TenantUpdate';
import type { UserRead } from '../models/UserRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class TenantsService {
    /**
     * List Tenants
     * The caller's own workspace (Admin/Owner only). Other tenants are never listed.
     * @param xTenantSlug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static listTenants(
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<TenantRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tenants',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Tenant Config
     * Public tenant branding/config for the X-Tenant-Slug header (no auth).
     * Only allow-listed settings keys are returned; admins load the full
     * settings from `GET /tenants/settings`.
     * @param xTenantSlug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static getTenantConfig(
        xTenantSlug?: (string | null),
    ): CancelablePromise<TenantRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tenants/config',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Current Tenant Settings
     * Full tenant settings for the Settings editor. Admin/Owner only (403 otherwise).
     * @param xTenantSlug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static getCurrentTenantSettings(
        xTenantSlug?: (string | null),
    ): CancelablePromise<TenantRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tenants/settings',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Current Tenant Settings
     * Additively updates current tenant settings via recursive deep-merge (resolved from X-Tenant-Slug header).
     * Preserves all existing tenant.settings keys that are not in the incoming payload.
     * Requires Admin or Owner privileges (returns 403 for Customers).
     * @param requestBody
     * @param xTenantSlug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static updateCurrentTenantSettings(
        requestBody: Record<string, any>,
        xTenantSlug?: (string | null),
    ): CancelablePromise<TenantRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/tenants/settings',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Settings History
     * Restorable settings versions (newest first, max 20). Admin/Owner only.
     * @param xTenantSlug
     * @returns TenantSettingsHistoryRead Successful Response
     * @throws ApiError
     */
    public static getSettingsHistory(
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<TenantSettingsHistoryRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tenants/settings/history',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Restore Settings Version
     * Restores the settings stored in history entry `version_id` (its `id`).
     * The current settings are snapshotted first, so the restore can be undone.
     * @param versionId
     * @param xTenantSlug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static restoreSettingsVersion(
        versionId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<TenantRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/tenants/settings/restore/{version_id}',
            path: {
                'version_id': versionId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Users For Tenant
     * List all users for a specific tenant (administrative: Admin/Owner only).
     * Enforces strict multi-tenant boundary so users cannot query another workspace.
     * @param tenantId
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static listUsersForTenant(
        tenantId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<UserRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tenants/{tenant_id}/users',
            path: {
                'tenant_id': tenantId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Public Tenant
     * Public endpoint to fetch tenant branding and landing page config.
     * No authentication required, so only allow-listed settings keys are returned.
     * @param slug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static getPublicTenant(
        slug: string,
    ): CancelablePromise<TenantRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tenants/{slug}/public',
            path: {
                'slug': slug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Tenant
     * Update tenant details (specifically the settings JSON).
     * Requires Admin privileges.
     * @param tenantId
     * @param requestBody
     * @param xTenantSlug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static updateTenant(
        tenantId: string,
        requestBody: TenantUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<TenantRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/tenants/{tenant_id}',
            path: {
                'tenant_id': tenantId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
