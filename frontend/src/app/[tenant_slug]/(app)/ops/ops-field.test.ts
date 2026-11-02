// frontend/src/app/[tenant_slug]/(app)/ops/ops-field.test.ts
import { describe, expect, it } from "vitest";

import { CodRemittanceStatus, ManifestStatus, NdrExceptionReason, PickupStatus, ShipmentType } from "@/api_client";

import {
  CashBadgeTone,
  DeliveryFilterKey,
  FIELD_NDR_SELECT_OPTIONS,
  canMoveTo,
  cashCollectionBadge,
  isActiveRunsheet,
  isDoorCashPending,
  loadPodDraft,
  matchesDeliveryFilter,
  matchesPickupFilter,
  PICKUP_FILTER_ACTIVE,
  PICKUP_FILTER_ALL,
  ndrReasonLabel,
  parseActualPieces,
  pickedBoxesLabel,
  podDraftStorageKey,
  savePodDraft,
  serviceTypeLabel,
  withoutEntry,
} from "./ops-field";

const forward = (status: PickupStatus) => ({ status, shipment_type: ShipmentType.FORWARD });
const reverse = (status: PickupStatus) => ({ status, shipment_type: ShipmentType.REVERSE });

describe("D-01 delivery filters", () => {
  it.each([
    PickupStatus.IN_TRANSIT,
    PickupStatus.OUT_FOR_DELIVERY,
    PickupStatus.RTO_INITIATED,
    PickupStatus.RTO_IN_TRANSIT,
  ])("keeps %s on the active run-sheet", (status) => {
    expect(isActiveRunsheet(forward(status))).toBe(true);
    expect(matchesDeliveryFilter(forward(status), DeliveryFilterKey.ACTIVE)).toBe(true);
  });

  it("lists reverse pickups before pickup but not forward ones", () => {
    expect(isActiveRunsheet(reverse(PickupStatus.OPEN))).toBe(true);
    expect(isActiveRunsheet(forward(PickupStatus.OPEN))).toBe(false);
  });

  it("an OFD parcel never disappears under ALL or its own chip", () => {
    const ofd = forward(PickupStatus.OUT_FOR_DELIVERY);
    expect(matchesDeliveryFilter(ofd, DeliveryFilterKey.ALL)).toBe(true);
    expect(matchesDeliveryFilter(ofd, PickupStatus.OUT_FOR_DELIVERY)).toBe(true);
    expect(matchesDeliveryFilter(ofd, PickupStatus.IN_TRANSIT)).toBe(false);
  });

  it("the RTO chip shows both RTO legs only", () => {
    expect(matchesDeliveryFilter(forward(PickupStatus.RTO_INITIATED), DeliveryFilterKey.RTO)).toBe(true);
    expect(matchesDeliveryFilter(forward(PickupStatus.RTO_IN_TRANSIT), DeliveryFilterKey.RTO)).toBe(true);
    expect(matchesDeliveryFilter(forward(PickupStatus.IN_TRANSIT), DeliveryFilterKey.RTO)).toBe(false);
  });

  it("hides statuses that need no field action", () => {
    expect(matchesDeliveryFilter(forward(PickupStatus.CANCELLED), DeliveryFilterKey.ALL)).toBe(false);
    expect(matchesDeliveryFilter(forward(PickupStatus.RTO_DELIVERED), DeliveryFilterKey.ALL)).toBe(false);
  });
});

describe("canMoveTo (E-11, server-driven)", () => {
  it("follows allowed_next_statuses only", () => {
    const row = { allowed_next_statuses: [PickupStatus.RTO_DELIVERED] };
    expect(canMoveTo(row, PickupStatus.RTO_DELIVERED)).toBe(true);
    expect(canMoveTo(row, PickupStatus.COMPLETED)).toBe(false);
  });
});

describe("E-07 field NDR reasons", () => {
  it("offers DO1 doorstep reasons and no charge-bearing reason", () => {
    const values = FIELD_NDR_SELECT_OPTIONS.map((o) => o.value);
    expect(values).toContain(NdrExceptionReason.DELIVERY_RESCHEDULED);
    expect(values).toContain(NdrExceptionReason.DAMAGED);
    expect(values).toContain(NdrExceptionReason.PAYMENT_DISPUTE);
    expect(values).toContain(NdrExceptionReason.EWAY_BILL_MISSING);
    expect(values).not.toContain(NdrExceptionReason.FREIGHT_COLLECTION);
    expect(values).not.toContain(NdrExceptionReason.ADDITIONAL_CHARGES);
    expect(FIELD_NDR_SELECT_OPTIONS.every((o) => o.label.length > 0)).toBe(true);
  });
});

