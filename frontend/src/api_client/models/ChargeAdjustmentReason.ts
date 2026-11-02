/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Why a shipment's bill changed. Mirrors the CHECK constraint of M-B1 exactly.
 * Spring equivalent: an `@Enumerated(EnumType.STRING)` column.
 */
export enum ChargeAdjustmentReason {
    CUSTOMER_EDIT = 'CUSTOMER_EDIT',
    ADMIN_EDIT = 'ADMIN_EDIT',
    PICKUP_MEASUREMENT = 'PICKUP_MEASUREMENT',
    HUB_MEASUREMENT = 'HUB_MEASUREMENT',
    MANUAL_WEIGHT_CHARGE = 'MANUAL_WEIGHT_CHARGE',
    CLAIM_ACCEPTED = 'CLAIM_ACCEPTED',
    PAYMENT_MODE_CHANGE = 'PAYMENT_MODE_CHANGE',
    COD_CHANGE = 'COD_CHANGE',
    SHORT_SHIPMENT = 'SHORT_SHIPMENT',
    FREIGHT_COLLECTION = 'FREIGHT_COLLECTION',
    EXCEPTION_CHARGE = 'EXCEPTION_CHARGE',
    RTO = 'RTO',
    COD_FEE_REVERSAL = 'COD_FEE_REVERSAL',
    CANCELLATION = 'CANCELLATION',
    PICKUP_REJECTION_REFUND = 'PICKUP_REJECTION_REFUND',
    LOST = 'LOST',
    LOST_FOUND = 'LOST_FOUND',
}
