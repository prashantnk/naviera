/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PrimeImportIssue } from './PrimeImportIssue';
/**
 * What a lanes CSV import did (or would do, on a dry run).
 */
export type PrimeImportReport = {
    created?: number;
    updated?: number;
    deactivated?: number;
    errors?: Array<PrimeImportIssue>;
    warnings?: Array<PrimeImportIssue>;
};

