/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { BulkActionFailure } from './BulkActionFailure';
/**
 * Partial-success result of a bulk action.
 */
export type BulkNdrActionResponse = {
    succeeded: Array<string>;
    failed: Array<BulkActionFailure>;
};

