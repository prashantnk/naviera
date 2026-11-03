/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Owner/Admin manual wallet credit when a customer sends money offline
 * (NEFT / IMPS / RTGS / Direct UPI / Cash / Cheque; #558 3b).
 */
export type AdminOfflineCreditRequest = {
    /**
     * Target user UUID in the tenant (optional if user_email is provided).
     */
    user_id?: (string | null);
    /**
     * Target user email in the tenant (optional if user_id is provided).
     */
    user_email?: (string | null);
    /**
     * Offline credit amount in INR (minimum ₹1).
     */
    amount: number;
    /**
     * Bank UTR, NEFT/IMPS/RTGS reference, cheque number, or cash receipt reference.
     */
    utr_number: string;
    /**
     * Offline payment instrument (e.g. NEFT / IMPS / RTGS, Direct UPI, Cash / Cheque).
     */
    payment_method?: string;
    /**
     * Optional finance remark recorded in the passbook and receipt voucher.
     */
    notes?: (string | null);
};

