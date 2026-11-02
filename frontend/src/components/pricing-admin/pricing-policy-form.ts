// frontend/src/components/pricing-admin/pricing-policy-form.ts
/**
 * Pure form logic for the Settings ▸ Pricing tab (API_CONTRACT §6).
 *
 * The inputs are strings so an empty COD box can mean "not set" (COD stays off).
 * This file only validates and converts what the admin typed; every price is
 * still computed by the backend (Zero Frontend Math).
 */
import { SERVICE_OPTION_OPTIONS } from "@/lib/form-options";
import * as z from "zod";

import {
  ALL_SERVICE_OPTIONS,
  MarkupMode,
  ServiceOption,
  type OptionMarkup,
  type PricingPolicy,
  type PricingPolicyRead,
} from "./pricing-admin-api";

/** Highest percentage the form accepts (anything above is almost surely a typo). */
export const MAX_PERCENT = 100;

/** Highest minimum COD fee the form accepts, in rupees. */
export const MAX_COD_FEE_MIN = 10000;

/** Shown in the change summary for an empty COD value. */
export const NOT_SET_TEXT = "Not set";

/**
 * Display labels for the service options sourced from the central form options.
 */
export const SERVICE_OPTION_LABELS: Readonly<Record<ServiceOption, string>> = {
  [ServiceOption.DELHIVERY_SURFACE]: SERVICE_OPTION_OPTIONS[ServiceOption.DELHIVERY_SURFACE].label,
  [ServiceOption.DELHIVERY_EXPRESS]: SERVICE_OPTION_OPTIONS[ServiceOption.DELHIVERY_EXPRESS].label,
  [ServiceOption.PRIME_SURFACE]: SERVICE_OPTION_OPTIONS[ServiceOption.PRIME_SURFACE].label,
  [ServiceOption.DELHIVERY_B2B_SURFACE]: SERVICE_OPTION_OPTIONS[ServiceOption.DELHIVERY_B2B_SURFACE].label,
};

/** One-line explanation under each option toggle sourced from the central form options. */
export const SERVICE_OPTION_HINTS: Readonly<Record<ServiceOption, string>> = {
  [ServiceOption.DELHIVERY_SURFACE]: SERVICE_OPTION_OPTIONS[ServiceOption.DELHIVERY_SURFACE].description,
  [ServiceOption.DELHIVERY_EXPRESS]: SERVICE_OPTION_OPTIONS[ServiceOption.DELHIVERY_EXPRESS].description,
  [ServiceOption.PRIME_SURFACE]: SERVICE_OPTION_OPTIONS[ServiceOption.PRIME_SURFACE].description,
  [ServiceOption.DELHIVERY_B2B_SURFACE]: SERVICE_OPTION_OPTIONS[ServiceOption.DELHIVERY_B2B_SURFACE].description,
};

/**
 * Checks that a typed value is a finite number within [0, max].
 *
 * @param raw - Text from the input.
 * @param max - Largest allowed value.
 * @returns True when the text parses to a number in range.
 */
function _isNumberInRange(raw: string, max: number): boolean {
  const value = Number(raw.trim());
  return raw.trim() !== "" && Number.isFinite(value) && value >= 0 && value <= max;
}

/** Highest flat markup the form accepts, in rupees per shipment (backend `MARKUP_FLAT_MAX`). */
export const MAX_FLAT_MARKUP = 100000;

/**
 * Prime only: no policy entry, so every Prime lane keeps its own markup % (Prime lanes page).
 * Not a backend mode; it means "leave `option_markups.PRIME_SURFACE` unset".
 */
export const LANE_MARKUP = "LANE" as const;

/** A markup row's mode as shown in the form. */
export type MarkupChoice = MarkupMode | typeof LANE_MARKUP;

/** One option's markup row (value is text so the box can be edited freely). */
export interface MarkupRowValues {
  mode: MarkupChoice;
  value: string;
}

/** Options whose markup can follow each lane (only Prime has lanes). */
const LANE_CAPABLE_OPTIONS: readonly ServiceOption[] = [ServiceOption.PRIME_SURFACE];

/**
 * True when the option can use the per-lane markup choice.
 *
 * @param option - Service option.
 */
export function supportsLaneMarkup(option: ServiceOption): boolean {
  return LANE_CAPABLE_OPTIONS.includes(option);
}

const markupRowSchema = z
  .object({
    mode: z.enum([MarkupMode.PERCENT, MarkupMode.FLAT, LANE_MARKUP]),
    value: z.string(),
  })
  .superRefine((row, ctx) => {
    if (row.mode === LANE_MARKUP) return;
    const max = row.mode === MarkupMode.PERCENT ? MAX_PERCENT : MAX_FLAT_MARKUP;
    if (row.value.trim() === "") {
      ctx.addIssue({ code: "custom", path: ["value"], message: "Required (use 0 for none)" });
    } else if (!_isNumberInRange(row.value, max)) {
      ctx.addIssue({ code: "custom", path: ["value"], message: `Enter a number from 0 to ${max}` });
    }
  });

