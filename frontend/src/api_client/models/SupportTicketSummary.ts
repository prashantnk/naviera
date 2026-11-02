/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Home-dashboard Support card counters (Delhivery One parity).
 *
 * Customers read `resolved` + `need_your_input` (Logismart replied last on an
 * open ticket); staff read `open` + `awaiting_support` (the shipper replied last).
 */
export type SupportTicketSummary = {
    open?: number;
    resolved?: number;
    closed?: number;
    need_your_input?: number;
    awaiting_support?: number;
};

