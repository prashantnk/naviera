// frontend/src/components/shipments/measurement-dialog.tsx
"use client";

/**
 * "Record measurement" (replaces the old "Audit Scale (kg)" button, plan B4/B14).
 *
 * Staff record what the parcel actually measured, either per box size (count, L × B × H,
 * kg per box) or as a weight-only hub scale reading. The measurement becomes the billing
 * basis and the backend re-bills both ways (debit + debit note, or refund + credit note).
 * The dialog only sends inputs; the new bill comes back from the API.
 *
 * Delhivery One parity: the hub's weight/dimension capture that drives the weight
 * discrepancy flow (help article `weight-discrepancy`).
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Ruler } from "lucide-react";
import { useState } from "react";
import { useForm, type Resolver } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { useUser } from "@/components/auth/auth-guard";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { extractApiErrorMessage } from "@/lib/utils";

import {
  ActualPiecesFields,
  emptyPiece,
  pieceSchema,
  piecesToPackages,
  type PieceValues,
} from "./actual-pieces-fields";
import { EvidencePhotosField, MAX_EVIDENCE_PHOTOS } from "./evidence-photos-field";
import {
  MeasurementSource,
  newIdempotencyKey,
  recordShipmentMeasurement,
  type MeasurementOutcome,
  type MeasurementPayload,
} from "./reprice-api";
import { formatInr, formatSignedInr } from "./shipment-money";

/** Backend cap on the remark column. */
const REMARK_MAX_LENGTH = 255;
const TEST_ID = "measurement";

/** How the measurement is captured. */
enum MeasurementMode {
  BOXES = "BOXES",
  WEIGHT_ONLY = "WEIGHT_ONLY",
}

const MODE_LABELS: Readonly<Record<MeasurementMode, string>> = {
  [MeasurementMode.BOXES]: "Box sizes",
  [MeasurementMode.WEIGHT_ONLY]: "Weight only",
};

const sharedMeasurementFields = {
  override_total_price: z.number().positive("Enter a price greater than ₹0").optional(),
  remark: z.string().max(REMARK_MAX_LENGTH).optional(),
  evidence_urls: z.array(z.string()).max(MAX_EVIDENCE_PHOTOS),
};

const boxRowSchema = z.object({
  box_count: z.number({ message: "Enter boxes" }).int("Whole boxes only").min(1, "At least 1 box"),
  length: z.number().positive("Enter length").optional(),
  breadth: z.number().positive("Enter breadth").optional(),
  height: z.number().positive("Enter height").optional(),
  dimension_unit: pieceSchema.shape.dimension_unit,
  weight: z.number({ message: "Enter weight" }).positive("Enter weight per box"),
});

/** Validates box sizes (allowing a single weight-only row when L/B/H are all omitted) or explicit weight-only mode. */
const measurementSchema = z
  .discriminatedUnion("mode", [
    z.object({
      mode: z.literal(MeasurementMode.BOXES),
      packages: z.array(boxRowSchema).min(1, "Add at least one box size"),
      ...sharedMeasurementFields,
    }),
    z.object({
      mode: z.literal(MeasurementMode.WEIGHT_ONLY),
      weight_kg: z.number({ message: "Enter the scale weight in kg" }).positive("Enter the scale weight in kg"),
      ...sharedMeasurementFields,
    }),
  ])
  .superRefine((data, ctx) => {
    if (data.mode !== MeasurementMode.BOXES) return;
    const isSingleWeightOnly =
      data.packages.length === 1 &&
      data.packages[0].length === undefined &&
      data.packages[0].breadth === undefined &&
      data.packages[0].height === undefined;
    if (isSingleWeightOnly) return;
    data.packages.forEach((pkg, idx) => {
      for (const dim of ["length", "breadth", "height"] as const) {
        if (pkg[dim] === undefined) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["packages", idx, dim],
            message: `Enter ${dim}`,
          });
        }
      }
    });
  });