/**
 * Builds an optional number field: empty means "not set".
 *
 * @param max - Largest allowed value.
 * @returns Zod string schema.
 */
function _optionalNumber(max: number) {
  return z.string().refine((v) => v.trim() === "" || _isNumberInRange(v, max), {
    message: `Enter a number from 0 to ${max}, or leave it empty`,
  });
}

/** Form schema for the Pricing tab. */
export const pricingPolicySchema = z.object({
  markups: z.object({
    [ServiceOption.DELHIVERY_SURFACE]: markupRowSchema,
    [ServiceOption.DELHIVERY_EXPRESS]: markupRowSchema,
    [ServiceOption.DELHIVERY_B2B_SURFACE]: markupRowSchema,
    [ServiceOption.PRIME_SURFACE]: markupRowSchema,
  }),
  cod_fee_min: _optionalNumber(MAX_COD_FEE_MIN),
  cod_fee_percent: _optionalNumber(MAX_PERCENT),
  enabled_options: z.array(z.enum(ServiceOption)),
});

/** Values held by the Pricing tab form. */
export type PricingPolicyFormValues = z.infer<typeof pricingPolicySchema>;

/** One changed setting, for the "Confirm pricing changes" dialog. */
export interface PolicyChange {
  label: string;
  before: string;
  after: string;
}

/**
 * Renders an optional number as input text.
 *
 * @param value - Stored number, or null when not set.
 * @returns The number as text, or "" when not set.
 */
function _toInputText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * Parses input text into an optional number.
 *
 * @param raw - Text from the input.
 * @returns The number, or null when the box is empty.
 */
function _toOptionalNumber(raw: string): number | null {
  return raw.trim() === "" ? null : Number(raw.trim());
}

/**
 * The row shown when the policy has no entry for an option (today's backend default):
 * Delhivery options use `delhivery_markup_percent`, Prime uses each lane's own markup.
 *
 * @param option - Service option.
 * @param policy - Saved policy.
 */
function _defaultMarkupRow(option: ServiceOption, policy: PricingPolicy): MarkupRowValues {
  if (supportsLaneMarkup(option)) return { mode: LANE_MARKUP, value: "" };
  return { mode: MarkupMode.PERCENT, value: _toInputText(policy.delhivery_markup_percent ?? 0) };
}

/**
 * The form row for one option: the stored entry, or the default when there is none.
 *
 * @param option - Service option.
 * @param policy - Saved policy.
 */
function _markupRow(option: ServiceOption, policy: PricingPolicy): MarkupRowValues {
  const entry = policy.option_markups?.[option];
  if (!entry) return _defaultMarkupRow(option, policy);
  return { mode: entry.mode ?? MarkupMode.PERCENT, value: _toInputText(entry.value ?? 0) };
}

/**
 * True when two rows mean the same rule (numbers compared by value, "5" == "5.0").
 *
 * @param a - First row.
 * @param b - Second row.
 */
function _sameRule(a: MarkupRowValues, b: MarkupRowValues): boolean {
  if (a.mode !== b.mode) return false;
  return a.mode === LANE_MARKUP || Number(a.value.trim()) === Number(b.value.trim());
}

/**
 * Converts the API policy into form values.
 *
 * @param policy - Policy from `GET /pricing/policy`.
 * @returns Values for `useForm`.
 */
export function policyToFormValues(policy: PricingPolicy): PricingPolicyFormValues {
  return {
    markups: {
      [ServiceOption.DELHIVERY_SURFACE]: _markupRow(ServiceOption.DELHIVERY_SURFACE, policy),
      [ServiceOption.DELHIVERY_EXPRESS]: _markupRow(ServiceOption.DELHIVERY_EXPRESS, policy),
      [ServiceOption.DELHIVERY_B2B_SURFACE]: _markupRow(ServiceOption.DELHIVERY_B2B_SURFACE, policy),
      [ServiceOption.PRIME_SURFACE]: _markupRow(ServiceOption.PRIME_SURFACE, policy),
    },
    cod_fee_min: _toInputText(policy.cod_fee_min),
    cod_fee_percent: _toInputText(policy.cod_fee_percent),
    enabled_options: ALL_SERVICE_OPTIONS.filter((o) => (policy.enabled_options ?? []).includes(o)),
  };
}

/**
 * Converts validated form values into the `PUT /pricing/policy` body.
 *
 * An option gets an `option_markups` entry only when it already had one or the admin
 * changed it away from the default, so untouched options keep following
 * `delhivery_markup_percent` / the lane markup. Fields the form does not edit
 * (`delhivery_markup_percent`, `prime_default_markup_percent`) are passed through.
 *
 * @param values - Values that passed `pricingPolicySchema`.
 * @param saved - Policy currently saved on the server.
 * @returns The policy to save (empty COD boxes become null).
 */
