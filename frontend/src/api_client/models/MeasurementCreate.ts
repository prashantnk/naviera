/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { MeasurementSource } from './MeasurementSource';
import type { PackageCreate } from './PackageCreate';
/**
 * Body of `POST /shipments/{id}/measurements` (staff: rider at pickup, hub, admin).
 *
 * Send exactly one of:
 * - `packages`: the full measured parcel (box count, L x B x H + unit, weight + unit), or
 * - `weight_kg`: a weight-only hub entry (the declared box sizes are kept and their
 * weights are scaled to this total by the re-pricing service).
 */
export type MeasurementCreate = {
    source?: MeasurementSource;
    packages?: (Array<PackageCreate> | null);
    weight_kg?: (number | null);
    evidence_urls?: Array<string>;
    remark?: (string | null);
};

