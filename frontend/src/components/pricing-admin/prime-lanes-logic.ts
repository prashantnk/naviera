// frontend/src/components/pricing-admin/prime-lanes-logic.ts
/**
 * Pure helpers for the Prime lanes editor: inline-edit validation, the PATCH body,
 * the search filter, CSV file checks and the plain-English import report.
 *
 * Nothing here prices a shipment. The editor only stores the transporter's rates;
 * the backend turns them into customer prices (Zero Frontend Math).
 */
import type { PrimeImportIssue, PrimeImportReport, PrimeLanePatch, PrimeLaneRead } from "./pricing-admin-api";

/** Numeric lane fields the inline editor changes. */
export type EditableLaneField = "tat_hours" | "rate_per_kg" | "min_lr_charge" | "docket_charge" | "markup_percent";

/** Text the admin typed per editable field while a row is in edit mode. */
export type LaneDraft = Record<EditableLaneField, string>;

/** Validation messages per field (only fields with a problem are present). */
export type LaneDraftErrors = Partial<Record<EditableLaneField, string>>;

/** How a field is shown and checked in the table. */
export interface EditableLaneColumn {
  field: EditableLaneField;
  label: string;
  prefix?: string;
  suffix?: string;
  /** True when 0 is not a valid value. */
  mustBePositive: boolean;
  /** True when only whole numbers are allowed. */
  wholeNumber: boolean;
  max: number;
}

/** Largest CSV the importer accepts from the browser (1 MB is ~10,000 lanes). */
export const MAX_CSV_BYTES = 1024 * 1024;

const MAX_TAT_HOURS = 720;
const MAX_RUPEES = 100000;
const MAX_MARKUP_PERCENT = 100;
const CSV_EXTENSION = ".csv";

/** Editable columns, in table order. */
export const EDITABLE_LANE_COLUMNS: readonly EditableLaneColumn[] = [
  { field: "tat_hours", label: "TAT", suffix: "h", mustBePositive: true, wholeNumber: true, max: MAX_TAT_HOURS },
  { field: "rate_per_kg", label: "Rate / kg", prefix: "₹", mustBePositive: true, wholeNumber: false, max: MAX_RUPEES },
  { field: "min_lr_charge", label: "Min LR", prefix: "₹", mustBePositive: false, wholeNumber: false, max: MAX_RUPEES },
  { field: "docket_charge", label: "Docket", prefix: "₹", mustBePositive: false, wholeNumber: false, max: MAX_RUPEES },
  {
    field: "markup_percent",
    label: "Markup",
    suffix: "%",
    mustBePositive: false,
    wholeNumber: false,
    max: MAX_MARKUP_PERCENT,
  },
];

/**
 * Copies a lane's editable numbers into input text.
 *
 * @param lane - Lane from the API.
 * @returns Draft text for every editable field.
 */
export function laneToDraft(lane: PrimeLaneRead): LaneDraft {
  return {
    tat_hours: String(lane.tat_hours),
    rate_per_kg: String(lane.rate_per_kg),
    min_lr_charge: String(lane.min_lr_charge),
    docket_charge: String(lane.docket_charge),
    markup_percent: String(lane.markup_percent),
  };
}

/**
 * Checks one typed value against its column rules.
 *
 * @param raw - Text from the input.
 * @param column - Column rules.
 * @returns A plain-English problem, or null when the value is fine.
 */
function _validateField(raw: string, column: EditableLaneColumn): string | null {
  const text = raw.trim();
  if (text === "") return `${column.label} is required`;
  const value = Number(text);
  if (!Number.isFinite(value)) return `${column.label} must be a number`;
  if (column.mustBePositive ? value <= 0 : value < 0) {
    return column.mustBePositive ? `${column.label} must be more than 0` : `${column.label} cannot be negative`;
  }
  if (column.wholeNumber && !Number.isInteger(value)) return `${column.label} must be a whole number`;
  if (value > column.max) return `${column.label} cannot be more than ${column.max}`;
  return null;
}

