/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { QuoteRequest } from '../models/QuoteRequest';
import type { QuoteResponse } from '../models/QuoteResponse';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class QuotesService {
    /**
     * Get Quotes
     * Prices every option of the flow on the exact booking inputs (A-03).
     * Greyed-out options carry a plain-English `unavailable_reason`; nothing is booked.
     * @param requestBody
     * @param xTenantSlug
     * @returns QuoteResponse Successful Response
     * @throws ApiError
     */
    public static getQuotes(
        requestBody: QuoteRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<QuoteResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/quotes',
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
