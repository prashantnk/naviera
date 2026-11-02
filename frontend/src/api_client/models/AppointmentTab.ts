/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Delhivery tabs. Definitions match the B2B dashboard appointment counters
 * (`DashboardRepository.appointment_counts`):
 * - pending: on hold for APPOINTMENT_NEEDED, or has an appointment id but no slot yet.
 * - at_risk: an active shipment whose booked slot starts within the next 24 hours.
 * - booked: an active shipment with an upcoming booked slot.
 */
export enum AppointmentTab {
    PENDING = 'pending',
    AT_RISK = 'at_risk',
    BOOKED = 'booked',
}
