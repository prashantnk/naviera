/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ManifestResponse } from './ManifestResponse';
import type { ServiceFlow } from './ServiceFlow';
/**
 * Result of validating a multi-selection from the Shipments list ('Add to Pickup').
 * 'candidates' are SCHEDULED pickups (today or later) of the same flow and location.
 */
export type PickupCandidatesResponse = {
    service_flow: ServiceFlow;
    pickup_address_id: string;
    pickup_location_name: string;
    candidates: Array<ManifestResponse>;
};