/**
 * Validates a draft row and builds the PATCH body with only the changed fields.
 *
 * @param lane - The lane as last saved.
 * @param draft - What the admin typed.
 * @returns `errors` per field, and `patch` (empty when nothing changed or anything is invalid).
 */
export function buildLanePatch(
  lane: PrimeLaneRead,
  draft: LaneDraft,
): { patch: PrimeLanePatch; errors: LaneDraftErrors } {
  const errors: LaneDraftErrors = {};
  const patch: PrimeLanePatch = {};
  for (const column of EDITABLE_LANE_COLUMNS) {
    const problem = _validateField(draft[column.field], column);
    if (problem) {
      errors[column.field] = problem;
      continue;
    }
    const value = Number(draft[column.field].trim());
    if (value !== lane[column.field]) patch[column.field] = value;
  }
  return { patch: Object.keys(errors).length > 0 ? {} : patch, errors };
}

/**
 * Filters lanes by a free-text search over zones and transporter.
 *
 * @param lanes - Lanes from the API.
 * @param query - What the admin typed in the search box.
 * @returns Matching lanes, in the original order.
 */
export function filterLanes(lanes: readonly PrimeLaneRead[], query: string): PrimeLaneRead[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return lanes.slice();
  return lanes.filter((lane) =>
    [lane.origin_zone, lane.dest_zone, lane.transporter_name].some((text) =>
      text.toLowerCase().includes(needle),
    ),
  );
}

/**
 * Checks a chosen file before uploading it.
 *
 * @param file - File from the picker.
 * @returns A plain-English problem, or null when the file can be sent.
 */
export function validateCsvFile(file: Pick<File, "name" | "size">): string | null {
  if (!file.name.toLowerCase().endsWith(CSV_EXTENSION)) {
    return "Choose a .csv file (download the current lanes to get the right format).";
  }
  if (file.size === 0) return "This file is empty.";
  if (file.size > MAX_CSV_BYTES) return "This file is larger than 1 MB. Split it or remove unused rows.";
  return null;
}

/**
 * Formats one importer issue as a line of text.
 *
 * @param issue - Error or warning from the import report.
 * @returns e.g. "Row 12: rate_per_kg must be a number".
 */
export function formatImportIssue(issue: PrimeImportIssue): string {
  return issue.row === null || issue.row === undefined ? issue.message : `Row ${issue.row}: ${issue.message}`;
}

/** Plain-English summary of an import report. */
export interface ImportSummary {
  /** One sentence describing the change counts. */
  headline: string;
  /** True when the server would write nothing because of row errors. */
  blocked: boolean;
  /** True when the file changes nothing at all. */
  noChanges: boolean;
}

/**
 * Pluralises a lane count, e.g. "1 lane" / "3 lanes".
 *
 * @param count - Number of lanes.
 * @returns Count with the right noun.
 */
function _lanes(count: number): string {
  return count === 1 ? "1 lane" : `${count} lanes`;
}

/**
 * Summarises an import report for the preview and the result toast.
 * The importer is all-or-nothing: any row error means nothing is written.
 *
 * @param report - Report from `POST /prime-lanes/import`.
 * @param dryRun - True for the preview ("will"), false after importing ("were").
 * @returns Headline plus the blocked / no-change flags.
 */
export function summarizeImportReport(report: PrimeImportReport, dryRun: boolean): ImportSummary {
  const blocked = report.errors.length > 0;
  const noChanges = report.created === 0 && report.updated === 0 && report.deactivated === 0;
  if (blocked) {
    const rows = report.errors.length === 1 ? "1 row has a problem" : `${report.errors.length} rows have problems`;
    return { headline: `${rows}. Nothing will be imported until the file is fixed.`, blocked, noChanges };
  }
  if (noChanges) {
    return { headline: "This file matches your current lanes. Nothing would change.", blocked, noChanges };
  }
  const verb = dryRun ? "will be" : "were";
  const headline =
    `${_lanes(report.created)} ${verb} added, ${_lanes(report.updated)} ${verb} updated ` +
    `and ${_lanes(report.deactivated)} ${verb} switched off.`;
  return { headline, blocked, noChanges };
}
