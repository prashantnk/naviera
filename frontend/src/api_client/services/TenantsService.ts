/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { TenantRead } from '../models/TenantRead';
import type { UserRead } from '../models/UserRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class TenantsService {
    /**
     * List Tenants
     * List all tenants in the system.
     * @param xTenantSlug
     * @returns TenantRead Successful Response
     * @throws ApiError
     */
    public static listTenants(
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<TenantRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tenants/',
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
     * List all users for a specific tenant (administrative).
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
            url: '/api/v1/tenants/{tenant_id}/users/',
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
     * No authentication required.
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
}
