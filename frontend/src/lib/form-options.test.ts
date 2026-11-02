// frontend/src/lib/form-options.test.ts
import { describe, expect, it } from "vitest";
import {
  AddressCategory,
  AddressScope,
  DimensionUnit,
  DocumentType,
  FreightPaymentMode,
  NdrExceptionReason,
  PickupStatus,
  PickupStrategy,
  PickupTimeSlot,
  ProductCategory,
  ServiceOption,
  ServiceScope,
  ServiceType,
  ShipmentType,
  UserRole,
  WeightUnit,
} from "@/api_client";
import {
  ACCOUNT_STATUS_OPTIONS,
  ADDRESS_CATEGORY_OPTIONS,
  ADDRESS_SCOPE_OPTIONS,
  ALL_FILTER_VALUE,
  AccountStatusFilter,
  B2C_PRODUCT_CATEGORIES,
  BOOKABLE_FREIGHT_PAYMENT_MODES,
  SERVICE_OPTION_OPTIONS,
  freightPaymentModesFor,
  withCurrentValue,
  DIMENSION_UNIT_OPTIONS,
  DOCUMENT_TYPE_OPTIONS,
  FREIGHT_PAYMENT_MODE_OPTIONS,
  NDR_REASON_OPTIONS,
  OPTION_TONE_CLASSES,
  PICKUP_STATUS_OPTIONS,
  PICKUP_STRATEGY_OPTIONS,
  PICKUP_TIME_SLOT_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
  RETURN_REASON_OPTIONS,
  SERVICE_SCOPE_OPTIONS,
  SERVICE_TYPE_OPTIONS,
  SHIPMENT_TYPE_OPTIONS,
  USER_ROLE_OPTIONS,
  VISIBILITY_TOGGLE_OPTIONS,
  VisibilityToggle,
  WEIGHT_UNIT_OPTIONS,
  getOptionMeta,
  optionLabels,
  toOptions,
  withAllOption,
  type OptionMeta,
} from "./form-options";

/** Each enum paired with its metadata map, so coverage is checked generically. */
const ENUM_MAPS: ReadonlyArray<[string, Record<string, string>, Readonly<Record<string, OptionMeta>>]> = [
  ["AddressCategory", AddressCategory, ADDRESS_CATEGORY_OPTIONS],
  ["AddressScope", AddressScope, ADDRESS_SCOPE_OPTIONS],
  ["ProductCategory", ProductCategory, PRODUCT_CATEGORY_OPTIONS],
  ["ShipmentType", ShipmentType, SHIPMENT_TYPE_OPTIONS],
  ["ServiceType", ServiceType, SERVICE_TYPE_OPTIONS],
  ["ServiceOption", ServiceOption, SERVICE_OPTION_OPTIONS],
  ["FreightPaymentMode", FreightPaymentMode, FREIGHT_PAYMENT_MODE_OPTIONS],
  ["PickupStatus", PickupStatus, PICKUP_STATUS_OPTIONS],
  ["NdrExceptionReason", NdrExceptionReason, NDR_REASON_OPTIONS],
  ["PickupStrategy", PickupStrategy, PICKUP_STRATEGY_OPTIONS],
  ["PickupTimeSlot", PickupTimeSlot, PICKUP_TIME_SLOT_OPTIONS],
  ["DocumentType", DocumentType, DOCUMENT_TYPE_OPTIONS],
  ["DimensionUnit", DimensionUnit, DIMENSION_UNIT_OPTIONS],
  ["WeightUnit", WeightUnit, WEIGHT_UNIT_OPTIONS],
  ["ServiceScope", ServiceScope, SERVICE_SCOPE_OPTIONS],
  ["UserRole", UserRole, USER_ROLE_OPTIONS],
  ["AccountStatusFilter", AccountStatusFilter, ACCOUNT_STATUS_OPTIONS],
  ["VisibilityToggle", VisibilityToggle, VISIBILITY_TOGGLE_OPTIONS],
];

describe("form-options enum coverage", () => {
  for (const [name, enumObject, map] of ENUM_MAPS) {
    describe(name, () => {
      const enumValues = Object.values(enumObject);

      it("has metadata for every enum value", () => {
        for (const value of enumValues) {
          expect(map[value], `${name}.${value} is missing metadata`).toBeDefined();
        }
      });

      it("has no stale keys that are not enum values", () => {
        expect(Object.keys(map).sort()).toEqual(enumValues.slice().sort());
      });

      it("provides a non-empty label, description, icon and a known tone", () => {
        for (const value of enumValues) {
          const meta = map[value];
          expect(meta.label.trim().length).toBeGreaterThan(0);
          expect(meta.description.trim().length).toBeGreaterThan(0);
          expect(meta.icon).toBeTruthy();
          expect(Object.keys(OPTION_TONE_CLASSES)).toContain(meta.tone);
        }
      });

      it("never shows the raw SCREAMING_CASE enum value as the label", () => {
        for (const value of enumValues) {
          if (value.length > 3) {
            expect(map[value].label).not.toBe(value);
          }
        }
      });
    });
  }
});

