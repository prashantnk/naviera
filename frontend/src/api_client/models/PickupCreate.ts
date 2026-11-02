/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressCreate } from './AddressCreate';
import type { NdrExceptionReason } from './NdrExceptionReason';
import type { PackageCreate } from './PackageCreate';
import type { PaymentDetailsCreate } from './PaymentDetailsCreate';
import type { PickupDocumentCreate } from './PickupDocumentCreate';
import type { PickupStrategy } from './PickupStrategy';
import type { PickupTimeSlot } from './PickupTimeSlot';
import type { ProductCategory } from './ProductCategory';
import type { ServiceFlow } from './ServiceFlow';
import type { ServiceOption } from './ServiceOption';
import type { ServiceType } from './ServiceType';
import type { ShipmentType } from './ShipmentType';
/**
 * The Master Input for Creating a Shipment.
 */
export type PickupCreate = {
    order_reference_id?: (string | null);
    shipment_type?: ShipmentType;
    service_type?: ServiceType;
    requested_pickup_date: string;
    pickup_time_slot?: (PickupTimeSlot | null);
    po_number?: (string | null);
    po_date?: (string | null);
    po_expiry_date?: (string | null);
    appointment_id?: (string | null);
    appointment_start?: (string | null);
    appointment_end?: (string | null);
    pickup_strategy?: (PickupStrategy | null);
    product_category: ProductCategory;
    other_category_description?: (string | null);
    reason_for_return?: (string | null);
    qc_required?: boolean;
    qc_notes?: (string | null);
    pickup_qc_params?: (Record<string, any> | string | null);
    ndr_reason?: (NdrExceptionReason | null);
    pickup_address_id?: (string | null);
    new_pickup_address?: (AddressCreate | null);
    delivery_address_id?: (string | null);
    new_delivery_address?: (AddressCreate | null);
    packages?: Array<PackageCreate>;
    payment_details: PaymentDetailsCreate;
    is_blind_pickup?: boolean;
    estimated_box_count?: (number | null);
    is_carriers_risk?: boolean;
    documents?: Array<PickupDocumentCreate>;
    /**
     * B2C or B2B, taken from the booking route (A-02). Legacy clients without it are inferred from B2B fields.
     */
    service_flow?: (ServiceFlow | null);
    /**
     * The option card the seller picked; defaults from the flow and service_type.
     */
    service_option?: (ServiceOption | null);
    /**
     * The option's total_amount the seller saw; a different fresh price → 409 PRICE_CHANGED.
     */
    expected_total?: (number | null);
    /**
     * Logismart Prime add-on: deliver to the consignee's door.
     */
    door_delivery?: boolean;
};

