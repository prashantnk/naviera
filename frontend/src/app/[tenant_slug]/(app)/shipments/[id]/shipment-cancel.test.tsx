// frontend/src/app/[tenant_slug]/(app)/shipments/[id]/shipment-cancel.test.tsx
import { PickupStatus, ShipmentType, UserRole } from "@/api_client";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetDetails = vi.fn();
const mockGetTimeline = vi.fn();
const mockCancel = vi.fn();

vi.mock("@/api_client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api_client")>();
  return {
    ...actual,
    ShipmentsService: {
      getShipmentDetails: (...a: unknown[]) => mockGetDetails(...a),
      getShipmentTimeline: (...a: unknown[]) => mockGetTimeline(...a),
      cancelShipment: (...a: unknown[]) => mockCancel(...a),
    },
    ManifestsService: { listManifests: vi.fn().mockResolvedValue([]) },
  };
});
vi.mock("next/navigation", () => ({ useParams: () => ({ id: "ship-1" }) }));
vi.mock("@/components/auth/auth-guard", async () => {
  const caps = await import("@/components/auth/capabilities");
  return {
    useUser: () => ({
      user: { id: "u-1", email: "customerb2c@logismart.in" },
      capabilities: caps.resolveCapabilities(UserRole.CUSTOMER),
    }),
  };
});
vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ tenantSlug: "logismart-test", routeTo: (p: string) => `/t${p}` }),
}));
// Panels with their own data fetching are out of scope for the cancel button.
vi.mock("@/components/carrier/carrier-billing-panel", () => ({ CarrierBillingPanel: () => null }));
vi.mock("@/components/shipments/charges-history-card", () => ({ ChargesHistoryCard: () => null }));
vi.mock("@/components/wallet/shipment-pod-controls", () => ({
  ShipmentPodActions: () => null,
  ShipmentPodBanner: () => null,
}));
vi.mock("@/components/pickups/next-add-to-pickup-banner", () => ({ NextAddToPickupBanner: () => null }));
vi.mock("../new/page", () => ({ CATEGORY_LABELS: {} }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { toast } from "sonner";

import ShipmentDetailsPage from "./page";

const ADDRESS = {
  id: "a-1",
  name: "Asha",
  company_name: "Asha Traders",
  phone: "9876543210",
  address_line1: "12 MG Road",
  city: "Bengaluru",
  state: "Karnataka",
  pincode: "560001",
};

const OPEN_SHIPMENT = {
  id: "ship-1",
  tracking_id: "LGS123",
  status: PickupStatus.OPEN,
  shipment_type: ShipmentType.FORWARD,
  created_at: "2026-11-01T10:00:00",
  updated_at: "2026-11-01T10:00:00",
  pickup_address: ADDRESS,
  delivery_address: { ...ADDRESS, id: "a-2", name: "Ravi" },
  packages: [],
  documents: [],
  allowed_next_statuses: [],
};

/** A promise the test settles by hand, so the request stays in flight across clicks. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("Shipment detail: Cancel Order", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetDetails.mockResolvedValue(OPEN_SHIPMENT);
    mockGetTimeline.mockResolvedValue([]);
  });

  it("shows a spinner, sends one cancel on a fast double click, then toasts success", async () => {
    const pendingCancel = deferred<typeof OPEN_SHIPMENT>();
    mockCancel.mockReturnValue(pendingCancel.promise);
    render(<ShipmentDetailsPage />);

    fireEvent.click(await screen.findByTestId("shipment-detail.actions.cancel"));
    const confirm = await screen.findByTestId("shipment-detail.actions.cancel-confirm");

    act(() => {
      confirm.click();
      confirm.click();
    });

    expect(mockCancel).toHaveBeenCalledTimes(1);
    expect(mockCancel).toHaveBeenCalledWith("ship-1");
    expect(confirm).toBeDisabled();
    expect(confirm.querySelector(".animate-spin")).not.toBeNull();

    await act(async () => {
      pendingCancel.resolve({ ...OPEN_SHIPMENT, status: PickupStatus.CANCELLED });
    });

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Order cancelled and prepaid wallet balance refunded!"),
    );
    expect(mockCancel).toHaveBeenCalledTimes(1);
  });

  it("shows the API error and re-enables the confirm button", async () => {
    mockCancel.mockRejectedValue({ body: { detail: "Shipment already picked up" } });
    render(<ShipmentDetailsPage />);

    fireEvent.click(await screen.findByTestId("shipment-detail.actions.cancel"));
    const confirm = await screen.findByTestId("shipment-detail.actions.cancel-confirm");
    fireEvent.click(confirm);

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Shipment already picked up"));
    expect(confirm).not.toBeDisabled();
    expect(confirm.querySelector(".animate-spin")).toBeNull();
  });
});
