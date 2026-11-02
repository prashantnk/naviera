// frontend/src/components/shipments/shipment-stage.test.ts
import { PickupStatus } from "@/api_client";
import { getShipmentStatusLabel } from "@/components/pickups/status-display";
import { describe, expect, it } from "vitest";

import {
  SHIPMENT_STAGE_BY_STATUS,
  ShipmentStepperStage,
  ShipmentTrack,
  getClosingStepLabel,
  getShipmentStage,
  getShipmentStatusBadgeClass,
  isRtoTrack,
  isShipmentPickedUp,
  isStepperStageReached,
} from "./shipment-stage";

const ALL_STATUSES = Object.values(PickupStatus);

const PICKED_UP_STATUSES: readonly PickupStatus[] = [
  PickupStatus.IN_TRANSIT,
  PickupStatus.OUT_FOR_DELIVERY,
  PickupStatus.EXCEPTION,
  PickupStatus.COMPLETED,
  PickupStatus.RTO_INITIATED,
  PickupStatus.RTO_IN_TRANSIT,
  PickupStatus.RTO_DELIVERED,
  PickupStatus.LOST,
];

const RTO_STATUSES: readonly PickupStatus[] = [
  PickupStatus.RTO_INITIATED,
  PickupStatus.RTO_IN_TRANSIT,
  PickupStatus.RTO_DELIVERED,
];

describe("SHIPMENT_STAGE_BY_STATUS", () => {
  it("maps every PickupStatus", () => {
    expect(Object.keys(SHIPMENT_STAGE_BY_STATUS).sort()).toEqual(
      [...ALL_STATUSES].sort()
    );
    for (const status of ALL_STATUSES) {
      expect(getShipmentStage(status)).toBeDefined();
    }
  });

  it("gives every status a tinted badge and a non-raw label", () => {
    for (const status of ALL_STATUSES) {
      expect(getShipmentStatusBadgeClass(status)).toMatch(/\bborder-/);
      expect(getShipmentStatusLabel(status)).not.toContain("_");
    }
  });
});

describe("Out for delivery", () => {
  const status = PickupStatus.OUT_FOR_DELIVERY;

  it("ticks In-transit and Out for delivery but not the closing step", () => {
    expect(isShipmentPickedUp(status)).toBe(true);
    expect(isStepperStageReached(status, ShipmentStepperStage.IN_TRANSIT)).toBe(true);
    expect(
      isStepperStageReached(status, ShipmentStepperStage.OUT_FOR_DELIVERY)
    ).toBe(true);
    expect(getShipmentStage(status).isClosed).toBe(false);
    expect(getClosingStepLabel(status)).toBe("Delivered");
  });

  it("is on the forward track with Delhivery wording", () => {
    expect(isRtoTrack(status)).toBe(false);
    expect(getShipmentStatusLabel(status).toLowerCase()).toBe("out for delivery");
  });
});

describe("RTO and Lost", () => {
  it.each(RTO_STATUSES)("%s is picked up, on the RTO track and closed", (status) => {
    expect(isShipmentPickedUp(status)).toBe(true);
    expect(isRtoTrack(status)).toBe(true);
    expect(getShipmentStage(status).track).toBe(ShipmentTrack.RTO);
    expect(getShipmentStage(status).isClosed).toBe(true);
    expect(getClosingStepLabel(status)).toBe(getShipmentStatusLabel(status));
  });

  it("does not claim an RTO parcel went out for delivery", () => {
    for (const status of RTO_STATUSES) {
      expect(
        isStepperStageReached(status, ShipmentStepperStage.OUT_FOR_DELIVERY)
      ).toBe(false);
    }
  });

  it("shows Lost as picked up with a Lost closing step", () => {
    expect(isShipmentPickedUp(PickupStatus.LOST)).toBe(true);
    expect(isRtoTrack(PickupStatus.LOST)).toBe(false);
    expect(getClosingStepLabel(PickupStatus.LOST)).toBe("Lost");
  });
});

describe("picked-up flag", () => {
  it("is true only after the parcel left the seller", () => {
    for (const status of ALL_STATUSES) {
      expect(isShipmentPickedUp(status)).toBe(PICKED_UP_STATUSES.includes(status));
    }
  });

  it("closes Delivered and pre-pickup outcomes with their own labels", () => {
    expect(getClosingStepLabel(PickupStatus.COMPLETED)).toBe("Delivered");
    expect(getClosingStepLabel(PickupStatus.CANCELLED)).toBe("Cancelled");
    expect(
      isStepperStageReached(PickupStatus.CANCELLED, ShipmentStepperStage.READY_TO_SHIP)
    ).toBe(false);
  });

  it("orders the pre-pickup steps", () => {
    expect(
      isStepperStageReached(PickupStatus.OPEN, ShipmentStepperStage.READY_TO_SHIP)
    ).toBe(true);
    expect(
      isStepperStageReached(PickupStatus.OPEN, ShipmentStepperStage.PICKUP_SCHEDULED)
    ).toBe(false);
    expect(
      isStepperStageReached(PickupStatus.ASSIGNED, ShipmentStepperStage.PICKUP_SCHEDULED)
    ).toBe(true);
  });
});
