/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
export type RateCalculationResponse = {
    chargeable_weight: number;
    base_charge: number;
    service_surcharge: number;
    fuel_surcharge: number;
    network_surcharge: number;
    cod_fee: number;
    tax_amount: number;
    total_amount: number;
    currency?: string;
    estimated_days: number;
};