export function formValuesToPolicy(values: PricingPolicyFormValues, saved: PricingPolicy): PricingPolicy {
  const optionMarkups: Record<string, OptionMarkup> = {};
  for (const option of ALL_SERVICE_OPTIONS) {
    const row = values.markups[option];
    const hadEntry = Boolean(saved.option_markups?.[option]);
    if (row.mode === LANE_MARKUP) continue;
    if (!hadEntry && _sameRule(row, _defaultMarkupRow(option, saved))) continue;
    optionMarkups[option] = { mode: row.mode, value: Number(row.value.trim()) };
  }
  return {
    delhivery_markup_percent: saved.delhivery_markup_percent ?? 0,
    prime_default_markup_percent: saved.prime_default_markup_percent ?? 20,
    cod_fee_min: _toOptionalNumber(values.cod_fee_min),
    cod_fee_percent: _toOptionalNumber(values.cod_fee_percent),
    enabled_options: ALL_SERVICE_OPTIONS.filter((o) => values.enabled_options.includes(o)),
    option_markups: optionMarkups,
  };
}

/**
 * Whether both COD fee boxes are filled in. When not, COD is off for every customer
 * (the backend fails closed); the form shows a banner so the admin knows why.
 *
 * @param values - Current form values.
 * @returns True when both the minimum and the percentage are set.
 */
export function hasCompleteCodFee(values: Pick<PricingPolicyFormValues, "cod_fee_min" | "cod_fee_percent">): boolean {
  return values.cod_fee_min.trim() !== "" && values.cod_fee_percent.trim() !== "";
}

/**
 * Formats a percentage for the change summary.
 *
 * @param value - Percentage, or null when not set.
 * @returns e.g. "20%" or "Not set".
 */
function _formatPercent(value: number | null): string {
  return value === null ? NOT_SET_TEXT : `${value}%`;
}

/**
 * Formats a rupee amount for the change summary.
 *
 * @param value - Rupees, or null when not set.
 * @returns e.g. "₹30" or "Not set".
 */
function _formatRupees(value: number | null): string {
  return value === null ? NOT_SET_TEXT : `₹${value}`;
}

/**
 * Formats the enabled options for the change summary.
 *
 * @param options - Enabled options.
 * @returns Comma-separated labels, or "None".
 */
function _formatOptions(options: readonly ServiceOption[]): string {
  const labels = ALL_SERVICE_OPTIONS.filter((o) => options.includes(o)).map(
    (o) => SERVICE_OPTION_LABELS[o],
  );
  return labels.length > 0 ? labels.join(", ") : "None";
}

/**
 * Plain-English markup rule for the change summary and the read-only view.
 *
 * @param row - Markup row.
 * @returns e.g. "10%", "₹25 per shipment" or "Each lane's own markup".
 */
export function describeMarkup(row: MarkupRowValues): string {
  if (row.mode === LANE_MARKUP) return "Each lane's own markup";
  const value = Number(row.value.trim());
  return row.mode === MarkupMode.FLAT ? `₹${value} per shipment` : `${value}%`;
}

/**
 * Lists the settings that differ between the saved policy and the new one.
 *
 * @param before - Policy currently saved on the server.
 * @param after - Policy about to be saved.
 * @returns One entry per changed setting, in form order (empty when nothing changed).
 */
export function describePolicyChanges(
  before: PricingPolicy,
  after: PricingPolicy,
): PolicyChange[] {
  const markupRows: PolicyChange[] = ALL_SERVICE_OPTIONS.map((option) => ({
    label: `${SERVICE_OPTION_LABELS[option]} markup`,
    before: describeMarkup(_markupRow(option, before)),
    after: describeMarkup(_markupRow(option, after)),
  }));
  const rows: PolicyChange[] = markupRows.concat([
    {
      label: "COD fee minimum",
      before: _formatRupees(before.cod_fee_min ?? null),
      after: _formatRupees(after.cod_fee_min ?? null),
    },
    {
      label: "COD fee percentage",
      before: _formatPercent(before.cod_fee_percent ?? null),
      after: _formatPercent(after.cod_fee_percent ?? null),
    },
    {
      label: "Services customers can book",
      before: _formatOptions(before.enabled_options ?? []),
      after: _formatOptions(after.enabled_options ?? []),
    },
  ]);
  return rows.filter((row) => row.before !== row.after);
}

/**
 * Picks the editable policy out of the GET/PUT response.
 *
 * @param read - Response including the computed flags.
 * @returns The editable part only.
 */
export function toEditablePolicy(read: PricingPolicyRead): PricingPolicy {
  return {
    delhivery_markup_percent: read.delhivery_markup_percent ?? 0,
    prime_default_markup_percent: read.prime_default_markup_percent ?? 20,
    cod_fee_percent: read.cod_fee_percent ?? null,
    cod_fee_min: read.cod_fee_min ?? null,
    enabled_options: read.enabled_options ?? [],
    option_markups: read.option_markups ?? {},
  };
}