/** Superset of both branches, as held by the form. */
interface MeasurementFormValues {
  mode: MeasurementMode;
  packages: PieceValues[];
  weight_kg?: number;
  override_total_price?: number;
  remark?: string;
  evidence_urls: string[];
}

const measurementResolver = zodResolver(measurementSchema) as unknown as Resolver<MeasurementFormValues>;

/**
 * Builds the API body for the chosen mode (exactly one of packages / weight_kg).
 *
 * @param values - Validated form values.
 * @param source - Who is recording (hub by default).
 * @returns The POST /measurements body.
 */
function _toPayload(values: MeasurementFormValues, source: MeasurementSource): MeasurementPayload {
  const shared = {
    source,
    override_total_price: values.override_total_price,
    remark: values.remark?.trim() || undefined,
    evidence_urls: values.evidence_urls.length > 0 ? values.evidence_urls : undefined,
  };
  if (values.mode === MeasurementMode.WEIGHT_ONLY) {
    return { ...shared, weight_kg: values.weight_kg };
  }
  const first = values.packages[0];
  const isSingleWeightOnly =
    values.packages.length === 1 &&
    first.length === undefined &&
    first.breadth === undefined &&
    first.height === undefined;
  return isSingleWeightOnly
    ? { ...shared, weight_kg: first.weight }
    : { ...shared, packages: piecesToPackages(values.packages) };
}

/**
 * Success message built from the backend adjustment (display only).
 *
 * @param outcome - API response.
 * @returns Toast text.
 */
function _successMessage(outcome: MeasurementOutcome): string {
  const adjustment = outcome.adjustment;
  if (!adjustment) return "Measurement recorded. Charges unchanged.";
  return `Measurement recorded. Charges ${formatInr(adjustment.old_total)} → ${formatInr(
    adjustment.new_total,
  )} (${formatSignedInr(adjustment.delta)}).`;
}

/** Props of {@link MeasurementDialog}. */
export interface MeasurementDialogProps {
  shipmentId: string;
  awbLabel: string;
  tenantSlug: string;
  open: boolean;
  source?: MeasurementSource;
  onOpenChange: (open: boolean) => void;
  onRecorded: (outcome: MeasurementOutcome) => void;
}

