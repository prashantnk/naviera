// frontend/src/lib/form-options.ts
/**
 * Presentation metadata for every enum rendered inside a form control.
 *
 * Single source of truth for dropdown labels, one-line helper text, lucide
 * icons and semantic tints. Forms must never print raw enum values
 * (`HOME`, `IN_TRANSIT`, `GST_INVOICE`) to users; they render these maps
 * through `IconSelect` instead.
 *
 * Spring Boot analogy: this is the `messages.properties` + `@JsonValue`
 * display layer for enums. The enum value itself (what the API receives)
 * never changes; only how it is presented.
 */
import type { LucideIcon } from "lucide-react";
import {
  ArrowUpRight,
  BadgeCheck,
  Ban,
  Banknote,
  Boxes,
  BriefcaseBusiness,
  Building2,
  CalendarClock,
  CalendarSync,
  Car,
  CircleCheckBig,
  CircleSlash,
  CircleX,
  ClipboardCheck,
  ClipboardList,
  Container,
  CreditCard,
  Crown,
  Eye,
  EyeOff,
  FilePenLine,
  FileText,
  FileWarning,
  FileX,
  Flame,
  HandCoins,
  House,
  IdCard,
  Image,
  Landmark,
  Layers,
  ListFilter,
  Lock,
  MapPin,
  MapPinOff,
  Moon,
  Package,
  PackageMinus,
  PackageX,
  PhoneOff,
  Plane,
  QrCode,
  Receipt,
  Ruler,
  Scale,
  ScrollText,
  ShieldCheck,
  ShieldX,
  Shirt,
  ShoppingCart,
  Shuffle,
  Smartphone,
  Sofa,
  Stamp,
  Store,
  Sun,
  Sunrise,
  Sunset,
  Tag,
  ThumbsDown,
  TrainFront,
  TriangleAlert,
  Truck,
  Undo2,
  User,
  Users,
  UserX,
  Wallet,
  Warehouse,
  Weight,
} from "lucide-react";
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
  ServiceScope,
  ServiceType,
  ShipmentType,
  UserRole,
  ServiceOption,
  WeightUnit,
} from "@/api_client";

/** Semantic tint applied to an option's icon tile (never a tenant brand hex). */
export type OptionTone = "neutral" | "brand" | "sky" | "amber" | "emerald" | "rose";

/** Tailwind classes per tone: neutral and status palettes plus the runtime `primary` token. */
export const OPTION_TONE_CLASSES: Readonly<Record<OptionTone, string>> = {
  neutral: "bg-slate-100 text-slate-600",
  brand: "bg-primary/10 text-primary",
  sky: "bg-sky-50 text-sky-700",
  amber: "bg-amber-50 text-amber-700",
  emerald: "bg-emerald-50 text-emerald-700",
  rose: "bg-rose-50 text-rose-700",
};

/** Display metadata for a single enum member. */
export interface OptionMeta {
  /** Short, human friendly label shown in the trigger and the list. */
  label: string;
  /** One-line helper text shown under the label inside the dropdown. */
  description: string;
  /** Lucide icon rendered inside a tinted tile. */
  icon: LucideIcon;
  /** Semantic tint of the icon tile. */
  tone: OptionTone;
}

/** An `OptionMeta` bound to the value that is written to the form state. */
export interface SelectOption<TValue extends string = string> extends OptionMeta {
  value: TValue;
}

/** Sentinel value used by list filters for the "show everything" choice. */
export const ALL_FILTER_VALUE = "ALL";

// ---------------------------------------------------------------------------
// Addresses
// ---------------------------------------------------------------------------

