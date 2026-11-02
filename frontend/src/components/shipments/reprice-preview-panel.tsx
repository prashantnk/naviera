// frontend/src/components/shipments/reprice-preview-panel.tsx
"use client";

/**
 * Shows the backend's re-price preview: current vs new charges, the signed difference,
 * how it will be settled (wallet debit / refund / freight to collect), the COD amount to
 * collect, and any field the backend refused (H-7 / H-8 / H-12). Display only: every
 * number is read from `RepricePreview` (Zero Frontend Math).
 *
 * Delhivery One parity: the "Edit order" flow shows the revised charges before the
 * merchant confirms (help article `update-forward-order`).
 */
import { AlertTriangle, ArrowRight, Info, Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

import { ChargeNoteType, SettlementAction, type RepricePreview } from "./reprice-api";
import {
  deltaDirection,
  formatInr,
  formatKg,
  formatSignedInr,
  type DeltaDirection,
} from "./shipment-money";

/** Delhivery One style wording for each settlement action. */
const SETTLEMENT_LABELS: Readonly<Record<SettlementAction, string>> = {
  [SettlementAction.DEBIT]: "Extra charge will be debited from the wallet",
  [SettlementAction.REFUND]: "Difference will be refunded to the wallet",
  [SettlementAction.COLLECTIBLE]: "Freight to collect from the receiver will change",
  [SettlementAction.NONE]: "No charge change",
};

/** GST document shown next to the settlement line. */
const NOTE_LABELS: Readonly<Record<ChargeNoteType, string>> = {
  [ChargeNoteType.DEBIT_NOTE]: "Debit note will be issued",
  [ChargeNoteType.CREDIT_NOTE]: "Credit note will be issued",
};

/** Colour tokens per delta direction (semantic, not brand colours). */
const DELTA_CLASSES: Readonly<Record<DeltaDirection, string>> = {
  up: "text-destructive",
  down: "text-emerald-700 dark:text-emerald-400",
  none: "text-muted-foreground",
};

/** Props of {@link RepricePreviewPanel}. */
export interface RepricePreviewPanelProps {
  preview: RepricePreview | null;
  loading: boolean;
  error?: string | null;
  /** `data-testid` prefix, e.g. `shipment-edit.preview`. */
  testIdPrefix: string;
  className?: string;
}

/**
 * Renders one labelled money figure.
 *
 * @param props.label - Caption.
 * @param props.value - Already formatted value.
 * @param props.testId - `data-testid` for the value element (text is exactly the amount).
 * @param props.valueClassName - Extra classes for the value.
 */
function _Figure({
  label,
  value,
  testId,
  valueClassName,
}: {
  label: string;
  value: string;
  testId: string;
  valueClassName?: string;
}) {
  return (
    <div className="min-w-0 space-y-0.5">
      <span className="block text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      <span data-testid={testId} className={cn("block text-base font-bold sm:text-lg", valueClassName)}>
        {value}
      </span>
    </div>
  );
}

/** Backend re-price preview, for edit pages and exception dialogs. */
export function RepricePreviewPanel({
  preview,
  loading,
  error,
  testIdPrefix,
  className,
}: RepricePreviewPanelProps) {
  if (loading) {
    return (
      <div
        data-testid={`${testIdPrefix}.loading`}
        className={cn("flex items-center gap-2 rounded-lg border border-border bg-muted/30 p-3 text-xs text-muted-foreground", className)}
      >
        <Loader2 className="h-4 w-4 animate-spin text-primary" />
        Checking revised charges
      </div>
    );
  }
  if (error) {
    return (
      <div
        data-testid={`${testIdPrefix}.error`}
        className={cn("flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive", className)}
      >
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{error}</span>
      </div>
    );
  }
  if (!preview) return null;

  const direction = deltaDirection(preview.delta);
  const showWeight =
    preview.new_chargeable_weight !== null && preview.new_chargeable_weight !== undefined;
  const showCollectible =
    preview.new_cod_collectible !== null &&
    preview.new_cod_collectible !== undefined &&
    preview.new_cod_collectible !== preview.old_cod_collectible;

  return (
    <div data-testid={testIdPrefix} className={cn("space-y-3", className)}>
      <div className="grid grid-cols-3 gap-3 rounded-lg border border-border bg-muted/30 p-3">
        <_Figure
          label="Current charges"
          value={formatInr(preview.old_total)}
          testId={`${testIdPrefix}.old-total`}
          valueClassName="text-muted-foreground"
        />
        <_Figure
          label="Revised charges"
          value={formatInr(preview.new_total)}
          testId={`${testIdPrefix}.new-total`}
          valueClassName="text-foreground"
        />
        <_Figure
          label="Difference"
          value={formatSignedInr(preview.delta)}
          testId={`${testIdPrefix}.delta`}
          valueClassName={DELTA_CLASSES[direction]}
        />
      </div>

      {showWeight && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">Chargeable weight:</span>
          <span data-testid={`${testIdPrefix}.old-weight`}>{formatKg(preview.old_chargeable_weight)}</span>
          <ArrowRight className="h-3 w-3" />
          <span data-testid={`${testIdPrefix}.new-weight`} className="font-semibold text-foreground">
            {formatKg(preview.new_chargeable_weight)}
          </span>
        </div>
      )}

      <div
        data-testid={`${testIdPrefix}.settlement`}
        className="flex items-start gap-2 rounded-lg border border-border bg-background p-3 text-xs"
      >
        <Info className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
        <div className="space-y-0.5">
          <p className="font-semibold text-foreground">
            {preview.settlement_message || SETTLEMENT_LABELS[preview.settlement_action]}
          </p>
          <p data-testid={`${testIdPrefix}.note-type`} className="text-muted-foreground">
            {preview.note_type
              ? `${NOTE_LABELS[preview.note_type]} (${preview.note_type})`
              : "No GST note required (NONE)"}
          </p>
        </div>
      </div>

      {showCollectible && (
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
          <span className="font-semibold text-foreground">Amount to collect at delivery:</span>
          <span data-testid={`${testIdPrefix}.old-collectible`}>{formatInr(preview.old_cod_collectible)}</span>
          <ArrowRight className="h-3 w-3" />
          <span data-testid={`${testIdPrefix}.new-collectible`} className="font-semibold text-foreground">
            {formatInr(preview.new_cod_collectible)}
          </span>
        </div>
      )}

      {preview.rejected_fields.length > 0 && (
        <ul data-testid={`${testIdPrefix}.rejections`} className="space-y-1.5">
          {preview.rejected_fields.map((item) => (
            <li
              key={`${item.field}-${item.rule}`}
              data-testid={`${testIdPrefix}.rejection-${item.field}`}
              className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5 text-xs text-destructive"
            >
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>{item.message}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
