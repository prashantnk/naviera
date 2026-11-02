/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { EligibleShipmentRead } from '../models/EligibleShipmentRead';
import type { ManifestCreate } from '../models/ManifestCreate';
import type { ManifestDispatchRequest } from '../models/ManifestDispatchRequest';
import type { ManifestNotPickedRequest } from '../models/ManifestNotPickedRequest';
import type { ManifestResponse } from '../models/ManifestResponse';
import type { ManifestShipmentsAdd } from '../models/ManifestShipmentsAdd';
import type { ManifestStatus } from '../models/ManifestStatus';
import type { PickupCandidatesResponse } from '../models/PickupCandidatesResponse';
import type { ServiceFlow } from '../models/ServiceFlow';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class ManifestsService {
    /**
     * Create Manifest
     * Create a Pickup Request (B2C or B2B) with a generated 9-digit Pickup ID.
     * Links the given OPEN shipment_ids (same flow + pickup location) and sets them ASSIGNED.
     * @param requestBody
     * @param xTenantSlug
     * @returns ManifestResponse Successful Response
     * @throws ApiError
     */
    public static createManifest(
        requestBody: ManifestCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ManifestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/manifests',
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
     * List Manifests
     * List Pickup Requests for the current tenant (filtered by customer ownership when role=customer).
     * @param serviceFlow Filter by B2C or B2B pickup requests
     * @param status Filter by pickup status
     * @param scheduledDate Filter by exact pickup date
     * @param xTenantSlug
     * @returns ManifestResponse Successful Response
     * @throws ApiError
     */
    public static listManifests(
        serviceFlow?: (ServiceFlow | null),
        status?: (ManifestStatus | null),
        scheduledDate?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<ManifestResponse>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/manifests',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'service_flow': serviceFlow,
                'status': status,
                'scheduled_date': scheduledDate,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Eligible Shipments
     * OPEN (Ready to Ship) shipments of one flow that ship from the selected pickup location.
     * Feeds the Create Pickup Request picker; the frontend must not filter on its own.
     * @param serviceFlow B2C or B2B
     * @param pickupAddressId Selected pickup location
     * @param xTenantSlug
     * @returns EligibleShipmentRead Successful Response
     * @throws ApiError
     */
    public static listEligibleShipments(
        serviceFlow: ServiceFlow,
        pickupAddressId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<EligibleShipmentRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/manifests/eligible-shipments',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'service_flow': serviceFlow,
                'pickup_address_id': pickupAddressId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Pickup Candidates
     * Validates a Shipments-list selection (one flow, one pickup location, all OPEN) and returns
     * SCHEDULED pickups from today onwards it can be added to (Delhivery "add to today's pickup").
     * @param shipmentIds Selected shipment ids (repeat the parameter)
     * @param xTenantSlug
     * @returns PickupCandidatesResponse Successful Response
     * @throws ApiError
     */
    public static getPickupCandidates(
        shipmentIds: Array<string>,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupCandidatesResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/manifests/pickup-candidates',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'shipment_ids': shipmentIds,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Add Shipments To Manifest
     * Add OPEN shipments to an existing SCHEDULED pickup (same flow + pickup location).
     * @param manifestId
     * @param requestBody
     * @param xTenantSlug
     * @returns ManifestResponse Successful Response
     * @throws ApiError
     */
    public static addShipmentsToManifest(
        manifestId: string,
        requestBody: ManifestShipmentsAdd,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ManifestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/manifests/{manifest_id}/shipments',
            path: {
                'manifest_id': manifestId,
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
     * Cancel Manifest
     * Cancel a SCHEDULED / OUT_FOR_PICKUP Manifest and release linked shipments back to OPEN status.
     * An optional `Idempotency-Key` header replays the first response (H-4); an un-keyed second
     * cancel is refused because the manifest is no longer cancellable.
     * @param manifestId
     * @param xTenantSlug
     * @returns ManifestResponse Successful Response
     * @throws ApiError
     */
    public static cancelManifest(
        manifestId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ManifestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/manifests/{manifest_id}/cancel',
            path: {
                'manifest_id': manifestId,
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
     * Mark Manifest Out For Pickup
     * Admin-only: SCHEDULED -> OUT_FOR_PICKUP (pickup executive is on the way).
     * @param manifestId
     * @param xTenantSlug
     * @returns ManifestResponse Successful Response
     * @throws ApiError
     */
    public static markManifestOutForPickup(
        manifestId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ManifestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/manifests/{manifest_id}/out-for-pickup',
            path: {
                'manifest_id': manifestId,
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
     * Mark Manifest Not Picked
     * Admin-only: SCHEDULED/OUT_FOR_PICKUP -> NOT_PICKED with a reason.
     * Linked shipments detach and revert ASSIGNED -> OPEN (Ready to Ship).
     * @param manifestId
     * @param requestBody
     * @param xTenantSlug
     * @returns ManifestResponse Successful Response
     * @throws ApiError
     */
    public static markManifestNotPicked(
        manifestId: string,
        requestBody: ManifestNotPickedRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ManifestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/manifests/{manifest_id}/not-picked',
            path: {
                'manifest_id': manifestId,
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
     * Dispatch Manifest
     * Mark a scheduled Manifest as Picked Up / Dispatched (COMPLETED),
     * transitioning picked shipments to IN_TRANSIT with a 6-digit delivery_otp and releasing unpicked shipments back to OPEN.
     *
     * Optional `measurements[]` carry the rider's "Actual pieces" per picked LR; each one is
     * recorded as a PICKUP measurement and the LR is re-priced on it (plan B5). Because that
     * moves money, an optional `Idempotency-Key` header replays the first response (H-4).
     * @param manifestId
     * @param xTenantSlug
     * @param requestBody
     * @returns ManifestResponse Successful Response
     * @throws ApiError
     */
    public static dispatchManifest(
        manifestId: string,
        xTenantSlug?: (string | null),
        requestBody?: (ManifestDispatchRequest | null),
    ): CancelablePromise<ManifestResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/manifests/{manifest_id}/dispatch',
            path: {
                'manifest_id': manifestId,
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
     * Download Manifest Labels
     * One merged PDF with the shipping labels of every shipment in the Pickup Request ("Print label").
     * @param manifestId
     * @param labelFormat a4 (standard labels / LR dockets) or thermal_4x2 (compact box labels)
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadManifestLabels(
        manifestId: string,
        labelFormat: string = 'a4',
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/manifests/{manifest_id}/labels',
            path: {
                'manifest_id': manifestId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'label_format': labelFormat,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Download Manifest Runsheet Pdf
     * Generates a printable A4 Driver Run-Sheet PDF ("Manifest Copy") for the specified Pickup Request.
     * @param manifestId
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadManifestRunsheetPdf(
        manifestId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/manifests/{manifest_id}/pdf',
            path: {
                'manifest_id': manifestId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