export const ADDRESS_CATEGORY_OPTIONS: Readonly<Record<AddressCategory, OptionMeta>> = {
  [AddressCategory.HOME]: {
    label: "Home",
    description: "House, flat or residential society",
    icon: House,
    tone: "sky",
  },
  [AddressCategory.OFFICE]: {
    label: "Office",
    description: "Corporate office or business park",
    icon: Building2,
    tone: "neutral",
  },
  [AddressCategory.WAREHOUSE]: {
    label: "Warehouse",
    description: "Godown, fulfilment or distribution centre",
    icon: Warehouse,
    tone: "amber",
  },
  [AddressCategory.STOREFRONT]: {
    label: "Storefront",
    description: "Retail shop, outlet or showroom",
    icon: Store,
    tone: "emerald",
  },
  [AddressCategory.OTHER]: {
    label: "Other",
    description: "Any other pickup or drop point",
    icon: MapPin,
    tone: "neutral",
  },
};

export const ADDRESS_SCOPE_OPTIONS: Readonly<Record<AddressScope, OptionMeta>> = {
  [AddressScope.PRIVATE]: {
    label: "Private",
    description: "Visible only to you",
    icon: Lock,
    tone: "neutral",
  },
  [AddressScope.TENANT]: {
    label: "Shared with team",
    description: "Every teammate can book with this address",
    icon: Users,
    tone: "brand",
  },
};

// ---------------------------------------------------------------------------
// Shipment classification
// ---------------------------------------------------------------------------

export const PRODUCT_CATEGORY_OPTIONS: Readonly<Record<ProductCategory, OptionMeta>> = {
  [ProductCategory.HOUSEHOLD_PERSONAL]: {
    label: "Household & Personal",
    description: "Personal effects, home goods, furniture",
    icon: Sofa,
    tone: "sky",
  },
  [ProductCategory.VEHICLE]: {
    label: "Vehicle & Automotive",
    description: "Two-wheelers, spares and auto parts",
    icon: Car,
    tone: "neutral",
  },
  [ProductCategory.DOCUMENTS]: {
    label: "Documents & Letters",
    description: "Papers, contracts and certificates",
    icon: FileText,
    tone: "neutral",
  },
  [ProductCategory.HAZARDOUS]: {
    label: "Hazardous (HAZMAT)",
    description: "Flammable, chemical or regulated goods",
    icon: Flame,
    tone: "rose",
  },
  [ProductCategory.COMMERCIAL]: {
    label: "Commercial Goods",
    description: "Trade stock and B2B consignments",
    icon: BriefcaseBusiness,
    tone: "amber",
  },
  [ProductCategory.ELECTRONICS]: {
    label: "Electronics & Gadgets",
    description: "Phones, laptops and appliances",
    icon: Smartphone,
    tone: "sky",
  },
  [ProductCategory.APPAREL]: {
    label: "Apparel & Clothing",
    description: "Garments, footwear and accessories",
    icon: Shirt,
    tone: "emerald",
  },
  [ProductCategory.OTHER]: {
    label: "Other (specify)",
    description: "Describe the contents in the next field",
    icon: Package,
    tone: "neutral",
  },
};

export const SHIPMENT_TYPE_OPTIONS: Readonly<Record<ShipmentType, OptionMeta>> = {
  [ShipmentType.FORWARD]: {
    label: "Forward",
    description: "Seller to customer delivery",
    icon: ArrowUpRight,
    tone: "sky",
  },
  [ShipmentType.REVERSE]: {
    label: "Reverse (DTO)",
    description: "Return pickup from the customer",
    icon: Undo2,
    tone: "amber",
  },
};

/**
 * Bookable services (pricing redesign, DESIGN.md v4). Delhivery options are B2C,
 * Logismart Prime is B2B Cargo; names follow Delhivery One ("Express", not "Air").
 */
