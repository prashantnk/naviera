/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressCreate } from './AddressCreate';
import type { PackageUpdate } from './PackageUpdate';
import type { PaymentDetailsCreate } from './PaymentDetailsCreate';
import type { PickupDocumentUpdate } from './PickupDocumentUpdate';
import type { PickupStatus } from './PickupStatus';
import type { PickupTimeSlot } from './PickupTimeSlot';
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
    product_category?: (string | null);
    shipment_description?: (string | null);
    reason_for_return?: (string | null);
    pickup_address_id?: (string | null);
    delivery_address_id?: (string | null);
    new_pickup_address?: (AddressCreate | null);
    new_delivery_address?: (AddressCreate | null);
    packages?: (Array<PackageUpdate> | null);
    documents?: (Array<PickupDocumentUpdate> | null);
    payment_details?: (PaymentDetailsCreate | null);
};

