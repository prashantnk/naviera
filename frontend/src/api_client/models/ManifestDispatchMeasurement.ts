/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PackageCreate } from './PackageCreate';
/**
 * "Actual pieces" recorded by the rider for one picked LR at the doorstep (plan B5 / A-11).
 * Either explicit `packages` (from the full measurement dialog) or `actual_pieces` (one-tap
 * count) is provided. When `actual_pieces` is sent, the backend scales the declared package
 * lines (no re-bill when the count matches; blind LRs record the carton count and wait for
 * hub measurement).
 */
export type ManifestDispatchMeasurement = {
    shipment_id: string;
    packages?: (Array<PackageCreate> | null);
    actual_pieces?: (number | null);
    evidence_urls?: Array<string>;
    remark?: (string | null);
};

