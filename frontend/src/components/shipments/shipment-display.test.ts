// frontend/src/components/shipments/shipment-display.test.ts
import { ServiceOption, ServiceType } from "@/api_client";
import { describe, expect, it } from "vitest";
import {
  PICKUP_NOT_SCHEDULED_LABEL,
  pickupDateLabel,
  serviceLabel,
  stageTimestampLabel,
} from "./shipment-display";

describe("serviceLabel", () => {
  it("uses the booked service option label (not the raw service_type enum)", () => {
    expect(
      serviceLabel({ service_option: ServiceOption.DELHIVERY_EXPRESS, service_type: ServiceType.AIR }),
    ).toBe("Delhivery Express");
    expect(
      serviceLabel({ service_option: ServiceOption.DELHIVERY_SURFACE, service_type: ServiceType.SURFACE_ROAD }),
    ).toBe("Delhivery Surface");
  });

  it("falls back to the legacy service type in words for rows without an option", () => {
    expect(serviceLabel({ service_option: undefined, service_type: ServiceType.SURFACE_ROAD })).toBe("Surface Road");
  });
});

describe("pickupDateLabel", () => {
  it("says 'Not scheduled yet' until the order is on a pickup request", () => {
    expect(pickupDateLabel("2026-11-01", false)).toBe(PICKUP_NOT_SCHEDULED_LABEL);
    expect(pickupDateLabel(null, true)).toBe(PICKUP_NOT_SCHEDULED_LABEL);
  });

  it("shows the pickup request's date once scheduled", () => {
    expect(pickupDateLabel("2026-11-03", true)).toBe("03 Nov 2026");
  });
});

describe("stageTimestampLabel", () => {
  it("treats naive API timestamps as UTC and shows IST", () => {
    // 08:59 UTC == 14:29 IST (the audit log already shows 2:29 pm).
    expect(stageTimestampLabel("2026-11-01T08:59:00")).toBe("01 Nov 2026 · 2:29 PM");
  });

  it("returns undefined for empty or invalid values", () => {
    expect(stageTimestampLabel(undefined)).toBeUndefined();
    expect(stageTimestampLabel("garbage")).toBeUndefined();
  });
});