export const SERVICE_OPTION_OPTIONS: Readonly<Record<ServiceOption, OptionMeta>> = {
  [ServiceOption.DELHIVERY_SURFACE]: {
    label: "Delhivery Surface",
    description: "Economical road delivery",
    icon: Truck,
    tone: "neutral",
  },
  [ServiceOption.DELHIVERY_EXPRESS]: {
    label: "Delhivery Express",
    description: "Fastest delivery (air where available)",
    icon: Plane,
    tone: "sky",
  },
  [ServiceOption.PRIME_SURFACE]: {
    label: "Logismart Prime",
    description: "B2B cargo by road through Logismart's partner network",
    icon: Warehouse,
    tone: "brand",
  },
  [ServiceOption.DELHIVERY_B2B_SURFACE]: {
    label: "Delhivery B2B Cargo",
    description: "B2B cargo (part truckload) by road on Delhivery's network",
    icon: Truck,
    tone: "neutral",
  },
};

export const SERVICE_TYPE_OPTIONS: Readonly<Record<ServiceType, OptionMeta>> = {
  [ServiceType.SURFACE_ROAD]: {
    label: "Surface (Truck)",
    description: "Economical line-haul by truck",
    icon: Truck,
    tone: "neutral",
  },
  [ServiceType.SURFACE_TRAIN]: {
    label: "Surface (Train)",
    description: "Long-distance rail line-haul",
    icon: TrainFront,
    tone: "neutral",
  },
  [ServiceType.AIR]: {
    label: "Air",
    description: "Fastest transit for urgent parcels",
    icon: Plane,
    tone: "sky",
  },
};

// ---------------------------------------------------------------------------
// Billing
// ---------------------------------------------------------------------------

export const FREIGHT_PAYMENT_MODE_OPTIONS: Readonly<Record<FreightPaymentMode, OptionMeta>> = {
  [FreightPaymentMode.PREPAID]: {
    label: "Prepaid",
    description: "Deducted from your wallet at booking",
    icon: Wallet,
    tone: "emerald",
  },
  [FreightPaymentMode.POSTPAID]: {
    label: "Postpaid (billed to wallet)",
    description: "Debited from your wallet like Prepaid; the balance may go negative",
    icon: Receipt,
    tone: "sky",
  },
  [FreightPaymentMode.TO_PAY]: {
    label: "Freight on Delivery (To-Pay)",
    description: "Receiver pays shipping charges at delivery",
    icon: HandCoins,
    tone: "amber",
  },
};

/**
 * Freight modes that can be picked on any booking or edit form (B2C + B2B).
 *
 * TO_PAY ("Freight on Delivery") is switched off for the MVP (owner decision
 * 2026-10-30, fix plan WP0) and the API rejects it. Its entry stays in
 * `FREIGHT_PAYMENT_MODE_OPTIONS` so legacy TO_PAY rows still render a label.
 */
export const BOOKABLE_FREIGHT_PAYMENT_MODES: readonly FreightPaymentMode[] = [
  FreightPaymentMode.PREPAID,
  FreightPaymentMode.POSTPAID,
];

/**
 * Freight modes a merchant (customer role) may choose on their own bookings.
 * A customer-booked POSTPAID order is billed to the merchant's own wallet exactly
 * like PREPAID (plan B16 / decision D85); the backend fixes the billing channel
 * at booking, so the UI only needs to offer the option.
 */
export const CUSTOMER_FREIGHT_PAYMENT_MODES: readonly FreightPaymentMode[] = [
  FreightPaymentMode.PREPAID,
  FreightPaymentMode.POSTPAID,
];

/**
 * Returns the freight-mode keys a user may pick (never a non-bookable mode).
 *
 * @param isAdmin - Whether the current user is a tenant Admin / Owner.
 * @param allowed - Optional flow-specific subset (e.g. reverse pickups).
 * @returns Ordered freight modes to render in a select.
 */
export function freightPaymentModesFor(
  isAdmin: boolean,
  allowed?: readonly FreightPaymentMode[],
): FreightPaymentMode[] {
  const base = (allowed ?? BOOKABLE_FREIGHT_PAYMENT_MODES).filter((mode) =>
    BOOKABLE_FREIGHT_PAYMENT_MODES.includes(mode),
  );
  if (isAdmin) return base;
  return base.filter((mode) => CUSTOMER_FREIGHT_PAYMENT_MODES.includes(mode));
}

