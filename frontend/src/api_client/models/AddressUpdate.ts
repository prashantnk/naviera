/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressCategory } from './AddressCategory';
import type { AddressScope } from './AddressScope';
export type AddressUpdate = {
    name?: (string | null);
    phone?: (string | null);
    alternate_phone?: (string | null);
    gstin?: (string | null);
    email?: (string | null);
    company_name?: (string | null);
    address_line1?: (string | null);
    address_line2?: (string | null);
    landmark?: (string | null);
    city?: (string | null);
    state?: (string | null);
    pincode?: (string | null);
    country?: (string | null);
    category?: (AddressCategory | null);
    scope?: (AddressScope | null);
};

