/* generated using openapi-typescript-codegen -- do not edit */
/* istanbul ignore file */
/* tslint:disable */
/* eslint-disable */
import type { AdminOfflineCreditRequest } from '../models/AdminOfflineCreditRequest';
import type { CodSettlementResponse } from '../models/CodSettlementResponse';
import type { PaginatedResponse_WalletTransactionRead_ } from '../models/PaginatedResponse_WalletTransactionRead_';
import type { RechargeRejectRequest } from '../models/RechargeRejectRequest';
import type { UpiConfirmRequest } from '../models/UpiConfirmRequest';
import type { UpiIntentRequest } from '../models/UpiIntentRequest';
import type { UpiIntentResponse } from '../models/UpiIntentResponse';
import type { UpiRechargeStatusResponse } from '../models/UpiRechargeStatusResponse';
import type { VerifyUtrRequest } from '../models/VerifyUtrRequest';
import type { VerifyUtrResponse } from '../models/VerifyUtrResponse';
import type { WalletIntegrityAuditResponse } from '../models/WalletIntegrityAuditResponse';
import type { WalletOverviewResponse } from '../models/WalletOverviewResponse';
import type { WalletTransactionRead_Output } from '../models/WalletTransactionRead_Output';
import type { CancelablePromise } from '../core/CancelablePromise';
import { OpenAPI } from '../core/OpenAPI';
import { request as __request } from '../core/request';
export class WalletService {
    /**
     * Get Wallet Overview
     * Fetch the logged-in user's Unified Wallet balance (starts strictly at ₹0.00),
     * tenant's DB-configured wallet & pricing settings, and ledger summary.
     * @param xTenantSlug
     * @returns WalletOverviewResponse Successful Response
     * @throws ApiError
     */
    public static getWalletOverview(
        xTenantSlug?: (string | null),
    ): CancelablePromise<WalletOverviewResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/wallet',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Audit Wallet Integrity
     * Cross-checks wallet balances, completed ledger rows, prepaid GST invoices,
     * COD remittances, and active pickup manifests for zero-discrepancy integrity.
     * F-04: finance staff only (Owner / Admin / Read-only), run on demand; customers never
     * see internal audit codes.
     * @param xTenantSlug
     * @returns WalletIntegrityAuditResponse Successful Response
     * @throws ApiError
     */
    public static auditWalletIntegrity(
        xTenantSlug?: (string | null),
    ): CancelablePromise<WalletIntegrityAuditResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/wallet/audit-integrity',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Wallet Transactions
     * List paginated wallet transactions.
     *
     * Owner / Admin / Read-Only staff see every user's transactions in the tenant
     * (each row carries `user_email`); everyone else sees only their own.
     * @param tab Tab filter: 'spends' (Spends & Refunds), 'recharges', or 'all'
     * @param page
     * @param size
     * @param userId Owner / Admin / Read-Only only: narrow the tenant-wide ledger to one user. Ignored for other roles (they always see only their own wallet).
     * @param xTenantSlug
     * @returns PaginatedResponse_WalletTransactionRead_ Successful Response
     * @throws ApiError
     */
    public static listWalletTransactions(
        tab: string = 'all',
        page: number = 1,
        size: number = 20,
        userId?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<PaginatedResponse_WalletTransactionRead_> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/wallet/transactions',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'tab': tab,
                'page': page,
                'size': size,
                'user_id': userId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Create Upi Recharge Intent
     * Generates an NPCI UPI intent URI + Base64 SVG QR Code for zero-fee UPI recharge.
     * @param requestBody
     * @param xTenantSlug
     * @returns UpiIntentResponse Successful Response
     * @throws ApiError
     */
    public static createUpiRechargeIntent(
        requestBody: UpiIntentRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<UpiIntentResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/wallet/recharge/upi-intent',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Get Upi Recharge Status
     * Polls the status of a UPI QR recharge transaction (`PENDING` -> `COMPLETED`).
     * @param transactionId
     * @param autoComplete Optional parameter (status check only returns COMPLETED once verified)
     * @param xTenantSlug
     * @returns UpiRechargeStatusResponse Successful Response
     * @throws ApiError
     */
    public static getUpiRechargeStatus(
        transactionId: string,
        autoComplete?: (boolean | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<UpiRechargeStatusResponse> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/wallet/recharge/{transaction_id}/status',
            path: {
                'transaction_id': transactionId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'auto_complete': autoComplete,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Confirm Upi Recharge
     * Records 'I Have Paid' on a UPI QR recharge intent (with optional 12-digit UTR for reference).
     * Keeps the transaction in PENDING status awaiting Admin approval.
     * @param transactionId
     * @param xTenantSlug
     * @param requestBody
     * @returns UpiRechargeStatusResponse Successful Response
     * @throws ApiError
     */
    public static confirmUpiRecharge(
        transactionId: string,
        xTenantSlug?: (string | null),
        requestBody?: (UpiConfirmRequest | null),
    ): CancelablePromise<UpiRechargeStatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/wallet/recharge/{transaction_id}/confirm',
            path: {
                'transaction_id': transactionId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * List Tenant Pending Recharges
     * Admin-only endpoint returning all PENDING recharge requests across the tenant
     * where a user has clicked 'I Have Paid'.
     * @param xTenantSlug
     * @returns WalletTransactionRead_Output Successful Response
     * @throws ApiError
     */
    public static listTenantPendingRecharges(
        xTenantSlug?: (string | null),
    ): CancelablePromise<Array<WalletTransactionRead_Output>> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/wallet/admin/pending-recharges',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Approve Pending Recharge
     * Admin-only endpoint that approves a PENDING recharge request and merges
     * its amount into the user's main Unified Wallet balance.
     * @param transactionId
     * @param xTenantSlug
     * @returns UpiRechargeStatusResponse Successful Response
     * @throws ApiError
     */
    public static approvePendingRecharge(
        transactionId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<UpiRechargeStatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/wallet/recharge/{transaction_id}/approve',
            path: {
                'transaction_id': transactionId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Reject Pending Recharge
     * Admin-only endpoint that rejects a PENDING recharge request without crediting the wallet.
     * The optional reason is shown to the merchant in their passbook (A-15).
     * @param transactionId
     * @param xTenantSlug
     * @param requestBody
     * @returns UpiRechargeStatusResponse Successful Response
     * @throws ApiError
     */
    public static rejectPendingRecharge(
        transactionId: string,
        xTenantSlug?: (string | null),
        requestBody?: (RechargeRejectRequest | null),
    ): CancelablePromise<UpiRechargeStatusResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/wallet/recharge/{transaction_id}/reject',
            path: {
                'transaction_id': transactionId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Record Admin Offline Wallet Credit
     * Owner/Admin manual wallet credit when a customer pays offline (NEFT / IMPS / RTGS /
     * direct UPI / cheque / cash; #558 3b). Immediately creates a COMPLETED RECHARGE
     * ledger entry and an official Wallet Advance Receipt Voucher (`REC-...`).
     * @param requestBody
     * @param xTenantSlug
     * @returns VerifyUtrResponse Successful Response
     * @throws ApiError
     */
    public static recordAdminOfflineWalletCredit(
        requestBody: AdminOfflineCreditRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<VerifyUtrResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/wallet/admin/credit',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Verify Upi Utr Recharge
     * Admin "approve with UTR": verifies a 12-digit UPI UTR (with duplicate replay
     * protection) against a MERCHANT's pending recharge request and credits that
     * merchant's wallet. Never the caller's own wallet (B-06 maker-checker).
     *
     * Restricted to Tenant Admins / Owners.
     * @param requestBody
     * @param xTenantSlug
     * @returns VerifyUtrResponse Successful Response
     * @throws ApiError
     */
    public static verifyUpiUtrRecharge(
        requestBody: VerifyUtrRequest,
        xTenantSlug?: (string | null),
    ): CancelablePromise<VerifyUtrResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/wallet/recharge/verify-utr',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            body: requestBody,
            mediaType: 'application/json',
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Settle Cod Shipments To Wallet
     * Settles Delivered (COMPLETED), not-yet-remitted COD shipments into a Unified Wallet.
     * Owner / Admin only; customers are paid in the finance team's COD remittance cycle (403).
     * @param merchantUserId Owner / Admin only: settle this merchant's delivered COD into the merchant's wallet (default: the caller's own bookings).
     * @param xTenantSlug
     * @returns CodSettlementResponse Successful Response
     * @throws ApiError
     */
    public static settleCodShipmentsToWallet(
        merchantUserId?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<CodSettlementResponse> {
        return __request(OpenAPI, {
            method: 'POST',
            url: '/api/v1/wallet/settle-cod',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'merchant_user_id': merchantUserId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Download Wallet Transaction Receipt Pdf
     * Generates a printable A4 PDF Receipt / Credit Note / GST Freight Invoice (HSN/SAC 996812)
     * for a specific COMPLETED wallet transaction.
     * @param txnId
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static downloadWalletTransactionReceiptPdf(
        txnId: string,
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/wallet/transactions/{txn_id}/receipt-pdf',
            path: {
                'txn_id': txnId,
            },
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
    /**
     * Export Wallet Ledger Csv
     * Streams a CSV export of the wallet ledger (tenant-wide for Owner / Admin /
     * Read-Only staff, otherwise the caller's own wallet).
     * @param userId Owner / Admin / Read-Only only: export a single user's ledger.
     * @param xTenantSlug
     * @returns any Successful Response
     * @throws ApiError
     */
    public static exportWalletLedgerCsv(
        userId?: (string | null),
        xTenantSlug?: (string | null),
    ): CancelablePromise<any> {
        return __request(OpenAPI, {
            method: 'GET',
            url: '/api/v1/wallet/export/csv',
            headers: {
                'x-tenant-slug': xTenantSlug,
            },
            query: {
                'user_id': userId,
            },
            errors: {
                422: `Validation Error`,
            },
        });
    }
}
