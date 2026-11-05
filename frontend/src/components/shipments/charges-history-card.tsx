// frontend/src/components/shipments/charges-history-card.tsx
"use client";

/**
 * "Charges history" card on the shipment detail pages (plan B14).
 *
 * Lists every price change recorded in `shipment_charge_adjustments` (edits, pickup and
 * hub measurements, weight claims, payment-mode changes, RTO, cancellation) with the old
 * and new charges, the signed difference and the GST note, so merchants and finance can
 * trace any bill change. Display only: all values come from GET /shipments/{id}/charges.
 *
 * Delhivery One parity: the order's billing / weight-discrepancy history with debit and
 * credit notes (help articles `billing-and-invoices`, `weight-discrepancy`).
 */
import { History, Loader2, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, extractApiErrorMessage, safeFormatDate } from "@/lib/utils";

import { ChargeNoteType, fetchShipmentCharges, type ChargeAdjustment } from "./reprice-api";
import { deltaDirection, formatInr, formatSignedInr, type DeltaDirection } from "./shipment-money";

/** Merchant-facing wording for each `ChargeAdjustmentReason` (17 DB values, M-B1). */
export const CHARGE_REASON_LABELS: Readonly<Record<string, string>> = {
  CUSTOMER_EDIT: "Order edited by you",
  ADMIN_EDIT: "Order edited by operations",
  PICKUP_MEASUREMENT: "Measured at pickup",
  HUB_MEASUREMENT: "Measured at hub",
  MANUAL_WEIGHT_CHARGE: "Weight charge applied",
  CLAIM_ACCEPTED: "Weight dispute accepted",
  PAYMENT_MODE_CHANGE: "Payment mode changed",
  COD_CHANGE: "COD amount changed",
  SHORT_SHIPMENT: "Short shipment",
  FREIGHT_COLLECTION: "Freight collected",
  EXCEPTION_CHARGE: "Exception charge",
  RTO: "Return to origin (RTO)",
  COD_FEE_REVERSAL: "COD fee reversed",
  CANCELLATION: "Order cancelled",
  PICKUP_REJECTION_REFUND: "Rejected at pickup refund",
  LOST: "Shipment lost",
  LOST_FOUND: "Lost shipment found",
};

const NOTE_SHORT_LABELS: Readonly<Record<ChargeNoteType, string>> = {
  [ChargeNoteType.DEBIT_NOTE]: "Debit note",
  [ChargeNoteType.CREDIT_NOTE]: "Credit note",
};

const DELTA_CLASSES: Readonly<Record<DeltaDirection, string>> = {
  up: "text-destructive",
  down: "text-emerald-700 dark:text-emerald-400",
  none: "text-muted-foreground",
};

const DATE_TIME_FORMAT = "dd MMM yyyy, HH:mm";

/**
 * Reason label with a readable fallback for values added later.
 *
 * @param reason - Backend reason code.
 * @returns Display label.
 */
function _reasonLabel(reason: string): string {
  return CHARGE_REASON_LABELS[reason] ?? reason.replace(/_/g, " ").toLowerCase();
}

/**
 * Note cell text, e.g. `Debit note LOGI2627D000004`.
 *
 * @param row - Adjustment row.
 * @returns Text or an em dash.
 */
function _noteLabel(row: ChargeAdjustment): string {
  if (!row.note_number) return "—";
  return row.note_type ? `${NOTE_SHORT_LABELS[row.note_type]} ${row.note_number}` : row.note_number;
}

/** Props of {@link ChargesHistoryCard}. */
export interface ChargesHistoryCardProps {
  shipmentId: string;
  tenantSlug: string;
  /** `payment_details.total_logistics_cost` as returned by the shipment API. */
  currentTotal: number | null | undefined;
  /** Bump to refetch after an action on the page (e.g. a measurement). */
  refreshKey?: number;
  /** `data-testid` page prefix. */
  testIdPage?: string;
  className?: string;
}

