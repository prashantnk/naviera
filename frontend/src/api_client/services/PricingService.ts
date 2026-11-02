/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PricingPolicy } from '../models/PricingPolicy';
import type { PricingPolicyRead } from '../models/PricingPolicyRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class PricingService {
    /**
     * Get Pricing Policy
     * The selling policy (tenant staff only; customers get 403).
     * @param xTenantSlug
     * @returns PricingPolicyRead Successful Response
     * @throws ApiError
     */
    public static getPricingPolicy(
        xTenantSlug?: (string | null),
    ): CancelablePromise<PricingPolicyRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/pricing/policy',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Replace Pricing Policy
     * Replaces the whole policy (Owner/Admin only); the previous settings are snapshotted.
     * @param requestBody
     * @param xTenantSlug
     * @returns PricingPolicyRead Successful Response
     * @throws ApiError
     */
    public static replacePricingPolicy(
        requestBody: PricingPolicy,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PricingPolicyRead> {
        return __request(OpenAPI, {
            method: 'PUT',
            url: '/api/v1/pricing/policy',
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
