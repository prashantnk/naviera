/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { NdrAction } from './NdrAction';
/**
 * Bulk action on up to 200 shipments (REATTEMPT / RETURN_TO_ORIGIN / RESCHEDULE_PICKUP / CANCEL_PICKUP).
 */
export type BulkNdrActionRequest = {
    action: NdrAction;
    shipment_ids: Array<string>;
};

