/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressType } from './AddressType';
export type AddressCreate = {
    name: string;
    phone: string;
    email?: (string | null);
    company_name?: (string | null);
    address_line1: string;
    address_line2?: (string | null);
    landmark?: (string | null);
    city: string;
    state: string;
    pincode: string;
    country?: string;
    address_type?: AddressType;
    is_saved?: boolean;
};

