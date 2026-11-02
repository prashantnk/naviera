/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { CodRemittancePreviewLine } from './CodRemittancePreviewLine';
/**
 * A-06 / A-05: what a bank payout to one merchant would cover right now.
 */
export type CodRemittancePreview = {
    merchant_user_id: string;
    merchant_email?: (string | null);
    wallet_balance: number;
    payout_blocked_reason?: (string | null);
    lines: Array<CodRemittancePreviewLine>;
    selected_count?: number;
    /**
     * Payout total of the ticked AWBs (all AWBs when none sent).
     */
    total: number;
};

