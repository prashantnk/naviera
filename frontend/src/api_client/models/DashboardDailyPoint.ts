/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Distinct shipments that moved into each state on that (UTC) day.
 */
export type DashboardDailyPoint = {
    date: string;
    in_transit: number;
    delivered: number;
    returned: number;
};

