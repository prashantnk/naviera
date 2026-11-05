// frontend/src/components/pickups/pickup-action-dialogs.tsx
"use client";

/**
 * Confirmation dialogs for destructive / operational Pickup Request actions:
 * a generic confirm dialog (cancel, out for pickup, mark picked up), the
 * Admin "Not picked" dialog that captures a failure reason, and the dispatch
 * checklist with optional "Actual pieces" per AWB.
 */
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, type Resolver } from "react-hook-form";
import * as z from "zod";

import { ManifestShipmentItem } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import {
  ActualPiecesFields,
  emptyPiece,
  pieceSchema,
  piecesToPackages,
  type PieceValues,
} from "@/components/shipments/actual-pieces-fields";
import {
  EvidencePhotosField,
  MAX_EVIDENCE_PHOTOS,
} from "@/components/shipments/evidence-photos-field";
import {
  buildMeasurementForPieceCount,
  type DispatchMeasurement,
} from "@/components/shipments/reprice-api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Form, FormField } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { AlertCircle, KeyRound, Loader2, ShieldAlert } from "lucide-react";
import { useState } from "react";

import { NOT_PICKED_REASONS, OTHER_REASON_VALUE } from "./pickup-constants";

/** Max length accepted by the backend for `failure_reason`. */
const FAILURE_REASON_MAX_LENGTH = 255;

/** Props of the generic confirm dialog. */
export interface ConfirmPickupDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  destructive?: boolean;
  submitting: boolean;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
}

