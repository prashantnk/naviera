/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressCreate } from './AddressCreate';
import type { NdrExceptionReason } from './NdrExceptionReason';
import type { PackageUpdate } from './PackageUpdate';
import type { PaymentDetailsCreate } from './PaymentDetailsCreate';
import type { PickupDocumentUpdate } from './PickupDocumentUpdate';
import type { PickupStatus } from './PickupStatus';
import type { PickupStrategy } from './PickupStrategy';
import type { PickupTimeSlot } from './PickupTimeSlot';
import type { ProductCategory } from './ProductCategory';
import type { ServiceOption } from './ServiceOption';
import type { ServiceType } from './ServiceType';
/**
 * The Master Payload for Editing a Shipment.
 * Supports both User corrections and Admin operations.
 * All fields are Optional -> "Patch" semantics.
 */
export type PickupUpdate = {
    status?: (PickupStatus | null);
    comment?: (string | null);
    is_public?: boolean;
    requested_pickup_date?: (string | null);
    order_reference_id?: (string | null);
    pickup_time_slot?: (PickupTimeSlot | null);
    service_type?: (ServiceType | null);
    service_option?: (ServiceOption | null);
    po_number?: (string | null);
    po_date?: (string | null);
    po_expiry_date?: (string | null);
    appointment_id?: (string | null);
    appointment_start?: (string | null);
    appointment_end?: (string | null);
    pickup_strategy?: (PickupStrategy | null);
    is_blind_pickup?: (boolean | null);
    estimated_box_count?: (number | null);
    is_carriers_risk?: (boolean | null);
    product_category?: (ProductCategory | null);
    other_category_description?: (string | null);
    reason_for_return?: (string | null);
    qc_required?: (boolean | null);
    qc_notes?: (string | null);
    ndr_reason?: (NdrExceptionReason | null);
    /**
     * Field-agent remark shown to the merchant
     */
    ndr_remark?: (string | null);
    /**
     * INR charge to acknowledge (FREIGHT_COLLECTION / ADDITIONAL_CHARGES / WEIGHT_DISCREPANCY)
     */
    charge_amount?: (number | null);
    /**
     * Hub-measured weight for WEIGHT_DISCREPANCY (re-billed if the merchant accepts)
     */
    measured_weight_kg?: (number | null);
    delivery_otp?: (string | null);
    pod_received_by?: (string | null);
    /**
     * COD collectible shown on the rider's screen when marking Delivered (A-10)
     */
    expected_cod_amount?: (number | null);
    pickup_address_id?: (string | null);
    delivery_address_id?: (string | null);
    new_pickup_address?: (AddressCreate | null);
    new_delivery_address?: (AddressCreate | null);
    packages?: (Array<PackageUpdate> | null);
    documents?: (Array<PickupDocumentUpdate> | null);
    payment_details?: (PaymentDetailsCreate | null);
};

