import { describe, expect, it } from "vitest";

import { buildRateHandoffQuery, matchAddressByPincode, parseRateHandoff } from "./rate-handoff";

const CATEGORIES = ["ELECTRONICS", "APPAREL", "OTHER"];

describe("rate hand-off", () => {
  it("round-trips calculator inputs", () => {
    const query = buildRateHandoffQuery({
      originPincode: "110001",
      destinationPincode: "400001",
      length: 30,
      breadth: 20,
      height: 10,
      weightKg: 1.5,
      boxCount: 2,
      productCategory: "ELECTRONICS",
      isCod: true,
      codAmount: 999,
      doorDelivery: true,
    });
    expect(parseRateHandoff(`?${query}`, CATEGORIES)).toEqual({
      originPincode: "110001",
      destinationPincode: "400001",
      length: 30,
      breadth: 20,
      height: 10,
      weightKg: 1.5,
      boxCount: 2,
      productCategory: "ELECTRONICS",
      isCod: true,
      codAmount: 999,
      shipmentValue: undefined,
      doorDelivery: true,
    });
  });

  it("omits COD amount when COD is off and skips zero/blank values", () => {
    const query = buildRateHandoffQuery({ originPincode: "110001", isCod: false, codAmount: 50, length: 0 });
    expect(query).toBe("origin=110001");
  });

  it("returns null when nothing usable is present", () => {
    expect(parseRateHandoff("", CATEGORIES)).toBeNull();
    expect(parseRateHandoff("?foo=bar", CATEGORIES)).toBeNull();
  });

  it("drops invalid pincodes, numbers and unknown categories", () => {
    const parsed = parseRateHandoff("?origin=012345&dest=40000&weight=-2&l=abc&category=WEAPONS&boxes=3", CATEGORIES);
    expect(parsed).toEqual(expect.objectContaining({ boxCount: 3 }));
    expect(parsed?.originPincode).toBeUndefined();
    expect(parsed?.destinationPincode).toBeUndefined();
    expect(parsed?.weightKg).toBeUndefined();
    expect(parsed?.length).toBeUndefined();
    expect(parsed?.productCategory).toBeUndefined();
  });

  it("ignores cod_amount unless cod=1", () => {
    expect(parseRateHandoff("?cod_amount=500&origin=110001", CATEGORIES)?.codAmount).toBeUndefined();
  });

  it("matches saved addresses by pincode, excluding the other leg", () => {
    const book = [
      { id: "a", pincode: "110001" },
      { id: "b", pincode: "110001" },
      { id: "c", pincode: "400001" },
    ];
    expect(matchAddressByPincode(book, "110001")).toBe("a");
    expect(matchAddressByPincode(book, "110001", "a")).toBe("b");
    expect(matchAddressByPincode(book, "560001")).toBeUndefined();
    expect(matchAddressByPincode(book, undefined)).toBeUndefined();
  });
});
