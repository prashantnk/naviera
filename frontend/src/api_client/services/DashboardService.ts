/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { DashboardSummaryResponse } from '../models/DashboardSummaryResponse';
import type { ServiceFlow } from '../models/ServiceFlow';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class DashboardService {
    /**
     * Get Dashboard Summary
     * Home dashboard summary for shipments created in the last `days`
     * (tenant-wide for Admin/Owner, own shipments for customers).
     * @param serviceFlow B2C (Domestic) or B2B (Surface)
     * @param days Window in days: 7, 14 or 30
     * @param xTenantSlug
     * @returns DashboardSummaryResponse Successful Response
     * @throws ApiError
     */
    public static getDashboardSummary(
        serviceFlow: ServiceFlow,
        days: number = 30,
        xTenantSlug?: (string | null),
    ): CancelablePromise<DashboardSummaryResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/dashboard/summary',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'service_flow': serviceFlow,
                'days': days,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
