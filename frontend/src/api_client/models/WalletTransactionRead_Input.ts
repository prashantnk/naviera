/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { WalletServiceCategory } from './WalletServiceCategory';
import type { WalletTxnStatus } from './WalletTxnStatus';
import type { WalletTxnType } from './WalletTxnType';
export type WalletTransactionRead_Input = {
    id: string;
    wallet_id: string;
    tenant_id: string;
    user_id: string;
    user_email?: (string | null);
    shipment_id?: (string | null);
    tracking_id?: (string | null);
    txn_type: WalletTxnType;
    service_category: WalletServiceCategory;
    opening_balance: number;
    amount: number;
    closing_balance: number;
    utr_number?: (string | null);
    receipt_number: string;
    status: WalletTxnStatus;
    remarks?: (string | null);
    created_at: string;
};

