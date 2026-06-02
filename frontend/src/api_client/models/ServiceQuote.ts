/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { RateCalculationResponse } from './RateCalculationResponse';
import type { ServiceType } from './ServiceType';
export type ServiceQuote = {
    service_type: ServiceType;
    is_rto?: boolean;
    serviceable: boolean;
    quote?: (RateCalculationResponse | null);
    error_message?: (string | null);
};