/**
 * Returns `allowed` plus the record's current value when it is no longer offered
 * (e.g. a TO_PAY or "Commercial" shipment booked before the MVP switches), so an
 * edit form still renders the saved value instead of an empty select.
 *
 * @param allowed - Values a user may pick today.
 * @param current - The record's saved value, if any.
 * @returns Ordered values for `toOptions`.
 */
export function withCurrentValue<TValue extends string>(
  allowed: readonly TValue[],
  current: TValue | null | undefined,
): TValue[] {
  if (!current || allowed.includes(current)) return allowed.slice();
  return [...allowed, current];
}

/**
 * Product categories offered on B2C (express parcel) forms.
 *
 * "Commercial Goods" is a B2B Cargo category; offering it on the B2C wizard made
 * a ₹94 parcel book as a ₹737 B2B LR (audit A-02). B2B forms keep the full list.
 */
export const B2C_PRODUCT_CATEGORIES: readonly ProductCategory[] = (
  Object.keys(PRODUCT_CATEGORY_OPTIONS) as ProductCategory[]
).filter((category) => category !== ProductCategory.COMMERCIAL);

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

export const PICKUP_STATUS_OPTIONS: Readonly<Record<PickupStatus, OptionMeta>> = {
  [PickupStatus.DRAFT]: {
    label: "Draft",
    description: "Saved but not booked yet",
    icon: FilePenLine,
    tone: "neutral",
  },
  [PickupStatus.OPEN]: {
    label: "Open",
    description: "Ready to ship · awaiting a pickup request",
    icon: Package,
    tone: "sky",
  },
  [PickupStatus.ASSIGNED]: {
    label: "Assigned",
    description: "Ready for pickup · linked to a pickup request",
    icon: ClipboardCheck,
    tone: "sky",
  },
  [PickupStatus.IN_TRANSIT]: {
    label: "In Transit",
    description: "Picked up and moving through the network",
    icon: Truck,
    tone: "brand",
  },
  [PickupStatus.OUT_FOR_DELIVERY]: {
    label: "Out for delivery",
    description: "Out for delivery today",
    icon: MapPin,
    tone: "brand",
  },
  [PickupStatus.EXCEPTION]: {
    label: "Exception (NDR)",
    description: "Delivery blocked · needs an NDR reason",
    icon: TriangleAlert,
    tone: "amber",
  },
  [PickupStatus.COMPLETED]: {
    label: "Delivered",
    description: "Completed with OTP proof of delivery",
    icon: CircleCheckBig,
    tone: "emerald",
  },
  [PickupStatus.CANCELLED]: {
    label: "Cancelled",
    description: "Booking cancelled before pickup",
    icon: CircleX,
    tone: "neutral",
  },
  [PickupStatus.RTO_INITIATED]: {
    label: "RTO Initiated",
    description: "Returning to origin",
    icon: Undo2,
    tone: "rose",
  },
  [PickupStatus.RTO_IN_TRANSIT]: {
    label: "RTO In Transit",
    description: "Returning to origin facility",
    icon: Undo2,
    tone: "rose",
  },
  [PickupStatus.RTO_DELIVERED]: {
    label: "Returned to seller",
    description: "Returned to the original pickup address",
    icon: CircleCheckBig,
    tone: "neutral",
  },
  [PickupStatus.LOST]: {
    label: "Lost",
    description: "Shipment lost in transit",
    icon: PackageX,
    tone: "rose",
  },
  [PickupStatus.QC_FAILED]: {
    label: "QC Failed",
    description: "Doorstep quality check failed",
    icon: ShieldX,
    tone: "rose",
  },
  [PickupStatus.REJECTED_AT_PICKUP]: {
    label: "Rejected at Pickup",
    description: "Pickup refused or cargo rejected",
    icon: Ban,
    tone: "rose",
  },
};

