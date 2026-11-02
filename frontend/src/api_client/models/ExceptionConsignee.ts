/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
/**
 * The customer-side party: consignee for forward, pickup customer for reverse.
 */
export type ExceptionConsignee = {
    name: string;
    phone: string;
    address_line1: string;
    address_line2?: (string | null);
    landmark?: (string | null);
    city: string;
    state: string;
    pincode: string;
};

