/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { NdrExceptionReason } from './NdrExceptionReason';
import type { PickupStatus } from './PickupStatus';
/**
 * One LR on the Manage Appointments table.
 */
export type AppointmentRow = {
    shipment_id: string;
    tracking_id?: (string | null);
    order_reference_id?: (string | null);
    box_count: number;
    consignee_name?: (string | null);
    consignee_company?: (string | null);
    consignee_city?: (string | null);
    consignee_pincode?: (string | null);
    po_number?: (string | null);
    po_expiry_date?: (string | null);
    po_missing: boolean;
    po_expired: boolean;
    status: PickupStatus;
    ndr_reason?: (NdrExceptionReason | null);
    delivery_by?: (string | null);
    appointment_start?: (string | null);
    appointment_end?: (string | null);
    appointment_id?: (string | null);
};

