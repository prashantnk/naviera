/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * Which product flow a Pickup Request belongs to (Delhivery One 'Domestic' vs 'B2B Surface').
 * Stored as VARCHAR(8) so new flows never need an enum DDL migration.
 * Spring Boot Equivalent: '@Enumerated(EnumType.STRING) ServiceFlow serviceFlow'.
 */
export enum ServiceFlow {
    B2C = 'B2C',
    B2B = 'B2B',
}
