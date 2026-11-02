/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { GstPartyRead } from './GstPartyRead';
import type { GstTaxRowRead } from './GstTaxRowRead';
export type BillingInvoiceRead = {
    id: string;
    tenant_id: string;
    merchant_user_id: string;
    /**
     * Merchant (customer) email, filled for tenant-wide staff views.
     */
    merchant_email?: (string | null);
    invoice_number: string;
    note_type?: string;
    service_type?: string;
    invoice_date: string;
    due_date: string;
    status?: string;
    gst_number: string;
    billing_address: string;
    freight_amount?: number;
    cgst_amount?: number;
    sgst_amount?: number;
    igst_amount?: number;
    total_amount?: number;
    line_items?: Array<any>;
    created_at: string;
    /**
     * "Tax Invoice" / "Credit Note" / "Debit Note".
     */
    readonly document_title: string;
    /**
     * True for a credit / debit note (no due date; quotes `original_invoice_number`).
     */
    readonly is_note: boolean;
    /**
     * CGST + SGST or IGST rows at the configured rate, e.g. "CGST @ 9%" (C-12).
     */
    readonly tax_rows: Array<GstTaxRowRead>;
    /**
     * "Haryana (06)" from the stored place-of-supply state code (C-02).
     */
    readonly place_of_supply_label: (string | null);
    /**
     * Recipient frozen at issue: name, address, approved GSTIN (C-01).
     */
    readonly bill_to: (GstPartyRead | null);
    /**
     * Supplier legal name frozen at issue (None on documents issued before C-04).
     */
    readonly supplier_name: (string | null);
    /**
     * The invoice a credit / debit note corrects (CGST Rule 53).
     */
    readonly original_invoice_number: (string | null);
    /**
     * ISO date of the invoice a credit / debit note corrects.
     */
    readonly original_invoice_date: (string | null);
    /**
     * AWB the document was issued for, if any.
     */
    readonly tracking_id: (string | null);
};

