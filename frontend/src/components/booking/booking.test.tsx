// frontend/src/components/booking/booking.test.tsx
import { ApiError, FreightPaymentMode, ServiceFlow, ShipmentType, type PickupRead } from "@/api_client";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  PRICE_CHANGED_CODE,
  QuoteUnavailableCode,
  ServiceOption,
  parsePriceChanged,
  type QuoteOption,
  type QuoteResponse,
} from "./booking-api";
import { buildPaymentInputs, buildQuoteRequest } from "./booking-inputs";
import {
  QuoteStep,
  defaultSelection,
  findSelectedOption,
  isCodBlocked,
  optionCardTestId,
  transitLineText,
} from "./quote-step";
import { bookedToastMessage, mayHaveCommitted } from "./use-quote-booking";
import { toValuationInput } from "./use-shipment-valuation";

function option(overrides: Partial<QuoteOption> = {}): QuoteOption {
  return {
    service_option: ServiceOption.DELHIVERY_SURFACE,
    serviceable: true,
    total_amount: 159.3,
    freight_amount: 135,
    cod_fee: 0,
    tax_amount: 24.3,
    chargeable_weight_kg: 2,
    transit_days: 3,
    expected_delivery_date: "2026-11-02",
    sell_lines: [
      { code: "FREIGHT", label: "Freight", amount: 135 },
      { code: "GST", label: "GST (18%)", amount: 24.3 },
    ],
    door_collectible_amount: 0,
    cod_remittance_amount: 0,
    priced_from_cache: false,
    ...overrides,
  };
}

function quote(overrides: Partial<QuoteResponse> = {}): QuoteResponse {
  return {
    shipment_total_value: 1000,
    eway_bill_required: false,
    eway_bill_threshold: 50000,
    cod_available: true,
    heavy_weight_warning: false,
    heavy_weight_threshold_kg: 100,
    options: [
      option(),
      option({ service_option: ServiceOption.DELHIVERY_EXPRESS, total_amount: 237.18 }),
    ],
    ...overrides,
  };
}

function apiError(status: number, body: unknown): ApiError {
  return new ApiError(
    { method: "POST", url: "/api/v1/shipments" },
    { url: "/api/v1/shipments", ok: false, status, statusText: "", body },
    "failed",
  );
}

describe("buildPaymentInputs / buildQuoteRequest (A-01, A-03)", () => {
  it("keeps the typed COD amount as goods COD and only adds shipping when COD is on", () => {
    const inputs = buildPaymentInputs(
      {
        freight_payment_mode: FreightPaymentMode.PREPAID,
        is_cod: true,
        cod_amount: 1000,
        shipment_value: 2000,
        shipment_tax_value: "",
      },
      true,
    );
    expect(inputs).toEqual({
      freight_payment_mode: FreightPaymentMode.PREPAID,
      is_cod: true,
      cod_amount: 1000,
      add_shipping_to_cod: true,
      shipment_value: 2000,
      shipment_tax_value: 0,
    });
  });

  it("zeroes COD fields when COD is off", () => {
    const inputs = buildPaymentInputs(
      { freight_payment_mode: FreightPaymentMode.POSTPAID, is_cod: false, cod_amount: 500 },
      true,
    );
    expect(inputs.cod_amount).toBe(0);
    expect(inputs.add_shipping_to_cod).toBe(false);
  });

  it("puts the same payment inputs on the quote request", () => {
    const payment = buildPaymentInputs({ freight_payment_mode: FreightPaymentMode.PREPAID, shipment_value: 10 }, false);
    const request = buildQuoteRequest({
      flow: ServiceFlow.B2B,
      shipmentType: ShipmentType.FORWARD,
      pickupPincode: "122001",
      deliveryPincode: "400001",
      packages: [],
      payment,
      isBlindPickup: true,
      estimatedBoxCount: 4,
      doorDelivery: true,
    });
    expect(request).toMatchObject({
      service_flow: ServiceFlow.B2B,
      is_blind_pickup: true,
      estimated_box_count: 4,
      door_delivery: true,
      ...payment,
    });
  });

  it("toValuationInput tolerates typing states", () => {
    expect(toValuationInput("")).toBe(0);
    expect(toValuationInput(Number.NaN)).toBe(0);
    expect(toValuationInput(-5)).toBe(0);
    expect(toValuationInput("12.5")).toBe(12.5);
  });
});

describe("parsePriceChanged", () => {
  const detail = {
    code: PRICE_CHANGED_CODE,
    message: "Price changed",
    expected_total: 159.3,
    new_total: 170.1,
    service_option: ServiceOption.DELHIVERY_SURFACE,
  };

  it("reads the 409 PRICE_CHANGED body", () => {
    expect(parsePriceChanged(apiError(409, { detail }))).toEqual(detail);
  });

  it("ignores other failures", () => {
    expect(parsePriceChanged(apiError(409, { detail: "Idempotency key in flight" }))).toBeNull();
    expect(parsePriceChanged(apiError(400, { detail }))).toBeNull();
    expect(parsePriceChanged(new Error("network"))).toBeNull();
  });
});

