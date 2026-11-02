/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { B2BStageSummary } from './B2BStageSummary';
import type { B2CStageSummary } from './B2CStageSummary';
import type { DashboardAppointments } from './DashboardAppointments';
import type { DashboardDailyPoint } from './DashboardDailyPoint';
import type { DashboardPerformance } from './DashboardPerformance';
import type { ServiceFlow } from './ServiceFlow';
export type DashboardSummaryResponse = {
    service_flow: ServiceFlow;
    days: number;
    generated_at: string;
    stages: (B2CStageSummary | B2BStageSummary);
    performance: DashboardPerformance;
    daily_series: Array<DashboardDailyPoint>;
    appointments?: (DashboardAppointments | null);
};

