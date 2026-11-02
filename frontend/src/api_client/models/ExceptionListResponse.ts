/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ExceptionRow } from './ExceptionRow';
/**
 * Paginated exception rows.
 */
export type ExceptionListResponse = {
    items: Array<ExceptionRow>;
    total: number;
    page: number;
    size: number;
    pages: number;
};

