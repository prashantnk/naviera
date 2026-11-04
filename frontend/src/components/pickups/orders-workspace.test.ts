// frontend/src/components/pickups/orders-workspace.test.ts
import {
  ManifestStatus,
  PickupStatus,
  ServiceFlow,
  ServiceOption,
  ServiceType,
  ShipmentType,
} from "@/api_client";
import { describe, expect, it } from "vitest";
import { matchesOrderSearch, parseSearchTerms, type SearchableOrder } from "./orders-workspace";
import { matchesManifestSearch, type SearchableManifest } from "./pickup-requests-list";

const SAMPLE_ORDER = {
  id: "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  tracking_id: "LOGISMART-TEST-AWB9001",
  order_reference_id: "ORD-2026-7788",
  po_number: "PO-DEL-4455",
  carrier_awb: "DLV7788990011",
  carrier_name: "Delhivery",
  transporter_name: "Logismart Prime",
  status: PickupStatus.IN_TRANSIT,
  shipment_type: ShipmentType.FORWARD,
  service_type: ServiceType.SURFACE_ROAD,
  service_option: ServiceOption.DELHIVERY_SURFACE,
  payment_details: {
    id: "pay-1",
    invoice_numbers: ["INV-2026-101"],
    invoice_number: "INV-2026-101",
    eway_bill_numbers: ["EWB-181920212223"],
    eway_bill_number: "EWB-181920212223",
  },
  delivery_address: {
    id: "addr-del-1",
    name: "Aarav Deshmukh",
    company_name: "Deshmukh Retail Pvt Ltd",
    phone: "9820112233",
    city: "Mumbai",
    state: "Maharashtra",
    pincode: "400001",
    address_line1: "42 Nariman Point",
  },
  pickup_address: {
    id: "addr-pck-1",
    name: "Whitefield Central Hub",
    company_name: "Logismart Fulfilment",
    phone: "9880445566",
    city: "Bengaluru",
    state: "Karnataka",
    pincode: "560066",
    address_line1: "Plot 18, ITPL Main Road",
  },
} as unknown as SearchableOrder;

const SAMPLE_MANIFEST: SearchableManifest = {
  id: "a1b2c3d4-e5f6-4789-9012-34567890abcd",
  tenant_id: "tenant-1",
  pickup_address_id: "addr-pck-1",
  scheduled_date: "2026-11-05",
  time_slot: "14:00 - 18:00",
  is_blind_pickup: false,
  total_boxes: 4,
  status: ManifestStatus.SCHEDULED,
  created_at: "2026-11-04",
  service_flow: ServiceFlow.B2C,
  pickup_request_number: "912345678",
  pickup_location_name: "Whitefield Central Hub",
  pickup_location_address: "Plot 18, ITPL Main Road, Bengaluru, Karnataka - 560066",
  pickup_city: "Bengaluru",
  pickup_pincode: "560066",
  transporter_name: "Delhivery Surface",
  vehicle_number: "KA01AB1234",
  expected_awbs: 2,
  picked_awbs: 0,
  shipments: [
    {
      id: "s-1",
      tracking_id: "LOGISMART-TEST-AWB9001",
      order_reference_id: "ORD-2026-7788",
      package_count: 2,
      status: PickupStatus.ASSIGNED,
    },
  ],
};

describe("matchesOrderSearch (Notion Issue #14 generic omni-search)", () => {
  it("matches empty search terms", () => {
    expect(matchesOrderSearch(SAMPLE_ORDER, [])).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("   "))).toBe(true);
  });

  it("matches by AWB/LRN, Order ID, PO number, invoice number, and E-Way bill number", () => {
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("AWB9001"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("ORD-2026-7788"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("PO-DEL-4455"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("INV-2026-101"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("EWB-181920212223"))).toBe(true);
  });

  it("matches by consignee name, company, phone, city, state, and pincode", () => {
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Aarav"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Deshmukh Retail"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("9820112233"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Mumbai"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Maharashtra"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("400001"))).toBe(true);
  });

  it("matches by pickup warehouse name, city, pincode, status, service, and transporter", () => {
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Whitefield"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Bengaluru"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("560066"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("IN_TRANSIT"))).toBe(true);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Logismart Prime"))).toBe(true);
  });

  it("returns false when no search term matches any order field", () => {
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("NONEXISTENT-999999"))).toBe(false);
    expect(matchesOrderSearch(SAMPLE_ORDER, parseSearchTerms("Chennai 600001"))).toBe(false);
  });
});

describe("matchesManifestSearch (Notion Issue #14 generic pickup request search)", () => {
  it("matches empty query", () => {
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "")).toBe(true);
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "   ")).toBe(true);
  });

  it("matches by Pickup display ID, warehouse location name, city, pincode, vehicle, and linked AWB", () => {
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "912345678")).toBe(true);
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "Whitefield Central Hub")).toBe(true);
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "Bengaluru")).toBe(true);
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "560066")).toBe(true);
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "KA01AB1234")).toBe(true);
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "AWB9001")).toBe(true);
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "ORD-2026-7788")).toBe(true);
  });

  it("returns false for non-matching pickup queries", () => {
    expect(matchesManifestSearch(SAMPLE_MANIFEST, "Hyderabad 500081")).toBe(false);
  });
});
