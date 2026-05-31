/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressCreate } from './AddressCreate';
import type { PackageCreate } from './PackageCreate';
import type { PaymentDetailsCreate } from './PaymentDetailsCreate';
import type { PickupDocumentCreate } from './PickupDocumentCreate';
import type { PickupTimeSlot } from './PickupTimeSlot';
import type { ProductCategory } from './ProductCategory';
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
    pickup_time_slot: PickupTimeSlot;
    product_category: ProductCategory;
    other_category_description?: (string | null);
    reason_for_return?: (string | null);
    pickup_address_id?: (string | null);
    new_pickup_address?: (AddressCreate | null);
    delivery_address_id?: (string | null);
    new_delivery_address?: (AddressCreate | null);
    packages: Array<PackageCreate>;
    payment_details?: (PaymentDetailsCreate | null);
    documents?: Array<PickupDocumentCreate>;
};

