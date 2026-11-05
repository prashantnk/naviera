// frontend/src/components/pickups/pickup-otp.test.tsx
import { ManifestResponse, ManifestStatus, PickupStatus, ServiceFlow } from "@/api_client";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DispatchPickupDialog } from "./pickup-action-dialogs";
import { PickupOtpBadge } from "./pickup-row-parts";

vi.mock("@/components/providers/tenant-provider", () => ({
  useTenant: () => ({ routeTo: (path: string) => `/logismart-test${path}`, tenantSlug: "logismart-test" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

function makeManifest(overrides: Partial<ManifestResponse> = {}): ManifestResponse {
  return {
    id: "m-101",
    tenant_id: "t-1",
    pickup_address_id: "addr-1",
    scheduled_date: "2026-11-05",
    time_slot: "14:00 - 18:00",
    is_blind_pickup: false,
    total_boxes: 1,
    created_at: "2026-11-05T04:00:00Z",
    status: ManifestStatus.SCHEDULED,
    service_flow: ServiceFlow.B2C,
    pickup_request_number: "742819201",
    pickup_otp: "482910",
    shipments: [
      {
        id: "ship-1",
        tracking_id: "AWB99001122",
        order_reference_id: "ORD-1",
        package_count: 1,
        status: PickupStatus.ASSIGNED,
      },
    ],
    ...overrides,
  };
}

describe("PickupOtpBadge", () => {
  it("renders the 6-digit handover OTP badge for active pickups when pickup_otp is returned", () => {
    const manifest = makeManifest({ pickup_otp: "482910", status: ManifestStatus.SCHEDULED });
    render(<PickupOtpBadge manifest={manifest} />);
    expect(screen.getByTestId("pickups.otp.m-101")).toHaveTextContent("482910");
    expect(screen.getByTestId("pickups.copy-otp.m-101")).toBeInTheDocument();
  });

  it("renders nothing when pickup_otp is stripped (operations/support/readonly) or pickup is terminal", () => {
    const stripped = makeManifest({ pickup_otp: null, status: ManifestStatus.SCHEDULED });
    const { rerender } = render(<PickupOtpBadge manifest={stripped} />);
    expect(screen.queryByTestId("pickups.otp.m-101")).not.toBeInTheDocument();

    const picked = makeManifest({ pickup_otp: "482910", status: ManifestStatus.PICKED });
    rerender(<PickupOtpBadge manifest={picked} />);
    expect(screen.queryByTestId("pickups.otp.m-101")).not.toBeInTheDocument();
  });
});

describe("DispatchPickupDialog (OTP verification & Owner/Admin override)", () => {
  const shipments = [
    {
      id: "ship-1",
      tracking_id: "AWB99001122",
      order_reference_id: "ORD-1",
      package_count: 1,
      status: PickupStatus.ASSIGNED,
    },
  ];

  it("requires a 6-digit OTP before calling onSubmit and hides override toggle for non-admin roles", async () => {
    const onSubmit = vi.fn();
    render(
      <DispatchPickupDialog
        open={true}
        pickupLabel="742819201"
        shipments={shipments}
        submitting={false}
        canOverrideOtp={false}
        onSubmit={onSubmit}
        onOpenChange={() => undefined}
      />,
    );

    expect(screen.queryByTestId("pickup-dispatch.override-toggle")).not.toBeInTheDocument();

    // Submitting without OTP shows validation message and does not call onSubmit
    fireEvent.click(screen.getByTestId("pickup-dispatch.actions.confirm"));
    expect(await screen.findByTestId("pickup-dispatch.error")).toHaveTextContent(
      /Enter the 6-digit pickup handover OTP/i,
    );
    expect(onSubmit).not.toHaveBeenCalled();

    // Entering a valid 6-digit OTP submits it
    fireEvent.change(screen.getByTestId("pickup-dispatch.otp-input"), {
      target: { value: "482910" },
    });
    fireEvent.click(screen.getByTestId("pickup-dispatch.actions.confirm"));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(["ship-1"], [], "482910", undefined),
    );
  });

  it("allows Owner/Admin to override OTP only when a mandatory reason is provided", async () => {
    const onSubmit = vi.fn();
    render(
      <DispatchPickupDialog
        open={true}
        pickupLabel="742819201"
        shipments={shipments}
        submitting={false}
        canOverrideOtp={true}
        onSubmit={onSubmit}
        onOpenChange={() => undefined}
      />,
    );

    const toggle = screen.getByTestId("pickup-dispatch.override-toggle");
    fireEvent.click(toggle);

    // Submitting with blank reason shows error
    fireEvent.click(screen.getByTestId("pickup-dispatch.actions.confirm"));
    expect(await screen.findByTestId("pickup-dispatch.error")).toHaveTextContent(
      /mandatory override reason is required/i,
    );
    expect(onSubmit).not.toHaveBeenCalled();

    // Filling mandatory reason submits override
    fireEvent.change(screen.getByTestId("pickup-dispatch.override-reason"), {
      target: { value: "Seller unreachable at dock; verified by hub manager" },
    });
    fireEvent.click(screen.getByTestId("pickup-dispatch.actions.confirm"));
    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        ["ship-1"],
        [],
        undefined,
        "Seller unreachable at dock; verified by hub manager",
      ),
    );
  });
});
