// frontend/src/components/dashboard/metric-tile.tsx
"use client";

import { cn } from "@/lib/utils";

import { MISSING_METRIC_HINT, MISSING_METRIC_PLACEHOLDER } from "./dashboard-model";
import { HintTooltip } from "./hint-tooltip";

interface MetricTileProps {
  label: string;
  /** Already-formatted value (use the `format*Metric` helpers). */
  formattedValue: string;
  /** Optional footer (e.g. a "View all" link). */
  footer?: React.ReactNode;
  className?: string;
}

/**
 * Read-only KPI tile. When the backend sent `null` (formatted as the
 * placeholder), the value gets a "Not enough data yet" tooltip instead of a
 * fake number.
 */
export function MetricTile({ label, formattedValue, footer, className }: MetricTileProps) {
  const isMissing = formattedValue === MISSING_METRIC_PLACEHOLDER;
  return (
    <div className={cn("flex min-w-0 flex-col rounded-lg border bg-card px-3 py-3", className)}>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <div className="mt-1.5 flex items-end justify-between gap-2">
        {isMissing ? (
          <HintTooltip hint={MISSING_METRIC_HINT}>
            <span className="text-lg font-bold text-muted-foreground" aria-label={`${label}: ${MISSING_METRIC_HINT}`}>
              {MISSING_METRIC_PLACEHOLDER}
            </span>
          </HintTooltip>
        ) : (
          <span className="text-lg font-bold tabular-nums text-foreground">{formattedValue}</span>
        )}
        {footer}
      </div>
    </div>
  );
}
