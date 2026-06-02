/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { FreightPaymentMode } from './FreightPaymentMode';
export type PaymentDetailsCreate = {
    currency?: string;
    freight_payment_mode?: FreightPaymentMode;
    is_cod?: boolean;
    cod_amount?: number;
    add_shipping_to_cod?: boolean;
    base_freight?: number;
    tax_amount?: number;
    total_logistics_cost?: number;
    pricing_breakdown?: Record<string, any>;
    shipment_value?: number;
    shipment_tax_value?: number;
    shipment_total_value?: number;
    hsn_code?: (string | null);
    invoice_number?: (string | null);
    invoice_date?: (string | null);
    eway_bill_number?: (string | null);
};

