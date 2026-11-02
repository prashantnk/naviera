/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * One restorable settings version (the settings JSON itself is not sent).
 */
export type TenantSettingsHistoryRead = {
    id: string;
    version: number;
    created_at: string;
    changed_by_email?: (string | null);
    changed_sections?: Array<string>;
};