/** Generic "Are you sure?" dialog used by row actions. */
export function ConfirmPickupDialog({
  open,
  title,
  description,
  confirmLabel,
  destructive = false,
  submitting,
  onConfirm,
  onOpenChange,
}: ConfirmPickupDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="gap-2">
          <Button variant="outline" disabled={submitting} onClick={() => onOpenChange(false)}>
            Keep it
          </Button>
          <Button
            variant={destructive ? "destructive" : "default"}
            disabled={submitting}
            onClick={onConfirm}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Props of the Admin Not picked dialog. */
export interface NotPickedDialogProps {
  open: boolean;
  pickupLabel: string;
  submitting: boolean;
  onSubmit: (reason: string) => void;
  onOpenChange: (open: boolean) => void;
}

/** Admin-only outcome: records why the pickup failed (shipments go back to Ready to Ship). */
export function NotPickedDialog({
  open,
  pickupLabel,
  submitting,
  onSubmit,
  onOpenChange,
}: NotPickedDialogProps) {
  // State starts fresh for every pickup: the parent remounts this dialog with `key={pickupId}`.
  const [preset, setPreset] = useState<string>(NOT_PICKED_REASONS[0]);
  const [otherReason, setOtherReason] = useState("");

  const isOther = preset === OTHER_REASON_VALUE;
  const reason = (isOther ? otherReason : preset).trim();

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Mark {pickupLabel} as Not Picked</DialogTitle>
          <DialogDescription>
            Linked shipments are released back to Ready to Ship so the seller can reschedule.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Reason</Label>
            <Select value={preset} onValueChange={setPreset}>
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {NOT_PICKED_REASONS.map((item) => (
                  <SelectItem key={item} value={item}>
                    {item}
                  </SelectItem>
                ))}
                <SelectItem value={OTHER_REASON_VALUE}>Other reason</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {isOther && (
            <div className="space-y-1.5">
              <Label htmlFor="not-picked-reason">Describe the reason</Label>
              <Textarea
                id="not-picked-reason"
                value={otherReason}
                maxLength={FAILURE_REASON_MAX_LENGTH}
                onChange={(event) => setOtherReason(event.target.value)}
                placeholder="e.g. Warehouse refused handover"
              />
            </div>
          )}
        </div>
        <DialogFooter className="gap-2">
          <Button variant="outline" disabled={submitting} onClick={() => onOpenChange(false)}>
            Back
          </Button>
          <Button
            variant="destructive"
            disabled={submitting || reason.length === 0}
            onClick={() => onSubmit(reason)}
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Mark Not Picked
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Props of the Admin Dispatch / Confirm Picked Up dialog (G1 partial pickup, B5 actual pieces). */
export interface DispatchPickupDialogProps {
  open: boolean;
  pickupLabel: string;
  shipments: ManifestShipmentItem[];
  submitting: boolean;
  /** True when the caller is Owner or Admin (may override OTP verification with a mandatory reason). */
  canOverrideOtp?: boolean;
  /** Server-side OTP verification or lockout error message to display inside the dialog. */
  errorMessage?: string | null;
  /**
   * Called with the handed-over AWB ids, optional "Actual pieces" per AWB, and Pickup OTP / override reason.
   */
  onSubmit: (
    pickedShipmentIds: string[],
    measurements: DispatchMeasurement[],
    pickupOtp?: string,
    overrideReason?: string,
  ) => void;
  onOpenChange: (open: boolean) => void;
}

/** One AWB row of the dispatch checklist. */
const dispatchEntrySchema = z.discriminatedUnion("record_pieces", [
  z.object({
    shipment_id: z.string(),
    picked: z.boolean(),
    actual_pieces: z.number().int().min(1).optional(),
    record_pieces: z.literal(true),
    packages: z.array(pieceSchema).min(1, "Add at least one box size"),
    evidence_urls: z.array(z.string()).max(MAX_EVIDENCE_PHOTOS),
  }),
  z.object({
    shipment_id: z.string(),
    picked: z.boolean(),
    actual_pieces: z.number().int().min(1).optional(),
    record_pieces: z.literal(false),
    packages: z.array(z.unknown()),
    evidence_urls: z.array(z.string()),
  }),
]);

const dispatchFormSchema = z.object({ entries: z.array(dispatchEntrySchema) });

/** Form state of one AWB row (superset of both schema branches). */
interface DispatchEntryValues {
  shipment_id: string;
  picked: boolean;
  actual_pieces?: number;
  record_pieces: boolean;
  packages: PieceValues[];
  evidence_urls: string[];
}

interface DispatchFormValues {
  entries: DispatchEntryValues[];
}

const dispatchResolver = zodResolver(dispatchFormSchema) as unknown as Resolver<DispatchFormValues>;

/**
 * Turns the checklist into the dispatch payload parts.
 *
 * @param entries - Validated rows.
 * @param tenantSlug - Tenant slug header.
 * @returns Picked AWB ids and the per-AWB measurements (only for picked rows with pieces).
 */
async function _toDispatchPayload(
  entries: readonly DispatchEntryValues[],
  tenantSlug?: string | null,
): Promise<{
  pickedIds: string[];
  measurements: DispatchMeasurement[];
}> {
  const picked = entries.filter((entry) => entry.picked);
  const measurements: DispatchMeasurement[] = [];
  for (const entry of picked) {
    if (entry.record_pieces) {
      measurements.push({
        shipment_id: entry.shipment_id,
        packages: piecesToPackages(entry.packages),
        evidence_urls: entry.evidence_urls.length > 0 ? entry.evidence_urls : undefined,
      });
    } else if (typeof entry.actual_pieces === "number" && entry.actual_pieces >= 1) {
      const m = await buildMeasurementForPieceCount(entry.shipment_id, entry.actual_pieces, tenantSlug);
      measurements.push(m);
    }
  }
  return {
    pickedIds: picked.map((entry) => entry.shipment_id),
    measurements,
  };
}

/**
 * Admin / field-executive outcome: confirms the pickup handover with an AWB checklist
 * (unticked AWBs detach back to Ready to Ship) and, optionally, the actual pieces found
 * for each AWB. Actual pieces become the billing basis; the backend re-prices the LR and
 * settles the difference (debit + debit note, or refund + credit note).
 *
 * Delhivery One parity: the pickup executive's "pieces picked" capture on the pickup
 * request (help article `pickup-request`).
 */
export function DispatchPickupDialog({
  open,
  pickupLabel,
  shipments,
  submitting,
  canOverrideOtp = false,
  errorMessage = null,
  onSubmit,
  onOpenChange,
}: DispatchPickupDialogProps) {
  const { tenantSlug } = useTenant();
  const [resolvingPieces, setResolvingPieces] = useState(false);
  const [pickupOtp, setPickupOtp] = useState("");
  const [useOverride, setUseOverride] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const form = useForm<DispatchFormValues>({
    resolver: dispatchResolver,
    defaultValues: {
      entries: shipments.map((item) => ({
        shipment_id: item.id,
        picked: true,
        actual_pieces: undefined,
        record_pieces: false,
        packages: [emptyPiece()],
        evidence_urls: [],
      })),
    },
  });
  const entries = form.watch("entries");

  const hasShipments = shipments.length > 0;
  const pickedCount = entries.filter((entry) => entry.picked).length;
  const allPicked = pickedCount === shipments.length;
  const allUnchecked = hasShipments && pickedCount === 0;
  const busy = submitting || resolvingPieces;
  const displayedError = localError || errorMessage;

  const setPicked = (index: number, picked: boolean) => {
    form.setValue(`entries.${index}.picked`, picked);
    // A measurement for an AWB that was not handed over is refused by the API (400).
    if (!picked) {
      form.setValue(`entries.${index}.record_pieces`, false);
      form.setValue(`entries.${index}.actual_pieces`, undefined);
    }
  };

  const submit = form.handleSubmit(async (values) => {
    setLocalError(null);
    const trimmedOtp = pickupOtp.trim();
    const trimmedReason = overrideReason.trim();
    if (useOverride && canOverrideOtp) {
      if (!trimmedReason) {
        setLocalError("A mandatory override reason is required to bypass pickup OTP verification.");
        return;
      }
    } else if (!/^\d{6}$/.test(trimmedOtp)) {
      setLocalError("Enter the 6-digit pickup handover OTP shared by the seller.");
      return;
    }

    setResolvingPieces(true);
    try {
      const { pickedIds, measurements } = await _toDispatchPayload(values.entries, tenantSlug);
      onSubmit(
        pickedIds,
        measurements,
        useOverride && canOverrideOtp ? undefined : trimmedOtp,
        useOverride && canOverrideOtp ? trimmedReason : undefined,
      );
    } finally {
      setResolvingPieces(false);
    }
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="pickup-dispatch.dialog" className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Confirm Picked Up — {pickupLabel}</DialogTitle>
          <DialogDescription>
            {hasShipments
              ? "Tick the AWBs handed over to the courier. Unticked AWBs return to Ready to Ship. Add the actual pieces if they differ from the booking."
              : "Confirm that this blind pickup has been collected by the courier."}
          </DialogDescription>
        </DialogHeader>

        <Form {...form}>
          <form onSubmit={submit} className="space-y-3">
            {hasShipments && (
              <div className="space-y-2.5">
                <div className="flex items-center justify-between text-xs font-medium text-muted-foreground">
                  <span data-testid="pickup-dispatch.summary.picked-count">
                    Handed over: <strong className="text-foreground">{pickedCount}</strong> of{" "}
                    <strong className="text-foreground">{shipments.length}</strong> AWB(s)
                  </span>
                  <button
                    type="button"
                    data-testid="pickup-dispatch.actions.toggle-all"
                    className="font-semibold text-primary hover:underline"
                    onClick={() => entries.forEach((_, index) => setPicked(index, !allPicked))}
                  >
                    {allPicked ? "Untick all" : "Tick all"}
                  </button>
                </div>

                <div className="divide-y divide-border rounded-lg border border-border bg-muted/20">
                  {shipments.map((item, index) => {
                    const entry = entries[index];
                    const awb = item.tracking_id || item.id.slice(0, 8).toUpperCase();
                    const rowTestId = `pickup-dispatch.row.${awb}`;
                    return (
                      <div key={item.id} data-testid={rowTestId} className="space-y-2.5 px-3 py-2.5 text-sm">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <label className="flex min-w-0 cursor-pointer items-center gap-2.5">
                            <input
                              type="checkbox"
                              data-testid={`${rowTestId}.picked`}
                              className="h-5 w-5 rounded border-input accent-primary"
                              checked={entry?.picked ?? false}
                              onChange={(event) => setPicked(index, event.target.checked)}
                            />
                            <span className="min-w-0">
                              <span className="block font-mono text-xs font-bold text-foreground">{awb}</span>
                              {item.order_reference_id && (
                                <span className="block truncate text-[11px] text-muted-foreground">
                                  Order: {item.order_reference_id}
                                </span>
                              )}
                            </span>
                          </label>
                          <div className="flex shrink-0 items-center gap-2">
                            {!entry?.picked && (
                              <span className="rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-300">
                                Not handed over — returns to Ready to Ship
                              </span>
                            )}
                            <span className="rounded border border-border bg-background px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
                              {item.package_count ?? 1} pkg booked
                            </span>
                          </div>
                        </div>

                        {entry?.picked && (
                          <div className="space-y-2 pl-0 sm:pl-7">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <div className="flex items-center gap-2">
                                <Label className="text-xs font-semibold text-foreground">
                                  Actual pieces
                                </Label>
                                <Input
                                  type="number"
                                  inputMode="numeric"
                                  min="1"
                                  step="1"
                                  disabled={busy}
                                  data-testid={`${rowTestId}.actual-pieces`}
                                  placeholder={String(item.package_count ?? 1)}
                                  value={entry.actual_pieces ?? ""}
                                  onChange={(event) => {
                                    const raw = event.target.value;
                                    const num = raw === "" ? undefined : Number(raw);
                                    form.setValue(`entries.${index}.actual_pieces`, num);
                                    if (typeof num === "number" && num >= 1) {
                                      form.setValue(`entries.${index}.packages.0.box_count`, num);
                                    }
                                  }}
                                  className="h-9 w-24 bg-background font-mono text-xs"
                                />
                              </div>

                              <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-foreground">
                                <input
                                  type="checkbox"
                                  data-testid={`${rowTestId}.actual-pieces-toggle`}
                                  className="h-4 w-4 rounded border-input accent-primary"
                                  checked={entry.record_pieces}
                                  onChange={(event) =>
                                    form.setValue(`entries.${index}.record_pieces`, event.target.checked)
                                  }
                                />
                                Box sizes &amp; photos
                                <span className="font-normal text-muted-foreground">(optional)</span>
                              </label>
                            </div>
                            {entry.record_pieces ? (
                              <div className="space-y-2">
                                <ActualPiecesFields
                                  control={form.control}
                                  name={`entries.${index}.packages`}
                                  testIdPrefix={`${rowTestId}.boxes`}
                                  disabled={busy}
                                />
                                <FormField
                                  control={form.control}
                                  name={`entries.${index}.evidence_urls`}
                                  render={({ field }) => (
                                    <EvidencePhotosField
                                      tenantSlug={tenantSlug}
                                      value={field.value}
                                      onChange={field.onChange}
                                      testIdPrefix={`${rowTestId}.photos`}
                                      disabled={busy}
                                    />
                                  )}
                                />
                              </div>
                            ) : (
                              <p className="text-[11px] text-muted-foreground">
                                Billed on the booked boxes unless actual pieces or box sizes are entered.
                              </p>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>

                {allUnchecked && (
                  <p className="text-xs font-medium text-amber-600 dark:text-amber-400">
                    Select at least 1 AWB to confirm pickup, or use &apos;Not Picked&apos; if no packages were handed over.
                  </p>
                )}
              </div>
            )}

            <div className="space-y-2.5 rounded-lg border border-border bg-muted/20 p-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <Label
                  htmlFor="pickup-dispatch-otp"
                  className="flex items-center gap-1.5 text-xs font-semibold text-foreground"
                >
                  <KeyRound className="h-3.5 w-3.5 text-primary" />
                  Pickup Handover OTP (shared by seller)
                </Label>
                {canOverrideOtp && (
                  <label className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
                    <input
                      type="checkbox"
                      data-testid="pickup-dispatch.override-toggle"
                      className="h-3.5 w-3.5 rounded border-input accent-primary"
                      checked={useOverride}
                      disabled={busy}
                      onChange={(event) => {
                        setUseOverride(event.target.checked);
                        setLocalError(null);
                      }}
                    />
                    Override without OTP (Owner/Admin)
                  </label>
                )}
              </div>

              {useOverride && canOverrideOtp ? (
                <div className="space-y-1.5">
                  <Label
                    htmlFor="pickup-dispatch-override-reason"
                    className="flex items-center gap-1 text-xs font-medium text-muted-foreground"
                  >
                    <ShieldAlert className="h-3.5 w-3.5 text-primary" />
                    Mandatory audit reason for overriding OTP
                  </Label>
                  <Input
                    id="pickup-dispatch-override-reason"
                    data-testid="pickup-dispatch.override-reason"
                    disabled={busy}
                    maxLength={FAILURE_REASON_MAX_LENGTH}
                    value={overrideReason}
                    onChange={(event) => {
                      setOverrideReason(event.target.value);
                      setLocalError(null);
                    }}
                    placeholder="e.g. Seller unreachable at dock; handover verified via hub phone call"
                    className="h-9 bg-background text-xs"
                  />
                </div>
              ) : (
                <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center sm:justify-between">
                  <Input
                    id="pickup-dispatch-otp"
                    data-testid="pickup-dispatch.otp-input"
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    maxLength={6}
                    disabled={busy}
                    value={pickupOtp}
                    onChange={(event) => {
                      setPickupOtp(event.target.value.replace(/\D/g, "").slice(0, 6));
                      setLocalError(null);
                    }}
                    placeholder="6-digit OTP (e.g. 482910)"
                    className="h-9 w-full bg-background font-mono text-sm tracking-widest sm:w-52"
                  />
                  <span className="text-[11px] text-muted-foreground">
                    Ask the seller/warehouse staff for the 6-digit pickup OTP before loading cartons.
                  </span>
                </div>
              )}

              {displayedError && (
                <div
                  data-testid="pickup-dispatch.error"
                  role="alert"
                  className="flex items-start gap-1.5 rounded-md border border-destructive/30 bg-destructive/10 px-2.5 py-1.5 text-xs font-medium text-destructive"
                >
                  <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>{displayedError}</span>
                </div>
              )}
            </div>

            <DialogFooter className="flex-col-reverse gap-2 sm:flex-row">
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => onOpenChange(false)}
                className="w-full sm:w-auto"
              >
                Cancel
              </Button>
              <Button
                type="submit"
                data-testid="pickup-dispatch.actions.confirm"
                disabled={busy || allUnchecked}
                className="w-full sm:w-auto"
              >
                {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Confirm Picked Up
              </Button>
            </DialogFooter>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
