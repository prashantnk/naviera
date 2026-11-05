// frontend/src/components/forms/update-status-dialog.submit.test.tsx
import { PickupStatus, UserRole } from "@/api_client";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockUpdate = vi.fn();

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    ShipmentsService: { updateShipment: (...a: unknown[]) => mockUpdate(...a) },
  };
});
vi.mock("@/components/auth/auth-guard", async () => {
  const caps = await import("@/components/auth/capabilities");
  return { useUser: () => ({ capabilities: caps.resolveCapabilities(UserRole.OPERATIONS_USER) }) };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";

import { UpdateStatusDialog } from "./update-status-dialog";

describe("UpdateStatusDialog submit", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("sends one update on a double submit and shows Saving… until the API settles", async () => {
    let resolveUpdate!: (value: unknown) => void;
    mockUpdate.mockReturnValue(new Promise((res) => (resolveUpdate = res)));
    const onSuccess = vi.fn();
    render(
      <UpdateStatusDialog
        shipmentId="ship-1"
        currentStatus={PickupStatus.IN_TRANSIT}
        allowedNextStatuses={[PickupStatus.OUT_FOR_DELIVERY]}
        onSuccess={onSuccess}
      />,
    );

    fireEvent.click(screen.getByTestId("shipment-detail.actions.update-status"));
    fireEvent.change(await screen.findByTestId("update-status.form.comment"), {
      target: { value: "Reached the destination hub." },
    });
    const submit = screen.getByTestId("update-status.actions.submit");
    const form = submit.closest("form") as HTMLFormElement;

    await act(async () => {
      fireEvent.submit(form);
      fireEvent.submit(form);
    });

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1));
    expect(submit).toBeDisabled();
    expect(submit).toHaveTextContent("Saving…");
    expect(submit.querySelector(".animate-spin")).not.toBeNull();

    await act(async () => resolveUpdate({}));

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith("Shipment status updated successfully!");
    expect(mockUpdate).toHaveBeenCalledTimes(1);
  });

  it("toasts the readable API error and re-enables the button", async () => {
    mockUpdate.mockRejectedValue({ body: { detail: "Invalid delivery OTP" } });
    render(
      <UpdateStatusDialog
        shipmentId="ship-1"
        currentStatus={PickupStatus.IN_TRANSIT}
        allowedNextStatuses={[]}
        onSuccess={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId("shipment-detail.actions.update-status"));
    fireEvent.change(await screen.findByTestId("update-status.form.comment"), {
      target: { value: "Reached the destination hub." },
    });
    const submit = screen.getByTestId("update-status.actions.submit");
    fireEvent.click(submit);

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Invalid delivery OTP"));
    expect(submit).not.toBeDisabled();
    expect(submit).toHaveTextContent("Save Update");
  });
});
