/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Percentages are 0-100 rounded to 1 decimal; null when the denominator is zero or data is missing.
 */
export type DashboardPerformance = {
    /**
     * delivered / (delivered + rto) x 100
     */
    successful_delivery_rate?: (number | null);
    /**
     * delivered with no EXCEPTION before delivery / delivered x 100
     */
    first_attempt_delivery_rate?: (number | null);
    /**
     * Mean days from first IN_TRANSIT to first COMPLETED/EXCEPTION
     */
    avg_days_to_first_attempt?: (number | null);
    /**
     * Null: shipments carry no promised / estimated delivery date or TAT yet
     */
    on_time_delivery_rate?: (number | null);
};

