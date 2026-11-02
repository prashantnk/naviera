/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ChargeAdjustmentReason } from './ChargeAdjustmentReason';
import type { FreightPaymentMode } from './FreightPaymentMode';
/**
 * One row of the charges history (`shipment_charge_adjustments`).
 */
export type ChargeAdjustmentRead = {
    id: string;
    created_at: string;
    reason: ChargeAdjustmentReason;
    old_total: number;
    new_total: number;
    delta: number;
    old_chargeable_weight?: (number | null);
    new_chargeable_weight?: (number | null);
    freight_payment_mode: FreightPaymentMode;
    wallet_txn_id?: (string | null);
    billing_invoice_id?: (string | null);
    note_number?: (string | null);
    note_type?: (string | null);
    actor_email?: (string | null);
};

