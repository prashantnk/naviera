/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { QuoteOption } from './QuoteOption';
/**
 * `POST /api/v1/quotes` answer.
 */
export type QuoteResponse = {
    shipment_total_value: number;
    eway_bill_required: boolean;
    eway_bill_threshold: number;
    cod_available: boolean;
    cod_unavailable_reason?: (string | null);
    heavy_weight_warning?: boolean;
    heavy_weight_threshold_kg: number;
    options: Array<QuoteOption>;
};