describe("E-09 cash badge", () => {
  const paid = (status: PickupStatus, remit: CodRemittanceStatus) => ({
    status,
    payment_details: { cod_remittance_status: remit } as never,
  });

  it("a delivered COD is 'cash with field team', not 'collected'", () => {
    const badge = cashCollectionBadge(paid(PickupStatus.COMPLETED, CodRemittanceStatus.PENDING_COLLECTION));
    expect(badge.tone).toBe(CashBadgeTone.WITH_FIELD_TEAM);
    expect(badge.label).not.toMatch(/collected/i);
  });

  it.each([
    [CodRemittanceStatus.REMITTED, CashBadgeTone.SETTLED],
    [CodRemittanceStatus.COLLECTED, CashBadgeTone.SETTLED],
    [CodRemittanceStatus.FAILED_RTO, CashBadgeTone.NOT_COLLECTED],
  ])("remittance %s -> %s", (remit, tone) => {
    expect(cashCollectionBadge(paid(PickupStatus.COMPLETED, remit)).tone).toBe(tone);
  });

  it("an undelivered COD is still to collect", () => {
    expect(cashCollectionBadge(paid(PickupStatus.OUT_FOR_DELIVERY, CodRemittanceStatus.PENDING_COLLECTION)).tone).toBe(
      CashBadgeTone.PENDING,
    );
  });

  it("door cash is pending only for a positive backend amount still in the field", () => {
    expect(isDoorCashPending({ status: PickupStatus.OUT_FOR_DELIVERY, door_collectible: 499 })).toBe(true);
    expect(isDoorCashPending({ status: PickupStatus.OUT_FOR_DELIVERY, door_collectible: 0 })).toBe(false);
    expect(isDoorCashPending({ status: PickupStatus.COMPLETED, door_collectible: 499 })).toBe(false);
  });
});

describe("E-10 doorstep drafts", () => {
  it("round-trips through storage and tolerates corrupt data", () => {
    const store = window.sessionStorage;
    store.clear();
    savePodDraft(store, "logismart-test", { otp: { a: "123456" }, receiver: { a: "Guard" } });
    expect(loadPodDraft(store, "logismart-test")).toEqual({ otp: { a: "123456" }, receiver: { a: "Guard" } });

    store.setItem(podDraftStorageKey("logismart-test"), "{not json");
    expect(loadPodDraft(store, "logismart-test")).toEqual({ otp: {}, receiver: {} });
  });

  it("withoutEntry drops only that shipment", () => {
    expect(withoutEntry({ a: "1", b: "2" }, "a")).toEqual({ b: "2" });
  });
});

describe("display labels", () => {
  it("maps service types to Delhivery-style labels", () => {
    expect(serviceTypeLabel("SURFACE_ROAD")).toBe("Surface (Truck)");
    expect(serviceTypeLabel("AIR")).toBe("Air");
    expect(serviceTypeLabel("LEGACY")).toBe("LEGACY");
    expect(serviceTypeLabel(undefined)).toBe("");
  });

  it("maps NDR reasons and falls back for missing ones", () => {
    expect(ndrReasonLabel(NdrExceptionReason.CONSIGNEE_UNAVAILABLE)).toBe("Consignee unavailable");
    expect(ndrReasonLabel(null)).toBe("Exception");
    expect(ndrReasonLabel("SOMETHING_NEW")).toBe("SOMETHING_NEW");
  });
});

describe("pickup tab filter", () => {
  it("defaults to pickups that still need a visit", () => {
    expect(matchesPickupFilter(ManifestStatus.SCHEDULED, PICKUP_FILTER_ACTIVE)).toBe(true);
    expect(matchesPickupFilter(ManifestStatus.OUT_FOR_PICKUP, PICKUP_FILTER_ACTIVE)).toBe(true);
    expect(matchesPickupFilter(ManifestStatus.PICKED, PICKUP_FILTER_ACTIVE)).toBe(false);
    expect(matchesPickupFilter(ManifestStatus.CANCELED, PICKUP_FILTER_ACTIVE)).toBe(false);
  });

  it("supports All and a single status", () => {
    expect(matchesPickupFilter(ManifestStatus.PICKED, PICKUP_FILTER_ALL)).toBe(true);
    expect(matchesPickupFilter(ManifestStatus.NOT_PICKED, ManifestStatus.NOT_PICKED)).toBe(true);
    expect(matchesPickupFilter(ManifestStatus.PICKED, ManifestStatus.NOT_PICKED)).toBe(false);
  });
});

describe("actual pieces on the pickup confirmation", () => {
  it("parses whole numbers of at least 1 only", () => {
    expect(parseActualPieces(" 2 ")).toBe(2);
    expect(parseActualPieces("")).toBeNull();
    expect(parseActualPieces("0")).toBeNull();
    expect(parseActualPieces("1.5")).toBeNull();
    expect(parseActualPieces(undefined)).toBeNull();
  });

  it("shows the rider's count next to the booked one when they differ", () => {
    expect(pickedBoxesLabel(1, "2")).toBe("2 boxes (booked 1)");
    expect(pickedBoxesLabel(1, "")).toBe("1 box");
    expect(pickedBoxesLabel(3, "3")).toBe("3 boxes");
    expect(pickedBoxesLabel(undefined, "abc")).toBe("1 box");
  });
});
