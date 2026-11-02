/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ChargeAdjustmentRead } from './ChargeAdjustmentRead';
import type { PickupRead } from './PickupRead';
/**
 * Response of `POST /shipments/{id}/measurements`: the re-priced shipment plus its adjustment row.
 */
export type MeasurementResult = {
    shipment: PickupRead;
    adjustment?: (ChargeAdjustmentRead | null);
};

