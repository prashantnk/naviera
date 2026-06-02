/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PackageCreate } from './PackageCreate';
import type { QuoteSpecification } from './QuoteSpecification';
import type { ShipmentType } from './ShipmentType';
export type BulkRateCalculationRequest = {
    pickup_pincode: string;
    delivery_pincode: string;
    packages: Array<PackageCreate>;
    is_cod?: boolean;
    cod_amount?: number;
    shipment_total_value?: number;
    shipment_type?: ShipmentType;
    quotes_to_calculate?: (Array<QuoteSpecification> | null);
};

