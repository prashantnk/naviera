/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AppointmentRow } from './AppointmentRow';
import type { AppointmentTab } from './AppointmentTab';
import type { AppointmentTabCounts } from './AppointmentTabCounts';
/**
 * Paginated rows for the selected tab plus the three tab counts.
 */
export type AppointmentListResponse = {
    tab: AppointmentTab;
    items: Array<AppointmentRow>;
    total: number;
    page: number;
    size: number;
    counts: AppointmentTabCounts;
};

