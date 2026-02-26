/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * For Customers: A sanitized timeline event.
 * No 'diff', no 'user_id', no internal 'comment'.
 */
export type PublicActivityRead = {
    timestamp: string;
    status_title: string;
    message?: (string | null);
};

