/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PrimeImportReport } from '../models/PrimeImportReport';
import type { PrimeLanePatch } from '../models/PrimeLanePatch';
import type { PrimeLaneRead } from '../models/PrimeLaneRead';
import type { PrimeZoneRead } from '../models/PrimeZoneRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class PrimeRatesService {
    /**
     * List Prime Zones
     * Prime delivery zones with their pincode counts (staff only).
     * @param xTenantSlug
     * @returns PrimeZoneRead Successful Response
     * @throws ApiError
     */
    public static listPrimeZones(
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<PrimeZoneRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/pricing/prime-zones',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Prime Lanes
     * Prime lanes with zone names (staff only).
     * @param activeOnly Only the active lane of each route
     * @param xTenantSlug
     * @returns PrimeLaneRead Successful Response
     * @throws ApiError
     */
    public static listPrimeLanes(
        activeOnly: boolean = false,
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<PrimeLaneRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/pricing/prime-lanes',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'active_only': activeOnly,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Export Prime Lanes
     * All lanes as CSV, re-importable through `POST /prime-lanes/import` (staff only).
     * @param xTenantSlug
     * @returns any Lanes CSV in the import format
     * @throws ApiError
     */
    public static exportPrimeLanes(
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/pricing/prime-lanes/export.csv',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Download Prime Lanes Template
     * Sample CSV template with headers and 2 example rows for `POST /prime-lanes/import` (staff only).
     * @param xTenantSlug
     * @returns any Sample Prime lanes CSV template
     * @throws ApiError
     */
    public static downloadPrimeLanesTemplate(
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/pricing/prime-lanes/template.csv',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Prime Lane
     * Edits a lane's numbers and/or active flag (owner/admin).
     * @param laneId
     * @param requestBody
     * @param xTenantSlug
     * @returns PrimeLaneRead Successful Response
     * @throws ApiError
     */
    public static updatePrimeLane(
        laneId: string,
        requestBody: PrimeLanePatch,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PrimeLaneRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/pricing/prime-lanes/{lane_id}',
            path: {
                'lane_id': laneId,
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
     * Import Prime Lanes
     * Imports lanes from CSV (owner/admin); any error writes nothing.
     * @param requestBody
     * @param dryRun Report only; write nothing
     * @param xTenantSlug
     * @returns PrimeImportReport Successful Response
     * @throws ApiError
     */
    public static importPrimeLanes(
        requestBody: Blob,
        dryRun: boolean = true,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PrimeImportReport> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/pricing/prime-lanes/import',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'dry_run': dryRun,
            },
            body: requestBody,
            mediaType: 'text/csv',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
