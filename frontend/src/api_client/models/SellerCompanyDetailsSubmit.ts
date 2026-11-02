/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * A seller's "Company details" printed as "Bill To" on their GST documents (audit C-01).
 * Submitted once from My profile; afterwards view-only, changes via a support ticket
 * (Delhivery One `profile`: company details cannot be edited).
 */
export type SellerCompanyDetailsSubmit = {
    legal_name: string;
    billing_address: string;
    /**
     * Optional 15-character GSTIN; checksum-verified and never the tenant's own GSTIN
     */
    gstin?: (string | null);
};

