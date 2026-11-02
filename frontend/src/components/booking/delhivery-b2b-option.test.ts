// frontend/src/components/booking/delhivery-b2b-option.test.ts
import { FreightPaymentMode, ServiceFlow, ShipmentType } from "@/api_client";
import { SERVICE_OPTION_OPTIONS, getOptionMeta } from "@/lib/form-options";
import { describe, expect, it } from "vitest";
import { ServiceOption } from "./booking-api";
import { buildPaymentInputs, buildQuoteRequest } from "./booking-inputs";
import { optionCardTestId } from "./quote-step";

describe("Delhivery B2B Cargo option", () => {
  it("has a human label (never the raw enum) and a stable card test id", () => {
    const meta = getOptionMeta(SERVICE_OPTION_OPTIONS, ServiceOption.DELHIVERY_B2B_SURFACE);
    expect(meta?.label).toBe("Delhivery B2B Cargo");
    expect(meta?.label).not.toContain("_");
    expect(optionCardTestId(ServiceOption.DELHIVERY_B2B_SURFACE)).toBe("booking.quote.card-delhivery-b2b-surface");
  });

  it("sends the carrier's-risk choice on the quote request (Delhivery prices its risk charge on it)", () => {
    const payment = buildPaymentInputs({ freight_payment_mode: FreightPaymentMode.PREPAID, shipment_value: 60000 }, false);
    const args = {
      flow: ServiceFlow.B2B,
      shipmentType: ShipmentType.FORWARD,
      pickupPincode: "122001",
      deliveryPincode: "110001",
      packages: [],
      payment,
    };
    expect(buildQuoteRequest({ ...args, isCarriersRisk: true }).is_carriers_risk).toBe(true);
    expect(buildQuoteRequest(args).is_carriers_risk).toBe(false);
  });
});
