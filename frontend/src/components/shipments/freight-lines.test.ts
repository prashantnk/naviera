import { describe, expect, it } from "vitest";

import { freightBreakupLines } from "./freight-lines";

describe("freightBreakupLines (B2B LR docket breakup)", () => {
  it("uses the backend sell_lines (same rows as the quote) and leaves GST to its own line", () => {
    const lines = freightBreakupLines({
      base_freight: 1608,
      pricing_breakdown: {
        docket_charge: 0,
        sell_lines: [
          { code: "FREIGHT", label: "Freight (Logismart Prime)", amount: 768 },
          { code: "DOCKET", label: "Docket charge", amount: 120 },
          { code: "PICKUP", label: "Pickup charge", amount: 720 },
          { code: "GST", label: "GST (18%)", amount: 289.44 },
        ],
      },
    });
    expect(lines).toEqual([
      { code: "FREIGHT", label: "Freight (Logismart Prime)", amount: 768 },
      { code: "DOCKET", label: "Docket charge", amount: 120 },
      { code: "PICKUP", label: "Pickup charge", amount: 720 },
    ]);
  });

  it("falls back to the legacy keys for shipments priced before sell_lines", () => {
    const lines = freightBreakupLines({
      base_freight: 500,
      pricing_breakdown: { docket_charge: 50, fov_charge: 0, fuel_surcharge: "12.5", cod_fee: 30, rto_surcharge: 0 },
    });
    expect(lines.map((line) => [line.label, line.amount])).toEqual([
      ["Base Freight", 500],
      ["Docket Fee", 50],
      ["FOV Surcharge (Carrier's Risk)", 0],
      ["Fuel Surcharge", 12.5],
      ["COD Collection Fee", 30],
    ]);
  });

  it("returns nothing while the shipment is loading", () => {
    expect(freightBreakupLines(null)).toEqual([]);
    expect(freightBreakupLines({ base_freight: null, pricing_breakdown: null })[0]).toEqual({
      code: "base_freight",
      label: "Base Freight",
      amount: 0,
    });
  });
});
