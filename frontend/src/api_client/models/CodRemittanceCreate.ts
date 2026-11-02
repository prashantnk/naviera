/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * One merchant's COD bank payout (A-06): finance first loads `GET /remittances/pending`,
 * ticks the AWBs the bank transfer actually paid and sends them with the total it saw.
 * The server recomputes the total and refuses a mismatch (409), so a UTR can never be
 * stamped on orders the transfer did not cover.
 */
export type CodRemittanceCreate = {
    merchant_user_id?: (string | null);
    remittance_number?: (string | null);
    processed_date?: (string | null);
    bank_utr: string;
    state?: string;
    shipment_ids?: (Array<string> | null);
    /**
     * The payout total shown in the preview for the ticked AWBs (required).
     */
    expected_total?: (number | null);
};

