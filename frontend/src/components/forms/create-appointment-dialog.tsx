"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Loader2, CalendarClock } from "lucide-react";
import { ShipmentsService } from "@/api_client";
import { extractApiErrorMessage, toIstIsoString } from "@/lib/utils";
import { MAX_PO_NUMBERS, splitPoNumbers } from "@/lib/validations/shipment";
import { useTenant } from "@/components/providers/tenant-provider";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { toast } from "sonner";
import { IconSelect } from "@/components/ui/icon-select";
import { RequiredMark } from "@/components/ui/form-extras";
import { PICKUP_TIME_SLOT_OPTIONS, toOptions } from "@/lib/form-options";

/** Appointment windows reuse the pickup slot metadata (same API values). */
const APPOINTMENT_SLOT_OPTIONS = toOptions(PICKUP_TIME_SLOT_OPTIONS);

interface CreateAppointmentDialogProps {
  shipmentId: string;
  onSuccess?: () => void;
  trigger?: React.ReactNode;
}

export function CreateAppointmentDialog({ shipmentId, onSuccess, trigger }: CreateAppointmentDialogProps) {
  const [open, setOpen] = useState(false);
  const { pending: loading, run } = useSingleFlight();
  const { tenantSlug } = useTenant();

  const [date, setDate] = useState("");
  const [slot, setSlot] = useState("");
  const [poNumber, setPoNumber] = useState("");
  const [poExpiry, setPoExpiry] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!date || !slot) {
      toast.error("Date and Time Slot are required.");
      return;
    }
    if (poNumber.trim() && splitPoNumbers(poNumber).length > MAX_PO_NUMBERS) {
      toast.error(`Maximum ${MAX_PO_NUMBERS} comma-separated PO numbers are allowed.`);
      return;
    }
    if (poExpiry && poExpiry < date) {
      toast.error("PO expiry date cannot be earlier than the appointment date.");
      return;
    }

    const [startStr, endStr] = slot.split(" - ");
    const startIso = toIstIsoString(`${date}T${startStr}:00`);
    const endIso = toIstIsoString(`${date}T${endStr}:00`);
    if (!startIso || !endIso) {
      toast.error("Invalid appointment date or time slot.");
      return;
    }

    void run(async () => {
      try {
        await ShipmentsService.updateAppointment(
          shipmentId,
          {
            appointment_start: startIso,
            appointment_end: endIso,
            po_number: poNumber || undefined,
            po_expiry_date: poExpiry || undefined,
          },
          tenantSlug
        );
        toast.success("Appointment scheduled successfully");
        setOpen(false);
        onSuccess?.();
      } catch (error: unknown) {
        console.error(error);
        toast.error(extractApiErrorMessage(error, "Failed to schedule appointment"));
      }
    });
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button variant="outline" className="font-bold border-primary/20 text-primary bg-primary/10 hover:bg-primary/20">
            <CalendarClock className="w-4 h-4 mr-2" />
            Schedule Appointment
          </Button>
        )}
      </DialogTrigger>
      <DialogContent className="sm:max-w-[425px]">
        <form onSubmit={handleSubmit}>
          <DialogHeader>
            <DialogTitle>Schedule Delivery Appointment</DialogTitle>
            <DialogDescription>
              Set the delivery window and PO details for this shipment.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="date">Delivery Date <RequiredMark /></Label>
              <Input
                id="date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                min={new Date().toISOString().split("T")[0]}
                required
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="slot">
                Time Slot
                <RequiredMark />
              </Label>
              <IconSelect
                id="slot"
                options={APPOINTMENT_SLOT_OPTIONS}
                value={slot}
                onValueChange={setSlot}
                placeholder="Select window"
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="poNumber">PO Number (Optional)</Label>
              <Input
                id="poNumber"
                placeholder="e.g. PO-987654321"
                value={poNumber}
                onChange={(e) => setPoNumber(e.target.value)}
              />
            </div>
            <div className="grid gap-2">
              <Label htmlFor="poExpiry">PO Expiry Date (Optional)</Label>
              <Input
                id="poExpiry"
                type="date"
                value={poExpiry}
                onChange={(e) => setPoExpiry(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)} disabled={loading}>
              Cancel
            </Button>
            <Button type="submit" disabled={loading}>
              {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {loading ? "Saving…" : "Save Appointment"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
