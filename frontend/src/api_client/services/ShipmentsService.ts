/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminShipmentChargeCreate } from '../models/AdminShipmentChargeCreate';
import type { AppointmentUpdate } from '../models/AppointmentUpdate';
import type { CarrierBillingRead } from '../models/CarrierBillingRead';
import type { CarrierBillingUpdate } from '../models/CarrierBillingUpdate';
import type { ChargeAdjustmentRead } from '../models/ChargeAdjustmentRead';
import type { MeasurementCreate } from '../models/MeasurementCreate';
import type { MeasurementResult } from '../models/MeasurementResult';
import type { NdrExceptionResolveRequest } from '../models/NdrExceptionResolveRequest';
import type { PaginatedResponse_PickupRead_ } from '../models/PaginatedResponse_PickupRead_';
import type { PickupCreate } from '../models/PickupCreate';
import type { PickupRead } from '../models/PickupRead';
import type { PickupStatus } from '../models/PickupStatus';
import type { PickupUpdate } from '../models/PickupUpdate';
import type { RepricePreviewResponse } from '../models/RepricePreviewResponse';
import type { ShipmentActivityRead } from '../models/ShipmentActivityRead';
import type { ShipmentType } from '../models/ShipmentType';
import type { ValuationRequest } from '../models/ValuationRequest';
import type { ValuationResponse } from '../models/ValuationResponse';
import type { WeightAuditRequest } from '../models/WeightAuditRequest';
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
     * - **Idempotency**: the `Idempotency-Key` header is REQUIRED (A-17); a retry with the same key
     * replays the first response, so a slow network never books twice (H-4).
     * - **Pricing**: always re-priced on the server; `expected_total` ≠ fresh total → 409 PRICE_CHANGED.
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
            url: '/api/v1/shipments',
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
     * List Shipments
     * List Shipments (Paginated).
     * - **Admins**: View ALL shipments.
     * - **Customers**: View ONLY their created shipments.
     * @param page Page number
     * @param size Items per page
     * @param isB2B Optional filter for B2B vs B2C shipments
     * @param status Optional status filter (repeat the param for several statuses).
     * @param shipmentType Optional filter for FORWARD vs REVERSE shipments.
     * @param xTenantSlug
     * @returns PaginatedResponse_PickupRead_ Successful Response
     * @throws ApiError
     */
    public static listShipments(
        page: number = 1,
        size: number = 20,
        isB2B?: (boolean | null),
        status?: (Array<PickupStatus> | null),
        shipmentType?: (ShipmentType | null),
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
                'is_b2b': isB2B,
                'status': status,
                'shipment_type': shipmentType,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Update Shipment
     * Update an existing Shipment.
     *
     * - **Permissions**: staff edit within the hard blocks; a merchant edits their own
     * shipment per the Delhivery One matrix (B9, enforced by the service): COD amount +
     * consignee up to and including In Transit, only the consignee contact at Out for
     * delivery (H-12), declared boxes while Ready to ship, service type before pickup (H-8).
     * - **Features**:
     * - Updates fields (Status, Date, etc.)
     * - Syncs Packages (Add/Update/Remove)
     * - Syncs Documents
     * - Re-prices through RepricingService only when a price input changed
     * - **Auto-generates Audit Log** (ShipmentActivity)
     * - **Errors**: refused changes are 400/403 with a `detail` string.
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
     * Update Shipment
     * Update an existing Shipment.
     *
     * - **Permissions**: staff edit within the hard blocks; a merchant edits their own
     * shipment per the Delhivery One matrix (B9, enforced by the service): COD amount +
     * consignee up to and including In Transit, only the consignee contact at Out for
     * delivery (H-12), declared boxes while Ready to ship, service type before pickup (H-8).
     * - **Features**:
     * - Updates fields (Status, Date, etc.)
     * - Syncs Packages (Add/Update/Remove)
     * - Syncs Documents
     * - Re-prices through RepricingService only when a price input changed
     * - **Auto-generates Audit Log** (ShipmentActivity)
     * - **Errors**: refused changes are 400/403 with a `detail` string.
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static updateShipment1(
        shipmentId: string,
        requestBody: PickupUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'PUT',
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
     * Export Shipments Csv
     * Streams a CSV export of shipments for the current user / tenant.
     * @param isB2B Optional filter for B2B vs B2C shipments CSV export
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static exportShipmentsCsv(
        isB2B?: (boolean | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/export/csv',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'is_b2b': isB2B,
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
     * Download Shipping Label
     * Generates and downloads a PDF Shipping Label (Consolidated A4/4x6 or 4x2 Thermal).
     * @param shipmentId
     * @param labelFormat Label format (a4 or thermal_4x2)
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadShippingLabel(
        shipmentId: string,
        labelFormat: string = 'a4',
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/{shipment_id}/label',
            path: {
                'shipment_id': shipmentId,
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
     * Shipment Valuation
     * D-06: the declared goods total (value + tax) and whether it needs an e-way bill.
     * Read-only; the booking recomputes the same total server-side.
     * @param requestBody
     * @param xTenantSlug
     * @returns ValuationResponse Successful Response
     * @throws ApiError
     */
    public static shipmentValuation(
        requestBody: ValuationRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<ValuationResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/valuation',
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
     * Download Shipment Invoice Pdf
     * Generates a printable A4 GST Tax Invoice PDF (HSN/SAC 996812) for a shipment.
     * It prints the shipment's GST register row (same number and tax split as
     * Finances > Invoices); legacy shipments without one get it allocated now.
     * @param shipmentId
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadShipmentInvoicePdf(
        shipmentId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/{shipment_id}/invoice-pdf',
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
     * Audit Shipment Weight
     * Legacy hub "Audit Scale": a weight-only HUB measurement. Kept as a thin wrapper of
     * `POST /shipments/{id}/measurements` (the declared box sizes stay; the re-pricing
     * service settles any delta both ways with a DEBIT/CREDIT_NOTE).
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static auditShipmentWeight(
        shipmentId: string,
        requestBody: WeightAuditRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/{shipment_id}/audit-weight',
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
     * Record Shipment Measurement
     * Records the measured parcel (rider at pickup, hub, admin) and re-prices the shipment
     * on it (Delhivery One `weight-dispute`: the measured parcel is the billing basis).
     *
     * - **Permissions**: operations user / admin / owner, never read-only (service-enforced).
     * - **Body**: exactly one of `packages` (full measurement) or `weight_kg` (weight-only).
     * - **Idempotency**: optional `Idempotency-Key` header (H-4).
     * - **Errors**: 400 for a ₹0 quote (H-7) or a refused state, 422 for an invalid measurement.
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns MeasurementResult Successful Response
     * @throws ApiError
     */
    public static recordShipmentMeasurement(
        shipmentId: string,
        requestBody: MeasurementCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<MeasurementResult> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/{shipment_id}/measurements',
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
     * Preview Shipment Reprice
     * Dry run of `PATCH /shipments/{id}` with the same body (changed fields only): old vs
     * new price, chargeable weight, wallet effect and GST note type. Nothing is written.
     *
     * Refusals (H-7 ₹0 quote, H-8 service type after pickup, H-9 collectible after delivery,
     * H-12 / B9 merchant edit window) come back as 200 with `rejected_fields`, so the edit
     * dialog can show them next to the field.
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns RepricePreviewResponse Successful Response
     * @throws ApiError
     */
    public static previewShipmentReprice(
        shipmentId: string,
        requestBody: PickupUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<RepricePreviewResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/{shipment_id}/reprice-preview',
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
     * List Shipment Charges
     * Charges history of a shipment, oldest first: every re-price with its reason,
     * old → new total, wallet transaction and GST note (Delhivery One wallet ledger per AWB).
     * Merchants see only their own shipments (404 otherwise).
     * @param shipmentId
     * @param xTenantSlug
     * @returns ChargeAdjustmentRead Successful Response
     * @throws ApiError
     */
    public static listShipmentCharges(
        shipmentId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<ChargeAdjustmentRead>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/{shipment_id}/charges',
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
     * Cancel Shipment
     * Cancel an existing Shipment.
     *
     * - **Permissions**: Admins/Owners or the creator of the shipment.
     * - **Before pickup**: cancelled with a full prepaid refund + CREDIT_NOTE.
     * - **After pickup**: the service converts it to RTO (Delhivery One `cancel-forward-order`).
     * - **Idempotency**: optional `Idempotency-Key` header (H-4).
     * @param shipmentId
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static cancelShipment(
        shipmentId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/{shipment_id}/cancel',
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
     * Update Appointment
     * Update Appointment.
     * Validates shipment status is OPEN or IN_TRANSIT. Saves details and logs a ShipmentActivity.
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static updateAppointment(
        shipmentId: string,
        requestBody: AppointmentUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'PATCH',
            url: '/api/v1/shipments/{shipment_id}/appointment',
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
     * Resolve Shipment Exception
     * Legacy: resolve an active Delivery Exception / NDR on a Shipment.
     * Maps legacy actions (DELIVER_WITHOUT_APPOINTMENT, UPDATE_CONSIGNEE_DETAILS,
     * RETURN_TO_SENDER, HOLD_SHIPMENT) or any NdrAction value onto the
     * `POST /exceptions/{id}/actions` pipeline (same matrix validation and audit log).
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns PickupRead Successful Response
     * @throws ApiError
     */
    public static resolveShipmentException(
        shipmentId: string,
        requestBody: NdrExceptionResolveRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<PickupRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/{shipment_id}/resolve-exception',
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
     * Read Shipment Carrier Billing
     * Staff-only view of the carrier booking (service option, carrier AWB, charged weight/amount,
     * and invoice-gap verdict; DESIGN.md v4 D4 / Q13).
     * @param shipmentId
     * @param xTenantSlug
     * @returns CarrierBillingRead Successful Response
     * @throws ApiError
     */
    public static readShipmentCarrierBilling(
        shipmentId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<CarrierBillingRead> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/shipments/{shipment_id}/carrier-billing',
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
     * Save Shipment Carrier Billing
     * Records the carrier AWB, optional charged weight (`CARRIER` measurement), and charged amount
     * (Owner, Admin, and Operations staff only).
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns CarrierBillingRead Successful Response
     * @throws ApiError
     */
    public static saveShipmentCarrierBilling(
        shipmentId: string,
        requestBody: CarrierBillingUpdate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<CarrierBillingRead> {
        return __request(OpenAPI, {
            method: 'PUT',
            url: '/api/v1/shipments/{shipment_id}/carrier-billing',
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
     * Create Admin Shipment Charge
     * Applies a direct Owner/Admin price adjustment to a shipment (#558 3c):
     * debits the customer's wallet, updates `total_logistics_cost`, issues a GST Debit Note,
     * and returns the updated `CarrierBillingRead` view.
     * @param shipmentId
     * @param requestBody
     * @param xTenantSlug
     * @returns CarrierBillingRead Successful Response
     * @throws ApiError
     */
    public static createAdminShipmentCharge(
        shipmentId: string,
        requestBody: AdminShipmentChargeCreate,
        xTenantSlug?: (string | null),
    ): CancelablePromise<CarrierBillingRead> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/shipments/{shipment_id}/admin-charge',
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
}
