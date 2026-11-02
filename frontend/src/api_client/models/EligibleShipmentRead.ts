/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Light row for the Create Pickup Request shipment picker (OPEN shipments of one location).
 */
export type EligibleShipmentRead = {
    id: string;
    tracking_id?: (string | null);
    order_reference_id?: (string | null);
    delivery_city: string;
    delivery_pincode: string;
    package_count: number;
    total_weight_kg: number;
    created_at: string;
};