describe("booking helpers", () => {
  it("formats the transit line like Delhivery One (dd MMM yyyy)", () => {
    expect(transitLineText({ transit_days: 5, expected_delivery_date: "2026-11-06" })).toBe(
      "Delivers in 5 days · by 06 Nov 2026",
    );
    expect(transitLineText({ transit_days: 1, expected_delivery_date: null })).toBe("Delivers in 1 day");
    expect(transitLineText({ transit_days: null, expected_delivery_date: "not-a-date" })).toBe("by not-a-date");
    expect(transitLineText({ transit_days: null, expected_delivery_date: null })).toBeNull();
  });

  it("keeps the Idempotency-Key whenever the booking may have committed (BUG-03)", () => {
    expect(mayHaveCommitted(new Error("Network Error"))).toBe(true);
    expect(mayHaveCommitted(apiError(500, {}))).toBe(true);
    expect(mayHaveCommitted(apiError(503, { detail: "Billing is busy" }))).toBe(true);
    expect(mayHaveCommitted(apiError(409, { detail: "Idempotency key in flight" }))).toBe(true);
    expect(
      mayHaveCommitted(
        apiError(409, {
          detail: { code: PRICE_CHANGED_CODE, new_total: 170.1, expected_total: 159.3 },
        }),
      ),
    ).toBe(false);
    expect(mayHaveCommitted(apiError(400, {}))).toBe(false);
    expect(mayHaveCommitted(apiError(403, {}))).toBe(false);
  });

  it("shows the booked total from the API in the toast", () => {
    const created = { payment_details: { total_logistics_cost: 159.3 } } as unknown as PickupRead;
    expect(bookedToastMessage(created)).toContain("₹159.30");
    expect(bookedToastMessage({} as PickupRead)).toBe("Shipment booked successfully!");
  });

  it("selection helpers keep a still-bookable choice, else the first bookable card", () => {
    const fresh = quote({
      options: [
        option({ serviceable: false, unavailable_code: QuoteUnavailableCode.EMBARGO }),
        option({ service_option: ServiceOption.DELHIVERY_EXPRESS }),
      ],
    });
    expect(defaultSelection(fresh, ServiceOption.DELHIVERY_SURFACE)).toBe(ServiceOption.DELHIVERY_EXPRESS);
    expect(defaultSelection(fresh, ServiceOption.DELHIVERY_EXPRESS)).toBe(ServiceOption.DELHIVERY_EXPRESS);
    expect(findSelectedOption(fresh, ServiceOption.DELHIVERY_SURFACE)).toBeNull();
    expect(defaultSelection(quote({ options: [option({ serviceable: false })] }), null)).toBeNull();
  });

  it("blocks booking when COD was asked for but is off", () => {
    expect(isCodBlocked(quote({ cod_available: false }), true)).toBe(true);
    expect(isCodBlocked(quote({ cod_available: false }), false)).toBe(false);
    expect(isCodBlocked(null, true)).toBe(false);
  });

  it("builds stable card test ids", () => {
    expect(optionCardTestId(ServiceOption.PRIME_SURFACE)).toBe("booking.quote.card-prime-surface");
  });
});

