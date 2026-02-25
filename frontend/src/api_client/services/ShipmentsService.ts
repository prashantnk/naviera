/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { PaginatedResponse_PickupRead_ } from '../models/PaginatedResponse_PickupRead_';
import type { PickupCreate } from '../models/PickupCreate';
import type { PickupRead } from '../models/PickupRead';
import type { PickupUpdate } from '../models/PickupUpdate';
import type { PublicTrackingRead } from '../models/PublicTrackingRead';
import type { ShipmentActivityRead } from '../models/ShipmentActivityRead';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class ShipmentsService {
    /**
     * Create Shipment
     * Create a new Shipment.
     *
     * - **Authentication**: Requires a valid JWT and X-Tenant-Slug header.
     * - **Validation**: Checks if "Saved Address IDs" belong to the current tenant.
     * - **Transaction**: Creates Addresses (if new), Packages, and Shipment in one go.
     * @param requestBody
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static createShipment(
        requestBody: PickupCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/',
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
    /**
     * Update Shipment
     * Update an existing Shipment.
     *
     * - **Permissions**: Only Admins/Owners can perform this action.
     * - **Features**:
     * - Updates fields (Status, Date, etc.)
     * - Syncs Packages (Add/Update/Remove)
     * - Syncs Documents
     * - **Auto-generates Audit Log** (ShipmentActivity)
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static updateShipment(
        shipmentId: string,
        requestBody: PickupUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/shipments/{shipment_id}',
            path: {
                'shipment_id': shipmentId,
            },
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
    /**
     * Get Shipment Details
     * Get full details of a specific shipment.
     * - **Admins**: Can view any shipment.
     * - **Customers**: Can only view their own.
     * @param shipmentId
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static getShipmentDetails(
        shipmentId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/{shipment_id}',
            path: {
                'shipment_id': shipmentId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Shipments
     * List Shipments (Paginated).
     * - **Admins**: View ALL shipments.
     * - **Customers**: View ONLY their created shipments.
     * @param page Page number
     * @param size Items per page
     * @param xTenantSlug
     * @returns PaginatedResponse_PickupRead_ Successful Response
     * @throws ApiError
     */
    public static listShipments(
        page: number = 1,
        size: number = 20,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PaginatedResponse_PickupRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'page': page,
                'size': size,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Shipment Timeline
     * Get Audit Timeline.
     * - **Restricted**: Only Admins/Owners can view this full technical history.
     * @param shipmentId
     * @param xTenantSlug
     * @returns ShipmentActivityRead Successful Response
     * @throws ApiError
     */
    public static getShipmentTimeline(
        shipmentId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<ShipmentActivityRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/{shipment_id}/timeline',
            path: {
                'shipment_id': shipmentId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Track Shipment
     * Public Tracking Page.
     * - **Public**: No authentication required.
     * - **Data**: Returns sanitized status and public timeline events only.
     * @param trackingId
     * @returns PublicTrackingRead Successful Response
     * @throws ApiError
     */
    public static trackShipment(
        trackingId: string,
    ): CancelablePromise<PublicTrackingRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/tracking/{tracking_id}',
            path: {
                'tracking_id': trackingId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
