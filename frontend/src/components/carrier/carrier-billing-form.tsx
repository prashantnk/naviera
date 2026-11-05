// frontend/src/components/carrier/carrier-billing-form.tsx
"use client";

/**
 * "Enter carrier booking" form (pricing redesign D7, ops part).
 *
 * Ops book the parcel on one.delhivery.com, then paste the Delhivery AWB (required) and,
 * when known, the weight and amount Delhivery charged. The form only validates and sends
 * these values; the backend stores them and decides whether there is a billing gap.
 *
 * A duplicate AWB comes back as HTTP 409 with a plain-English message, which is shown
 * under the AWB field (and as a toast) so ops can fix the typo.
 *
 * Spring analogy: a Thymeleaf form bound to a `@Valid` DTO, posting to a `@PutMapping`.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Save } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { InputAdornment, RequiredMark } from "@/components/ui/form-extras";
import { Input } from "@/components/ui/input";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { extractApiErrorMessage } from "@/lib/utils";

import {
  awbFieldCopy,
  isDuplicateAwbError,
  saveCarrierBilling,
  type CarrierBillingRead,
  type CarrierBillingUpdate,
} from "./carrier-api";

/** Longest AWB we accept (Delhivery waybills are 12–14 digits; leaves headroom). */
const AWB_MAX_LENGTH = 40;

/** Root `data-testid` of the form; fields append `.awb`, `.charged-weight`, … */
export const CARRIER_FORM_TESTID = "carrier-billing.form";

/**
 * Validates an optional decimal text input.
 *
 * @param raw - Text typed by the user (may be blank).
 * @param allowZero - Whether `0` is a valid value.
 * @returns True when blank or a finite number in range.
 */
function _isOptionalNumber(raw: string, allowZero: boolean): boolean {
  if (!raw.trim()) return true;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return false;
  return allowZero ? parsed >= 0 : parsed > 0;
}

const carrierBillingSchema = z.object({
  carrier_awb: z
    .string()
    .trim()
    .min(1, "Enter the AWB from one.delhivery.com.")
    .max(AWB_MAX_LENGTH, `AWB must be at most ${AWB_MAX_LENGTH} characters.`),
  charged_weight_kg: z
    .string()
    .refine((raw) => _isOptionalNumber(raw, false), "Enter a weight above 0 kg, or leave it blank."),
  charged_amount: z
    .string()
    .refine((raw) => _isOptionalNumber(raw, true), "Enter an amount of ₹0 or more, or leave it blank."),
});

type CarrierBillingFormValues = z.infer<typeof carrierBillingSchema>;

/**
 * Converts a nullable API number into the text an input shows.
 *
 * @param value - Number from the API.
 * @returns The number as text, or an empty string.
 */
function _toInputText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * Converts optional input text into the JSON number the API expects.
 *
 * @param raw - Validated text (blank or numeric).
 * @returns The parsed number, or null when blank.
 */
function _toOptionalNumber(raw: string): number | null {
  return raw.trim() ? Number(raw) : null;
}

/**
 * Builds the PUT body from the validated form values.
 *
 * @param values - Values that passed the zod schema.
 * @returns The `CarrierBillingUpdate` payload.
 */
function _toPayload(values: CarrierBillingFormValues): CarrierBillingUpdate {
  return {
    carrier_awb: values.carrier_awb.trim(),
    charged_weight_kg: _toOptionalNumber(values.charged_weight_kg),
    charged_amount: _toOptionalNumber(values.charged_amount),
  };
}

export interface CarrierBillingFormProps {
  shipmentId: string;
  tenantSlug?: string | null;
  /** Current values, used to pre-fill the inputs when editing. */
  initial?: CarrierBillingRead | null;
  /** Called with the backend's response after a successful save. */
  onSaved: (billing: CarrierBillingRead) => void;
  onCancel: () => void;
}

/**
 * Renders the AWB / charged weight / charged amount form and saves it.
 *
 * @param props - See {@link CarrierBillingFormProps}.
 */
export function CarrierBillingForm({
  shipmentId,
  tenantSlug,
  initial,
  onSaved,
  onCancel,
}: CarrierBillingFormProps) {
  const { pending: submitting, run: runSubmit } = useSingleFlight();
  const awbCopy = awbFieldCopy(initial?.service_option);
  const form = useForm<CarrierBillingFormValues>({
    resolver: zodResolver(carrierBillingSchema),
    defaultValues: {
      carrier_awb: initial?.carrier_awb ?? "",
      charged_weight_kg: _toInputText(initial?.charged_weight_kg),
      charged_amount: _toInputText(initial?.charged_amount),
    },
  });

  const onSubmit = async (values: CarrierBillingFormValues) => {
    await runSubmit(async () => {
      try {
        const saved = await saveCarrierBilling(shipmentId, _toPayload(values), tenantSlug);
        toast.success("Carrier booking saved.");
        onSaved(saved);
      } catch (err) {
        const message = extractApiErrorMessage(err, "Could not save the carrier booking.");
        if (isDuplicateAwbError(err)) {
          form.setError("carrier_awb", { type: "server", message });
        }
        toast.error(message);
      }
    });
  };

  return (
    <Form {...form}>
      <form
        data-testid={CARRIER_FORM_TESTID}
        onSubmit={form.handleSubmit(onSubmit)}
        className="min-w-0 space-y-3"
        noValidate
      >
        <FormField
          control={form.control}
          name="carrier_awb"
          render={({ field }) => (
            <FormItem className="min-w-0">
              <FormLabel className="break-words">
                {awbCopy.label}
                <RequiredMark />
              </FormLabel>
              <FormControl>
                <Input
                  {...field}
                  data-testid={`${CARRIER_FORM_TESTID}.awb`}
                  placeholder="e.g. 1234567890123"
                  autoComplete="off"
                  maxLength={AWB_MAX_LENGTH}
                  className="min-w-0 w-full"
                />
              </FormControl>
              <FormDescription className="break-words">{awbCopy.description}</FormDescription>
              <FormMessage data-testid={`${CARRIER_FORM_TESTID}.awb-error`} />
            </FormItem>
          )}
        />
        <div className="grid grid-cols-1 gap-3 @[420px]:grid-cols-2">
          <FormField
            control={form.control}
            name="charged_weight_kg"
            render={({ field }) => (
              <FormItem className="min-w-0">
                <FormLabel className="break-words">Charged weight</FormLabel>
                <FormControl>
                  <InputAdornment suffix="kg">
                    <Input
                      {...field}
                      data-testid={`${CARRIER_FORM_TESTID}.charged-weight`}
                      inputMode="decimal"
                      placeholder="Optional"
                      className="min-w-0 w-full"
                    />
                  </InputAdornment>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={form.control}
            name="charged_amount"
            render={({ field }) => (
              <FormItem className="min-w-0">
                <FormLabel className="break-words">Charged amount (incl. GST)</FormLabel>
                <FormControl>
                  <InputAdornment prefix="₹">
                    <Input
                      {...field}
                      data-testid={`${CARRIER_FORM_TESTID}.charged-amount`}
                      inputMode="decimal"
                      placeholder="Optional"
                      className="min-w-0 w-full"
                    />
                  </InputAdornment>
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
        <div className="flex flex-wrap justify-end gap-2 min-w-0">
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={submitting}
            data-testid={`${CARRIER_FORM_TESTID}.cancel`}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={submitting} data-testid={`${CARRIER_FORM_TESTID}.submit`}>
            {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save carrier booking
          </Button>
        </div>
      </form>
    </Form>
  );
}
