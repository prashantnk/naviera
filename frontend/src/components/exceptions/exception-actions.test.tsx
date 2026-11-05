// frontend/src/components/exceptions/exception-actions.test.tsx
import { ExceptionsService, NdrAction, UserRole } from "@/api_client";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { toast } from "sonner";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ExceptionActionDialog, type ExtendedExceptionRow } from "./exception-action-dialogs";

vi.mock("@/components/auth/auth-guard", async () => {
  const caps = await import("@/components/auth/capabilities");
  return { useUser: () => ({ capabilities: caps.resolveCapabilities(UserRole.OWNER) }) };
});

vi.mock("@/components/shipments/use-reprice-preview", () => ({
  useRepricePreview: () => ({ preview: null, loading: false, error: null }),
}));

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return { ...actual, ExceptionsService: { applyExceptionAction: vi.fn() } };
});

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const ROW = {
  shipment_id: "11111111-1111-1111-1111-111111111111",
  tracking_id: "LS123456789",
  attempts: 1,
  max_attempts: 3,
  box_count: 1,
  consignee: { name: "Asha", phone: "9876543210", pincode: "560001" },
} as unknown as ExtendedExceptionRow;

/** Renders the Re-attempt NDR dialog and returns its submit button. */
function renderReattemptDialog(onSuccess = vi.fn()): HTMLElement {
  render(
    <ExceptionActionDialog
      open
      action={NdrAction.REATTEMPT}
      row={ROW}
      tenantSlug="logismart-test"
      onOpenChange={vi.fn()}
      onSuccess={onSuccess}
    />,
  );
  return screen.getByTestId("exception-action.actions.submit");
}

describe("ExceptionActionDialog submit acknowledgement", () => {
  beforeEach(() => {
    vi.mocked(ExceptionsService.applyExceptionAction).mockReset();
    vi.mocked(toast.success).mockReset();
    vi.mocked(toast.error).mockReset();
  });

  it("shows a spinner, disables the button and sends exactly one request on a double click", async () => {
    let resolveCall: (value: ExtendedExceptionRow) => void = () => {};
    vi.mocked(ExceptionsService.applyExceptionAction).mockReturnValue(
      new Promise<ExtendedExceptionRow>((resolve) => {
        resolveCall = resolve;
      }) as ReturnType<typeof ExceptionsService.applyExceptionAction>,
    );
    const onSuccess = vi.fn();
    const submit = renderReattemptDialog(onSuccess);

    // Both clicks land in one batch, before React re-renders the button as disabled.
    act(() => {
      submit.click();
      submit.click();
    });

    await waitFor(() => expect(submit).toBeDisabled());
    expect(submit.querySelector(".animate-spin")).not.toBeNull();
    expect(ExceptionsService.applyExceptionAction).toHaveBeenCalledTimes(1);

    resolveCall(ROW);

    await waitFor(() => expect(submit).not.toBeDisabled());
    expect(submit.querySelector(".animate-spin")).toBeNull();
    expect(toast.success).toHaveBeenCalledTimes(1);
    expect(onSuccess).toHaveBeenCalledTimes(1);
  });

  it("re-enables the button and shows a friendly error toast when the request fails", async () => {
    vi.mocked(ExceptionsService.applyExceptionAction).mockRejectedValue(new Error("boom"));
    const submit = renderReattemptDialog();

    fireEvent.click(submit);

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(submit).not.toBeDisabled());
    expect(toast.success).not.toHaveBeenCalled();
  });
});
