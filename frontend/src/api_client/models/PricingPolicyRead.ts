/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { OptionMarkup } from './OptionMarkup';
import type { ServiceOption } from './ServiceOption';
/**
 * `GET /api/v1/pricing/policy` (staff).
 */
export type PricingPolicyRead = {
    delhivery_markup_percent?: number;
    prime_default_markup_percent?: number;
    cod_fee_percent?: (number | null);
    cod_fee_min?: (number | null);
    enabled_options?: Array<ServiceOption>;
    option_markups?: Record<string, OptionMarkup>;
    cod_enabled?: boolean;
    delhivery_configured?: boolean;
    delhivery_b2b_configured?: boolean;
};

