/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { WalletTransactionRead_Output } from './WalletTransactionRead_Output';
import type { WalletTxnStatus } from './WalletTxnStatus';
export type UpiRechargeStatusResponse = {
    transaction_id: string;
    status: WalletTxnStatus;
    balance: number;
    transaction: WalletTransactionRead_Output;
    auto_detected?: boolean;
};

