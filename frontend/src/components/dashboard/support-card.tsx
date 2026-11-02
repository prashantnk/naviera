// frontend/src/components/dashboard/support-card.tsx
"use client";

import { SupportTicketsService, type SupportTicketSummary } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { ChevronRight, Headset } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { SkeletonBlock } from "./dashboard-section";

/** Support page route and the tab deep links the card opens. */
const SUPPORT_HREF = "/support";
const OPEN_TAB_QUERY = "?tab=OPEN";
const RESOLVED_TAB_QUERY = "?tab=RESOLVED";

interface SupportTileProps {
  label: string;
  count: number;
  linkLabel: string;
  href: string;
  /** Highlights the tile when it needs the viewer's action. */
  needsAction?: boolean;
}

/** One counter tile (Delhivery One "Resolved" / "Need your input"). */
function SupportTile({ label, count, linkLabel, href, needsAction = false }: SupportTileProps) {
  return (
    <div
      className={
        needsAction && count > 0
          ? "flex flex-col justify-between rounded-lg border border-amber-200 bg-amber-50/60 p-3"
          : "flex flex-col justify-between rounded-lg border bg-card p-3"
      }
    >
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="mt-1 text-xl font-bold tabular-nums text-foreground">{count}</p>
      </div>
      <Link
        href={href}
        className="mt-2 inline-flex items-center justify-end gap-0.5 self-end rounded-sm text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
      >
        {linkLabel}
        <ChevronRight className="h-3 w-3" aria-hidden />
      </Link>
    </div>
  );
}

/**
 * Right-rail Support card (Delhivery One parity).
 *
 * Shippers see **Resolved** and **Need your input** (Logismart replied last on an
 * open ticket). Logismart staff see **Open tickets** and **Awaiting reply** (the
 * shipper replied last). Numbers come from `GET /api/v1/support-tickets/summary`.
 */
export function DashboardSupportCard() {
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  const [summary, setSummary] = useState<SupportTicketSummary | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [hasError, setHasError] = useState<boolean>(false);

  const loadSummary = useCallback(async () => {
    setIsLoading(true);
    try {
      setSummary(await SupportTicketsService.getSupportTicketSummary(tenantSlug));
      setHasError(false);
    } catch {
      setHasError(true);
    } finally {
      setIsLoading(false);
    }
  }, [tenantSlug]);

  useEffect(() => {
    void loadSummary();
  }, [loadSummary]);

  const openHref = routeTo(SUPPORT_HREF + OPEN_TAB_QUERY);
  const resolvedHref = routeTo(SUPPORT_HREF + RESOLVED_TAB_QUERY);

  return (
    <section aria-labelledby="dashboard-support-heading" className="rounded-xl border bg-card p-4 shadow-sm">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h2 id="dashboard-support-heading" className="flex items-center gap-2 text-sm font-semibold text-foreground">
          <Headset className="h-4 w-4 text-primary" aria-hidden />
          Support
        </h2>
        <Link
          href={routeTo(SUPPORT_HREF)}
          className="rounded-sm text-xs font-medium text-primary outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring"
        >
          All tickets
        </Link>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-2 gap-2" aria-label="Loading support tickets">
          <SkeletonBlock className="h-20 w-full" />
          <SkeletonBlock className="h-20 w-full" />
        </div>
      ) : hasError || !summary ? (
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">Couldn&apos;t load support tickets.</p>
          <button
            type="button"
            onClick={() => {
              void loadSummary();
            }}
            className="rounded-sm text-xs font-medium text-primary hover:underline"
          >
            Retry
          </button>
        </div>
      ) : capabilities.isStaff ? (
        <div className="grid grid-cols-2 gap-2">
          <SupportTile label="Open tickets" count={summary.open ?? 0} linkLabel="View now" href={openHref} />
          <SupportTile
            label="Awaiting reply"
            count={summary.awaiting_support ?? 0}
            linkLabel="Respond"
            href={openHref}
            needsAction
          />
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2">
          <SupportTile label="Resolved" count={summary.resolved ?? 0} linkLabel="View now" href={resolvedHref} />
          <SupportTile
            label="Need your input"
            count={summary.need_your_input ?? 0}
            linkLabel="Respond"
            href={openHref}
            needsAction
          />
        </div>
      )}
    </section>
  );
}
