/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BulkNdrActionRequest } from '../models/BulkNdrActionRequest';
import type { BulkNdrActionResponse } from '../models/BulkNdrActionResponse';
import type { ExceptionCategory } from '../models/ExceptionCategory';
import type { ExceptionListResponse } from '../models/ExceptionListResponse';
import type { ExceptionRow } from '../models/ExceptionRow';
import type { ExceptionSummaryResponse } from '../models/ExceptionSummaryResponse';
import type { NdrActionRequest } from '../models/NdrActionRequest';
import type { ServiceFlow } from '../models/ServiceFlow';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class ExceptionsService {
    /**
     * Get Exceptions Summary
     * Live counts per group (B2C) / category (B2B), actionable vs non-actionable.
     * @param serviceFlow B2C (Domestic) or B2B (Cargo)
     * @param xTenantSlug
     * @returns ExceptionSummaryResponse Successful Response
     * @throws ApiError
     */
    public static getExceptionsSummary(
        serviceFlow: ServiceFlow,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ExceptionSummaryResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/exceptions/summary',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'service_flow': serviceFlow,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Exceptions
     * On-hold shipments with allowed actions, attempts, last remark and server-side aging.
     * @param serviceFlow B2C (Domestic) or B2B (Cargo)
     * @param category
     * @param actionableOnly
     * @param search AWB / LRN or Order ID
     * @param page
     * @param size
     * @param xTenantSlug
     * @returns ExceptionListResponse Successful Response
     * @throws ApiError
     */
    public static listExceptions(
        serviceFlow: ServiceFlow,
        category?: (ExceptionCategory | null),
        actionableOnly: boolean = false,
        search?: (string | null),
        page: number = 1,
        size: number = 20,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ExceptionListResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/exceptions',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'service_flow': serviceFlow,
                'category': category,
                'actionable_only': actionableOnly,
                'search': search,
                'page': page,
                'size': size,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Apply Bulk Exception Action
     * Bulk REATTEMPT / RETURN_TO_ORIGIN / RESCHEDULE_PICKUP / CANCEL_PICKUP (max 200, partial success).
     * @param requestBody
     * @param xTenantSlug
     * @returns BulkNdrActionResponse Successful Response
     * @throws ApiError
     */
    public static applyBulkExceptionAction(
        requestBody: BulkNdrActionRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<BulkNdrActionResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/exceptions/bulk-action',
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
     * Apply Exception Action
     * Apply one merchant action (validated against the allowed-actions matrix).
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns ExceptionRow Successful Response
     * @throws ApiError
     */
    public static applyExceptionAction(
        shipmentId: string,
        requestBody: NdrActionRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ExceptionRow> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/exceptions/{shipment_id}/actions',
            path: {
                'shipment_id': shipmentId,
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
