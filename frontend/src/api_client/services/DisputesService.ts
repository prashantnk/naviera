/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { WeightDisputeClaimCreate } from '../models/WeightDisputeClaimCreate';
import type { WeightDisputeRead } from '../models/WeightDisputeRead';
import type { WeightDisputeResolveRequest } from '../models/WeightDisputeResolveRequest';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class DisputesService {
    /**
     * List Weight Mismatch Disputes
     * Lists WeightDispute rows for the current tenant.
     * @param search
     * @param claimStatus
     * @param xTenantSlug
     * @returns WeightDisputeRead Successful Response
     * @throws ApiError
     */
    public static listWeightMismatchDisputes(
        search?: (string | null),
        claimStatus?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<WeightDisputeRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/disputes/weight-mismatch',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'search': search,
                'claim_status': claimStatus,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Raise Weight Mismatch Claims
     * Raises a weight mismatch claim on one or more AWB tracking IDs.
     * @param requestBody
     * @param xTenantSlug
     * @returns WeightDisputeRead Successful Response
     * @throws ApiError
     */
    public static raiseWeightMismatchClaims(
        requestBody: WeightDisputeClaimCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<WeightDisputeRead>> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/disputes/weight-mismatch/claims',
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
     * Resolve Weight Mismatch Dispute
     * Accepts or rejects a weight mismatch claim (Admin only).
     * @param disputeId
     * @param requestBody
     * @param xTenantSlug
     * @returns WeightDisputeRead Successful Response
     * @throws ApiError
     */
    public static resolveWeightMismatchDispute(
        disputeId: string,
        requestBody: WeightDisputeResolveRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<WeightDisputeRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/disputes/weight-mismatch/{dispute_id}/resolve',
            path: {
                'dispute_id': disputeId,
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
     * Export Weight Mismatch Csv
     * Streams CSV of weight mismatch rows.
     * @param search
     * @param claimStatus
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static exportWeightMismatchCsv(
        search?: (string | null),
        claimStatus?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/disputes/weight-mismatch/export/csv',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'search': search,
                'claim_status': claimStatus,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
