// frontend/src/lib/whatsapp-notify.test.ts
import { describe, expect, it } from "vitest";

import { PickupStatus } from "@/api_client";

import {
  buildConsigneeNotificationMessage,
  consigneeStageForStatus,
  hasWhatsAppPhone,
} from "./whatsapp-notify";

const OTP = "482913";
const base = {
  consigneeName: "Asha",
  trackingId: "LOGISMART-1",
  tenantName: "Logismart",
  trackingUrl: "https://logismart.naviera.com/track/LOGISMART-1",
  deliveryOtp: OTP,
};

describe("E-08 consignee stage map", () => {
  it("In Transit is not 'out for delivery' and never carries the OTP", () => {
    expect(consigneeStageForStatus(PickupStatus.IN_TRANSIT)).toBe("IN_TRANSIT");
    const { body } = buildConsigneeNotificationMessage({ ...base, stage: "IN_TRANSIT" });
    expect(body).not.toContain(OTP);
    expect(body).not.toMatch(/out for delivery\*? today/i);
  });

  it("only Out for Delivery gets the OTP text", () => {
    expect(consigneeStageForStatus(PickupStatus.OUT_FOR_DELIVERY)).toBe("OUT_FOR_DELIVERY");
    const { body } = buildConsigneeNotificationMessage({ ...base, stage: "OUT_FOR_DELIVERY" });
    expect(body).toContain(OTP);
  });

  it.each([PickupStatus.RTO_INITIATED, PickupStatus.RTO_IN_TRANSIT, PickupStatus.CANCELLED, PickupStatus.LOST])(
    "%s gets no consignee message",
    (status) => {
      expect(consigneeStageForStatus(status)).toBeNull();
    },
  );

  it("delivered and NDR map to their own stages", () => {
    expect(consigneeStageForStatus(PickupStatus.COMPLETED)).toBe("DELIVERED");
    expect(consigneeStageForStatus(PickupStatus.EXCEPTION)).toBe("EXCEPTION");
  });
});

describe("OPSX-25 empty-phone guard", () => {
  it.each([
    [undefined, false],
    ["", false],
    ["  ", false],
    ["12345", false],
    ["98765 43210", true],
    ["+91-98765-43210", true],
  ])("hasWhatsAppPhone(%s) = %s", (phone, expected) => {
    expect(hasWhatsAppPhone(phone)).toBe(expected);
  });
});
