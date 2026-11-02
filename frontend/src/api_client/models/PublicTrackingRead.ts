/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PackageRead } from './PackageRead';
import type { PickupStatus } from './PickupStatus';
import type { PublicActivityRead } from './PublicActivityRead';
/**
 * The Public Tracking Page Data.
 * Minimal info to prove shipment exists and show status.
 */
export type PublicTrackingRead = {
    tracking_id: string;
    status: PickupStatus;
    current_location?: string;
    estimated_delivery?: (string | null);
    carrier_name?: (string | null);
    carrier_awb?: (string | null);
    delivery_otp?: (string | null);
    pod_received_by?: (string | null);
    timeline?: Array<PublicActivityRead>;
    package_details?: Array<PackageRead>;
};

