// frontend/src/components/dashboard/chart-model.ts
/**
 * Pure layout model for the stacked daily bar chart.
 *
 * Converts the backend `daily_series` counts into bar segment heights (as a
 * percentage of the chart's height), "nice" y-axis ticks and x-axis tick
 * visibility. This is purely visual scaling of shipment counts: it never
 * derives a business metric (Zero Frontend Math directive).
 */

import type { DashboardDailyPoint } from "@/api_client";

import { formatDayLabel } from "./dashboard-model";

/** Series keys in stacking order (first = bottom of the bar). */
export type ChartSeriesKey = "in_transit" | "delivered" | "returned";

/** Static description of one stacked series (legend + segment colour). */
export interface ChartSeriesMeta {
  key: ChartSeriesKey;
  label: string;
  /** Tailwind class for the segment / legend swatch (status palette). */
  swatchClassName: string;
}

/** Legend + stacking order shown under the chart. */
export const CHART_SERIES: readonly ChartSeriesMeta[] = [
  { key: "in_transit", label: "In Transit", swatchClassName: "bg-sky-400" },
  { key: "delivered", label: "Delivered", swatchClassName: "bg-emerald-500" },
  { key: "returned", label: "Returned", swatchClassName: "bg-rose-500" },
];

/** Target number of y-axis intervals (gives 4-6 gridlines). */
const TARGET_Y_INTERVALS = 4;

/** Maximum number of x-axis date labels before we start skipping days. */
const MAX_X_TICK_LABELS = 7;

/** "Nice" step multipliers, applied to powers of ten. */
const NICE_STEP_MULTIPLIERS: readonly number[] = [1, 2, 5, 10];

/** Full height of the plot area, in percent. */
const FULL_HEIGHT_PERCENT = 100;

/** One coloured slice of a stacked bar. */
export interface ChartSegment {
  key: ChartSeriesKey;
  label: string;
  count: number;
  swatchClassName: string;
  /** Height relative to the plot area (0-100). */
  heightPercent: number;
}

/** One day's stacked bar. */
export interface ChartBar {
  date: string;
  dateLabel: string;
  /** Whether this day's date label is rendered on the x axis. */
  showTick: boolean;
  /** Sum of the stacked counts (bar height in shipments). */
  stackCount: number;
  segments: ChartSegment[];
}

/** One horizontal gridline / y-axis label. */
export interface ChartYTick {
  value: number;
  /** Offset from the bottom of the plot area (0-100). */
  offsetPercent: number;
}

/** Everything the chart component needs to render. */
export interface ChartModel {
  bars: ChartBar[];
  yTicks: ChartYTick[];
  axisMax: number;
  /** True when no shipment moved on any day of the window. */
  isEmpty: boolean;
}

/**
 * Picks a human-friendly y-axis step (1, 2, 5 x 10^n) for the tallest bar.
 *
 * @param peak - Tallest stacked bar in shipments (must be > 0).
 * @returns Step size; at least 1 because counts are integers.
 */
export function niceAxisStep(peak: number): number {
  const rawStep = peak / TARGET_Y_INTERVALS;
  if (rawStep <= 1) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const multiplier =
    NICE_STEP_MULTIPLIERS.find((candidate) => candidate * magnitude >= rawStep) ??
    NICE_STEP_MULTIPLIERS[NICE_STEP_MULTIPLIERS.length - 1];
  return multiplier * magnitude;
}

/**
 * Sums the three stacked counts for one day.
 *
 * @param point - One `daily_series` entry.
 * @returns Shipments stacked in that day's bar.
 */
function _stackCount(point: DashboardDailyPoint): number {
  return point.in_transit + point.delivered + point.returned;
}

/**
 * Builds the y-axis ticks from 0 up to `axisMax` in `step` increments.
 *
 * @param axisMax - Top of the axis.
 * @param step - Distance between ticks.
 * @returns Ticks with their offset from the bottom of the plot.
 */
function _buildYTicks(axisMax: number, step: number): ChartYTick[] {
  const ticks: ChartYTick[] = [];
  for (let value = 0; value <= axisMax; value += step) {
    ticks.push({ value, offsetPercent: (value / axisMax) * FULL_HEIGHT_PERCENT });
  }
  return ticks;
}

/**
 * Converts a day into its stacked bar description.
 *
 * @param point - One `daily_series` entry.
 * @param index - Position in the series (drives tick skipping).
 * @param tickInterval - Show every `tickInterval`-th date label.
 * @param axisMax - Top of the y axis (0 when the window is empty).
 * @returns Bar with per-series segment heights.
 */
function _buildBar(
  point: DashboardDailyPoint,
  index: number,
  tickInterval: number,
  axisMax: number
): ChartBar {
  const segments = CHART_SERIES.map((series) => {
    const count = point[series.key];
    return {
      key: series.key,
      label: series.label,
      count,
      swatchClassName: series.swatchClassName,
      heightPercent: axisMax > 0 ? (count / axisMax) * FULL_HEIGHT_PERCENT : 0,
    };
  });
  return {
    date: point.date,
    dateLabel: formatDayLabel(point.date),
    showTick: index % tickInterval === 0,
    stackCount: _stackCount(point),
    segments,
  };
}

/**
 * Builds the full render model for the stacked daily bar chart.
 *
 * @param series - `daily_series` from the dashboard summary response.
 * @returns Bars, y ticks, axis maximum and empty flag.
 */
export function buildChartModel(series: readonly DashboardDailyPoint[]): ChartModel {
  const peak = series.reduce((highest, point) => Math.max(highest, _stackCount(point)), 0);
  const isEmpty = peak === 0;
  const step = isEmpty ? 1 : niceAxisStep(peak);
  const axisMax = isEmpty ? 0 : Math.ceil(peak / step) * step;
  const tickInterval = Math.max(1, Math.ceil(series.length / MAX_X_TICK_LABELS));

  return {
    bars: series.map((point, index) => _buildBar(point, index, tickInterval, axisMax)),
    yTicks: isEmpty ? [] : _buildYTicks(axisMax, step),
    axisMax,
    isEmpty,
  };
}
