/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * B2B appointment management counters (null sub-metric = not derivable).
 */
export type DashboardAppointments = {
    /**
     * EXCEPTION/APPOINTMENT_NEEDED, or appointment ID present without a booked slot
     */
    needed?: (number | null);
    /**
     * Booked slot starting within the next 24h and not delivered
     */
    at_risk?: (number | null);
    /**
     * Upcoming booked slot on an active shipment
     */
    booked?: (number | null);
};

