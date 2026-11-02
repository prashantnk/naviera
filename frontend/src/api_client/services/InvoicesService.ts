/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BillingInvoiceCreate } from '../models/BillingInvoiceCreate';
import type { BillingInvoiceRead } from '../models/BillingInvoiceRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class InvoicesService {
    /**
     * List Billing Invoices
     * Lists BillingInvoice rows for the current tenant.
     * @param noteType Filter by INVOICE, CREDIT_NOTE, or DEBIT_NOTE
     * @param search
     * @param xTenantSlug
     * @returns BillingInvoiceRead Successful Response
     * @throws ApiError
     */
    public static listBillingInvoices(
        noteType?: (string | null),
        search?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<BillingInvoiceRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/invoices',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'note_type': noteType,
                'search': search,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Billing Invoice
     * Issues a new GST Invoice, Credit Note, or Debit Note (Admin only).
     * @param requestBody
     * @param xTenantSlug
     * @returns BillingInvoiceRead Successful Response
     * @throws ApiError
     */
    public static createBillingInvoice(
        requestBody: BillingInvoiceCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<BillingInvoiceRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/invoices',
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
     * Download Billing Invoice Pdf
     * Generates a printable A4 GST Invoice PDF.
     * @param identifier
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadBillingInvoicePdf(
        identifier: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/invoices/{identifier}/pdf',
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
     * Download Billing Invoice Transactions Csv
     * Streams the transaction list CSV for a BillingInvoice.
     * @param identifier
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadBillingInvoiceTransactionsCsv(
        identifier: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/invoices/{identifier}/transactions-csv',
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
     * Get Billing Invoice Detail
     * Lookup a BillingInvoice by UUID or invoice_number.
     * @param identifier
     * @param xTenantSlug
     * @returns BillingInvoiceRead Successful Response
     * @throws ApiError
     */
    public static getBillingInvoiceDetail(
        identifier: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<BillingInvoiceRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/invoices/{identifier}',
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
