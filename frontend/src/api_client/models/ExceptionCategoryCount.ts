/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ExceptionCategory } from './ExceptionCategory';
/**
 * Live count for one category / group tab.
 */
export type ExceptionCategoryCount = {
    category: ExceptionCategory;
    label: string;
    total: number;
    actionable: number;
};

