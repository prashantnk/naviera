/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PackageCreate } from './PackageCreate';
import type { ServiceType } from './ServiceType';
export type RateCalculationRequest = {
    pickup_pincode: string;
    delivery_pincode: string;
    packages: Array<PackageCreate>;
    service_type: ServiceType;
    is_cod?: boolean;
    shipment_total_value?: number;
};

