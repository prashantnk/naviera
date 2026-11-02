// frontend/src/lib/icon-registry.ts
/**
 * Curated icon registry shared between Platform Settings (`IconPicker`) and
 * the public Services page (`/[tenant_slug]/services`).
 *
 * Keys match `ALLOWED_ICON_KEYS` in `backend/app/core/icon_registry.py` 1-to-1.
 */
import {
  Bike,
  Boxes,
  Clock,
  Factory,
  FileText,
  Globe,
  MapPin,
  Package,
  Plane,
  RefreshCcw,
  ShieldCheck,
  Ship,
  ShoppingCart,
  Snowflake,
  Store,
  Train,
  Truck,
  Warehouse,
  type LucideIcon,
} from "lucide-react";

export const ALLOWED_ICON_KEYS = [
  "truck",
  "plane",
  "train",
  "ship",
  "warehouse",
  "package",
  "boxes",
  "shopping-cart",
  "refresh-ccw",
  "clock",
  "shield-check",
  "snowflake",
  "store",
  "factory",
  "globe",
  "bike",
  "map-pin",
  "file-text",
] as const;

export type ServiceIconKey = (typeof ALLOWED_ICON_KEYS)[number];

export interface ServiceIconMeta {
  key: ServiceIconKey;
  label: string;
  description: string;
  keywords: readonly string[];
  icon: LucideIcon;
}

export const SERVICE_ICON_REGISTRY: readonly ServiceIconMeta[] = [
  {
    key: "truck",
    label: "Road & Surface",
    description: "Linehaul trucks, PTL and FTL road transport",
    keywords: ["truck", "road", "surface", "ptl", "ftl", "fleet"],
    icon: Truck,
  },
  {
    key: "plane",
    label: "Air Express",
    description: "Priority air cargo and next-day delivery",
    keywords: ["plane", "air", "express", "flight", "next day"],
    icon: Plane,
  },
  {
    key: "train",
    label: "Rail Cargo",
    description: "Multimodal rail logistics and container movement",
    keywords: ["train", "rail", "railway", "multimodal"],
    icon: Train,
  },
  {
    key: "ship",
    label: "Ocean & Port",
    description: "Sea cargo, container shipping and port handling",
    keywords: ["ship", "sea", "ocean", "port", "marine", "vessel"],
    icon: Ship,
  },
  {
    key: "warehouse",
    label: "Warehousing & 3PL",
    description: "Fulfillment centers, storage and inventory hubs",
    keywords: ["warehouse", "storage", "hub", "3pl", "fulfillment"],
    icon: Warehouse,
  },
  {
    key: "package",
    label: "Parcel Delivery",
    description: "Standard B2C parcels and doorstep couriers",
    keywords: ["package", "parcel", "box", "b2c", "courier"],
    icon: Package,
  },
  {
    key: "boxes",
    label: "B2B Multi-Box",
    description: "Consignments, pallets and multi-piece LRs",
    keywords: ["boxes", "b2b", "pallet", "bulk", "lot", "lr"],
    icon: Boxes,
  },
  {
    key: "shopping-cart",
    label: "E-Commerce",
    description: "D2C storefronts, marketplace orders and checkout",
    keywords: ["shopping-cart", "ecommerce", "d2c", "retail", "cart"],
    icon: ShoppingCart,
  },
  {
    key: "refresh-ccw",
    label: "Reverse & Returns",
    description: "Customer returns (DTO), exchanges and doorstep QC",
    keywords: ["refresh-ccw", "reverse", "return", "dto", "rto", "qc"],
    icon: RefreshCcw,
  },
  {
    key: "clock",
    label: "Time-Definite",
    description: "Same-day, scheduled slot and appointment delivery",
    keywords: ["clock", "time", "same day", "slot", "appointment", "sla"],
    icon: Clock,
  },
  {
    key: "shield-check",
    label: "Insured & Secure",
    description: "Carrier risk (FOV), high-value and OTP-verified",
    keywords: ["shield-check", "insured", "fov", "security", "safe", "otp"],
    icon: ShieldCheck,
  },
  {
    key: "snowflake",
    label: "Cold Chain",
    description: "Temperature-controlled reefer and pharma logistics",
    keywords: ["snowflake", "cold", "reefer", "pharma", "perishable"],
    icon: Snowflake,
  },
  {
    key: "store",
    label: "Store & Retail",
    description: "Mall distribution, dark stores and B2B retail drops",
    keywords: ["store", "shop", "retail", "mall", "outlet"],
    icon: Store,
  },
  {
    key: "factory",
    label: "Industrial & Plant",
    description: "Factory-to-dealer and manufacturing supply chain",
    keywords: ["factory", "plant", "industrial", "manufacturing", "oem"],
    icon: Factory,
  },
  {
    key: "globe",
    label: "Cross-Border",
    description: "Pan-India network and international shipping",
    keywords: ["globe", "global", "international", "network", "world"],
    icon: Globe,
  },
  {
    key: "bike",
    label: "Hyperlocal 2-Wheeler",
    description: "Last-mile bike couriers and intra-city point-to-point",
    keywords: ["bike", "hyperlocal", "local", "last mile", "courier"],
    icon: Bike,
  },
  {
    key: "map-pin",
    label: "Live Tracking",
    description: "Pin-to-pin coverage, hub scans and milestone alerts",
    keywords: ["map-pin", "tracking", "location", "route", "gps"],
    icon: MapPin,
  },
  {
    key: "file-text",
    label: "Documentation & Compliance",
    description: "Digital LR, e-Way Bill, POD and GST invoicing",
    keywords: ["file-text", "document", "eway", "pod", "invoice", "lr"],
    icon: FileText,
  },
] as const;

const ICON_BY_KEY: Readonly<Record<ServiceIconKey, ServiceIconMeta>> = SERVICE_ICON_REGISTRY.reduce(
  (acc, item) => {
    acc[item.key] = item;
    return acc;
  },
  {} as Record<ServiceIconKey, ServiceIconMeta>,
);

/** Legacy aliases mapped to canonical registry keys. */
const LEGACY_ICON_ALIASES: Readonly<Record<string, ServiceIconKey>> = {
  box: "package",
  return: "refresh-ccw",
  returns: "refresh-ccw",
  shield: "shield-check",
  cart: "shopping-cart",
  document: "file-text",
  pin: "map-pin",
};

/**
 * Normalizes a raw icon string into a valid `ServiceIconKey`, or `null` if unknown.
 */
export function normalizeServiceIconKey(raw: string | null | undefined): ServiceIconKey | null {
  if (!raw) return null;
  const cleaned = raw.trim().toLowerCase();
  if (cleaned in ICON_BY_KEY) {
    return cleaned as ServiceIconKey;
  }
  if (cleaned in LEGACY_ICON_ALIASES) {
    return LEGACY_ICON_ALIASES[cleaned];
  }
  return null;
}

/**
 * Resolves metadata for a service icon key (or `null` when unknown).
 */
export function getServiceIconMeta(raw: string | null | undefined): ServiceIconMeta | null {
  const key = normalizeServiceIconKey(raw);
  return key ? ICON_BY_KEY[key] : null;
}

/**
 * Resolves the Lucide component for the public Services page, falling back to `Package`.
 */
export function resolveServiceIcon(raw: string | null | undefined): LucideIcon {
  const meta = getServiceIconMeta(raw);
  return meta ? meta.icon : Package;
}
