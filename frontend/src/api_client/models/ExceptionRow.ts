/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ExceptionCategory } from './ExceptionCategory';
import type { ExceptionConsignee } from './ExceptionConsignee';
import type { ExceptionPaymentMode } from './ExceptionPaymentMode';
import type { FreightPaymentMode } from './FreightPaymentMode';
import type { NdrAction } from './NdrAction';
import type { NdrExceptionReason } from './NdrExceptionReason';
import type { PickupStatus } from './PickupStatus';
import type { ServiceFlow } from './ServiceFlow';
import type { ShipmentType } from './ShipmentType';
/**
 * One on-hold shipment with everything the exceptions grid needs (server-computed).
 */
export type ExceptionRow = {
    shipment_id: string;
    tracking_id?: (string | null);
    order_reference_id?: (string | null);
    service_flow: ServiceFlow;
    shipment_type: ShipmentType;
    status: PickupStatus;
    ndr_reason?: (NdrExceptionReason | null);
    category?: (ExceptionCategory | null);
    is_actionable: boolean;
    /**
     * Merchant already responded (HOLD / DISPUTE_WEIGHT)
     */
    awaiting_ops?: boolean;
    allowed_actions?: Array<NdrAction>;
    attempts: number;
    max_attempts: number;
    last_remark?: (string | null);
    exception_raised_at?: (string | null);
    aging_days: number;
    consignee: ExceptionConsignee;
    origin_city: string;
    destination_city: string;
    payment_mode: ExceptionPaymentMode;
    freight_payment_mode?: (FreightPaymentMode | null);
    cod_amount?: number;
    charge_amount?: (number | null);
    /**
     * What the shipper's wallet is actually debited if they accept the charge, GST included (A-20). `charge_amount` is the ops-entered figure (GST-exclusive for additional / weight charges, GST-inclusive for freight collection).
     */
    charge_amount_payable?: (number | null);
    /**
     * True when staff may waive the RTO charge as 'Logismart liable' (DAMAGED / SHORT_SHIPMENT).
     */
    logismart_liable_allowed?: boolean;
    box_count: number;
    /**
     * Promised delivery date (booked appointment date)
     */
    pdd?: (string | null);
    appointment_start?: (string | null);
    appointment_end?: (string | null);
    created_at: string;
};

