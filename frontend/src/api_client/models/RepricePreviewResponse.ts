/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { ChargeAdjustmentReason } from './ChargeAdjustmentReason';
import type { FreightPaymentMode } from './FreightPaymentMode';
import type { RejectedField } from './RejectedField';
import type { SettlementAction } from './SettlementAction';
/**
 * Result of `POST /shipments/{id}/reprice-preview`: what saving the change would do.
 * Nothing is written. Refusals come back as 200 with `rejected_fields` filled in.
 */
export type RepricePreviewResponse = {
    shipment_id: string;
    reason?: (ChargeAdjustmentReason | null);
    old_total: number;
    new_total: number;
    delta: number;
    old_chargeable_weight: number;
    new_chargeable_weight: number;
    new_pricing_breakdown?: Record<string, any>;
    freight_payment_mode?: (FreightPaymentMode | null);
    settlement_action?: SettlementAction;
    wallet_delta?: number;
    note_type?: (string | null);
    settlement_message?: string;
    old_cod_collectible?: number;
    new_cod_collectible?: number;
    old_freight_collectible?: number;
    new_freight_collectible?: number;
    collectible_frozen?: boolean;
    price_changed?: boolean;
    warnings?: Array<string>;
    rejected_fields?: Array<RejectedField>;
};