describe("QuoteStep", () => {
  const baseProps = {
    isLoading: false,
    onSelect: vi.fn(),
    onBack: vi.fn(),
    onSubmit: vi.fn(),
    isSubmitting: false,
    isCod: false,
  };

  it("renders backend numbers and books the selected card", () => {
    const onSubmit = vi.fn();
    render(
      <QuoteStep {...baseProps} onSubmit={onSubmit} quote={quote()} selectedOption={ServiceOption.DELHIVERY_SURFACE} />,
    );
    expect(screen.getByTestId("booking.quote.total")).toHaveTextContent("₹159.30");
    expect(screen.getByTestId("booking.quote.card-delhivery-express")).toHaveTextContent("₹237.18");
    fireEvent.click(screen.getByTestId("booking.actions.submit"));
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("shows the chargeable weight with a single kg unit and a readable delivery date", () => {
    render(<QuoteStep {...baseProps} quote={quote()} selectedOption={ServiceOption.DELHIVERY_SURFACE} />);
    expect(screen.getByText(/Chargeable weight:/).textContent).not.toMatch(/kg\s*kg/);
    expect(screen.getAllByText("Delivers in 3 days · by 02 Nov 2026").length).toBeGreaterThan(0);
  });

  it("shows the reason on an unavailable card and does not select it", () => {
    const onSelect = vi.fn();
    render(
      <QuoteStep
        {...baseProps}
        onSelect={onSelect}
        quote={quote({
          options: [option({ serviceable: false, unavailable_reason: "Pincode is under embargo." })],
        })}
        selectedOption={null}
      />,
    );
    const card = screen.getByTestId("booking.quote.card-delhivery-surface");
    expect(card).toHaveTextContent("Pincode is under embargo.");
    fireEvent.click(card);
    expect(onSelect).not.toHaveBeenCalled();
    expect(screen.getByTestId("booking.actions.submit")).toBeDisabled();
    expect(screen.getByTestId("booking.quote.none-available")).toBeInTheDocument();
  });

  it("explains COD is off and keeps Book disabled", () => {
    render(
      <QuoteStep
        {...baseProps}
        isCod
        quote={quote({ cod_available: false, cod_unavailable_reason: "COD is not enabled yet." })}
        selectedOption={ServiceOption.DELHIVERY_SURFACE}
      />,
    );
    expect(screen.getByTestId("booking.quote.cod-unavailable")).toHaveTextContent("COD is not enabled yet.");
    expect(screen.getByTestId("booking.actions.submit")).toBeDisabled();
  });

  it("requires the heavy-weight confirmation before booking (A-26)", () => {
    render(
      <QuoteStep
        {...baseProps}
        quote={quote({ heavy_weight_warning: true, heavy_weight_threshold_kg: 100 })}
        selectedOption={ServiceOption.DELHIVERY_SURFACE}
      />,
    );
    const submit = screen.getByTestId("booking.actions.submit");
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByTestId("booking.quote.heavy-weight-confirm"));
    expect(submit).not.toBeDisabled();
  });

  it("flags a price taken from the cache", () => {
    render(
      <QuoteStep
        {...baseProps}
        quote={quote({ options: [option({ priced_from_cache: true, price_age_minutes: 42 })] })}
        selectedOption={ServiceOption.DELHIVERY_SURFACE}
      />,
    );
    expect(screen.getByTestId("booking.quote.cached")).toHaveTextContent("42 min old");
  });

  it("renders B2B delivery mode toggle in Step 2 and switches between Door Delivery and Godown Self-Pickup", () => {
    const onDoorDeliveryChange = vi.fn();
    const primeGodown = option({
      service_option: ServiceOption.PRIME_SURFACE,
      total_amount: 1699.2,
      sell_lines: [
        { code: "FREIGHT", label: "Freight", amount: 600 },
        { code: "DOCKET", label: "Docket charge", amount: 120 },
        { code: "PICKUP", label: "Pickup charge", amount: 720 },
        { code: "GST", label: "GST (18%)", amount: 259.2 },
      ],
    });
    render(
      <QuoteStep
        {...baseProps}
        quote={quote({ options: [primeGodown] })}
        selectedOption={ServiceOption.PRIME_SURFACE}
        doorDelivery={false}
        onDoorDeliveryChange={onDoorDeliveryChange}
      />,
    );

    const toggle = screen.getByTestId("quote-step-delivery-mode-toggle");
    expect(toggle).toBeInTheDocument();
    expect(toggle.textContent).not.toMatch(/🚚|🏭/);
    expect(screen.getByTestId("prime-delivery-mode-badge")).toHaveTextContent(
      /Godown Self-Pickup \(₹0 Door Delivery Charge\)/i,
    );
    expect(screen.getByTestId("prime-delivery-mode-badge").textContent).not.toMatch(/🚚|🏭/);
    expect(screen.getByTestId("booking.quote.card-prime-surface").className).toContain("justify-start");
    expect(screen.getByTestId("booking.quote.card-prime-surface").className).not.toContain("justify-between");
    expect(screen.getByTestId("prime-card-sell-lines")).toHaveTextContent("Pickup charge");
    expect(screen.getByTestId("prime-card-sell-lines")).toHaveTextContent("₹720.00");

    fireEvent.click(screen.getByTestId("quote-step-delivery-mode-door"));
    expect(onDoorDeliveryChange).toHaveBeenCalledWith(true);
  });

  it("shows Door Delivery badge and itemized Door delivery line on Logismart Prime card when doorDelivery is true", () => {
    const primeDoor = option({
      service_option: ServiceOption.PRIME_SURFACE,
      total_amount: 2548.8,
      sell_lines: [
        { code: "FREIGHT", label: "Freight", amount: 600 },
        { code: "DOCKET", label: "Docket charge", amount: 120 },
        { code: "PICKUP", label: "Pickup charge", amount: 720 },
        { code: "DOOR_DELIVERY", label: "Door delivery", amount: 720 },
        { code: "GST", label: "GST (18%)", amount: 388.8 },
      ],
    });
    render(
      <QuoteStep
        {...baseProps}
        quote={quote({ options: [primeDoor] })}
        selectedOption={ServiceOption.PRIME_SURFACE}
        doorDelivery={true}
        onDoorDeliveryChange={vi.fn()}
      />,
    );

    expect(screen.getByTestId("prime-delivery-mode-badge")).toHaveTextContent(
      /Door Delivery \(incl\. Door Delivery Charge\)/i,
    );
    expect(screen.getByTestId("prime-card-sell-lines")).toHaveTextContent("Door delivery");
    expect(screen.getByTestId("prime-card-sell-lines")).toHaveTextContent("₹720.00");
  });
});