/** Charges history for one shipment. */
export function ChargesHistoryCard({
  shipmentId,
  tenantSlug,
  currentTotal,
  refreshKey = 0,
  testIdPage = "shipment-detail",
  className,
}: ChargesHistoryCardProps) {
  const [rows, setRows] = useState<ChargeAdjustment[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const prefix = `${testIdPage}.charges`;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setRows(await fetchShipmentCharges(shipmentId, tenantSlug));
    } catch (err: unknown) {
      setError(extractApiErrorMessage(err, "Could not load the charges history."));
    } finally {
      setLoading(false);
    }
  }, [shipmentId, tenantSlug]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const effectiveTotal = rows.length > 0 ? rows[rows.length - 1].new_total : currentTotal;

  return (
    <Card data-testid={prefix} className={cn("@container min-w-0 overflow-hidden gap-3", className)}>
      <CardHeader className="flex flex-row items-start justify-between gap-3 min-w-0">
        <div className="min-w-0 space-y-1">
          <CardTitle className="flex items-center gap-2 text-base break-words">
            <History className="h-4 w-4 shrink-0 text-primary" />
            <span>Charges history</span>
          </CardTitle>
          <CardDescription className="text-xs break-words">
            Current charges{" "}
            <span data-testid={`${prefix}.total`} className="font-bold text-foreground">
              {formatInr(effectiveTotal)}
            </span>
          </CardDescription>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={() => void load()}
          disabled={loading}
          aria-label="Refresh charges history"
          data-testid={`${prefix}.refresh`}
          className="h-8 w-8 shrink-0"
        >
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
        </Button>
      </CardHeader>
      <CardContent className="min-w-0">
        {loading ? (
          <div className="flex h-16 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-primary" />
          </div>
        ) : error ? (
          <p data-testid={`${prefix}.error`} className="text-xs text-destructive break-words">
            {error}
          </p>
        ) : rows.length === 0 ? (
          <p data-testid={`${prefix}.empty`} className="text-xs text-muted-foreground">
            No changes to the charges since booking.
          </p>
        ) : (
          <div className="space-y-2 @[640px]:space-y-0 @[640px]:divide-y @[640px]:divide-border @[640px]:rounded-md @[640px]:border @[640px]:border-border">
            <div className="hidden @[640px]:grid @[640px]:grid-cols-7 @[640px]:gap-2 @[640px]:bg-muted/50 @[640px]:px-3 @[640px]:py-2 @[640px]:text-xs @[640px]:font-medium @[640px]:text-muted-foreground">
              <span>Date</span>
              <span>Change</span>
              <span className="text-right">Old charges</span>
              <span className="text-right">New charges</span>
              <span className="text-right">Difference</span>
              <span>Note</span>
              <span>By</span>
            </div>
            {rows.map((row, index) => (
              <div
                key={row.id}
                data-testid={`${prefix}.row-${index}`}
                className="min-w-0 space-y-1 rounded-lg border border-border p-2.5 text-xs @[640px]:grid @[640px]:grid-cols-7 @[640px]:items-center @[640px]:gap-2 @[640px]:space-y-0 @[640px]:rounded-none @[640px]:border-0 @[640px]:px-3 @[640px]:py-2"
              >
                <div className="text-[11px] text-muted-foreground @[640px]:whitespace-nowrap @[640px]:text-xs @[640px]:text-foreground">
                  {safeFormatDate(row.created_at, DATE_TIME_FORMAT)}
                </div>
                <div className="font-semibold text-foreground break-words @[640px]:font-medium">
                  {_reasonLabel(row.reason)}
                </div>
                <div className="text-muted-foreground @[640px]:text-right @[640px]:text-foreground">
                  <span className="@[640px]:hidden">Old: </span>
                  <span data-testid={`${prefix}.row-${index}.old-total`}>{formatInr(row.old_total)}</span>
                </div>
                <div className="text-muted-foreground @[640px]:text-right @[640px]:text-foreground">
                  <span className="@[640px]:hidden">New: </span>
                  <span data-testid={`${prefix}.row-${index}.new-total`}>{formatInr(row.new_total)}</span>
                </div>
                <div
                  className={cn(
                    "font-bold @[640px]:text-right",
                    DELTA_CLASSES[deltaDirection(row.delta)],
                  )}
                >
                  <span data-testid={`${prefix}.row-${index}.delta`}>{formatSignedInr(row.delta)}</span>
                </div>
                <div data-testid={`${prefix}.row-${index}.note`} className="text-[11px] text-muted-foreground break-words @[640px]:text-xs @[640px]:text-foreground">
                  {_noteLabel(row)}
                </div>
                <div className="max-w-full truncate text-[11px] text-muted-foreground @[640px]:max-w-40 @[640px]:text-xs">
                  {row.actor_email || "System"}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