export const NDR_REASON_OPTIONS: Readonly<Record<NdrExceptionReason, OptionMeta>> = {
  [NdrExceptionReason.DOCUMENT_NEEDED]: {
    label: "Documents missing",
    description: "E-way bill or compliance paperwork missing",
    icon: FileWarning,
    tone: "amber",
  },
  [NdrExceptionReason.APPOINTMENT_NEEDED]: {
    label: "Appointment required",
    description: "Consignee needs a delivery appointment",
    icon: CalendarClock,
    tone: "amber",
  },
  [NdrExceptionReason.SHORT_SHIPMENT]: {
    label: "Short shipment",
    description: "Box count mismatch or incomplete address",
    icon: PackageMinus,
    tone: "rose",
  },
  [NdrExceptionReason.CUSTOMER_UNAVAILABLE]: {
    label: "Consignee unavailable",
    description: "Unreachable, refused or premises closed",
    icon: UserX,
    tone: "rose",
  },
  [NdrExceptionReason.CONSIGNEE_UNAVAILABLE]: {
    label: "Consignee unavailable",
    description: "Not reachable or premises closed at delivery attempt",
    icon: PhoneOff,
    tone: "rose",
  },
  [NdrExceptionReason.CONSIGNEE_REFUSED]: {
    label: "Consignee refused",
    description: "Delivery refused or order cancelled at doorstep",
    icon: ThumbsDown,
    tone: "rose",
  },
  [NdrExceptionReason.DELIVERY_RESCHEDULED]: {
    label: "Delivery rescheduled",
    description: "Consignee asked for delivery on another date",
    icon: CalendarSync,
    tone: "amber",
  },
  [NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED]: {
    label: "Consignee details required",
    description: "Phone or address incomplete or incorrect",
    icon: MapPinOff,
    tone: "amber",
  },
  [NdrExceptionReason.PAYMENT_DISPUTE]: {
    label: "Payment dispute",
    description: "COD vs prepaid mismatch claimed by consignee",
    icon: CreditCard,
    tone: "amber",
  },
  [NdrExceptionReason.DAMAGED]: {
    label: "Damaged in transit",
    description: "Package damaged; deliver anyway or return",
    icon: PackageX,
    tone: "rose",
  },
  [NdrExceptionReason.EWAY_BILL_MISSING]: {
    label: "E-way bill missing",
    description: "E-way bill missing or expired for this movement",
    icon: FileX,
    tone: "amber",
  },
  [NdrExceptionReason.FREIGHT_COLLECTION]: {
    label: "Freight collection pending",
    description: "Pending freight must be cleared before delivery",
    icon: Banknote,
    tone: "amber",
  },
  [NdrExceptionReason.ADDITIONAL_CHARGES]: {
    label: "Additional charges",
    description: "Extra charges (e.g. Mathadi / union) need acknowledgement",
    icon: Receipt,
    tone: "amber",
  },
  [NdrExceptionReason.WEIGHT_DISCREPANCY]: {
    label: "Weight discrepancy",
    description: "Measured weight differs from declared weight",
    icon: Scale,
    tone: "amber",
  },
  [NdrExceptionReason.PICKUP_FAILED]: {
    label: "Pickup failed",
    description: "Reverse pickup could not be completed",
    icon: Undo2,
    tone: "rose",
  },
};

// ---------------------------------------------------------------------------
// Pickup scheduling
// ---------------------------------------------------------------------------

export const PICKUP_STRATEGY_OPTIONS: Readonly<Record<PickupStrategy, OptionMeta>> = {
  [PickupStrategy.DEFAULT]: {
    label: "Standard pickup",
    description: "Regular scheduled milk-run pickup",
    icon: Truck,
    tone: "neutral",
  },
  [PickupStrategy.DEDICATED]: {
    label: "Dedicated vehicle",
    description: "Exclusive vehicle for this consignment",
    icon: Container,
    tone: "amber",
  },
  [PickupStrategy.CONSOLIDATED]: {
    label: "Consolidated dispatch",
    description: "Merged with other consignments on one run",
    icon: Layers,
    tone: "sky",
  },
};

