/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CodRemittanceCreate } from '../models/CodRemittanceCreate';
import type { CodRemittancePreview } from '../models/CodRemittancePreview';
import type { CodRemittanceRead } from '../models/CodRemittanceRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class RemittancesService {
    /**
     * List Remittances
     * Lists COD Remittance rows for the current tenant.
     * @param search
     * @param processedDate
     * @param xTenantSlug
     * @returns CodRemittanceRead Successful Response
     * @throws ApiError
     */
    public static listRemittances(
        search?: (string | null),
        processedDate?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<CodRemittanceRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/remittances',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'search': search,
                'processed_date': processedDate,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Remittance
     * Creates a COD Remittance batch (Admin only).
     * @param requestBody
     * @param xTenantSlug
     * @returns CodRemittanceRead Successful Response
     * @throws ApiError
     */
    public static createRemittance(
        requestBody: CodRemittanceCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<CodRemittanceRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/remittances',
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
     * Preview Pending Remittance
     * A-06: the AWBs one merchant can be paid for now (server amounts) and the payout total
     * of the ticked `shipment_ids` (all when omitted), plus whether the payout is on hold
     * because their wallet is negative (A-05). Admin only.
     * @param merchantUserId
     * @param shipmentIds
     * @param xTenantSlug
     * @returns CodRemittancePreview Successful Response
     * @throws ApiError
     */
    public static previewPendingRemittance(
        merchantUserId: string,
        shipmentIds?: (Array<string> | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<CodRemittancePreview> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/remittances/pending',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'merchant_user_id': merchantUserId,
                'shipment_ids': shipmentIds,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Download Remittance Csv
     * Streams the AWB breakdown CSV for a COD Remittance.
     * @param identifier
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadRemittanceCsv(
        identifier: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/remittances/{identifier}/csv',
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
     * Get Remittance Detail
     * Lookup a COD Remittance by UUID or remittance_number.
     * @param identifier
     * @param xTenantSlug
     * @returns CodRemittanceRead Successful Response
     * @throws ApiError
     */
    public static getRemittanceDetail(
        identifier: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<CodRemittanceRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/remittances/{identifier}',
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
