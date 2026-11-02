/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * The carrier service a shipment is booked on (carrier × mode × rate source, M-P1).
 * Stored as VARCHAR(40) + CHECK `ck_pickups_service_option_valid`; a new option is a
 * CHECK swap, never an enum DDL migration.
 * DELHIVERY_SURFACE / DELHIVERY_EXPRESS are B2C parcels priced live by Delhivery's
 * Express API; PRIME_SURFACE is B2B cargo priced from Logismart's Prime rate table;
 * DELHIVERY_B2B_SURFACE is B2B cargo (LTL) priced live by Delhivery's B2B freight
 * estimate API (M-P3 adds it to the CHECK).
 */
export enum ServiceOption {
    DELHIVERY_SURFACE = 'DELHIVERY_SURFACE',
    DELHIVERY_EXPRESS = 'DELHIVERY_EXPRESS',
    PRIME_SURFACE = 'PRIME_SURFACE',
    DELHIVERY_B2B_SURFACE = 'DELHIVERY_B2B_SURFACE',
}