export const PICKUP_TIME_SLOT_OPTIONS: Readonly<Record<PickupTimeSlot, OptionMeta>> = {
  [PickupTimeSlot._06_00_10_00]: {
    label: "06:00 AM – 10:00 AM",
    description: "Morning · before business hours",
    icon: Sunrise,
    tone: "amber",
  },
  [PickupTimeSlot._10_00_14_00]: {
    label: "10:00 AM – 02:00 PM",
    description: "Midday · most popular window",
    icon: Sun,
    tone: "amber",
  },
  [PickupTimeSlot._14_00_18_00]: {
    label: "02:00 PM – 06:00 PM",
    description: "Afternoon · same-day dispatch",
    icon: Sunset,
    tone: "sky",
  },
  [PickupTimeSlot._18_00_22_00]: {
    label: "06:00 PM – 10:00 PM",
    description: "Evening · after-hours pickup",
    icon: Moon,
    tone: "neutral",
  },
};

// ---------------------------------------------------------------------------
// Documents
// ---------------------------------------------------------------------------

export const DOCUMENT_TYPE_OPTIONS: Readonly<Record<DocumentType, OptionMeta>> = {
  [DocumentType.GST_INVOICE]: {
    label: "GST invoice",
    description: "Tax invoice for the goods",
    icon: Receipt,
    tone: "sky",
  },
  [DocumentType.EWAY_BILL]: {
    label: "E-way bill",
    description: "Mandatory above ₹50,000 cargo value",
    icon: ScrollText,
    tone: "amber",
  },
  [DocumentType.DELIVERY_CHALLAN]: {
    label: "Delivery challan",
    description: "Non-sale movement of goods",
    icon: ClipboardList,
    tone: "neutral",
  },
  [DocumentType.DECLARATION]: {
    label: "Declaration",
    description: "Self-declaration or undertaking",
    icon: Stamp,
    tone: "neutral",
  },
  [DocumentType.BOX_PHOTO]: {
    label: "Box photo",
    description: "Condition of packages before dispatch",
    icon: Image,
    tone: "emerald",
  },
  [DocumentType.LABEL_IMAGE]: {
    label: "Label image",
    description: "Photo of the pasted shipping label",
    icon: Tag,
    tone: "neutral",
  },
  [DocumentType.OTHER]: {
    label: "Other document",
    description: "Any other supporting file",
    icon: FileText,
    tone: "neutral",
  },
  [DocumentType.PO_COPY]: {
    label: "PO copy",
    description: "Purchase order from the consignee",
    icon: ShoppingCart,
    tone: "sky",
  },
  [DocumentType.KYC]: {
    label: "KYC document",
    description: "Business or identity KYC proof",
    icon: IdCard,
    tone: "neutral",
  },
  [DocumentType.REGULATORY_FORM]: {
    label: "Regulatory form",
    description: "State or statutory permit",
    icon: Landmark,
    tone: "neutral",
  },
  [DocumentType.PHOTO_ID]: {
    label: "Photo ID",
    description: "Government photo ID of the sender",
    icon: BadgeCheck,
    tone: "neutral",
  },
  [DocumentType.ASN]: {
    label: "ASN",
    description: "Advance shipping notice for the warehouse",
    icon: Boxes,
    tone: "neutral",
  },
  [DocumentType.E_INVOICE_QR]: {
    label: "E-invoice QR",
    description: "Signed IRN QR from the e-invoice portal",
    icon: QrCode,
    tone: "sky",
  },
};

// ---------------------------------------------------------------------------
// Units
// ---------------------------------------------------------------------------

