/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { WalletTransactionRead_Output } from './WalletTransactionRead_Output';
export type CodSettlementResponse = {
    settled_count: number;
    settled_amount: number;
    new_balance: number;
    transactions?: Array<WalletTransactionRead_Output>;
};

