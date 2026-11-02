// frontend/src/components/ui/screen-guide-banner.test.tsx
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ScreenGuideBanner, type GuideStep } from "./screen-guide-banner";

const CUSTOMER_STEPS: readonly GuideStep[] = [
  {
    title: "Pick Addresses & Box Weight",
    description: "Select pickup and delivery addresses, then enter box weight and dimensions.",
  },
  {
    title: "Enter Goods Value",
    description: "Enter invoice value (E-Way Bill is only needed above ₹50,000).",
  },
  {
    title: "Compare Rates & Book",
    description: "Click Find Rates to compare Surface vs Express and book from your wallet.",
  },
];

const STAFF_STEPS: readonly GuideStep[] = [
  {
    title: "Verify Customer & Route",
    description: "Confirm pickup/drop pincodes and package weight.",
  },
  {
    title: "Check Compliance (> ₹50k)",
    description: "Ensure 12-digit E-Way Bill is attached if shipment value exceeds ₹50,000.",
  },
  {
    title: "Book & Assign Carrier AWB",
    description: "Select carrier rate, book order, then link Carrier AWB on Shipment Detail.",
  },
];

describe("ScreenGuideBanner", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders customer 3-step guide and Delhivery One equivalent badge when isStaff is false", () => {
    render(
      <ScreenGuideBanner
        guideId="b2c-booking"
        title="Quick Start: Book a Parcel in 3 Steps"
        delhiveryEquivalent="Delhivery One: Orders → Create Shipment"
        steps={CUSTOMER_STEPS}
        staffSteps={STAFF_STEPS}
        isStaff={false}
      />
    );

    expect(screen.getByTestId("screen-guide.b2c-booking")).toBeTruthy();
    expect(screen.getByText("Delhivery One: Orders → Create Shipment")).toBeTruthy();
    expect(screen.getByText("Pick Addresses & Box Weight")).toBeTruthy();
    expect(screen.queryByText("Book & Assign Carrier AWB")).toBeNull();
  });

  it("renders staff/admin steps when isStaff is true", () => {
    render(
      <ScreenGuideBanner
        guideId="b2c-booking"
        title="Quick Start: Book a Parcel in 3 Steps"
        staffTitle="Staff Guide: B2C Booking & Compliance"
        delhiveryEquivalent="Delhivery One: Orders → Create Shipment"
        steps={CUSTOMER_STEPS}
        staffSteps={STAFF_STEPS}
        isStaff={true}
      />
    );

    expect(screen.getByText("Staff Guide: B2C Booking & Compliance")).toBeTruthy();
    expect(screen.getByText("Book & Assign Carrier AWB")).toBeTruthy();
    expect(screen.queryByText("Pick Addresses & Box Weight")).toBeNull();
  });

  it("dismisses to a compact 'How it works ?' pill persisted in localStorage and reopens on click", () => {
    render(
      <ScreenGuideBanner
        guideId="pricing-policy"
        title="How Pricing & Markups Work"
        delhiveryEquivalent="Delhivery One: Rate Card + Admin Markup"
        steps={STAFF_STEPS}
      />
    );

    const dismissBtn = screen.getByTestId("screen-guide.pricing-policy.dismiss");
    fireEvent.click(dismissBtn);

    expect(window.localStorage.getItem("logismart-guide-dismissed:pricing-policy")).toBe("1");
    expect(screen.queryByTestId("screen-guide.pricing-policy")).toBeNull();

    const reopenBtn = screen.getByTestId("screen-guide.pricing-policy.reopen");
    expect(reopenBtn.textContent).toContain("How it works");
    fireEvent.click(reopenBtn);

    expect(window.localStorage.getItem("logismart-guide-dismissed:pricing-policy")).toBeNull();
    expect(screen.getByTestId("screen-guide.pricing-policy")).toBeTruthy();
  });
});
