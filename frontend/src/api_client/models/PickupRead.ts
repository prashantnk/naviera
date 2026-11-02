/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressRead } from './AddressRead';
import type { NdrExceptionReason } from './NdrExceptionReason';
import type { PackageRead } from './PackageRead';
import type { PaymentDetailsRead_Output } from './PaymentDetailsRead_Output';
import type { PickupDocumentRead } from './PickupDocumentRead';
import type { PickupStatus } from './PickupStatus';
import type { PickupStrategy } from './PickupStrategy';
import type { PickupTimeSlot } from './PickupTimeSlot';
import type { ProductCategory } from './ProductCategory';
import type { ServiceOption } from './ServiceOption';
import type { ServiceType } from './ServiceType';
import type { ShipmentType } from './ShipmentType';
/**
 * Output schema.
 */
export type PickupRead = {
    id: string;
    tracking_id: (string | null);
    status: PickupStatus;
    latest_status_comment?: (string | null);
    order_reference_id?: (string | null);
    shipment_type: ShipmentType;
    service_type: ServiceType;
    requested_pickup_date: string;
    pickup_time_slot?: (PickupTimeSlot | null);
    po_number?: (string | null);
    po_date?: (string | null);
    po_expiry_date?: (string | null);
    appointment_id?: (string | null);
    appointment_start?: (string | null);
    appointment_end?: (string | null);
    pickup_strategy?: (PickupStrategy | null);
    is_blind_pickup: boolean;
    estimated_box_count?: (number | null);
    is_carriers_risk: boolean;
    delivered_box_count?: (number | null);
    product_category: ProductCategory;
    other_category_description?: (string | null);
    reason_for_return?: (string | null);
    qc_required: boolean;
    qc_notes?: (string | null);
    ndr_reason?: (NdrExceptionReason | null);
    ndr_attempt_count?: number;
    ndr_remark?: (string | null);
    exception_raised_at?: (string | null);
    charge_amount?: (number | null);
    delivery_otp?: (string | null);
    pod_received_by?: (string | null);
    created_by_user_id: string;
    creator_email?: (string | null);
    manifest_id?: (string | null);
    service_option?: ServiceOption;
    carrier_awb?: (string | null);
    transporter_name?: (string | null);
    pickup_address: AddressRead;
    delivery_address: AddressRead;
    packages: Array<PackageRead>;
    payment_details?: (PaymentDetailsRead_Output | null);
    documents?: Array<PickupDocumentRead>;
    created_at: string;
    /**
     * Who moves the parcel, for the detail page ("Delhivery" / "Logismart Prime").
     */
    readonly carrier_name: string;
    /**
     * Cash the rider collects at the door (COD + any freight still due), read-only.
     *
     * Computed only by `services.cod_payout.door_collectible` (frozen once Delivered), so the
     * ops card, the label and the detail pages never recompute it (WP2 / E-06). 0 = prepaid.
     */
    readonly door_collectible: number;
    /**
     * Statuses the server accepts next from the current one (E-11), straight from
     * `ShipmentLifecycleMachine`, so the status dialog never offers a move that 400s.
     */
    readonly allowed_next_statuses: Array<PickupStatus>;
    readonly total_box_count: number;
};

