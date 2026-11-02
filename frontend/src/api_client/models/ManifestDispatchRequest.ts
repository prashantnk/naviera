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
 */
export type ManifestDispatchRequest = {
    picked_shipment_ids?: (Array<string> | null);
    measurements?: (Array<ManifestDispatchMeasurement> | null);
};

