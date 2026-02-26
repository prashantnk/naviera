/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { UserRead } from '../models/UserRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class UsersService {
    /**
     * Onboard New User
     * Onboarding endpoint for new and existing users.
     * Delegates the core "get or create" logic to the TenantService.
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static onboardNewUser(
        xTenantSlug?: (string | null),
    ): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/users/onboard',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Users In Tenant
     * List all users for the current authenticated user's tenant.
     * (This will be refactored to use the service layer fully next).
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static listUsersInTenant(
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<UserRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/users/',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get My Profile
     * Returns the currently authenticated user's profile (including their role).
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static getMyProfile(
        xTenantSlug?: (string | null),
    ): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/users/me',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