describe("tone classes", () => {
  it("never use hardcoded brand hues (indigo, blue, purple, violet)", () => {
    for (const classes of Object.values(OPTION_TONE_CLASSES)) {
      expect(classes).not.toMatch(/(indigo|blue|purple|violet)-/);
    }
  });
});

describe("RETURN_REASON_OPTIONS", () => {
  it("keeps legacy preset values byte-identical (they are written to reason_for_return)", () => {
    expect(RETURN_REASON_OPTIONS.map((option) => option.value)).toEqual([
      "Defective / Damaged Item",
      "Wrong Item Delivered",
      "Size / Fit Issue",
      "Quality Not As Expected",
      "Customer Changed Mind",
    ]);
  });
});

describe("helpers", () => {
  it("toOptions keeps declaration order and attaches the value", () => {
    const options = toOptions(ADDRESS_CATEGORY_OPTIONS);
    expect(options.map((option) => option.value)).toEqual(Object.values(AddressCategory));
    expect(options[0].label).toBe("Home");
  });

  it("toOptions honours an explicit subset and order", () => {
    const options = toOptions(FREIGHT_PAYMENT_MODE_OPTIONS, [
      FreightPaymentMode.POSTPAID,
      FreightPaymentMode.PREPAID,
    ]);
    expect(options.map((option) => option.value)).toEqual([
      FreightPaymentMode.POSTPAID,
      FreightPaymentMode.PREPAID,
    ]);
  });

  it("optionLabels returns a value to label record", () => {
    const labels = optionLabels(PRODUCT_CATEGORY_OPTIONS);
    expect(labels[ProductCategory.ELECTRONICS]).toBe("Electronics & Gadgets");
  });

  it("getOptionMeta tolerates unknown, empty and inherited keys", () => {
    expect(getOptionMeta(ADDRESS_CATEGORY_OPTIONS, AddressCategory.WAREHOUSE)?.label).toBe("Warehouse");
    expect(getOptionMeta(ADDRESS_CATEGORY_OPTIONS, "LEGACY_VALUE")).toBeUndefined();
    expect(getOptionMeta(ADDRESS_CATEGORY_OPTIONS, "")).toBeUndefined();
    expect(getOptionMeta(ADDRESS_CATEGORY_OPTIONS, null)).toBeUndefined();
    expect(getOptionMeta(ADDRESS_CATEGORY_OPTIONS, "toString")).toBeUndefined();
  });

  it("withAllOption prepends the catch-all filter without mutating the input", () => {
    const base = toOptions(USER_ROLE_OPTIONS);
    const withAll = withAllOption(base, "All roles");
    expect(withAll[0].value).toBe(ALL_FILTER_VALUE);
    expect(withAll[0].label).toBe("All roles");
    expect(withAll).toHaveLength(base.length + 1);
    expect(base[0].value).toBe(UserRole.OWNER);
  });
});

describe("MVP scope switches (WP0 / A-02)", () => {
  it("never offers TO_PAY on any booking or edit form", () => {
    expect(BOOKABLE_FREIGHT_PAYMENT_MODES).not.toContain(FreightPaymentMode.TO_PAY);
    for (const isAdmin of [true, false]) {
      expect(freightPaymentModesFor(isAdmin)).not.toContain(FreightPaymentMode.TO_PAY);
      expect(
        freightPaymentModesFor(isAdmin, [FreightPaymentMode.TO_PAY, FreightPaymentMode.PREPAID]),
      ).toEqual([FreightPaymentMode.PREPAID]);
    }
    // Legacy rows still render a label.
    expect(FREIGHT_PAYMENT_MODE_OPTIONS[FreightPaymentMode.TO_PAY].label).toMatch(/To-Pay/);
  });

  it("keeps Commercial Goods off B2C forms only", () => {
    expect(B2C_PRODUCT_CATEGORIES).not.toContain(ProductCategory.COMMERCIAL);
    expect(B2C_PRODUCT_CATEGORIES).toHaveLength(Object.values(ProductCategory).length - 1);
  });

  it("withCurrentValue appends a legacy saved value once", () => {
    expect(withCurrentValue(BOOKABLE_FREIGHT_PAYMENT_MODES, FreightPaymentMode.TO_PAY)).toEqual([
      FreightPaymentMode.PREPAID,
      FreightPaymentMode.POSTPAID,
      FreightPaymentMode.TO_PAY,
    ]);
    expect(withCurrentValue(BOOKABLE_FREIGHT_PAYMENT_MODES, FreightPaymentMode.PREPAID)).toEqual([
      ...BOOKABLE_FREIGHT_PAYMENT_MODES,
    ]);
    expect(withCurrentValue(B2C_PRODUCT_CATEGORIES, undefined)).toEqual([...B2C_PRODUCT_CATEGORIES]);
  });
});
