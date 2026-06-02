/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressCategory } from './AddressCategory';
import type { AddressScope } from './AddressScope';
export type AddressCreate = {
    name: string;
    phone: string;
    alternate_phone?: (string | null);
    email?: (string | null);
    company_name?: (string | null);
    gstin?: (string | null);
    address_line1: string;
    address_line2?: (string | null);
    landmark?: (string | null);
    city: string;
    state: string;
    pincode: string;
    country?: string;
    category?: AddressCategory;
    scope?: AddressScope;
    is_saved?: boolean;
};

