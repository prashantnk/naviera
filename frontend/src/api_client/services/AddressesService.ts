/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressCreate } from '../models/AddressCreate';
import type { AddressRead } from '../models/AddressRead';
import type { AddressType } from '../models/AddressType';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class AddressesService {
    /**
     * List Saved Addresses
     * Fetch all SAVED addresses for the current user in this tenant.
     * @param addressType Filter by WAREHOUSE or CUSTOMER
     * @param xTenantSlug
     * @returns AddressRead Successful Response
     * @throws ApiError
     */
    public static listSavedAddresses(
        addressType?: (AddressType | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<AddressRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/addresses',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'address_type': addressType,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Saved Address
     * Add a new address to the user's Address Book.
     * @param requestBody
     * @param xTenantSlug
     * @returns AddressRead Successful Response
     * @throws ApiError
     */
    public static createSavedAddress(
        requestBody: AddressCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<AddressRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/addresses',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
