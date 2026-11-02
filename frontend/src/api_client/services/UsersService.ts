/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { B2BAccessRequestCreate } from '../models/B2BAccessRequestCreate';
import type { B2BAccessReviewRequest } from '../models/B2BAccessReviewRequest';
import type { PasswordAuthResponse } from '../models/PasswordAuthResponse';
import type { PasswordLoginRequest } from '../models/PasswordLoginRequest';
import type { PasswordSignupRequest } from '../models/PasswordSignupRequest';
import type { UserRead } from '../models/UserRead';
import type { UserSelfUpdate } from '../models/UserSelfUpdate';
import type { UserUpdate } from '../models/UserUpdate';
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
     * Signup With Email And Password
     * Creates or activates a user account with Email & Password in `auth.users`,
     * provisions their `public."user"` profile in the current tenant (bootstrapping
     * the first tenant user as OWNER), and returns a Supabase-compatible JWT session.
     * Rate-limited per IP (B-05).
     * @param requestBody
     * @param xTenantSlug
     * @returns PasswordAuthResponse Successful Response
     * @throws ApiError
     */
    public static signupWithEmailAndPassword(
        requestBody: PasswordSignupRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PasswordAuthResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/users/auth/signup',
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
     * Login With Email And Password
     * Authenticates a user with Email & Password against `auth.users` and returns
     * a Supabase-compatible JWT session + synced tenant profile. Rate-limited per
     * account and per IP (B-05).
     * @param requestBody
     * @param xTenantSlug
     * @returns PasswordAuthResponse Successful Response
     * @throws ApiError
     */
    public static loginWithEmailAndPassword(
        requestBody: PasswordLoginRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PasswordAuthResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/users/auth/login',
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
     * List Users In Tenant
     * List users for the current workspace:
     * - LogiSmart Platform Admins / Owners see all tenant users.
     * - B2B Merchant Owners / Admins see only their own Merchant Organization's sub-team.
     * - Individual B2C customers or non-admin roles receive 403 Forbidden.
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static listUsersInTenant(
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<UserRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/users',
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
     * Returns the currently authenticated user's profile (including their role,
     * account_type, merchant_org_id, and B2B access request status).
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
    /**
     * Update My Profile
     * Lets any signed-in user change their own display name and phone.
     * Declared before `PATCH /{user_id}` so `/me` is not parsed as a user id.
     * @param requestBody
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static updateMyProfile(
        requestBody: UserSelfUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/users/me',
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
     * Request B2B Access For Current User
     * Allows an authenticated customer to request B2B Cargo access,
     * optionally providing their Company Name, 15-digit GSTIN, or 10-digit PAN.
     * @param requestBody
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static requestB2BAccessForCurrentUser(
        requestBody: B2BAccessRequestCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/users/me/request-b2b',
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
     * Review User B2B Access Request
     * Allows a Tenant Admin / Owner to approve or reject a customer's B2B access request.
     * @param userId
     * @param requestBody
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static reviewUserB2BAccessRequest(
        userId: string,
        requestBody: B2BAccessReviewRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/users/{user_id}/review-b2b',
            path: {
                'user_id': userId,
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
    /**
     * Update User Role
     * Update a user's role or active status (Platform Admin or B2B Merchant Admin).
     * @param userId
     * @param requestBody
     * @param xTenantSlug
     * @returns UserRead Successful Response
     * @throws ApiError
     */
    public static updateUserRole(
        userId: string,
        requestBody: UserUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<UserRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/users/{user_id}',
            path: {
                'user_id': userId,
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
