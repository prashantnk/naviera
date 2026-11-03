"use client";

import {
  UpiIntentResponse,
  WalletService,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { useWallet } from "@/components/providers/wallet-provider";
import { formatInr } from "@/components/shipments/shipment-money";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { InputAdornment } from "@/components/ui/form-extras";
import {
  CheckCircle2,
  Loader2,
  Plus,
  QrCode,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { extractApiErrorMessage } from "@/lib/utils";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

const QUICK_RECHARGE_AMOUNTS = [500, 1000, 2000, 5000];

interface WalletRechargeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: (newBalance: number) => void;
}

export function WalletRechargeDialog({
  open,
  onOpenChange,
  onSuccess,
}: WalletRechargeDialogProps) {
  const { tenantSlug } = useTenant();
  const { wallet } = useWallet();
  /** The tenant has no merchant UPI ID (backend sends `merchant_vpa: ""`); recharge is off. */
  const upiNotConfigured = wallet !== null && !wallet.wallet_config?.merchant_vpa;
  const [amountInput, setAmountInput] = useState<string>("1000");
  const [intent, setIntent] = useState<UpiIntentResponse | null>(null);
  const [utrNumber, setUtrNumber] = useState<string>("");
  const [loadingIntent, setLoadingIntent] = useState<boolean>(false);
  const [confirmingPayment, setConfirmingPayment] = useState<boolean>(false);

  const handlePaymentCompleted = useCallback(
    (creditedAmount: number, newBalance: number, receiptNumber?: string | null) => {
      toast.success(
        `UPI payment detected! Wallet credited with ₹${creditedAmount.toFixed(2)}${
          receiptNumber ? ` (Receipt: ${receiptNumber})` : ""
        }`
      );
      setIntent(null);
      setUtrNumber("");
      onOpenChange(false);
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      if (onSuccess) {
        onSuccess(newBalance);
      }
    },
    [onOpenChange, onSuccess]
  );

  // Automatic background polling for UPI QR payment completion (every 2.5s)
  useEffect(() => {
    if (!open || !intent) return;

    let cancelled = false;
    const pollTimer = window.setInterval(async () => {
      try {
        const statusRes = await WalletService.getUpiRechargeStatus(
          intent.transaction_id,
          undefined,
          tenantSlug
        );
        if (!cancelled && statusRes.status === "COMPLETED") {
          window.clearInterval(pollTimer);
          handlePaymentCompleted(
            intent.amount,
            statusRes.balance,
            statusRes.transaction.receipt_number
          );
        }
      } catch {
        // Ignore transient polling errors while waiting
      }
    }, 2500);

    return () => {
      cancelled = true;
      window.clearInterval(pollTimer);
    };
  }, [open, intent, tenantSlug, handlePaymentCompleted]);

  const handleGenerateQr = async () => {
    const parsedVal = Number(amountInput);
    if (!parsedVal || parsedVal < 1) {
      toast.error("Please enter a valid recharge amount of at least ₹1.");
      return;
    }

    setLoadingIntent(true);
    try {
      const response = await WalletService.createUpiRechargeIntent(
        {
          amount: parsedVal,
        },
        tenantSlug
      );
      setIntent(response);
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to generate UPI QR intent.")
      );
    } finally {
      setLoadingIntent(false);
    }
  };

  const handleMarkAsPaid = async () => {
    if (!intent) return;
    const trimmedUtr = utrNumber.trim();
    if (!/^\d{12}$/.test(trimmedUtr)) {
      toast.error(
        "Please enter the 12-digit UPI UTR reference number from your payment app."
      );
      return;
    }

    setConfirmingPayment(true);
    try {
      const res = await WalletService.confirmUpiRecharge(
        intent.transaction_id,
        tenantSlug,
        {
          utr_number: trimmedUtr,
        }
      );
      toast.success(
        `Payment of ₹${intent.amount.toFixed(
          2
        )} submitted! It is now in Pending Approval and will merge into your main balance once approved by Admin.`
      );
      setIntent(null);
      setUtrNumber("");
      onOpenChange(false);
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      if (onSuccess) {
        onSuccess(res.balance);
      }
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(
          err,
          "Failed to submit payment confirmation."
        )
      );
    } finally {
      setConfirmingPayment(false);
    }
  };

  const handleReset = (nextOpen: boolean) => {
    if (!nextOpen) {
      setIntent(null);
      setUtrNumber("");
      setConfirmingPayment(false);
    }
    onOpenChange(nextOpen);
  };

  return (
    <Dialog open={open} onOpenChange={handleReset}>
      <DialogContent className="sm:max-w-[460px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-slate-900">
            <QrCode className="h-5 w-5 text-primary" />
            UPI Wallet Recharge
          </DialogTitle>
          <DialogDescription>
            Scan the NPCI UPI QR with GPay, PhonePe, or Paytm and click{" "}
            <span className="font-semibold text-slate-700">&ldquo;I Have Paid&rdquo;</span>.
            Once approved by Admin, your pending recharge merges into your main balance.
          </DialogDescription>
        </DialogHeader>

        {upiNotConfigured ? (
          <div className="space-y-4 py-2">
            <div
              data-testid="wallet.recharge.upi-not-configured"
              className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900"
            >
              <p className="font-semibold">UPI not configured</p>
              <p className="mt-1 text-xs">
                This workspace has no merchant UPI ID yet, so wallet recharge is
                unavailable. Ask the workspace owner to add one in Settings.
              </p>
            </div>
            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleReset(false)}
              >
                Close
              </Button>
            </DialogFooter>
          </div>
        ) : !intent ? (
          <div className="space-y-5 py-2">
            <div className="space-y-2">
              <label
                htmlFor="wallet-recharge-amount"
                className="text-xs font-bold uppercase tracking-wider text-slate-500"
              >
                Select or enter amount
              </label>
              <InputAdornment prefix="₹" className="[&_input]:pl-8">
                <Input
                  id="wallet-recharge-amount"
                  type="number"
                  min={1}
                  inputMode="numeric"
                  value={amountInput}
                  onChange={(e) => setAmountInput(e.target.value)}
                  placeholder="Enter amount"
                  className="text-lg font-bold h-11 border-slate-200 focus-visible:ring-primary"
                />
              </InputAdornment>
              <p className="text-[11px] text-slate-500">
                Pick a quick amount or type your own. Credited after admin approval.
              </p>
              <div className="grid grid-cols-4 gap-2 pt-1">
                {QUICK_RECHARGE_AMOUNTS.map((preset) => (
                  <Button
                    key={preset}
                    type="button"
                    variant={
                      Number(amountInput) === preset ? "default" : "outline"
                    }
                    size="sm"
                    onClick={() => setAmountInput(String(preset))}
                    className="font-semibold text-xs"
                  >
                    ₹{preset.toLocaleString("en-IN")}
                  </Button>
                ))}
              </div>
            </div>

            <div className="rounded-xl bg-emerald-50 border border-emerald-200 p-3 flex items-center justify-between">
              <div className="flex items-center gap-2 text-emerald-800 text-xs font-semibold">
                <ShieldCheck className="h-4 w-4 text-emerald-600 shrink-0" />
                <span>Direct NPCI UPI Transfer (Admin Approved)</span>
              </div>
              <Badge
                variant="outline"
                className="bg-emerald-100 text-emerald-800 border-emerald-300 text-[10px] font-bold"
              >
                0% Gateway Charge
              </Badge>
            </div>

            <DialogFooter>
              <Button
                type="button"
                variant="outline"
                onClick={() => handleReset(false)}
              >
                Cancel
              </Button>
              <Button
                type="button"
                onClick={handleGenerateQr}
                disabled={loadingIntent}
                className="bg-primary text-primary-foreground font-bold"
              >
                {loadingIntent && (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                )}
                Generate UPI QR
              </Button>
            </DialogFooter>
          </div>
        ) : (
          <div className="space-y-4 py-2">
            <div className="flex flex-col items-center justify-center p-4 bg-slate-50 rounded-2xl border border-slate-200 space-y-3">
              <div className="bg-white p-3 rounded-xl shadow-sm border border-slate-200">
                <img
                  src={intent.qr_svg_data_url}
                  alt="UPI QR"
                  className="w-44 h-44 object-contain"
                />
              </div>
              <div className="text-center space-y-0.5">
                <p className="text-lg font-extrabold text-slate-900">
                  ₹
                  {intent.amount.toLocaleString("en-IN", {
                    minimumFractionDigits: 2,
                  })}
                </p>
                <p className="text-xs font-semibold text-slate-600">
                  Payee: {intent.merchant_name} ({intent.merchant_vpa})
                </p>
                <span className="inline-block text-[11px] font-bold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded">
                  0% Gateway Charge
                </span>
              </div>
              {intent.upi_uri && (
                <a
                  href={intent.upi_uri}
                  data-testid="wallet.recharge.pay-upi-app"
                  className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-xs font-bold text-primary-foreground hover:bg-primary/90 transition-colors w-full sm:w-auto"
                >
                  Pay with UPI App
                </a>
              )}
            </div>

            {/* Mandatory 12-Digit NPCI UPI UTR Reference Input (A-14) */}
            <div className="space-y-2 rounded-xl border border-slate-200 bg-slate-50/70 p-3.5">
              <label className="text-xs font-bold uppercase tracking-wider text-slate-700 flex items-center justify-between">
                <span>12-Digit UTR Number</span>
                <span className="text-[10px] font-semibold text-rose-600">
                  Required
                </span>
              </label>
              <Input
                type="text"
                maxLength={12}
                value={utrNumber}
                onChange={(e) =>
                  setUtrNumber(e.target.value.replace(/\D/g, ""))
                }
                placeholder="Enter 12-digit UPI UTR reference"
                className="font-mono text-sm tracking-widest h-10 bg-white border-slate-300"
                data-testid="wallet.recharge.utr-input"
              />
              <p className="text-[11px] text-slate-500">
                After paying in GPay / PhonePe / Paytm, enter the 12-digit UPI reference number and click{" "}
                <span className="font-semibold text-slate-700">&ldquo;I Have Paid&rdquo;</span>{" "}
                below. Your amount will show under Pending Approval until Admin merges it.
              </p>
            </div>

            <DialogFooter className="gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setIntent(null)}
                disabled={confirmingPayment}
              >
                Change Amount
              </Button>
              <Button
                type="button"
                onClick={handleMarkAsPaid}
                disabled={confirmingPayment || !/^\d{12}$/.test(utrNumber.trim())}
                className="bg-primary text-primary-foreground font-bold"
              >
                {confirmingPayment ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="mr-2 h-4 w-4" />
                )}
                I Have Paid
              </Button>
            </DialogFooter>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/**
 * Header wallet pill: own balance (+ pending recharge) and a Recharge button.
 *
 * Hidden for staff without a wallet of their own (read-only and support users,
 * decision #487); the Recharge button only for roles the backend lets recharge
 * (`assert_can_manage_finance_or_wallet`: customers, Owner, Admin). Below `sm`
 * the pending amount collapses to a dot so the header fits a 390 px phone.
 */
export function WalletHeaderPill() {
  const { routeTo } = useTenant();
  const { capabilities } = useUser();
  // Shared overview (one GET /wallet per app shell, refreshed on `wallet-updated`).
  const { wallet, refresh: refreshWallet } = useWallet();
  const [rechargeOpen, setRechargeOpen] = useState(false);

  if (!capabilities.hasOwnWallet) return null;

  if (capabilities.isStaff) {
    return (
      <div className="flex items-center gap-1.5">
        <Link
          href={routeTo("/wallet")}
          className="inline-flex items-center gap-1.5 h-9 px-2.5 sm:px-3 rounded-lg border border-slate-200 bg-white text-slate-700 hover:text-primary hover:border-primary/20 transition-colors text-xs font-semibold shadow-2xs whitespace-nowrap"
          title="View Unified Wallet & Ledger"
          data-testid="wallet.header.pill"
        >
          <Wallet className="w-3.5 h-3.5 text-slate-500 shrink-0" />
          <span className="hidden sm:inline">Wallet &amp; Ledger</span>
        </Link>
      </div>
    );
  }

  // Undefined until GET /wallet resolves: show "—", never a misleading ₹0.00.
  const balanceLabel = formatInr(wallet?.balance);
  const pendingValue = wallet?.summary?.pending_recharge ?? 0;

  return (
    <div className="flex items-center gap-1.5">
      <Link
        href={routeTo("/wallet")}
        className="inline-flex items-center gap-1.5 sm:gap-2 h-9 px-2.5 sm:px-3 rounded-lg border bg-primary/10 text-primary border-primary/20 hover:bg-primary/15 transition-colors text-xs font-bold shadow-xs whitespace-nowrap"
        title="View Unified Wallet & Ledger"
        data-testid="wallet.header.pill"
      >
        <Wallet className="h-3.5 w-3.5 shrink-0" />
        <span>
          <span className="hidden sm:inline">Wallet: </span>
          <span data-testid="wallet.header.balance">{balanceLabel}</span>
        </span>
        {pendingValue > 0 && (
          <>
            <span
              className="sm:hidden h-2 w-2 rounded-full bg-amber-500"
              aria-label="Recharge pending approval"
            />
            <span className="hidden sm:inline ml-0.5 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-extrabold text-amber-800 border border-amber-300">
              +{formatInr(pendingValue)} Pending
            </span>
          </>
        )}
      </Link>

      {capabilities.canRechargeWallet && (
        <>
          <Button
            type="button"
            size="sm"
            aria-label="Recharge Wallet"
            onClick={() => setRechargeOpen(true)}
            className="h-9 px-2 sm:px-2.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-bold shadow-xs"
          >
            <Plus className="h-3.5 w-3.5 sm:mr-1" />
            <span className="hidden sm:inline">Recharge</span>
          </Button>

          <WalletRechargeDialog
            open={rechargeOpen}
            onOpenChange={setRechargeOpen}
            onSuccess={() => {
              void refreshWallet();
            }}
          />
        </>
      )}
    </div>
  );
}
