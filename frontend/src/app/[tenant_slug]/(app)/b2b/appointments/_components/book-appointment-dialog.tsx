// frontend/src/app/[tenant_slug]/(app)/b2b/appointments/_components/book-appointment-dialog.tsx
"use client";

/**
 * Delhivery "Book appointment" modal: PO number*, PO expiry date*, Appointment
 * date*, Appointment time* (time unlocks after a date is picked). Saves through
 * the existing `PATCH /api/v1/shipments/{id}/appointment`.
 *
 * In bulk mode (several LRs) only the date and time are required; PO fields are
 * applied to every LR only when filled in.
 */
import { PickupTimeSlot, ShipmentsService, type AppointmentRow } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { RequiredMark } from "@/components/ui/form-extras";
import { IconSelect } from "@/components/ui/icon-select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { todayApiDate } from "@/components/pickups/pickup-constants";
import { PICKUP_TIME_SLOT_OPTIONS, toOptions } from "@/lib/form-options";
import { extractApiErrorMessage } from "@/lib/utils";
import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { isoToDateAndSlot, slotToIsoWindow, validateBookAppointment } from "./appointment-helpers";

/** Appointment windows reuse the pickup slot metadata (same API values). */
const APPOINTMENT_SLOT_OPTIONS = toOptions(PICKUP_TIME_SLOT_OPTIONS);

interface BookAppointmentDialogProps {
  open: boolean;
  /** One row (single booking) or several rows (bulk booking). */
  rows: readonly AppointmentRow[];
  onOpenChange: (open: boolean) => void;
  onBooked: () => void;
}

/** Inline field error, Delhivery style (red text under the input). */
function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return <p className="text-xs font-medium text-destructive">{message}</p>;
}

export function BookAppointmentDialog({
  open,
  rows,
  onOpenChange,
  onBooked,
}: BookAppointmentDialogProps) {
  const { tenantSlug } = useTenant();
  const isBulk = rows.length > 1;
  const single = rows.length === 1 ? rows[0] : null;

  const [poNumber, setPoNumber] = useState("");
  const [poExpiry, setPoExpiry] = useState("");
  const [date, setDate] = useState("");
  const [slot, setSlot] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    const existing = isoToDateAndSlot(single?.appointment_start);
    setPoNumber(single?.po_number ?? "");
    setPoExpiry(single?.po_expiry_date ?? "");
    setDate(existing.date ?? "");
    setSlot(existing.slot ?? "");
    setErrors({});
  }, [open, single]);

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const nextErrors = validateBookAppointment({ poNumber, poExpiry, date, slot });
    if (isBulk) {
      if (!poNumber.trim()) delete nextErrors.poNumber;
      if (!poExpiry) delete nextErrors.poExpiry;
    }
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) return;

    const slotWindow = slotToIsoWindow(date, slot as PickupTimeSlot);
    const body = Object.assign({}, slotWindow, {
      po_number: poNumber.trim() || undefined,
      po_expiry_date: poExpiry || undefined,
    });

    setSaving(true);
    let booked = 0;
    let failed = 0;
    let lastError = "";
    for (const row of rows) {
      try {
        await ShipmentsService.updateAppointment(row.shipment_id, body, tenantSlug);
        booked += 1;
      } catch (error) {
        failed += 1;
        lastError = extractApiErrorMessage(error, "Failed to book appointment.");
      }
    }
    setSaving(false);

    if (booked > 0) {
      toast.success(
        isBulk ? `Appointment booked for ${booked} LR(s).` : "Appointment booked."
      );
    }
    if (failed > 0) {
      toast.error(isBulk ? `${failed} LR(s) could not be booked. ${lastError}` : lastError);
    }
    if (booked > 0) {
      onOpenChange(false);
      onBooked();
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-[520px]">
        <form onSubmit={handleSubmit} noValidate>
          <DialogHeader>
            <DialogTitle>{isBulk ? "Create bulk appointment" : "Book appointment"}</DialogTitle>
            <DialogDescription>
              {isBulk
                ? `${rows.length} LRs selected`
                : `LRN : ${single?.tracking_id || single?.order_reference_id || "-"}`}
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-4 py-4 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="appt-po-number">
                PO number {!isBulk && <RequiredMark />}
              </Label>
              <Input
                id="appt-po-number"
                placeholder="Enter PO number"
                maxLength={255}
                value={poNumber}
                aria-invalid={Boolean(errors.poNumber)}
                onChange={(event) => setPoNumber(event.target.value)}
              />
              <FieldError message={errors.poNumber} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="appt-po-expiry">
                PO expiry date {!isBulk && <RequiredMark />}
              </Label>
              <Input
                id="appt-po-expiry"
                type="date"
                value={poExpiry}
                aria-invalid={Boolean(errors.poExpiry)}
                onChange={(event) => setPoExpiry(event.target.value)}
              />
              <FieldError message={errors.poExpiry} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="appt-date">
                Appointment date <RequiredMark />
              </Label>
              <Input
                id="appt-date"
                type="date"
                min={todayApiDate()}
                value={date}
                aria-invalid={Boolean(errors.date)}
                onChange={(event) => setDate(event.target.value)}
              />
              <FieldError message={errors.date} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="appt-slot" className={!date ? "text-muted-foreground" : undefined}>
                Appointment time <RequiredMark />
              </Label>
              <IconSelect
                id="appt-slot"
                options={APPOINTMENT_SLOT_OPTIONS}
                value={slot}
                onValueChange={setSlot}
                placeholder="Select time"
                disabled={!date}
              />
              <FieldError message={errors.slot} />
            </div>
          </div>

          <DialogFooter>
            <Button type="submit" disabled={saving || !date || !slot}>
              {saving && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Book appointment
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
