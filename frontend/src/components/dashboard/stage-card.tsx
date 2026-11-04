// frontend/src/components/dashboard/stage-card.tsx
"use client";

import { cn } from "@/lib/utils";
import { ChevronRight, Info, type LucideIcon } from "lucide-react";
import Link from "next/link";

interface StageCardProps {
  title: string;
  icon: LucideIcon;
  children: React.ReactNode;
  /** Optional strip of quick links under the tiles (e.g. "View returned"). */
  footer?: React.ReactNode;
}

/**
 * One lifecycle stage column (e.g. "Pre-Shipping") holding clickable tiles,
 * modelled on Delhivery One's "Order summary" cards.
 */
export function StageCard({ title, icon: Icon, children, footer }: StageCardProps) {
  return (
    <div className="flex min-w-0 flex-col rounded-lg border bg-muted/40">
      <div className="flex items-center gap-2 px-3 py-2.5">
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      </div>
      <div className="flex flex-1 flex-col gap-2 px-2 pb-2">{children}</div>
      {footer && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t px-3 py-2">
          {footer}
        </div>
      )}
    </div>
  );
}

interface StageTileProps {
  label: string;
  count: number;
  href: string;
  /** Optional explanation rendered as an info icon next to the label. */
  hint?: string;
  /** Optional quick link rendered under the tile (e.g. "Create PUR"). */
  footer?: React.ReactNode;
}

/**
 * Clickable stage counter: label + chevron on top, large count below.
 */
export function StageTile({ label, count, href, hint, footer }: StageTileProps) {
  return (
    <div className="overflow-hidden rounded-md border bg-card shadow-xs">
      <Link
        href={href}
        prefetch={true}
        className="group block px-3 py-2.5 outline-none transition-colors hover:bg-primary/5 active:bg-primary/10 focus-visible:bg-primary/5 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
        aria-label={`${label}: ${count}`}
      >
        <span className="flex items-center justify-between gap-2">
          <span className="flex min-w-0 items-center gap-1 text-xs font-medium text-muted-foreground">
            <span className="truncate">{label}</span>
            {hint && (
              <span title={hint} className="inline-flex shrink-0">
                <Info className="h-3 w-3" aria-hidden />
                <span className="sr-only">{hint}</span>
              </span>
            )}
          </span>
          <ChevronRight
            className="h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary"
            aria-hidden
          />
        </span>
        <span className="mt-1 block text-xl font-bold tabular-nums text-foreground">
          {count.toLocaleString("en-IN")}
        </span>
      </Link>
      {footer && <div className="border-t bg-muted/40 px-3 py-1.5">{footer}</div>}
    </div>
  );
}

interface StageQuickLinkProps {
  href: string;
  label: string;
  /** Optional count chip shown before the label. */
  count?: number;
  className?: string;
}

/** Small "› link" used in tile and card footers (e.g. "2 View returned ›"). */
export function StageQuickLink({ href, label, count, className }: StageQuickLinkProps) {
  return (
    <Link
      href={href}
      prefetch={true}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-sm text-[11px] font-medium text-foreground/80 outline-none hover:text-primary focus-visible:ring-2 focus-visible:ring-ring",
        className
      )}
    >
      {count !== undefined && (
        <span className="rounded border bg-card px-1.5 py-px text-[10px] font-semibold tabular-nums">
          {count.toLocaleString("en-IN")}
        </span>
      )}
      {label}
      <ChevronRight className="h-3 w-3" aria-hidden />
    </Link>
  );
}

/** Skeleton for a stage card with `tiles` placeholder tiles. */
export function StageCardSkeleton({ tiles }: { tiles: number }) {
  return (
    <div aria-hidden className="flex flex-col gap-2 rounded-lg border bg-muted/40 p-2">
      <div className="h-4 w-24 animate-pulse rounded bg-muted" />
      {Array.from({ length: tiles }, (_, index) => (
        <div key={index} className="h-16 animate-pulse rounded-md bg-card" />
      ))}
    </div>
  );
}
