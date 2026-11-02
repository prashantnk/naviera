// frontend/src/components/carrier/carrier-booking-dialog.tsx
"use client";

/**
 * "Carrier AWB" button + dialog for the ops desk rows (pricing redesign D7).
 *
 * The ops control tower lists many shipments per tab, so instead of a full card per row
 * it shows one small button that opens {@link CarrierBillingPanel} in a dialog. The
 * panel is mounted only while the dialog is open, so no carrier-billing request is made
 * for rows nobody opens.
 */
import { Truck } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

import type { CarrierBillingRead } from "./carrier-api";
import { CarrierBillingPanel } from "./carrier-billing-panel";

export interface CarrierBookingDialogProps {
  shipmentId: string;
  tenantSlug?: string | null;
  /** Logismart tracking id, used in the title and the test ids. */
  trackingId: string;
  /** Called after a save (e.g. to reload the ops lists). */
  onSaved?: (billing: CarrierBillingRead) => void;
}

/**
 * Renders the trigger button and, when open, the carrier booking panel.
 *
 * @param props - See {@link CarrierBookingDialogProps}.
 */
export function CarrierBookingDialog({ shipmentId, tenantSlug, trackingId, onSaved }: CarrierBookingDialogProps) {
  const [open, setOpen] = useState(false);
  const testId = `carrier-booking-dialog.${trackingId}`;

  return (
    <>
      <Button type="button" size="sm" variant="outline" onClick={() => setOpen(true)} data-testid={`${testId}.open`}>
        <Truck className="h-4 w-4" /> Carrier AWB
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent data-testid={testId} className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Carrier booking · {trackingId}</DialogTitle>
            <DialogDescription>Carrier AWB and the charges the carrier billed for this shipment.</DialogDescription>
          </DialogHeader>
          {open && (
            <CarrierBillingPanel
              shipmentId={shipmentId}
              tenantSlug={tenantSlug}
              onSaved={onSaved}
              className="border-0 p-0 shadow-none"
            />
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}
