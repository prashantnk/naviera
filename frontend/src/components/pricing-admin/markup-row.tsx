// frontend/src/components/pricing-admin/markup-row.tsx
"use client";

/**
 * One "Markups" row of Settings ▸ Pricing: the service, a mode (% of the carrier cost,
 * a fixed ₹ per shipment, or, for Logismart Prime, each lane's own markup) and a value.
 *
 * Only edits form values; the price itself is always computed by the backend
 * (`services/pricing/sell_price.py`), so this file holds no money math.
 */
import { useWatch, type Control } from "react-hook-form";

import { FormControl, FormField, FormItem, FormMessage } from "@/components/ui/form";
import { InputAdornment } from "@/components/ui/form-extras";
import { Input } from "@/components/ui/input";

import { MarkupMode, type ServiceOption } from "./pricing-admin-api";
import {
  LANE_MARKUP,
  SERVICE_OPTION_HINTS,
  SERVICE_OPTION_LABELS,
  supportsLaneMarkup,
  type MarkupChoice,
  type PricingPolicyFormValues,
} from "./pricing-policy-form";

const TEST_ID = "pricing-policy.markup";

/** Labels of the mode dropdown. */
const MODE_LABELS: Readonly<Record<MarkupChoice, string>> = {
  [MarkupMode.PERCENT]: "% of carrier cost",
  [MarkupMode.FLAT]: "₹ per shipment",
  [LANE_MARKUP]: "Each lane's own markup",
};

interface MarkupRowProps {
  option: ServiceOption;
  canEdit: boolean;
  control: Control<PricingPolicyFormValues>;
}

/**
 * Renders the markup controls for one service option.
 *
 * @param props - The option, edit permission and the panel's form control.
 */
export function MarkupRow({ option, canEdit, control }: MarkupRowProps) {
  const mode = useWatch({ control, name: `markups.${option}.mode` });
  const choices: MarkupChoice[] = supportsLaneMarkup(option)
    ? [LANE_MARKUP, MarkupMode.PERCENT, MarkupMode.FLAT]
    : [MarkupMode.PERCENT, MarkupMode.FLAT];
  const testId = `${TEST_ID}.${option}`;

  return (
    <div
      className="grid grid-cols-1 items-start gap-3 rounded-xl border border-slate-200 bg-white p-3 min-w-0 overflow-hidden sm:grid-cols-12"
      data-testid={testId}
    >
      <div className="min-w-0 sm:col-span-5">
        <p className="text-xs font-bold text-slate-900 break-words">{SERVICE_OPTION_LABELS[option]}</p>
        <p className="text-[11px] text-slate-500 break-words">{SERVICE_OPTION_HINTS[option]}</p>
      </div>
      <FormField
        control={control}
        name={`markups.${option}.mode`}
        render={({ field }) => (
          <FormItem className="min-w-0 sm:col-span-4">
            <FormControl>
              <select
                value={field.value}
                onChange={(e) => field.onChange(e.target.value as MarkupChoice)}
                disabled={!canEdit}
                aria-label={`${SERVICE_OPTION_LABELS[option]} markup type`}
                data-testid={`${testId}.mode`}
                className="h-9 min-w-0 w-full rounded-md border border-slate-200 bg-white px-2 text-xs font-semibold text-slate-700 disabled:opacity-60"
              >
                {choices.map((choice) => (
                  <option key={choice} value={choice}>
                    {MODE_LABELS[choice]}
                  </option>
                ))}
              </select>
            </FormControl>
          </FormItem>
        )}
      />
      <FormField
        control={control}
        name={`markups.${option}.value`}
        render={({ field }) => (
          <FormItem className="min-w-0 sm:col-span-3">
            {mode === LANE_MARKUP ? (
              <p className="py-2 text-[11px] text-slate-500 break-words">Set per lane on the Prime lanes page.</p>
            ) : (
              <>
                <FormControl>
                  <InputAdornment
                    prefix={mode === MarkupMode.FLAT ? "₹" : undefined}
                    suffix={mode === MarkupMode.PERCENT ? "%" : undefined}
                  >
                    <Input
                      {...field}
                      inputMode="decimal"
                      disabled={!canEdit}
                      aria-label={`${SERVICE_OPTION_LABELS[option]} markup value`}
                      data-testid={`${testId}.value`}
                      className="min-w-0 w-full bg-white font-mono"
                    />
                  </InputAdornment>
                </FormControl>
                <FormMessage />
              </>
            )}
          </FormItem>
        )}
      />
    </div>
  );
}
