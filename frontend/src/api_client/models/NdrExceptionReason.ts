/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Why a shipment is on hold (Delhivery One "Exceptions & NDR" parity).
 * CUSTOMER_UNAVAILABLE is the legacy label of CONSIGNEE_UNAVAILABLE; both are
 * treated identically by the allowed-actions matrix (`services/ndr_rules.py`).
 */
export enum NdrExceptionReason {
    DOCUMENT_NEEDED = 'DOCUMENT_NEEDED',
    APPOINTMENT_NEEDED = 'APPOINTMENT_NEEDED',
    SHORT_SHIPMENT = 'SHORT_SHIPMENT',
    CUSTOMER_UNAVAILABLE = 'CUSTOMER_UNAVAILABLE',
    PAYMENT_DISPUTE = 'PAYMENT_DISPUTE',
    DAMAGED = 'DAMAGED',
    EWAY_BILL_MISSING = 'EWAY_BILL_MISSING',
    CONSIGNEE_DETAILS_REQUIRED = 'CONSIGNEE_DETAILS_REQUIRED',
    CONSIGNEE_REFUSED = 'CONSIGNEE_REFUSED',
    CONSIGNEE_UNAVAILABLE = 'CONSIGNEE_UNAVAILABLE',
    DELIVERY_RESCHEDULED = 'DELIVERY_RESCHEDULED',
    FREIGHT_COLLECTION = 'FREIGHT_COLLECTION',
    ADDITIONAL_CHARGES = 'ADDITIONAL_CHARGES',
    WEIGHT_DISCREPANCY = 'WEIGHT_DISCREPANCY',
    PICKUP_FAILED = 'PICKUP_FAILED',
}
