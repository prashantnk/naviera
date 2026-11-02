// frontend/src/components/booking/price-changed-dialog.tsx
"use client";

/**
 * Shown when "Book" returns 409 PRICE_CHANGED: the backend re-prices every booking
 * (DESIGN.md v4, Q7) and asks the user to confirm a different total before booking.
 */
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { formatInr } from "@/components/shipments/shipment-money";
import { Loader2 } from "lucide-react";
import type { PriceChangedDetail } from "./booking-api";

export interface PriceChangedDialogProps {
  /** The 409 detail, or null when the dialog is closed. */
  change: PriceChangedDetail | null;
  isSubmitting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function PriceChangedDialog({ change, isSubmitting, onConfirm, onCancel }: PriceChangedDialogProps) {
  return (
    <Dialog open={change !== null} onOpenChange={(open) => !open && !isSubmitting && onCancel()}>
      <DialogContent data-testid="booking.price-changed">
        <DialogHeader>
          <DialogTitle>The price has changed</DialogTitle>
          <DialogDescription>
            {change?.message || "The carrier's price changed since you checked rates."}
          </DialogDescription>
        </DialogHeader>
        {change && (
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div className="rounded-lg border border-border p-3">
              <p className="text-xs text-muted-foreground">You saw</p>
              <p className="font-mono font-semibold line-through" data-testid="booking.price-changed.old">
                {formatInr(change.expected_total)}
              </p>
            </div>
            <div className="rounded-lg border border-primary/40 bg-primary/5 p-3">
              <p className="text-xs text-muted-foreground">New price</p>
              <p className="font-mono text-lg font-bold" data-testid="booking.price-changed.new">
                {formatInr(change.new_total)}
              </p>
            </div>
          </div>
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel} disabled={isSubmitting}>
            Don&apos;t book
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            disabled={isSubmitting}
            data-testid="booking.price-changed.confirm"
          >
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {change ? `Book for ${formatInr(change.new_total)}` : "Book"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
