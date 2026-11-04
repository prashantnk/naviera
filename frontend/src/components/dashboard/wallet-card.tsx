// frontend/src/components/dashboard/wallet-card.tsx
"use client";

import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { useWallet } from "@/components/providers/wallet-provider";
import { Button } from "@/components/ui/button";
import { WalletRechargeDialog } from "@/components/wallet/wallet-header-pill";
import { ServiceFlow } from "@/lib/workspace-flow";
import { AlertCircle, ChevronRight, Plus, Wallet } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { formatWalletMoney, getMinimumWalletBalance } from "./dashboard-model";
import { SkeletonBlock } from "./dashboard-section";

interface DashboardWalletCardProps {
  /** Flow whose minimum-balance threshold drives the warning. */
  flow: ServiceFlow;
}

/**
 * Right-rail wallet card: live balance from `GET /api/v1/wallet`, low-balance
 * warning from the tenant's `wallet_config`, History link and the shared
 * Recharge dialog. Refreshes on the global `wallet-updated` event.
 */
export function DashboardWalletCard({ flow }: DashboardWalletCardProps) {
  const { routeTo } = useTenant();
  const { capabilities } = useUser();
  /** Mirrors backend `assert_can_manage_finance_or_wallet`: customers and Owner/Admin only. */
  const canRecharge =
    capabilities.canWrite && (!capabilities.isStaff || capabilities.canManageFinance);
  // Shared overview from WalletProvider (same request as the header pill).
  const { wallet, isLoading, hasError, refresh } = useWallet();
  const [rechargeOpen, setRechargeOpen] = useState<boolean>(false);

  const minimumBalance = wallet ? getMinimumWalletBalance(wallet, flow) : null;
  const isLowBalance =
    wallet !== null && minimumBalance !== null && wallet.balance < minimumBalance;
  const pendingRecharge = wallet?.summary?.pending_recharge ?? 0;

  return (
    <section aria-labelledby="dashboard-wallet-heading" className="overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="flex items-center justify-between gap-2 bg-primary/5 px-4 py-3">
        <h2 id="dashboard-wallet-heading" className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Wallet className="h-4 w-4 text-primary" aria-hidden />
          Wallet
        </h2>
        {canRecharge && (
          <Button
            type="button"
            size="sm"
            onClick={() => setRechargeOpen(true)}
            className="h-8 px-2.5 text-xs font-semibold"
          >
            <Plus className="mr-1 h-3.5 w-3.5" aria-hidden />
            Recharge wallet
          </Button>
        )}
      </div>

      <div className="px-4 py-3">
        {isLoading ? (
          <div className="space-y-2" aria-label="Loading wallet">
            <SkeletonBlock className="h-3 w-24" />
            <SkeletonBlock className="h-6 w-32" />
          </div>
        ) : hasError || !wallet ? (
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs text-muted-foreground">Couldn&apos;t load your wallet.</p>
            <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={() => { void refresh(); }}>
              Retry
            </Button>
          </div>
        ) : (
          <div className="flex items-end justify-between gap-2">
            <div className="min-w-0">
              <p className="text-xs text-muted-foreground">Available balance</p>
              <p
                className={
                  wallet.balance < 0
                    ? "text-xl font-bold tabular-nums text-rose-600"
                    : "text-xl font-bold tabular-nums text-foreground"
                }
              >
                {formatWalletMoney(wallet.balance, wallet.currency)}
              </p>
              {pendingRecharge > 0 && (
                <p className="mt-0.5 text-[11px] font-medium text-amber-700">
                  {formatWalletMoney(pendingRecharge, wallet.currency)} pending approval
                </p>
              )}
            </div>
            <Link
              href={routeTo("/wallet")}
              prefetch={true}
              className="inline-flex shrink-0 items-center gap-0.5 rounded-sm text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
            >
              History
              <ChevronRight className="h-3 w-3" aria-hidden />
            </Link>
          </div>
        )}
      </div>

      {isLowBalance && wallet && minimumBalance !== null && (
        <div role="status" className="flex items-start gap-2 border-t border-amber-200 bg-amber-50 px-4 py-2 text-[11px] text-amber-900">
          <AlertCircle className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            <span className="font-semibold">Low balance:</span> recharge to avoid disruption
            (minimum {formatWalletMoney(minimumBalance, wallet.currency)}).
          </span>
        </div>
      )}

      <WalletRechargeDialog
        open={rechargeOpen}
        onOpenChange={setRechargeOpen}
        onSuccess={() => {
          void refresh();
        }}
      />
    </section>
  );
}
