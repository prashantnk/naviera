/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Manual GST document. `freight_amount` is the taxable value; GST (CGST+SGST or
 * IGST by place of supply), totals, the supplier GSTIN / address and the
 * sequential document number are always computed server-side.
 */
export type BillingInvoiceCreate = {
    merchant_user_id?: (string | null);
    note_type?: string;
    service_type?: string;
    invoice_date?: (string | null);
    due_date?: (string | null);
    status?: string;
    freight_amount?: number;
    /**
     * Why this manual GST document is issued (recorded on the document line)
     */
    reason?: (string | null);
    /**
     * Original invoice number / AWB / agreement this document refers to (Rule 53)
     */
    original_reference?: (string | null);
};