export const DIMENSION_UNIT_OPTIONS: Readonly<Record<DimensionUnit, OptionMeta>> = {
  [DimensionUnit.CM]: { label: "cm", description: "Centimetres", icon: Ruler, tone: "neutral" },
  [DimensionUnit.M]: { label: "m", description: "Metres", icon: Ruler, tone: "neutral" },
  [DimensionUnit.IN]: { label: "in", description: "Inches", icon: Ruler, tone: "neutral" },
  [DimensionUnit.FT]: { label: "ft", description: "Feet", icon: Ruler, tone: "neutral" },
};

export const WEIGHT_UNIT_OPTIONS: Readonly<Record<WeightUnit, OptionMeta>> = {
  [WeightUnit.KG]: { label: "kg", description: "Kilograms", icon: Weight, tone: "neutral" },
  [WeightUnit.G]: { label: "g", description: "Grams", icon: Weight, tone: "neutral" },
};

// ---------------------------------------------------------------------------
// Team and access
// ---------------------------------------------------------------------------

export const SERVICE_SCOPE_OPTIONS: Readonly<Record<ServiceScope, OptionMeta>> = {
  [ServiceScope.B2C]: {
    label: "B2C Express",
    description: "Domestic parcels · Forward & DTO",
    icon: Package,
    tone: "sky",
  },
  [ServiceScope.B2B]: {
    label: "B2B Cargo",
    description: "Heavy cargo · LTL surface shipping",
    icon: Truck,
    tone: "amber",
  },
  [ServiceScope.BOTH]: {
    label: "Unified (Both)",
    description: "Access to both B2C and B2B flows",
    icon: Layers,
    tone: "brand",
  },
};

export const USER_ROLE_OPTIONS: Readonly<Record<UserRole, OptionMeta>> = {
  [UserRole.OWNER]: {
    label: "Owner",
    description: "Full control including billing",
    icon: Crown,
    tone: "amber",
  },
  [UserRole.ADMIN]: {
    label: "Admin",
    description: "Manages team, rates and operations",
    icon: ShieldCheck,
    tone: "sky",
  },
  [UserRole.OPERATIONS_USER]: {
    label: "Operations-User",
    description: "Manages orders, pickups, exceptions and weight audits",
    icon: Truck,
    tone: "emerald",
  },
  [UserRole.SUPPORT_USER]: {
    label: "Support-User",
    description: "Manages support tickets, exceptions and weight claims",
    icon: Users,
    tone: "sky",
  },
  [UserRole.READ_ONLY_USER]: {
    label: "Read access Only-User",
    description: "View-only access across dashboards, orders and reports",
    icon: Eye,
    tone: "neutral",
  },
  [UserRole.CUSTOMER]: {
    label: "Customer",
    description: "Books and tracks own shipments",
    icon: User,
    tone: "neutral",
  },
};

/** Account status values used by the team page filter (not an API enum). */
export enum AccountStatusFilter {
  ACTIVE = "ACTIVE",
  SUSPENDED = "SUSPENDED",
}

export const ACCOUNT_STATUS_OPTIONS: Readonly<Record<AccountStatusFilter, OptionMeta>> = {
  [AccountStatusFilter.ACTIVE]: {
    label: "Active",
    description: "Can sign in and book",
    icon: CircleCheckBig,
    tone: "emerald",
  },
  [AccountStatusFilter.SUSPENDED]: {
    label: "Suspended",
    description: "Access revoked by an admin",
    icon: CircleSlash,
    tone: "rose",
  },
};

/** String booleans used by settings toggles rendered as selects. */
export enum VisibilityToggle {
  SHOW = "true",
  HIDE = "false",
}

