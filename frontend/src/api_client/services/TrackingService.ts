/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PublicTrackingRead } from '../models/PublicTrackingRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class TrackingService {
    /**
     * Track Shipment
     * Public Tracking Page.
     * - **Public**: No authentication required.
     * - **Data**: Returns sanitized status and public timeline events only.
     * @param identifier
     * @param xTenantSlug
     * @returns PublicTrackingRead Successful Response
     * @throws ApiError
     */
    public static trackShipment(
        identifier: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PublicTrackingRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/tracking/{identifier}',
            path: {
                'identifier': identifier,
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
     * Track Shipment
     * Public Tracking Page.
     * - **Public**: No authentication required.
     * - **Data**: Returns sanitized status and public timeline events only.
     * @param identifier
     * @param xTenantSlug
     * @returns PublicTrackingRead Successful Response
     * @throws ApiError
     */
    public static trackShipment1(
        identifier: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PublicTrackingRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/tracking/{identifier}',
            path: {
                'identifier': identifier,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
