/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ServiceFlow } from './ServiceFlow';
/**
 * Create a Pickup Request (PUR).
 *
 * - B2B (default, backward compatible): blind pickups allowed, 'total_boxes' honoured for blind.
 * - B2C: 'is_blind_pickup' must be False, at least one shipment is required and
 * 'total_boxes' is always computed on the server from the linked shipments.
 */
export type ManifestCreate = {
    pickup_address_id: string;
    scheduled_date: string;
    time_slot: string;
    service_flow?: ServiceFlow;
    is_blind_pickup?: boolean;
    total_boxes?: number;
    shipment_ids?: Array<string>;
};