/** Record measurement dialog. Mount with `key` per open so each submission gets a new key. */
export function MeasurementDialog({
  shipmentId,
  awbLabel,
  tenantSlug,
  open,
  source = MeasurementSource.HUB,
  onOpenChange,
  onRecorded,
}: MeasurementDialogProps) {
  const { capabilities } = useUser();
  // One Idempotency-Key per dialog instance: a double tap replays, never double-bills (H-4).
  const [idempotencyKey] = useState(newIdempotencyKey);
  const [submitting, setSubmitting] = useState(false);
  const form = useForm<MeasurementFormValues>({
    resolver: measurementResolver,
    defaultValues: {
      mode: MeasurementMode.BOXES,
      packages: [emptyPiece()],
      weight_kg: undefined,
      override_total_price: undefined,
      remark: "",
      evidence_urls: [],
    },
  });
  const mode = form.watch("mode");

  const onSubmit = async (values: MeasurementFormValues) => {
    setSubmitting(true);
    try {
      const outcome = await recordShipmentMeasurement(
        shipmentId,
        _toPayload(values, source),
        idempotencyKey,
        tenantSlug,
      );
      toast.success(_successMessage(outcome));
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      onRecorded(outcome);
      onOpenChange(false);
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Could not record the measurement."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid={`${TEST_ID}.dialog`}
        className="max-h-[90vh] w-[calc(100vw-2rem)] overflow-x-hidden overflow-y-auto sm:max-w-2xl"
      >
        <DialogHeader className="min-w-0">
          <DialogTitle className="flex items-center gap-2 break-words">
            <Ruler className="h-4 w-4 shrink-0 text-primary" />
            <span>Record measurement</span>
          </DialogTitle>
          <DialogDescription className="break-words">
            AWB {awbLabel}. The measured boxes become the billing basis. Any difference is
            charged to or refunded to the wallet with a debit or credit note.
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="min-w-0 space-y-4">
            <div className="inline-flex w-full flex-wrap rounded-lg border border-border bg-muted/30 p-1 sm:w-auto">
              {Object.values(MeasurementMode).map((option) => (
                <button
                  key={option}
                  type="button"
                  data-testid={`${TEST_ID}.form.mode-${option.toLowerCase().replace("_", "-")}`}
                  onClick={() => form.setValue("mode", option, { shouldValidate: false })}
                  className={
                    option === mode
                      ? "flex-1 rounded-md bg-background px-3 py-1.5 text-xs font-semibold text-foreground shadow-xs sm:flex-none"
                      : "flex-1 rounded-md px-3 py-1.5 text-xs font-medium text-muted-foreground sm:flex-none"
                  }
                >
                  {MODE_LABELS[option]}
                </button>
              ))}
            </div>

            {mode === MeasurementMode.BOXES ? (
              <ActualPiecesFields
                control={form.control}
                name="packages"
                testIdPrefix={`${TEST_ID}.form`}
                flatFirstRowTestIds
                disabled={submitting}
              />
            ) : (
              <FormField
                control={form.control}
                name="weight_kg"
                render={({ field }) => (
                  <FormItem className="min-w-0">
                    <FormLabel>Scale weight (kg)</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        inputMode="decimal"
                        step="0.01"
                        min="0"
                        data-testid={`${TEST_ID}.form.weight`}
                        value={field.value ?? ""}
                        onChange={(event) =>
                          field.onChange(event.target.value === "" ? undefined : Number(event.target.value))
                        }
                        className="h-10 min-w-0 w-full font-mono"
                        placeholder="e.g. 15.5"
                      />
                    </FormControl>
                    <p className="text-[11px] text-muted-foreground">
                      The declared box sizes are kept; only their weight is updated.
                    </p>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            {capabilities.canManageFinance && (
              <FormField
                control={form.control}
                name="override_total_price"
                render={({ field }) => (
                  <FormItem className="min-w-0">
                    <FormLabel>Override Final Price (₹ incl. GST, optional)</FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        inputMode="decimal"
                        step="0.01"
                        min="1"
                        data-testid={`${TEST_ID}.form.override-price`}
                        value={field.value ?? ""}
                        onChange={(event) =>
                          field.onChange(
                            event.target.value === "" ? undefined : Number(event.target.value),
                          )
                        }
                        className="h-10 min-w-0 w-full font-mono"
                        placeholder="Leave blank to use pricing engine quote"
                      />
                    </FormControl>
                    <p className="text-[11px] text-muted-foreground">
                      Leave blank to bill the pricing engine&apos;s quote for the measured weight/dimensions, or enter a custom ₹ total to credit/debit the difference.
                    </p>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={form.control}
              name="remark"
              render={({ field }) => (
                <FormItem className="min-w-0">
                  <FormLabel>Remark (optional)</FormLabel>
                  <FormControl>
                    <Textarea
                      {...field}
                      rows={2}
                      maxLength={REMARK_MAX_LENGTH}
                      data-testid={`${TEST_ID}.form.remark`}
                      placeholder="e.g. Re-weighed at Bhiwandi hub"
                      className="min-w-0 w-full resize-none"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="evidence_urls"
              render={({ field }) => (
                <FormItem className="min-w-0">
                  <FormLabel>Photos</FormLabel>
                  <EvidencePhotosField
                    tenantSlug={tenantSlug}
                    value={field.value}
                    onChange={field.onChange}
                    testIdPrefix={`${TEST_ID}.form.photos`}
                    disabled={submitting}
                  />
                </FormItem>
              )}
            />

            <DialogFooter className="flex-col-reverse gap-2 sm:flex-row">
              <Button
                type="button"
                variant="outline"
                disabled={submitting}
                onClick={() => onOpenChange(false)}
                className="w-full sm:w-auto"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                data-testid={`${TEST_ID}.actions.submit`}
                disabled={submitting}
                className="w-full sm:w-auto"
              >
                {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Save measurement
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
