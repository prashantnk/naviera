/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PaymentMode } from './PaymentMode';
export type PaymentDetailsRead = {
    amount?: number;
    currency?: string;
    payment_mode?: PaymentMode;
    declared_value?: number;
    tax_amount?: number;
    hsn_code?: (string | null);
    invoice_number?: (string | null);
    invoice_date?: (string | null);
    eway_bill_number?: (string | null);
    id: string;
};

