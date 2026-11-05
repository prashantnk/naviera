// frontend/src/app/[tenant_slug]/(app)/b2b/appointments/_components/book-appointment-dialog.test.tsx
import {
  PickupStatus,
  PickupTimeSlot,
  ShipmentsService,
  type AppointmentRow,
  type PickupRead,
} from "@/api_client";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { slotToIsoWindow } from "./appointment-helpers";
import { BookAppointmentDialog } from "./book-appointment-dialog";

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ tenantSlug: "logismart-test" }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ROW: AppointmentRow = {
  shipment_id: "11111111-1111-1111-1111-111111111111",
  tracking_id: "LR-0001",
  box_count: 1,
  po_number: "PO-1",
  po_expiry_date: "2030-02-01",
  po_missing: false,
  po_expired: false,
  status: PickupStatus.IN_TRANSIT,
  appointment_start: slotToIsoWindow("2030-01-15", PickupTimeSlot._10_00_14_00).appointment_start,
};

/** Renders the dialog prefilled from ROW, so the submit button is enabled. */
function renderDialog() {
  const onBooked = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <BookAppointmentDialog open rows={[ROW]} onOpenChange={onOpenChange} onBooked={onBooked} />,
  );
  return { onBooked, onOpenChange };
}

describe("BookAppointmentDialog submit acknowledgement", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it("shows a pending state and sends exactly one request on a fast double submit", async () => {
    let resolveUpdate: (value: PickupRead) => void = () => {};
    const update = vi
      .spyOn(ShipmentsService, "updateAppointment")
      .mockReturnValue(
        new Promise<PickupRead>((resolve) => {
          resolveUpdate = resolve;
        }) as ReturnType<typeof ShipmentsService.updateAppointment>,
      );
    const { onBooked, onOpenChange } = renderDialog();

    const button = screen.getByRole("button", { name: /book appointment/i });
    const form = button.closest("form") as HTMLFormElement;
    fireEvent.click(button);
    // A second submit that bypasses the disabled button (e.g. Enter) must still be dropped.
    fireEvent.submit(form);
    fireEvent.click(button);

    const pendingButton = await screen.findByRole("button", { name: /booking/i });
    expect(pendingButton).toBeDisabled();
    expect(pendingButton.querySelector(".animate-spin")).not.toBeNull();
    expect(update).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveUpdate({} as PickupRead);
    });

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Appointment booked."));
    expect(update).toHaveBeenCalledTimes(1);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onBooked).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: /book appointment/i })).toBeEnabled();
  });

  it("toasts the API error and re-enables the button when booking fails", async () => {
    vi.spyOn(ShipmentsService, "updateAppointment").mockRejectedValue({
      body: { detail: "Appointment window is in the past." },
    });
    const { onBooked } = renderDialog();

    fireEvent.click(screen.getByRole("button", { name: /book appointment/i }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Appointment window is in the past."),
    );
    expect(onBooked).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: /book appointment/i })).toBeEnabled();
  });
});
