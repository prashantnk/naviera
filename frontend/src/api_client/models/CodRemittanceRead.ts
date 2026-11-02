/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type CodRemittanceRead = {
    id: string;
    tenant_id: string;
    merchant_user_id: string;
    /**
     * Merchant (customer) email, filled for tenant-wide staff views.
     */
    merchant_email?: (string | null);
    remittance_number: string;
    processed_date: string;
    bank_utr: string;
    state?: string;
    total_remittance?: number;
    total_orders?: number;
    shipment_breakdown?: Array<any>;
    created_at: string;
};

