/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AddressRead } from './AddressRead';
import type { PackageRead } from './PackageRead';
import type { PaymentDetailsRead } from './PaymentDetailsRead';
import type { PickupDocumentRead } from './PickupDocumentRead';
import type { PickupStatus } from './PickupStatus';
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
    order_reference_id: string;
    shipment_type: ShipmentType;
    service_type: ServiceType;
    requested_pickup_date: string;
    pickup_address: AddressRead;
    delivery_address: AddressRead;
    packages: Array<PackageRead>;
    payment_details?: (PaymentDetailsRead | null);
    documents?: Array<PickupDocumentRead>;
    created_at: string;
};

