/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type RateCalculationResponse = {
    chargeable_weight: number;
    base_charge: number;
    tax_amount: number;
    total_amount: number;
    currency?: string;
    estimated_days: number;
    pricing_breakdown?: Record<string, any>;
    serviceable?: boolean;
    error_message?: (string | null);
};

