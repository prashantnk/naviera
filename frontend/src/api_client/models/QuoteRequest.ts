/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { FreightPaymentMode } from './FreightPaymentMode';
import type { PackageCreate } from './PackageCreate';
import type { ServiceFlow } from './ServiceFlow';
import type { ShipmentType } from './ShipmentType';
/**
 * The exact booking inputs that change the price (A-03: quote == booking inputs).
 */
export type QuoteRequest = {
    service_flow: ServiceFlow;
    shipment_type?: ShipmentType;
    pickup_pincode: string;
    delivery_pincode: string;
    packages?: Array<PackageCreate>;
    is_blind_pickup?: boolean;
    estimated_box_count?: (number | null);
    freight_payment_mode?: FreightPaymentMode;
    is_cod?: boolean;
    cod_amount?: number;
    add_shipping_to_cod?: boolean;
    shipment_value?: number;
    shipment_tax_value?: number;
    door_delivery?: boolean;
    is_carriers_risk?: boolean;
};

