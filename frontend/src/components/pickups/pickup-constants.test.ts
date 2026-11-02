// frontend/src/components/pickups/pickup-constants.test.ts
import { ManifestStatus, PickupStatus, PickupTimeSlot, ServiceFlow } from "@/api_client";
import { describe, expect, it } from "vitest";

import {
  buildCreatePickupHref,
  firstAvailablePickupSlot,
  formatPickupDate,
  getPickupDisplayId,
  getPickupSlotLabel,
  isPickupSlotPassed,
  nextWorkingApiDate,
  PICKUP_FLOW_CONFIG,
} from "./pickup-constants";
import {
  getManifestStatusDisplay,
  getShipmentStatusLabel,
  isShipmentPickupSelectable,
} from "./status-display";

const TODAY = "2026-10-16";
// Friday 16 Oct 2026, 15:30 local time.
const AFTERNOON = new Date(2026, 9, 16, 15, 30);

describe("pickup slot helpers", () => {
  it("renders Delhivery-style slot labels with a plain hyphen", () => {
    expect(getPickupSlotLabel(PickupTimeSlot._14_00_18_00)).toBe("02:00 PM - 06:00 PM");
    expect(getPickupSlotLabel("custom slot")).toBe("custom slot");
  });

  it("greys out slots that already started today only", () => {
    expect(isPickupSlotPassed(PickupTimeSlot._14_00_18_00, TODAY, AFTERNOON)).toBe(true);
    expect(isPickupSlotPassed(PickupTimeSlot._18_00_22_00, TODAY, AFTERNOON)).toBe(false);
    expect(isPickupSlotPassed(PickupTimeSlot._06_00_10_00, "2026-10-17", AFTERNOON)).toBe(false);
  });

  it("picks the first bookable slot", () => {
    expect(firstAvailablePickupSlot(TODAY, AFTERNOON)).toBe(PickupTimeSlot._18_00_22_00);
    expect(firstAvailablePickupSlot("2026-10-17", AFTERNOON)).toBe(PickupTimeSlot._06_00_10_00);
  });
});

describe("pickup date helpers", () => {
  it("formats API dates without a UTC shift", () => {
    expect(formatPickupDate("2026-10-15")).toBe("15 Oct, 2026");
    expect(formatPickupDate(null)).toBe("-");
    expect(formatPickupDate("not-a-date")).toBe("-");
  });

  it("skips Sunday for the next working day", () => {
    // Saturday 17 Oct 2026 -> Monday 19 Oct 2026.
    expect(nextWorkingApiDate(new Date(2026, 9, 17, 10, 0))).toBe("2026-10-19");
    expect(nextWorkingApiDate(AFTERNOON)).toBe("2026-10-17");
  });
});

describe("buildCreatePickupHref", () => {
  it("returns the bare create route without prefill", () => {
    expect(buildCreatePickupHref(ServiceFlow.B2C, {})).toBe("/pickup-requests/new");
  });

  it("encodes location, shipments and date for the flow", () => {
    const href = buildCreatePickupHref(ServiceFlow.B2B, {
      locationId: "loc-1",
      locationName: "Main Warehouse",
      shipmentIds: ["a", "b"],
      date: "2026-10-19",
    });
    const [path, query] = href.split("?");
    expect(path).toBe(PICKUP_FLOW_CONFIG[ServiceFlow.B2B].createHref);
    const params = new URLSearchParams(query);
    expect(params.get("location")).toBe("loc-1");
    expect(params.get("location_name")).toBe("Main Warehouse");
    expect(params.get("shipments")).toBe("a,b");
    expect(params.get("date")).toBe("2026-10-19");
  });
});

describe("status display", () => {
  it("uses Delhivery wording for pre-pickup shipment states", () => {
    expect(getShipmentStatusLabel(PickupStatus.OPEN)).toBe("Ready to Ship");
    expect(getShipmentStatusLabel(PickupStatus.ASSIGNED)).toBe("Ready for Pickup");
    expect(getShipmentStatusLabel(PickupStatus.IN_TRANSIT)).toBe("In Transit");
  });

  it("only lets Ready to Ship shipments be added to a pickup", () => {
    expect(isShipmentPickupSelectable(PickupStatus.OPEN)).toBe(true);
    expect(isShipmentPickupSelectable(PickupStatus.ASSIGNED)).toBe(false);
  });

  it("labels every pickup request status", () => {
    expect(getManifestStatusDisplay(ManifestStatus.NOT_PICKED).label).toBe("Not Picked");
    expect(getManifestStatusDisplay(ManifestStatus.CANCELED).label).toBe("Cancelled");
  });

  it("shows the 9-digit Pickup ID, or a short id for legacy rows", () => {
    expect(getPickupDisplayId({ id: "abcdef12-3456", pickup_request_number: "328874598" })).toBe(
      "328874598"
    );
    expect(getPickupDisplayId({ id: "abcdef12-3456", pickup_request_number: null })).toBe("ABCDEF12");
  });
});
