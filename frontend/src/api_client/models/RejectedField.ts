/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { RejectionRule } from './RejectionRule';
/**
 * One field the server refused in a preview (shown next to that input in the dialog).
 */
export type RejectedField = {
    field?: (string | null);
    rule: RejectionRule;
    message: string;
};

