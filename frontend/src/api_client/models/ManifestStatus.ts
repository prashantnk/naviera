/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Pickup Request (PUR) / Truck Dispatch Lifecycle ('manifests' table):
 * - SCHEDULED: Warehouse booked a pickup slot (e.g., 4:00 PM - 6:00 PM) and linked OPEN shipments.
 * - OUT_FOR_PICKUP: Logismart hub assigned a vehicle/driver and dispatched it to the warehouse dock.
 * - PICKED: Driver physically loaded the cartons at the dock and signed the Run-Sheet PDF.
 * - CANCELED: Booking cancelled; linked shipments automatically detach ('manifest_id = None') and revert to 'OPEN'.
 * - NOT_PICKED: Pickup attempt failed (reason in 'failure_reason'); linked shipments detach and revert to 'OPEN'.
 */
export enum ManifestStatus {
    SCHEDULED = 'SCHEDULED',
    OUT_FOR_PICKUP = 'OUT_FOR_PICKUP',
    PICKED = 'PICKED',
    CANCELED = 'CANCELED',
    NOT_PICKED = 'NOT_PICKED',
}
