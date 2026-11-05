/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ManifestShipmentItem } from './ManifestShipmentItem';
import type { ManifestStatus } from './ManifestStatus';
import type { ServiceFlow } from './ServiceFlow';
export type ManifestResponse = {
    id: string;
    tenant_id: string;
    pickup_address_id: string;
    scheduled_date: string;
    time_slot: string;
    is_blind_pickup: boolean;
    total_boxes: number;
    status: ManifestStatus;
    created_at: string;
    service_flow?: ServiceFlow;
    pickup_request_number?: (string | null);
    failure_reason?: (string | null);
    pickup_otp?: (string | null);
    pickup_otp_verified_at?: (string | null);
    pickup_otp_verified_by?: (string | null);
    pickup_otp_override_reason?: (string | null);
    pickup_location_name?: string;
    pickup_location_address?: string;
    expected_awbs?: number;
    picked_awbs?: number;
    shipments?: Array<ManifestShipmentItem>;
    notice?: (string | null);
};

