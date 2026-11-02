/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * The merchant's response to an exception. Which actions are allowed for a
 * given shipment is decided server-side by the allowed-actions matrix.
 * Spring Boot Equivalent: an '@Enumerated(EnumType.STRING)' command type.
 */
export enum NdrAction {
    REATTEMPT = 'REATTEMPT',
    RETURN_TO_ORIGIN = 'RETURN_TO_ORIGIN',
    UPDATE_CONSIGNEE = 'UPDATE_CONSIGNEE',
    UPDATE_PAYMENT_MODE = 'UPDATE_PAYMENT_MODE',
    UPDATE_EWAY_BILL = 'UPDATE_EWAY_BILL',
    UPLOAD_DOCUMENT = 'UPLOAD_DOCUMENT',
    BOOK_APPOINTMENT = 'BOOK_APPOINTMENT',
    DELIVER_WITHOUT_APPOINTMENT = 'DELIVER_WITHOUT_APPOINTMENT',
    PARTIAL_DELIVERY = 'PARTIAL_DELIVERY',
    HOLD = 'HOLD',
    REPACK_AND_DELIVER = 'REPACK_AND_DELIVER',
    ACKNOWLEDGE_CHARGES = 'ACKNOWLEDGE_CHARGES',
    ACCEPT_WEIGHT = 'ACCEPT_WEIGHT',
    DISPUTE_WEIGHT = 'DISPUTE_WEIGHT',
    RESCHEDULE_PICKUP = 'RESCHEDULE_PICKUP',
    CANCEL_PICKUP = 'CANCEL_PICKUP',
}
