// frontend/src/components/blocks/tracking-display.test.ts
import { ApiError, PickupStatus } from "@/api_client";
import { describe, expect, it } from "vitest";
import {
  TrackingLoadError,
  TrackingStepTone,
  buildPublicTrackingSteps,
  classifyTrackingError,
  contiguousProgressIndex,
  friendlyActivityTitle,
  getPublicStatusLabel,
  normalizeTrackingId,
} from "./tracking-display";

const reached = (status: PickupStatus) =>
  buildPublicTrackingSteps(status).map((step) => step.reached);

function apiError(status: number): ApiError {
  return new ApiError(
    { method: "GET", url: "/api/v1/tracking/X" },
    { url: "/api/v1/tracking/X", ok: false, status, statusText: "", body: {} },
    "failed",
  );
}

describe("buildPublicTrackingSteps (F-01)", () => {
  it("has a Picked up step and friendly labels", () => {
    expect(buildPublicTrackingSteps(PickupStatus.OPEN).map((s) => s.label)).toEqual([
      "Booked",
      "Picked up",
      "In transit",
      "Out for delivery",
      "Delivered",
    ]);
  });

  it.each([PickupStatus.DRAFT, PickupStatus.OPEN, PickupStatus.ASSIGNED])(
    "%s waits for pickup: only Booked is ticked (no 'Dispatched')",
    (status) => {
      expect(reached(status)).toEqual([true, false, false, false, false]);
    },
  );

  it("ticks Picked up + In transit once in transit", () => {
    expect(reached(PickupStatus.IN_TRANSIT)).toEqual([true, true, true, false, false]);
  });

  it("delivered ticks every step with a normal tone", () => {
    const steps = buildPublicTrackingSteps(PickupStatus.COMPLETED);
    expect(steps.every((s) => s.reached)).toBe(true);
    expect(steps[4]).toMatchObject({ label: "Delivered", tone: TrackingStepTone.PROGRESS });
  });

  it("RTO shows its outcome as an alert closing step", () => {
    const steps = buildPublicTrackingSteps(PickupStatus.RTO_IN_TRANSIT);
    expect(steps[4]).toMatchObject({
      label: "Returning to seller",
      reached: true,
      tone: TrackingStepTone.ALERT,
    });
    expect(steps[4].label).not.toBe("Delivered");
    expect(contiguousProgressIndex(steps)).toBe(2);

    const rtoDeliveredSteps = buildPublicTrackingSteps(PickupStatus.RTO_DELIVERED);
    expect(rtoDeliveredSteps[4]).toMatchObject({
      label: "Returned to seller",
      reached: true,
      tone: TrackingStepTone.ALERT,
    });
  });

  it("getPublicStatusLabel uses consumer wording and never shows RTO jargon or Delivered for RTO", () => {
    expect(getPublicStatusLabel(PickupStatus.RTO_INITIATED)).toBe("Returning to seller");
    expect(getPublicStatusLabel(PickupStatus.RTO_IN_TRANSIT)).toBe("Returning to seller");
    expect(getPublicStatusLabel(PickupStatus.RTO_DELIVERED)).toBe("Returned to seller");
    expect(getPublicStatusLabel(PickupStatus.EXCEPTION)).toBe("Shipment on hold");
    expect(getPublicStatusLabel(PickupStatus.OPEN)).toBe("Order placed");
    expect(getPublicStatusLabel(PickupStatus.COMPLETED)).toBe("Delivered");
  });

  it("cancelled before pickup does not fill the progress line", () => {
    const steps = buildPublicTrackingSteps(PickupStatus.CANCELLED);
    expect(steps[4]).toMatchObject({ label: "Cancelled", reached: true });
    expect(contiguousProgressIndex(steps)).toBe(0);
  });
});

describe("friendlyActivityTitle (F-01)", () => {
  it("maps raw status fragments to labels", () => {
    expect(friendlyActivityTitle("Status: OUT_FOR_DELIVERY")).toBe("Out for delivery");
    expect(friendlyActivityTitle("Status: COMPLETED")).toBe("Delivered");
    expect(friendlyActivityTitle("OPEN")).toBe("Ready to Ship");
  });

  it("maps NDR fragments and keeps the rest of a joined summary", () => {
    expect(
      friendlyActivityTitle("Status: EXCEPTION, Exception Raised: CONSIGNEE_REFUSED"),
    ).toBe("Exception (NDR), Delivery issue: Consignee refused");
  });

  it("leaves human titles and unknown enums untouched", () => {
    expect(friendlyActivityTitle("Shipment Created")).toBe("Shipment Created");
    expect(friendlyActivityTitle("Status: NOT_A_STATUS")).toBe("Status: NOT_A_STATUS");
  });
});

describe("normalizeTrackingId / classifyTrackingError (F-09)", () => {
  it("trims, removes spaces and upper-cases", () => {
    expect(normalizeTrackingId("  nav-a1b2 c3d4 ")).toBe("NAV-A1B2C3D4");
    expect(normalizeTrackingId(undefined)).toBe("");
  });

  it("only a real 404 is 'not found'; anything else is retryable", () => {
    expect(classifyTrackingError(apiError(404))).toBe(TrackingLoadError.NOT_FOUND);
    expect(classifyTrackingError(apiError(500))).toBe(TrackingLoadError.UNAVAILABLE);
    expect(classifyTrackingError(apiError(502))).toBe(TrackingLoadError.UNAVAILABLE);
    expect(classifyTrackingError(new TypeError("Network Error"))).toBe(
      TrackingLoadError.UNAVAILABLE,
    );
  });
});
