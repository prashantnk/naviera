/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { OptionMarkup } from './OptionMarkup';
import type { ServiceOption } from './ServiceOption';
/**
 * Logismart's selling policy (staff-only). Percentages are plain percents (20 = 20 %).
 * COD stays OFF until BOTH `cod_fee_percent` and `cod_fee_min` are set (fail closed).
 */
export type PricingPolicy = {
    delhivery_markup_percent?: number;
    prime_default_markup_percent?: number;
    cod_fee_percent?: (number | null);
    cod_fee_min?: (number | null);
    enabled_options?: Array<ServiceOption>;
    option_markups?: Record<string, OptionMarkup>;
};

