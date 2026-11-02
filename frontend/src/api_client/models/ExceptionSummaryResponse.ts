/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ExceptionCategoryCount } from './ExceptionCategoryCount';
import type { ServiceFlow } from './ServiceFlow';
/**
 * Counts powering the category menu, tabs and dashboard / sidebar badges.
 */
export type ExceptionSummaryResponse = {
    service_flow: ServiceFlow;
    total: number;
    actionable: number;
    non_actionable: number;
    categories: Array<ExceptionCategoryCount>;
};

