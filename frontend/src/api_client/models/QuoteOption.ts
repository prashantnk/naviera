/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { QuoteUnavailableCode } from './QuoteUnavailableCode';
import type { SellLine } from './SellLine';
import type { ServiceOption } from './ServiceOption';
/**
 * One option card.
 */
export type QuoteOption = {
    service_option: ServiceOption;
    serviceable: boolean;
    unavailable_code?: (QuoteUnavailableCode | null);
    unavailable_reason?: (string | null);
    total_amount?: number;
    freight_amount?: number;
    cod_fee?: number;
    tax_amount?: number;
    chargeable_weight_kg?: number;
    transit_days?: (number | null);
    expected_delivery_date?: (string | null);
    sell_lines?: Array<SellLine>;
    door_collectible_amount?: number;
    cod_remittance_amount?: number;
    priced_from_cache?: boolean;
    price_age_minutes?: (number | null);
};

