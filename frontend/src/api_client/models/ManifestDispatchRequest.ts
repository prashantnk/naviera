/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ManifestDispatchMeasurement } from './ManifestDispatchMeasurement';
/**
 * Optional body of 'POST /manifests/{id}/dispatch'.
 *
 * - `picked_shipment_ids`: partial pickup AWB checklist (omitted = every linked LR picked).
 * - `measurements`: optional actual pieces per picked LR (also optional for blind LRs).
 * - `pickup_otp`: 6-digit pickup handover OTP shared by the seller with the pickup executive.
 * - `pickup_otp_override_reason`: mandatory audit reason when an Owner/Admin overrides OTP verification.
 */
export type ManifestDispatchRequest = {
    picked_shipment_ids?: (Array<string> | null);
    measurements?: (Array<ManifestDispatchMeasurement> | null);
    pickup_otp?: (string | null);
    pickup_otp_override_reason?: (string | null);
};

