/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ServiceOption } from './ServiceOption';
/**
 * The ops view of the carrier booking, the shipment margin and the gap flag (staff only).
 */
export type CarrierBillingRead = {
    service_option: ServiceOption;
    carrier_awb?: (string | null);
    charged_weight_kg?: (number | null);
    charged_amount?: (number | null);
    has_gap?: boolean;
    gap_amount?: (number | null);
    gap_gross_amount?: (number | null);
    gap_message?: (string | null);
    seller_billed_amount?: (number | null);
    seller_billed_taxable?: (number | null);
    carrier_charged_taxable?: (number | null);
    margin_amount?: (number | null);
    transporter_name?: (string | null);
};

