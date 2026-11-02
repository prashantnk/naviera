/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { WalletAuditDiscrepancy } from './WalletAuditDiscrepancy';
export type WalletIntegrityAuditResponse = {
    passed: boolean;
    checked_at: string;
    wallets_checked: number;
    transactions_checked: number;
    shipments_checked: number;
    invoices_checked: number;
    remittances_checked: number;
    discrepancy_count: number;
    discrepancies?: Array<WalletAuditDiscrepancy>;
    warnings?: Array<WalletAuditDiscrepancy>;
};

