/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CodRemittanceStatus } from './CodRemittanceStatus';
import type { FreightPaymentMode } from './FreightPaymentMode';
export type PaymentDetailsRead_Output = {
    currency?: string;
    freight_payment_mode?: FreightPaymentMode;
    is_cod?: boolean;
    cod_amount?: number;
    add_shipping_to_cod?: boolean;
    base_freight?: number;
    tax_amount?: number;
    total_logistics_cost?: number;
    chargeable_weight?: number;
    pricing_breakdown?: Record<string, any>;
    shipment_value?: number;
    shipment_tax_value?: number;
    shipment_total_value?: number;
    hsn_code?: (string | null);
    invoice_numbers?: (Array<string> | null);
    invoice_date?: (string | null);
    eway_bill_numbers?: (Array<string> | null);
    id: string;
    cod_remittance_status: CodRemittanceStatus;
    /**
     * TO_PAY freight the rider still collects at the door (server-computed, read-only)
     */
    freight_collectible?: number;
    readonly invoice_number: (string | null);
    readonly eway_bill_number: (string | null);
};

