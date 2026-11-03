"use client";

import {
  WalletIntegrityAuditResponse,
  WalletService,
  WalletServiceCategory,
  type WalletTransactionRead_Output as WalletTransactionRead,
  WalletTxnDirection,
  WalletTxnStatus,
  WalletTxnType,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { useWallet } from "@/components/providers/wallet-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { WalletRechargeDialog } from "@/components/wallet/wallet-header-pill";
import { downloadWalletLedgerCsv, downloadWalletReceiptPdf } from "@/lib/api";
import {
  cn,
  extractApiErrorMessage,
  safeFormatDate,
} from "@/lib/utils";
import {
  ArrowDownLeft,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  Download,
  ExternalLink,
  FileText,
  IndianRupee,
  Loader2,
  Plus,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Users,
  Wallet,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

const ALL_USERS_FILTER = "ALL";
const LEDGER_PAGE_SIZE = 100;
/** Approvers match a recharge to the bank statement by time as well as UTR (IST). */
const SUBMITTED_AT_FORMAT = "dd MMM yyyy, hh:mm a";

interface LedgerUserOption {
  id: string;
  email: string;
}

/**
 * Distinct wallet owners present in the loaded ledger rows, sorted by email.
 *
 * @param rows - Ledger rows from both tabs.
 * @returns One option per user id.
 */
function _collectLedgerUsers(rows: WalletTransactionRead[]): LedgerUserOption[] {
  const byId = new Map<string, string>();
  rows.forEach((row) => {
    if (!byId.has(row.user_id)) {
      byId.set(row.user_id, row.user_email || row.user_id.slice(0, 8));
    }
  });
  return Array.from(byId.entries())
    .map(([id, email]) => ({ id, email }))
    .sort((a, b) => a.email.localeCompare(b.email));
}

/**
 * One KPI amount on the wallet summary cards. Renders the `data-testid` span only once the
 * backend value is known, and a muted placeholder while the overview is still loading.
 *
 * @param testId - `data-testid` of the amount (`wallet.summary.<field>`).
 * @param value - Backend amount in ₹, or undefined while loading.
 */
function SummaryAmount({ testId, value }: { testId: string; value: number | undefined }) {
  if (value === undefined) {
    return (
      <span className="text-slate-300" aria-busy="true">
        ₹—
      </span>
    );
  }
  return <span data-testid={testId}>₹{value.toFixed(2)}</span>;
}

export default function UnifiedWalletPage() {
  const { routeTo, tenantSlug } = useTenant();
  const { user, canAccessB2B, capabilities } = useUser();
  const canViewAllTxns = capabilities.canViewTenantFinance;
  const canManageFinance = capabilities.canManageFinance;
  /** Mirrors backend `assert_can_manage_finance_or_wallet`: customers and Owner/Admin only. */
  const canMoveMoney = capabilities.canRechargeWallet;
  /**
   * Coordinator #534 (DO1 `cod-remittance`): sellers are paid COD by the finance team's
   * remittance batches, never by self-settling; only Owner / Admin keep "Settle Cash to Wallet".
   */
  const canSettleCod = canManageFinance;
  /** Read-only staff have no wallet of their own: the own-balance cards are hidden. */
  const hasOwnWallet = capabilities.hasOwnWallet;
  const [ledgerUserFilter, setLedgerUserFilter] = useState<string>(ALL_USERS_FILTER);
  const [ledgerUsers, setLedgerUsers] = useState<LedgerUserOption[]>([]);
  /**
   * Maker-checker: an admin may approve or reject other users' recharges,
   * never their own (the request must be cleared by a different admin/owner).
   */
  const canReviewRecharge = (txn: WalletTransactionRead): boolean =>
    canManageFinance && txn.user_id !== user?.id;
  // Balance + summary come from the shared WalletProvider (same request as the header pill).
  const { wallet: overview } = useWallet();
  const [spendsTxns, setSpendsTxns] = useState<WalletTransactionRead[]>([]);
  const [rechargeTxns, setRechargeTxns] = useState<WalletTransactionRead[]>([]);
  const [spendsTotal, setSpendsTotal] = useState<number>(0);
  const [rechargesTotal, setRechargesTotal] = useState<number>(0);
  const [pendingApprovals, setPendingApprovals] = useState<
    WalletTransactionRead[]
  >([]);
  const [auditReport, setAuditReport] =
    useState<WalletIntegrityAuditResponse | null>(null);
  const [runningAudit, setRunningAudit] = useState<boolean>(false);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<string>("spends");
  const [rechargeOpen, setRechargeOpen] = useState<boolean>(false);
  const [settlingRemittance, setSettlingRemittance] = useState<boolean>(false);
  const [downloadingCsv, setDownloadingCsv] = useState<boolean>(false);
  const [downloadingTxnId, setDownloadingTxnId] = useState<string | null>(null);
  const [processingApprovalId, setProcessingApprovalId] = useState<
    string | null
  >(null);
  const [inlineUtrByTxnId, setInlineUtrByTxnId] = useState<
    Record<string, string>
  >({});
  /** Recharge awaiting the approver's explicit confirmation (money is credited on confirm). */
  const [approveTarget, setApproveTarget] = useState<WalletTransactionRead | null>(null);
  const [rejectReasonByTxnId, setRejectReasonByTxnId] = useState<
    Record<string, string>
  >({});
  /** Admin Offline Wallet Credit dialog (#558 3b / #568 4). */
  const [offlineCreditOpen, setOfflineCreditOpen] = useState<boolean>(false);
  const [offlineUserEmail, setOfflineUserEmail] = useState<string>("");
  const [offlineAmount, setOfflineAmount] = useState<string>("");
  const [offlineMethod, setOfflineMethod] = useState<string>("NEFT");
  const [offlineReference, setOfflineReference] = useState<string>("");
  const [offlineNotes, setOfflineNotes] = useState<string>("");
  const [submittingOfflineCredit, setSubmittingOfflineCredit] = useState<boolean>(false);

  const fetchWalletData = useCallback(async () => {
    if (!tenantSlug) return;
    setLoading(true);
    const userIdFilter =
      canViewAllTxns && ledgerUserFilter !== ALL_USERS_FILTER
        ? ledgerUserFilter
        : null;
    try {
      const [spendsRes, rechargesRes] = await Promise.all([
        WalletService.listWalletTransactions(
          "spends",
          1,
          LEDGER_PAGE_SIZE,
          userIdFilter,
          tenantSlug
        ),
        WalletService.listWalletTransactions(
          "recharges",
          1,
          LEDGER_PAGE_SIZE,
          userIdFilter,
          tenantSlug
        ),
      ]);
      const spendItems = spendsRes.items || [];
      const rechargeItems = rechargesRes.items || [];
      setSpendsTxns(spendItems);
      setRechargeTxns(rechargeItems);
      setSpendsTotal(spendsRes.total ?? spendItems.length);
      setRechargesTotal(rechargesRes.total ?? rechargeItems.length);
      if (canViewAllTxns && userIdFilter === null) {
        setLedgerUsers(_collectLedgerUsers(spendItems.concat(rechargeItems)));
      }

      if (canManageFinance) {
        try {
          const pendingRes = await WalletService.listTenantPendingRecharges(
            tenantSlug
          );
          setPendingApprovals(pendingRes || []);
        } catch {
          setPendingApprovals([]);
        }
      }
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Unable to load Unified Wallet data.")
      );
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, canManageFinance, canViewAllTxns, ledgerUserFilter]);

  const handleRunIntegrityAudit = async () => {
    if (!tenantSlug) return;
    setRunningAudit(true);
    try {
      const report = await WalletService.auditWalletIntegrity(tenantSlug);
      setAuditReport(report);
      if (report.passed) {
        toast.success(
          `Ledger & Lifecycle Integrity Verified (${report.wallets_checked} wallet(s), ${report.transactions_checked} txns, ${report.shipments_checked} shipments, ${report.invoices_checked} GST invoices — 0 discrepancies).`
        );
      } else {
        toast.error(
          `Integrity audit detected ${report.discrepancy_count} discrepancy(ies).`
        );
      }
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to run wallet integrity audit.")
      );
    } finally {
      setRunningAudit(false);
    }
  };

  useEffect(() => {
    fetchWalletData();
    const handleUpdated = () => {
      fetchWalletData();
    };
    window.addEventListener("wallet-updated", handleUpdated);
    return () => {
      window.removeEventListener("wallet-updated", handleUpdated);
    };
  }, [fetchWalletData]);

  const handleApproveRecharge = async (txn: WalletTransactionRead) => {
    setProcessingApprovalId(txn.id);
    try {
      const res = await WalletService.approvePendingRecharge(
        txn.id,
        tenantSlug
      );
      toast.success(
        `Approved! ₹${txn.amount.toFixed(
          2
        )} merged into main wallet balance (New Balance: ₹${res.balance.toFixed(
          2
        )}).`
      );
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      fetchWalletData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to approve pending recharge.")
      );
    } finally {
      setProcessingApprovalId(null);
    }
  };

  const handleRejectRecharge = async (txn: WalletTransactionRead) => {
    setProcessingApprovalId(txn.id);
    const reason = (rejectReasonByTxnId[txn.id] || "").trim() || undefined;
    try {
      await WalletService.rejectPendingRecharge(txn.id, tenantSlug, {
        reason,
      });
      toast.info(
        `Rejected pending recharge request (${txn.receipt_number}).`
      );
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      fetchWalletData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to reject pending recharge.")
      );
    } finally {
      setProcessingApprovalId(null);
    }
  };

  const handleRecordOfflineCredit = async () => {
    const email = offlineUserEmail.trim();
    const amountNum = Number(offlineAmount);
    const reference = offlineReference.trim();
    if (!email) {
      toast.error("Please select or enter the customer's email address.");
      return;
    }
    if (!Number.isFinite(amountNum) || amountNum <= 0) {
      toast.error("Enter a valid credit amount in ₹.");
      return;
    }
    if (reference.length < 3) {
      toast.error("Enter a bank reference / UTR / receipt number (min 3 characters).");
      return;
    }
    setSubmittingOfflineCredit(true);
    try {
      const res = await WalletService.recordAdminOfflineWalletCredit(
        {
          user_email: email,
          amount: amountNum,
          payment_method: offlineMethod,
          utr_number: reference,
          notes: offlineNotes.trim() || null,
        },
        tenantSlug
      );
      toast.success(
        `Credited ₹${res.transaction.amount.toFixed(2)} to ${res.transaction.user_email || email} (${res.transaction.receipt_number}).`
      );
      setOfflineCreditOpen(false);
      setOfflineAmount("");
      setOfflineReference("");
      setOfflineNotes("");
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      fetchWalletData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to record offline wallet credit.")
      );
    } finally {
      setSubmittingOfflineCredit(false);
    }
  };

  const handleSubmitInlineUtr = async (txn: WalletTransactionRead) => {
    const trimmedUtr = (inlineUtrByTxnId[txn.id] || "").trim();
    if (!/^\d{12}$/.test(trimmedUtr)) {
      toast.error("Please enter a valid 12-digit UPI UTR reference number.");
      return;
    }
    setProcessingApprovalId(txn.id);
    try {
      await WalletService.confirmUpiRecharge(txn.id, tenantSlug, {
        utr_number: trimmedUtr,
      });
      toast.success(
        `UTR submitted for ${txn.receipt_number}. Request is now awaiting admin approval.`
      );
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      fetchWalletData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to submit UTR reference.")
      );
    } finally {
      setProcessingApprovalId(null);
    }
  };

  const handleSettleDeliveredRemittance = async () => {
    setSettlingRemittance(true);
    try {
      const res = await WalletService.settleCodShipmentsToWallet(null, tenantSlug);
      if (res.settled_count > 0) {
        toast.success(
          `Settled ₹${res.settled_amount.toFixed(2)} across ${res.settled_count} delivered shipment(s) into your Wallet!`
        );
      } else {
        toast.info("No pending delivered cash shipments available to settle.");
      }
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      fetchWalletData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to settle cash to wallet.")
      );
    } finally {
      setSettlingRemittance(false);
    }
  };

  const handleExportCsv = async () => {
    setDownloadingCsv(true);
    try {
      await downloadWalletLedgerCsv(
        canViewAllTxns && ledgerUserFilter !== ALL_USERS_FILTER
          ? ledgerUserFilter
          : undefined
      );
      toast.success("Unified Wallet Ledger CSV downloaded!");
    } catch {
      toast.error("Failed to download wallet ledger CSV.");
    } finally {
      setDownloadingCsv(false);
    }
  };

  const handleDownloadReceipt = async (txn: WalletTransactionRead) => {
    setDownloadingTxnId(txn.id);
    try {
      await downloadWalletReceiptPdf(txn.id, txn.receipt_number);
      toast.success(`Receipt ${txn.receipt_number} downloaded!`);
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to generate receipt PDF.")
      );
    } finally {
      setDownloadingTxnId(null);
    }
  };

  const getTxnBadgeStyle = (txn: WalletTransactionRead) => {
    if (txn.txn_type === WalletTxnType.SPEND) {
      return "bg-rose-100 text-rose-700 border-rose-200";
    }
    if (txn.direction === WalletTxnDirection.DEBIT) {
      return "bg-amber-100 text-amber-800 border-amber-200";
    }
    return "bg-emerald-100 text-emerald-700 border-emerald-200";
  };

  // Undefined until the wallet overview has loaded: the cards show a placeholder instead
  // of a misleading ₹0.00 (screen ₹ must always be the backend's ₹).
  const balanceVal = overview?.balance;
  const pendingVal = overview?.summary?.pending_recharge ?? 0;
  const spentVal = overview?.summary?.total_spent;
  const refundedVal = overview?.summary?.total_refunded;
  const collectibleVal = overview?.summary?.collectible_cod;
  const minB2bBalance =
    overview?.wallet_config?.min_wallet_balance_b2b ?? 500;

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-12 animate-in fade-in duration-500">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-slate-200 pb-6">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-2.5">
            <Wallet className="h-8 w-8 text-primary" />
            Unified Wallet & Financial Ledger
          </h1>
          <p className="text-slate-500 mt-1">
            Prepaid wallet for your B2C Express and B2B Cargo shipments:
            recharges, shipping spends, refunds and COD credits in one ledger.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="button"
            variant="outline"
            onClick={handleExportCsv}
            disabled={downloadingCsv}
            className="h-10 font-semibold border-slate-200"
          >
            {downloadingCsv ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <Download className="mr-2 h-4 w-4" />
            )}
            Download Ledger CSV
          </Button>
          {canManageFinance && (
            <Button
              type="button"
              variant="outline"
              onClick={() => setOfflineCreditOpen(true)}
              className="h-10 px-4 font-bold border-emerald-300 text-emerald-800 hover:bg-emerald-50"
              data-testid="wallet.actions.offline-credit"
            >
              <Plus className="mr-2 h-4 w-4" />
              Record Offline Credit
            </Button>
          )}
          {canMoveMoney && (
            <Button
              type="button"
              onClick={() => setRechargeOpen(true)}
              className="h-10 px-4 font-bold bg-primary text-primary-foreground hover:bg-primary/90"
             data-testid="wallet.actions.recharge">
              <Plus className="mr-2 h-4 w-4" />
              Recharge Wallet
            </Button>
          )}
        </div>
      </div>

      {/* F-04 / G6: Finance-Only System & Wallet Ledger Integrity Audit (On-Demand) */}
      {canViewAllTxns && (
        <div
          className={cn(
            "rounded-xl border px-4 py-3.5 shadow-xs transition",
            !auditReport
              ? "border-slate-200 bg-slate-50/70 text-slate-900"
              : auditReport.passed
                ? "border-emerald-200 bg-emerald-50/70 text-emerald-950"
                : "border-rose-300 bg-rose-50/80 text-rose-950"
          )}
          data-testid="wallet.audit.banner"
        >
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
            <div className="flex items-start gap-2.5">
              {!auditReport ? (
                <ShieldCheck className="h-5 w-5 text-slate-600 shrink-0 mt-0.5" />
              ) : auditReport.passed ? (
                <ShieldCheck className="h-5 w-5 text-emerald-700 shrink-0 mt-0.5" />
              ) : (
                <ShieldAlert className="h-5 w-5 text-rose-700 shrink-0 mt-0.5" />
              )}
              <div className="space-y-0.5">
                <p className="text-xs sm:text-sm font-extrabold">
                  {!auditReport
                    ? "Ledger & Lifecycle Integrity Check (Finance Audit)"
                    : auditReport.passed
                      ? `Ledger & Lifecycle Integrity Verified — ${auditReport.wallets_checked} Wallet(s), ${auditReport.transactions_checked} Ledger Txns, ${auditReport.shipments_checked} Shipments, ${auditReport.invoices_checked} GST Invoices, ${auditReport.remittances_checked} Remittances — 0 Discrepancies`
                      : `Ledger & Lifecycle Integrity Alert — ${auditReport.discrepancy_count} Discrepancy(ies) Detected`}
                </p>
                <p className="text-[11px] opacity-80">
                  Cross-verifies wallet balances, opening/closing transaction chains, cancelled order refunds, B2B GST invoice totals, and COD remittance cycles.
                </p>
              </div>
            </div>

            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={runningAudit}
              onClick={handleRunIntegrityAudit}
              data-testid="wallet.audit.run"
              className={cn(
                "h-8 px-3 text-xs font-bold shrink-0",
                !auditReport
                  ? "border-slate-300 bg-white text-slate-900 hover:bg-slate-100"
                  : auditReport.passed
                    ? "border-emerald-300 bg-white text-emerald-900 hover:bg-emerald-100"
                    : "border-rose-300 bg-white text-rose-900 hover:bg-rose-100"
              )}
            >
              {runningAudit ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              )}
              Run Audit Check
            </Button>
          </div>

          {auditReport &&
            !auditReport.passed &&
            auditReport.discrepancies &&
            auditReport.discrepancies.length > 0 && (
              <div className="mt-3 space-y-1.5 border-t border-rose-200 pt-2.5">
                {auditReport.discrepancies.map((d, idx) => (
                  <div
                    key={`${d.category}-${d.entity_id}-${idx}`}
                    className="rounded-lg border border-rose-200 bg-white px-3 py-2 text-xs text-rose-900 flex flex-col sm:flex-row sm:items-center justify-between gap-2"
                  >
                    <div>
                      <span className="font-mono font-extrabold text-rose-700 mr-2">
                        [{d.category}]
                      </span>
                      <span className="font-mono font-bold mr-2">
                        {d.reference}:
                      </span>
                      <span>{d.detail}</span>
                    </div>
                    <div className="font-mono text-[11px] shrink-0 text-rose-800">
                      ID: <strong>{d.entity_id.slice(0, 8)}</strong>
                    </div>
                  </div>
                ))}
              </div>
            )}
        </div>
      )}

      {/* KPI Summary Cards (own wallet only) */}
      {hasOwnWallet && (
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Card 1: Current Wallet Balance + Pending Approval */}
        <Card className="min-w-0 overflow-hidden border-slate-200 shadow-xs">
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Current Wallet Balance
            </CardDescription>
            <CardTitle className="text-2xl font-extrabold text-slate-900 flex items-center gap-1">
              <IndianRupee className="h-5 w-5 text-primary" />
              <SummaryAmount testId="wallet.summary.balance" value={balanceVal} />
            </CardTitle>
            {pendingVal > 0 && (
              <div className="pt-1">
                <Badge
                  variant="outline"
                  className="bg-amber-100 text-amber-800 border-amber-300 text-[11px] font-bold flex items-center gap-1 w-fit"
                >
                  <Clock className="h-3 w-3 shrink-0" />
                  Pending Approval: +₹{pendingVal.toFixed(2)}
                </Badge>
              </div>
            )}
          </CardHeader>
          <CardContent className="pt-1">
            {canMoveMoney && (
              <Button
                type="button"
                size="sm"
                onClick={() => setRechargeOpen(true)}
                className="w-full font-bold bg-primary text-primary-foreground hover:bg-primary/90 h-8 text-xs"
               data-testid="wallet.actions.recharge">
                <Plus className="mr-1.5 h-3.5 w-3.5" />
                Add Money (0% UPI QR)
              </Button>
            )}
          </CardContent>
        </Card>

        {/* Card 2: Spent on B2C & B2B */}
        <Card className="min-w-0 overflow-hidden border-slate-200 shadow-xs">
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Spent (B2C & B2B)
            </CardDescription>
            <CardTitle className="text-2xl font-extrabold text-slate-900 flex items-center gap-1">
              <IndianRupee className="h-5 w-5 text-rose-600" />
              <SummaryAmount testId="wallet.summary.spent" value={spentVal} />
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-1">
            {canAccessB2B && (
            <Badge
              variant="outline"
              className="bg-slate-100 text-slate-700 border-slate-200 text-[11px] font-semibold"
            >
              Min B2B Finlock: ₹{Number(minB2bBalance).toFixed(2)}
            </Badge>
            )}
          </CardContent>
        </Card>

        {/* Card 3: Refunds & Credits */}
        <Card className="min-w-0 overflow-hidden border-slate-200 shadow-xs">
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-bold uppercase tracking-wider text-slate-500">
              Refunds & Credits
            </CardDescription>
            <CardTitle className="text-2xl font-extrabold text-emerald-700 flex items-center gap-1">
              <IndianRupee className="h-5 w-5 text-emerald-600" />
              <SummaryAmount testId="wallet.summary.refunded" value={refundedVal} />
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-1">
            <span className="text-xs text-slate-500 font-medium">
              Auto-credited upon order cancellation
            </span>
          </CardContent>
        </Card>

        {/* Card 4: Collectible Cash Remittance */}
        <Card className="min-w-0 overflow-hidden border-slate-200 shadow-xs">
          <CardHeader className="pb-2">
            <CardDescription className="text-xs font-bold uppercase tracking-wider text-slate-500">
              {canSettleCod ? "Delivered Cash Collectible" : "Delivered COD awaiting remittance"}
            </CardDescription>
            <CardTitle className="text-2xl font-extrabold text-slate-900 flex items-center gap-1">
              <IndianRupee className="h-5 w-5 text-amber-600" />
              <SummaryAmount testId="wallet.summary.collectible" value={collectibleVal} />
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-1">
            {!canSettleCod && (
              <span className="text-xs text-slate-500 font-medium" data-testid="wallet.summary.collectible-note">
                Paid to your bank account in the next COD remittance cycle
              </span>
            )}
            {canSettleCod && (
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={settlingRemittance || !collectibleVal || collectibleVal <= 0}
              onClick={handleSettleDeliveredRemittance}
              className="w-full font-bold border-emerald-300 text-emerald-800 hover:bg-emerald-50 h-8 text-xs"
            >
              {settlingRemittance ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              )}
              Settle Cash to Wallet
            </Button>
            )}
          </CardContent>
        </Card>
      </div>
      )}

      {/* Admin Maker-Checker Queue: Pending Recharges Requiring Approval */}
      {canManageFinance && pendingApprovals.length > 0 && (
        <Card className="min-w-0 border-amber-300 bg-amber-50/40 shadow-xs overflow-hidden">
          <CardHeader className="pb-3 border-b border-amber-200 bg-amber-50/80">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 min-w-0">
              <div className="min-w-0">
                <CardTitle className="text-base font-extrabold text-amber-900 flex items-center gap-2">
                  <ShieldAlert className="h-5 w-5 shrink-0 text-amber-700" />
                  <span>
                    Pending UPI Recharges Requiring Admin Approval (
                    {pendingApprovals.length})
                  </span>
                </CardTitle>
                <CardDescription className="text-xs text-amber-800/80 mt-0.5">
                  Verify that the UPI transfer has been received in your bank
                  account, then click{" "}
                  <span className="font-bold">Approve &amp; Merge</span> to
                  merge the pending amount into the user&apos;s main wallet
                  balance.
                </CardDescription>
              </div>
              <Badge
                variant="outline"
                className="bg-amber-100 text-amber-900 border-amber-300 text-xs font-bold w-fit shrink-0"
              >
                Maker-Checker Queue
              </Badge>
            </div>
          </CardHeader>
          <div className="overflow-x-auto">
            <table className="w-full text-sm text-left">
              <thead className="bg-amber-100/50 border-b border-amber-200 text-[11px] font-bold uppercase tracking-wider text-amber-900">
                <tr>
                  <th className="px-3 py-2.5">Receipt #</th>
                  <th className="px-3 py-2.5">User Email</th>
                  <th className="px-3 py-2.5">Submitted At</th>
                  <th className="px-3 py-2.5">UTR / Reference</th>
                  <th className="px-3 py-2.5 text-right">Pending Amount</th>
                  <th className="px-3 py-2.5 text-right">Admin Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-amber-200/70 bg-white">
                {pendingApprovals.map((txn) => (
                  <tr key={txn.id}
                          data-testid={`wallet.txn.${txn.receipt_number}`} className="hover:bg-amber-50/30">
                    <td className="px-3 py-3 font-mono text-xs font-bold text-slate-900">
                      {txn.receipt_number}
                    </td>
                    <td className="px-3 py-3 text-xs font-semibold text-slate-700 max-w-[160px] truncate">
                      {txn.user_email || "—"}
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-600 whitespace-nowrap">
                      {safeFormatDate(txn.created_at, SUBMITTED_AT_FORMAT)}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs font-bold text-slate-800">
                      {txn.utr_number || "—"}
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-sm font-extrabold text-amber-800 whitespace-nowrap">
                      +<span data-testid={`wallet.txn.${txn.receipt_number}.amount`}>₹{txn.amount.toFixed(2)}</span>
                    </td>
                    <td className="px-3 py-3 text-right">
                      {canReviewRecharge(txn) ? (
                      <div className="flex flex-wrap items-center justify-end gap-1.5 min-w-0">
                        <Input
                          type="text"
                          value={rejectReasonByTxnId[txn.id] || ""}
                          onChange={(e) =>
                            setRejectReasonByTxnId((prev) => ({
                              ...prev,
                              [txn.id]: e.target.value,
                            }))
                          }
                          placeholder="Reason (optional)"
                          aria-label="Reject reason (optional)"
                          className="h-8 w-36 min-w-0 max-w-full text-xs bg-white border-amber-300"
                          data-testid={`wallet.txn.${txn.receipt_number}.reject-reason`}
                        />
                        <Button
                          type="button"
                          size="sm"
                          disabled={processingApprovalId === txn.id}
                          onClick={() => setApproveTarget(txn)}
                          className="h-8 px-2.5 text-xs font-bold bg-emerald-600 text-white hover:bg-emerald-700"
                        >
                          {processingApprovalId === txn.id ? (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                          )}
                          Approve &amp; Merge
                        </Button>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          disabled={processingApprovalId === txn.id}
                          onClick={() => handleRejectRecharge(txn)}
                          className="h-8 px-2.5 text-xs font-bold border-rose-200 text-rose-700 hover:bg-rose-50"
                        >
                          <XCircle className="mr-1 h-3.5 w-3.5" />
                          Reject
                        </Button>
                      </div>
                      ) : (
                        <span className="text-[11px] font-semibold text-amber-700">
                          Your request: another admin must approve
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Two Clean Tabs: Spends & Refunds vs Recharges */}
      {canViewAllTxns && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50/70 px-4 py-3 min-w-0">
          <div className="flex items-start gap-2.5 min-w-0">
            <Users className="h-4 w-4 text-primary mt-0.5 shrink-0" />
            <div className="min-w-0">
              <p className="text-sm font-bold text-slate-900">
                Tenant-wide ledger
              </p>
              <p className="text-xs text-slate-500">
                You are viewing wallet transactions of every user in this
                workspace.
                {hasOwnWallet && " The balance cards above show your own wallet."}
              </p>
            </div>
          </div>
          <select
            aria-label="Filter ledger by user"
            value={ledgerUserFilter}
            onChange={(e) => setLedgerUserFilter(e.target.value)}
            className="h-9 w-full sm:w-72 min-w-0 max-w-full rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            <option value={ALL_USERS_FILTER}>All users</option>
            {ledgerUsers.map((option) => (
              <option key={option.id} value={option.id}>
                {option.email}
              </option>
            ))}
          </select>
        </div>
      )}

      <Tabs
        value={activeTab}
        onValueChange={setActiveTab}
        className="w-full space-y-4"
      >
        <TabsList className="bg-slate-100 border border-slate-200 p-1">
          <TabsTrigger value="spends" className="font-bold text-xs px-5 py-2">
            Spends & Refunds ({spendsTotal})
          </TabsTrigger>
          <TabsTrigger
            value="recharges"
            className="font-bold text-xs px-5 py-2"
          >
            Recharges ({rechargesTotal})
          </TabsTrigger>
        </TabsList>
        {(spendsTotal > spendsTxns.length || rechargesTotal > rechargeTxns.length) && (
          <p className="text-xs text-slate-500" data-testid="wallet.ledger.truncated-note">
            Showing the latest {LEDGER_PAGE_SIZE} entries per tab. Use Download Ledger CSV for the
            full history.
          </p>
        )}

        {/* TAB 1: SPENDS & REFUNDS */}
        <TabsContent value="spends">
          <Card className="border-slate-200 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-50 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Receipt / Note #</th>
                    <th className="px-4 py-3">Date</th>
                    {canViewAllTxns && <th className="px-4 py-3">User</th>}
                    <th className="px-4 py-3">AWB / LRN</th>
                    <th className="px-4 py-3">Service</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3 text-right">Opening Bal</th>
                    <th className="px-4 py-3 text-right">Amount</th>
                    <th className="px-4 py-3 text-right">Closing Bal</th>
                    <th className="px-4 py-3">Remarks</th>
                    <th className="px-4 py-3 text-right">Receipt PDF</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 bg-white">
                  {loading ? (
                    <tr>
                      <td colSpan={canViewAllTxns ? 11 : 10} className="py-12 text-center">
                        <Loader2 className="h-6 w-6 animate-spin text-primary mx-auto" />
                      </td>
                    </tr>
                  ) : spendsTxns.length === 0 ? (
                    <tr>
                      <td
                        colSpan={canViewAllTxns ? 11 : 10}
                        className="py-12 text-center text-slate-500 font-medium"
                      >
                        No spends or refunds recorded yet. Book a shipment to
                        see ledger entries here.
                      </td>
                    </tr>
                  ) : (
                    spendsTxns.map((txn) => {
                      const isDebit =
                        txn.direction === WalletTxnDirection.DEBIT;
                      const shipmentPath =
                        txn.service_category === WalletServiceCategory.B2B
                          ? `/b2b/shipments/${txn.shipment_id}`
                          : `/shipments/${txn.shipment_id}`;

                      return (
                        <tr
                          key={txn.id}
                          data-testid={`wallet.txn.${txn.receipt_number}`}
                          className="hover:bg-slate-50/80 transition-colors"
                        >
                          <td className="px-4 py-3 font-mono text-xs font-bold text-slate-900">
                            {txn.receipt_number}
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                            {safeFormatDate(txn.created_at)}
                          </td>
                          {canViewAllTxns && (
                            <td className="px-4 py-3 text-xs font-semibold text-slate-700 max-w-[180px] truncate">
                              {txn.user_email || "—"}
                            </td>
                          )}
                          <td className="px-4 py-3 text-xs font-mono">
                            {txn.shipment_id ? (
                              <Link
                                href={routeTo(shipmentPath)}
                                className="inline-flex items-center gap-1 text-primary font-bold hover:underline"
                              >
                                {txn.tracking_id ||
                                  txn.shipment_id.slice(0, 8).toUpperCase()}
                                <ExternalLink className="h-3 w-3" />
                              </Link>
                            ) : (
                              <span className="text-slate-400">—</span>
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <Badge
                              variant="outline"
                              className="text-[10px] font-bold bg-slate-100 text-slate-700 border-slate-200"
                            >
                              {txn.service_category}
                            </Badge>
                          </td>
                          <td className="px-4 py-3">
                            <Badge
                              variant="outline"
                              className={cn(
                                "text-[10px] font-bold",
                                getTxnBadgeStyle(txn)
                              )}
                            >
                              {String(txn.txn_type).replace(/_/g, " ")}
                            </Badge>
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs text-slate-600">
                            ₹{txn.opening_balance.toFixed(2)}
                          </td>
                          <td
                            className={cn(
                              "px-4 py-3 text-right font-mono text-xs font-bold",
                              isDebit ? "text-rose-600" : "text-emerald-700"
                            )}
                          >
                            <span className="inline-flex items-center gap-0.5">
                              {isDebit ? (
                                <ArrowUpRight className="h-3.5 w-3.5" />
                              ) : (
                                <ArrowDownLeft className="h-3.5 w-3.5" />
                              )}
                              <span data-testid={`wallet.txn.${txn.receipt_number}.amount`}>₹{txn.amount.toFixed(2)}</span>
                            </span>
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs font-bold text-slate-900">
                            ₹{txn.closing_balance.toFixed(2)}
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600 max-w-xs truncate">
                            {txn.remarks || "—"}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <Button
                              type="button"
                              variant="ghost"
                              size="sm"
                              disabled={downloadingTxnId === txn.id}
                              onClick={() => handleDownloadReceipt(txn)}
                              className="h-8 text-xs font-bold text-primary hover:bg-primary/10"
                            >
                              {downloadingTxnId === txn.id ? (
                                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                              ) : (
                                <FileText className="h-3.5 w-3.5 mr-1" />
                              )}
                              PDF
                            </Button>
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </TabsContent>

        {/* TAB 2: RECHARGES */}
        <TabsContent value="recharges">
          <Card className="border-slate-200 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm text-left">
                <thead className="bg-slate-50 border-b border-slate-200 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Receipt #</th>
                    <th className="px-4 py-3">Date</th>
                    {canViewAllTxns && <th className="px-4 py-3">User</th>}
                    <th className="px-4 py-3">UTR / Reference</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Opening Bal</th>
                    <th className="px-4 py-3 text-right">Recharge Amount</th>
                    <th className="px-4 py-3 text-right">Closing Bal</th>
                    <th className="px-4 py-3 text-right">Receipt / Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 bg-white">
                  {loading ? (
                    <tr>
                      <td colSpan={canViewAllTxns ? 9 : 8} className="py-12 text-center">
                        <Loader2 className="h-6 w-6 animate-spin text-primary mx-auto" />
                      </td>
                    </tr>
                  ) : rechargeTxns.length === 0 ? (
                    <tr>
                      <td
                        colSpan={canViewAllTxns ? 9 : 8}
                        className="py-12 text-center text-slate-500 font-medium"
                      >
                        No wallet recharges yet. Click Recharge Wallet to add
                        funds via UPI QR.
                      </td>
                    </tr>
                  ) : (
                    rechargeTxns.map((txn) => {
                      const isPending =
                        txn.status === WalletTxnStatus.PENDING;
                      const isFailed =
                        txn.status === WalletTxnStatus.FAILED;
                      const needsUtr = isPending && !txn.utr_number;
                      const isOwnIntent = txn.user_id === user?.id;
                      return (
                        <tr
                          key={txn.id}
                          data-testid={`wallet.txn.${txn.receipt_number}`}
                          className="hover:bg-slate-50/80 transition-colors"
                        >
                          <td className="px-4 py-3 font-mono text-xs font-bold text-slate-900">
                            {txn.receipt_number}
                          </td>
                          <td className="px-4 py-3 text-xs text-slate-600 whitespace-nowrap">
                            {safeFormatDate(txn.created_at)}
                          </td>
                          {canViewAllTxns && (
                            <td className="px-4 py-3 text-xs font-semibold text-slate-700 max-w-[180px] truncate">
                              {txn.user_email || "—"}
                            </td>
                          )}
                          <td className="px-4 py-3 font-mono text-xs font-bold text-slate-800">
                            {txn.utr_number || "—"}
                          </td>
                          <td className="px-4 py-3">
                            <div className="space-y-1">
                              <Badge
                                variant="outline"
                                className={cn(
                                  "text-[10px] font-bold",
                                  isFailed
                                    ? "bg-rose-100 text-rose-700 border-rose-200"
                                    : isPending
                                      ? "bg-amber-100 text-amber-800 border-amber-300"
                                      : "bg-emerald-100 text-emerald-700 border-emerald-200"
                                )}
                              >
                                {isFailed
                                  ? "REJECTED"
                                  : needsUtr
                                    ? "AWAITING UTR"
                                    : isPending
                                      ? "PENDING APPROVAL"
                                      : txn.status}
                              </Badge>
                              {isFailed && txn.remarks && (
                                <p
                                  className="text-[11px] font-medium text-rose-700 max-w-xs"
                                  data-testid={`wallet.txn.${txn.receipt_number}.remarks`}
                                >
                                  {txn.remarks}
                                </p>
                              )}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs text-slate-600">
                            ₹{txn.opening_balance.toFixed(2)}
                          </td>
                          <td
                            className={cn(
                              "px-4 py-3 text-right font-mono text-xs font-bold",
                              isFailed
                                ? "text-slate-400 line-through"
                                : isPending
                                  ? "text-amber-700"
                                  : "text-emerald-700"
                            )}
                          >
                            +<span data-testid={`wallet.txn.${txn.receipt_number}.amount`}>₹{txn.amount.toFixed(2)}</span>
                          </td>
                          <td className="px-4 py-3 text-right font-mono text-xs font-bold text-slate-900">
                            {isFailed
                              ? `₹${txn.closing_balance.toFixed(2)}`
                              : isPending
                                ? "Pending Merge"
                                : `₹${txn.closing_balance.toFixed(2)}`}
                          </td>
                          <td className="px-4 py-3 text-right">
                            {needsUtr ? (
                              isOwnIntent ? (
                                <div className="inline-flex items-center gap-1.5">
                                  <Input
                                    type="text"
                                    maxLength={12}
                                    value={inlineUtrByTxnId[txn.id] || ""}
                                    onChange={(e) =>
                                      setInlineUtrByTxnId((prev) => ({
                                        ...prev,
                                        [txn.id]: e.target.value.replace(/\D/g, ""),
                                      }))
                                    }
                                    placeholder="12-digit UTR"
                                    className="h-7 w-32 font-mono text-xs bg-white border-slate-300"
                                    data-testid={`wallet.txn.${txn.receipt_number}.utr-input`}
                                  />
                                  <Button
                                    type="button"
                                    size="sm"
                                    disabled={
                                      processingApprovalId === txn.id ||
                                      !/^\d{12}$/.test(
                                        (inlineUtrByTxnId[txn.id] || "").trim()
                                      )
                                    }
                                    onClick={() => handleSubmitInlineUtr(txn)}
                                    className="h-7 px-2.5 text-[11px] font-bold bg-primary text-primary-foreground"
                                    data-testid={`wallet.txn.${txn.receipt_number}.submit-utr`}
                                  >
                                    Submit UTR
                                  </Button>
                                </div>
                              ) : (
                                <span className="text-[11px] font-semibold text-slate-500">
                                  UTR not entered
                                </span>
                              )
                            ) : isPending ? (
                              canReviewRecharge(txn) ? (
                                <div className="inline-flex items-center gap-1.5">
                                  <Button
                                    type="button"
                                    size="sm"
                                    disabled={processingApprovalId === txn.id}
                                    onClick={() => setApproveTarget(txn)}
                                    className="h-7 px-2.5 text-[11px] font-bold bg-emerald-600 text-white hover:bg-emerald-700"
                                  >
                                    {processingApprovalId === txn.id ? (
                                      <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                                    ) : (
                                      <CheckCircle2 className="mr-1 h-3 w-3" />
                                    )}
                                    Approve &amp; Merge
                                  </Button>
                                  <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    disabled={processingApprovalId === txn.id}
                                    onClick={() => handleRejectRecharge(txn)}
                                    className="h-7 px-2 text-[11px] font-bold border-rose-200 text-rose-700 hover:bg-rose-50"
                                  >
                                    Reject
                                  </Button>
                                </div>
                              ) : (
                                <span className="text-[11px] font-semibold text-amber-700">
                                  {canManageFinance ? "Awaiting another admin" : "Awaiting Admin"}
                                </span>
                              )
                            ) : isFailed ? (
                              <span className="text-[11px] font-semibold text-rose-600">
                                Rejected
                              </span>
                            ) : (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                disabled={downloadingTxnId === txn.id}
                                onClick={() => handleDownloadReceipt(txn)}
                                className="h-8 text-xs font-bold text-primary hover:bg-primary/10"
                              >
                                {downloadingTxnId === txn.id ? (
                                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                ) : (
                                  <FileText className="h-3.5 w-3.5 mr-1" />
                                )}
                                PDF
                              </Button>
                            )}
                          </td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </Card>
        </TabsContent>
      </Tabs>

      <Dialog
        open={approveTarget !== null}
        onOpenChange={(open) => {
          if (!open) setApproveTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-md" data-testid="wallet.approve-dialog">
          <DialogHeader>
            <DialogTitle>Approve recharge?</DialogTitle>
            <DialogDescription>
              Confirm the UPI transfer is in the bank account before approving. The amount is
              credited to the user&apos;s wallet immediately and cannot be undone here.
            </DialogDescription>
          </DialogHeader>
          {approveTarget && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
              <dt className="text-slate-500">User</dt>
              <dd className="font-semibold text-slate-900 break-all">{approveTarget.user_email || "—"}</dd>
              <dt className="text-slate-500">UTR</dt>
              <dd className="font-mono font-semibold text-slate-900">{approveTarget.utr_number || "—"}</dd>
              <dt className="text-slate-500">Amount</dt>
              <dd className="font-mono font-extrabold text-emerald-700">₹{approveTarget.amount.toFixed(2)}</dd>
            </dl>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setApproveTarget(null)}>
              Cancel
            </Button>
            <Button
              type="button"
              data-testid="wallet.approve-dialog.confirm"
              disabled={approveTarget === null || processingApprovalId === approveTarget.id}
              onClick={() => {
                const target = approveTarget;
                setApproveTarget(null);
                if (target) void handleApproveRecharge(target);
              }}
              className="bg-emerald-600 text-white hover:bg-emerald-700"
            >
              <CheckCircle2 className="mr-1.5 h-4 w-4" />
              Approve &amp; Credit Wallet
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={offlineCreditOpen}
        onOpenChange={(open) => {
          if (!submittingOfflineCredit) setOfflineCreditOpen(open);
        }}
      >
        <DialogContent className="sm:max-w-md overflow-x-hidden" data-testid="wallet.offline-credit.dialog">
          <DialogHeader className="min-w-0">
            <DialogTitle>Record Offline Wallet Credit</DialogTitle>
            <DialogDescription>
              Credit a customer&apos;s wallet when they have paid via NEFT / RTGS / IMPS, bank
              transfer, cheque, or cash. Creates a completed recharge receipt immediately.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-1 min-w-0">
            {ledgerUsers.length > 0 && (
              <div className="space-y-1 min-w-0">
                <label className="text-xs font-semibold text-slate-600">
                  Quick Select Customer
                </label>
                <select
                  aria-label="Quick Select Customer"
                  value={offlineUserEmail}
                  onChange={(e) => setOfflineUserEmail(e.target.value)}
                  className="h-9 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700"
                  data-testid="wallet.offline-credit.user-select"
                >
                  <option value="">Select a user or type email below…</option>
                  {ledgerUsers.map((option) => (
                    <option key={option.id} value={option.email}>
                      {option.email}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div className="space-y-1 min-w-0">
              <label className="text-xs font-semibold text-slate-600">
                Customer Email *
              </label>
              <Input
                type="email"
                value={offlineUserEmail}
                onChange={(e) => setOfflineUserEmail(e.target.value)}
                placeholder="customer@company.com"
                className="min-w-0 w-full"
                data-testid="wallet.offline-credit.user-email"
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 min-w-0">
              <div className="space-y-1 min-w-0">
                <label className="text-xs font-semibold text-slate-600">
                  Amount (₹) *
                </label>
                <Input
                  type="number"
                  step="0.01"
                  min="1"
                  value={offlineAmount}
                  onChange={(e) => setOfflineAmount(e.target.value)}
                  placeholder="e.g. 5000"
                  className="min-w-0 w-full"
                  data-testid="wallet.offline-credit.amount"
                />
              </div>
              <div className="space-y-1 min-w-0">
                <label className="text-xs font-semibold text-slate-600">
                  Payment Method *
                </label>
                <select
                  aria-label="Payment Method"
                  value={offlineMethod}
                  onChange={(e) => setOfflineMethod(e.target.value)}
                  className="h-9 w-full min-w-0 rounded-lg border border-slate-200 bg-white px-3 text-xs font-semibold text-slate-700"
                  data-testid="wallet.offline-credit.method"
                >
                  <option value="NEFT">NEFT / RTGS</option>
                  <option value="IMPS">IMPS</option>
                  <option value="UPI">UPI</option>
                  <option value="BANK_TRANSFER">Bank Transfer</option>
                  <option value="CHEQUE">Cheque</option>
                  <option value="CASH">Cash</option>
                </select>
              </div>
            </div>
            <div className="space-y-1 min-w-0">
              <label className="text-xs font-semibold text-slate-600">
                Bank Reference / UTR / Receipt # *
              </label>
              <Input
                type="text"
                value={offlineReference}
                onChange={(e) => setOfflineReference(e.target.value)}
                placeholder="e.g. NEFT20261101987654"
                className="min-w-0 w-full"
                data-testid="wallet.offline-credit.utr"
              />
            </div>
            <div className="space-y-1 min-w-0">
              <label className="text-xs font-semibold text-slate-600">
                Audit Note (optional)
              </label>
              <Input
                type="text"
                value={offlineNotes}
                onChange={(e) => setOfflineNotes(e.target.value)}
                placeholder="e.g. HDFC bank credit verified by Finance"
                className="min-w-0 w-full"
                data-testid="wallet.offline-credit.notes"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              disabled={submittingOfflineCredit}
              onClick={() => setOfflineCreditOpen(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={submittingOfflineCredit}
              onClick={() => void handleRecordOfflineCredit()}
              className="bg-emerald-600 text-white hover:bg-emerald-700"
              data-testid="wallet.offline-credit.submit"
            >
              {submittingOfflineCredit ? (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              ) : (
                <CheckCircle2 className="mr-1.5 h-4 w-4" />
              )}
              Credit Wallet
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <WalletRechargeDialog
        open={rechargeOpen}
        onOpenChange={setRechargeOpen}
        onSuccess={() => {
          fetchWalletData();
        }}
      />
    </div>
  );
}
