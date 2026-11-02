/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PickupStatus } from './PickupStatus';
/**
 * Light shipment item attached to a Pickup Request response for the AWB handover checklist.
 */
export type ManifestShipmentItem = {
    id: string;
    tracking_id?: (string | null);
    order_reference_id: string;
    package_count?: number;
    status: PickupStatus;
};