export const VISIBILITY_TOGGLE_OPTIONS: Readonly<Record<VisibilityToggle, OptionMeta>> = {
  [VisibilityToggle.SHOW]: {
    label: "Yes, show it",
    description: "Visible on the public landing page",
    icon: Eye,
    tone: "emerald",
  },
  [VisibilityToggle.HIDE]: {
    label: "No, hide it",
    description: "Hidden from visitors",
    icon: EyeOff,
    tone: "neutral",
  },
};

// ---------------------------------------------------------------------------
// Free-text presets
// ---------------------------------------------------------------------------

/**
 * Return-reason presets. `value` is the exact text written into
 * `reason_for_return`, so it must stay byte-identical to the legacy presets.
 */
export const RETURN_REASON_OPTIONS: readonly SelectOption<string>[] = [
  {
    value: "Defective / Damaged Item",
    label: "Defective or damaged",
    description: "Item arrived broken or not working",
    icon: PackageX,
    tone: "rose",
  },
  {
    value: "Wrong Item Delivered",
    label: "Wrong item delivered",
    description: "Different product, colour or variant",
    icon: Shuffle,
    tone: "amber",
  },
  {
    value: "Size / Fit Issue",
    label: "Size or fit issue",
    description: "Does not fit as expected",
    icon: Ruler,
    tone: "sky",
  },
  {
    value: "Quality Not As Expected",
    label: "Quality not as expected",
    description: "Material or finish below expectation",
    icon: ThumbsDown,
    tone: "amber",
  },
  {
    value: "Customer Changed Mind",
    label: "Customer changed mind",
    description: "No longer needed by the buyer",
    icon: Undo2,
    tone: "neutral",
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Converts a metadata map into an ordered option array for `IconSelect`.
 *
 * @param map - Metadata keyed by enum value.
 * @param order - Optional explicit subset or order; defaults to declaration order.
 * @returns Options carrying their `value`.
 */
export function toOptions<TValue extends string>(
  map: Readonly<Record<TValue, OptionMeta>>,
  order?: readonly TValue[],
): SelectOption<TValue>[] {
  const keys = order ?? (Object.keys(map) as TValue[]);
  return keys.map((value) => Object.assign({ value }, map[value]));
}

/**
 * Derives a `value -> label` lookup (kept for legacy `CATEGORY_LABELS` consumers).
 *
 * @param map - Metadata keyed by enum value.
 * @returns Plain label record.
 */
export function optionLabels<TValue extends string>(
  map: Readonly<Record<TValue, OptionMeta>>,
): Record<TValue, string> {
  const labels = {} as Record<TValue, string>;
  for (const key of Object.keys(map) as TValue[]) {
    labels[key] = map[key].label;
  }
  return labels;
}

/**
 * Safe metadata lookup for values that may be unknown, empty or legacy.
 *
 * @param map - Metadata keyed by enum value.
 * @param value - Raw value from the API or form state.
 * @returns The metadata, or `undefined` when the value is not mapped.
 */
export function getOptionMeta<TValue extends string>(
  map: Readonly<Record<TValue, OptionMeta>>,
  value: string | null | undefined,
): OptionMeta | undefined {
  if (!value || !Object.prototype.hasOwnProperty.call(map, value)) {
    return undefined;
  }
  return map[value as TValue];
}

/**
 * Prepends an "All" choice to filter options (list pages and filter bars).
 *
 * @param options - Concrete filter options.
 * @param label - Label of the catch-all choice, e.g. "All categories".
 * @returns A new array starting with the `ALL_FILTER_VALUE` option.
 */
export function withAllOption<TValue extends string>(
  options: readonly SelectOption<TValue>[],
  label: string,
): SelectOption<TValue | typeof ALL_FILTER_VALUE>[] {
  const allOption: SelectOption<typeof ALL_FILTER_VALUE> = {
    value: ALL_FILTER_VALUE,
    label,
    description: "No filter applied",
    icon: ListFilter,
    tone: "neutral",
  };
  return ([allOption] as SelectOption<TValue | typeof ALL_FILTER_VALUE>[]).concat(options);
}
