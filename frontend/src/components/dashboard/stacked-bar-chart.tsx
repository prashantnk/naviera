// frontend/src/components/dashboard/stacked-bar-chart.tsx
"use client";

import type { DashboardDailyPoint } from "@/api_client";
import { cn } from "@/lib/utils";
import { BarChart3 } from "lucide-react";
import { useMemo } from "react";

import { buildChartModel, CHART_SERIES, type ChartBar } from "./chart-model";

interface StackedDailyBarChartProps {
  /** `daily_series` exactly as returned by the dashboard summary API. */
  series: readonly DashboardDailyPoint[];
  /** Accessible name, e.g. "Daily shipment movement, last 7 days". */
  title: string;
  /** Dims the chart while a new window is loading. */
  isRefreshing?: boolean;
  /** Message shown when nothing moved during the window. */
  emptyMessage?: string;
  className?: string;
}

/**
 * Builds the hover/title text for one day's bar.
 *
 * @param bar - Bar from the chart model.
 * @returns e.g. "8 Oct: In Transit 3, Delivered 2, Returned 0".
 */
function _barTooltip(bar: ChartBar): string {
  const parts = bar.segments.map((segment) => `${segment.label} ${segment.count}`);
  return `${bar.dateLabel}: ${parts.join(", ")}`;
}

/**
 * Dependency-free stacked daily bar chart (In Transit / Delivered / Returned).
 *
 * Rendered with plain CSS flexbox so it is responsive without measuring the
 * DOM. Bars are decorative for assistive tech; the same numbers are exposed
 * in a visually hidden data table.
 */
export function StackedDailyBarChart({
  series,
  title,
  isRefreshing = false,
  emptyMessage = "No shipment movement in this period yet.",
  className,
}: StackedDailyBarChartProps) {
  const model = useMemo(() => buildChartModel(series), [series]);

  return (
    <figure
      aria-label={title}
      aria-busy={isRefreshing}
      className={cn("transition-opacity", isRefreshing && "opacity-60", className)}
    >
      {model.isEmpty ? (
        <div className="flex h-56 flex-col items-center justify-center gap-2 rounded-lg border border-dashed text-center">
          <BarChart3 className="h-6 w-6 text-muted-foreground" aria-hidden />
          <p className="text-sm text-muted-foreground">{emptyMessage}</p>
        </div>
      ) : (
        <div aria-hidden className="flex h-56 flex-col">
          <div className="flex min-h-0 flex-1 gap-2">
            {/* Y axis labels (same height as the plot area) */}
            <div className="relative w-8 shrink-0 text-right text-[10px] tabular-nums text-muted-foreground">
              {model.yTicks.map((tick) => (
                <span
                  key={tick.value}
                  className="absolute right-0 translate-y-1/2 leading-none"
                  style={{ bottom: `${tick.offsetPercent}%` }}
                >
                  {tick.value.toLocaleString("en-IN")}
                </span>
              ))}
            </div>

            {/* Plot area: gridlines + bars */}
            <div className="relative min-w-0 flex-1 border-b">
              {model.yTicks.map((tick) => (
                <div
                  key={tick.value}
                  className="absolute inset-x-0 border-t border-dashed border-border"
                  style={{ bottom: `${tick.offsetPercent}%` }}
                />
              ))}
              <div className="absolute inset-0 flex items-end gap-1 sm:gap-1.5">
                {model.bars.map((bar) => (
                  <div
                    key={bar.date}
                    data-testid="chart-bar"
                    title={_barTooltip(bar)}
                    className="flex h-full min-w-0 flex-1 justify-center"
                  >
                    <div className="flex h-full w-full max-w-10 flex-col-reverse">
                      {bar.segments.map((segment) => (
                        <div
                          key={segment.key}
                          data-testid={`chart-segment-${segment.key}`}
                          className={cn(
                            "w-full transition-[height] duration-300",
                            segment.swatchClassName
                          )}
                          style={{ height: `${segment.heightPercent}%` }}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          {/* X axis date ticks, centred under their bar and never truncated */}
          <div className="mt-1.5 flex h-4 gap-2">
            <div className="w-8 shrink-0" />
            <div className="flex min-w-0 flex-1 gap-1 sm:gap-1.5">
              {model.bars.map((bar) => (
                <span key={bar.date} className="relative min-w-0 flex-1">
                  {bar.showTick && (
                    <span className="absolute left-1/2 top-0 -translate-x-1/2 whitespace-nowrap text-[10px] text-muted-foreground">
                      {bar.dateLabel}
                    </span>
                  )}
                </span>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Legend */}
      <figcaption className="mt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
        {CHART_SERIES.map((meta) => (
          <span key={meta.key} className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <span aria-hidden className={cn("h-2.5 w-2.5 rounded-sm", meta.swatchClassName)} />
            {meta.label}
          </span>
        ))}
      </figcaption>

      {/* Screen-reader equivalent of the bars */}
      <table className="sr-only">
        <caption>{title}</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            {CHART_SERIES.map((meta) => (
              <th key={meta.key} scope="col">
                {meta.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {model.bars.map((bar) => (
            <tr key={bar.date}>
              <th scope="row">{bar.dateLabel}</th>
              {bar.segments.map((segment) => (
                <td key={segment.key}>{segment.count}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </figure>
  );
}
