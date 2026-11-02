// frontend/src/components/dashboard/dashboard-section.tsx
"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { AlertTriangle, RotateCw } from "lucide-react";

interface DashboardSectionProps {
  title: string;
  description?: string;
  /** Right-aligned header content (e.g. the 7D / 14D / 30D toggle). */
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** Element id used for `aria-labelledby` on the section landmark. */
  headingId: string;
}

/**
 * White card shell shared by every dashboard block (Delhivery "Order summary",
 * "Performance", "Appointment management").
 */
export function DashboardSection({
  title,
  description,
  actions,
  children,
  className,
  headingId,
}: DashboardSectionProps) {
  return (
    <section
      aria-labelledby={headingId}
      className={cn("rounded-xl border bg-card p-4 shadow-sm sm:p-5", className)}
    >
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id={headingId} className="text-base font-semibold text-foreground">
            {title}
          </h2>
          {description && (
            <p className="mt-0.5 text-xs text-muted-foreground">{description}</p>
          )}
        </div>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** Pulsing placeholder block used by loading skeletons. */
export function SkeletonBlock({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-muted", className)} />;
}

interface DashboardErrorStateProps {
  message: string;
  onRetry: () => void;
}

/** Inline error panel with a retry button. */
export function DashboardErrorState({ message, onRetry }: DashboardErrorStateProps) {
  return (
    <div
      role="alert"
      className="flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-rose-200 bg-rose-50/60 px-4 py-8 text-center"
    >
      <AlertTriangle className="h-6 w-6 text-rose-600" aria-hidden />
      <p className="text-sm font-medium text-rose-900">{message}</p>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>
        <RotateCw className="mr-1.5 h-3.5 w-3.5" aria-hidden />
        Retry
      </Button>
    </div>
  );
}
