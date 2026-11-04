// frontend/src/lib/validations/shipment.ts
import {
  AddressCategory,
  AddressScope,
  DocumentType,
  FreightPaymentMode,
  PickupTimeSlot,
  ProductCategory,
  ServiceType,
  ShipmentType,
  DimensionUnit,
  WeightUnit,
  PickupStrategy,
} from "@/api_client";
import * as z from "zod";

export const addressSchema = z.object({
  name: z.string().min(2, "Name is required").optional().or(z.literal("")),
  company_name: z.string().optional().or(z.literal("")),
  phone: z
    .string()
    .refine((val) => !val || /^[6-9]\d{9}$/.test(val), {
      message: "Must be a 10-digit mobile number starting with 6-9",
    })
    .optional()
    .or(z.literal("")),
  alternate_phone: z
    .string()
    .refine((val) => !val || /^[6-9]\d{9}$/.test(val), {
      message: "Must be a 10-digit mobile number starting with 6-9",
    })
    .optional()
    .or(z.literal("")),
  email: z.string().email("Invalid email").optional().or(z.literal("")),
  gstin: z
    .string()
    .refine((val) => !val || /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(val), {
      message: "Invalid Indian GSTIN format",
    })
    .optional()
    .or(z.literal("")),
  address_line1: z
    .string()
    .min(5, "Complete address required")
    .optional()
    .or(z.literal("")),
  address_line2: z.string().optional(),
  landmark: z.string().optional(),
  city: z.string().min(2, "City is required").optional().or(z.literal("")),
  state: z.string().min(2, "State is required").optional().or(z.literal("")),
  pincode: z
    .string()
    .refine((val) => !val || /^[1-9][0-9]{5}$/.test(val), {
      message: "Must be a valid 6-digit Indian pincode (cannot start with 0)",
    })
    .optional()
    .or(z.literal("")),
  category: z.nativeEnum(AddressCategory).default(AddressCategory.HOME),
  scope: z.nativeEnum(AddressScope).default(AddressScope.PRIVATE),
  save_to_address_book: z.boolean().default(true),
  is_shared_with_team: z.boolean().default(false),
});

const packageSchema = z.object({
  length: z.number().min(0, "Cannot be negative").default(0),
  breadth: z.number().min(0, "Cannot be negative").default(0),
  height: z.number().min(0, "Cannot be negative").default(0),
  dimension_unit: z.nativeEnum(DimensionUnit).default(DimensionUnit.CM),
  weight: z.number().min(0.1, "Weight is required"),
  weight_unit: z.nativeEnum(WeightUnit).default(WeightUnit.KG),
  box_count: z.number().min(1).default(1),
  is_fragile: z.boolean().default(false),
  description: z.string().optional(),
});

/** Package fields checked by `addPackageDimensionIssues`. */
type PackageDims = Pick<z.infer<typeof packageSchema>, "length" | "breadth" | "height">;

/**
 * A-26: every box needs real dimensions (0×0×0 guarantees a weight dispute later).
 * Shared by the booking schemas; blind pickups (no boxes measured yet) skip it.
 *
 * @param packages - Packages from the form.
 * @param ctx - Zod refinement context.
 */
export function addPackageDimensionIssues(packages: PackageDims[], ctx: z.RefinementCtx): void {
  packages.forEach((pkg, index) => {
    for (const field of ["length", "breadth", "height"] as const) {
      if (!(pkg[field] > 0)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Enter a size greater than 0",
          path: ["packages", index, field],
        });
      }
    }
  });
}

const documentSchema = z.object({
  document_type: z.nativeEnum(DocumentType),
  file_url: z.string(),
  file_name: z.string(),
});

// Specialized Outbound Forward Shipment Schema
export const forwardShipmentSchema = z
  .object({
    order_reference_id: z.string().optional().or(z.literal("")),
    // Delhivery flow: the booking form has no pickup options. The page sends
    // today's date silently; the real pickup date/slot is chosen on the Pickup Request.
    requested_pickup_date: z.string().optional(),
    pickup_time_slot: z.nativeEnum(PickupTimeSlot).optional(),
    service_type: z.nativeEnum(ServiceType),
    shipment_type: z.literal(ShipmentType.FORWARD),
    product_category: z.nativeEnum(ProductCategory, {
      message: "Please select a product category",
    }),
    other_category_description: z.string().optional(),
    payment_details: z.object({
      freight_payment_mode: z.nativeEnum(FreightPaymentMode),
      is_cod: z.boolean().default(false),
      cod_amount: z.number().min(0, "COD amount cannot be negative").default(0),
      add_shipping_to_cod: z.boolean().default(false),
      shipment_value: z.number().min(0, "Shipment value cannot be negative"),
      shipment_tax_value: z.number().default(0),
      shipment_total_value: z.number().default(0),
      tax_amount: z.number().default(0),
      base_freight: z.number().default(0),
      total_logistics_cost: z.number().default(0),
      hsn_code: z.string().optional(),
      invoice_number: z.string().optional(),
      invoice_date: z.string().optional(),
      eway_bill_number: z.string().optional(),
      // Set from the backend valuation (D-06); never derived in the browser.
      eway_bill_required: z.boolean().default(false),
    }),
    pickup_address_id: z.string().optional(),
    new_pickup_address: addressSchema.optional(),
    delivery_address_id: z.string().optional(),
    new_delivery_address: addressSchema.optional(),
    packages: z.array(packageSchema).min(1, "At least one package is required"),
    documents: z.array(documentSchema).optional(),
  })
  .superRefine((data, ctx) => {
    // Rule A: E-Way Bill required when the backend valuation says so (D-06)
    if (data.payment_details.eway_bill_required && !data.payment_details.eway_bill_number) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "An E-Way Bill is required for this goods value.",
        path: ["payment_details", "eway_bill_number"],
      });
    }

    addPackageDimensionIssues(data.packages, ctx);

    // Rule B: ProductCategory OTHER requires description
    if (
      data.product_category === ProductCategory.OTHER &&
      (!data.other_category_description || data.other_category_description.trim() === "")
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please specify the custom category description.",
        path: ["other_category_description"],
      });
    }

    // Rule C: No Vehicles in Air Cargo
    if (
      data.service_type === ServiceType.AIR &&
      data.product_category === ProductCategory.VEHICLE
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Vehicles cannot be transported via Air Cargo. Please select a Surface service.",
        path: ["product_category"],
      });
    }

    // Rule D: COD cash collection requirements
    if (data.payment_details.is_cod === true) {
      if (data.payment_details.cod_amount <= 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "COD amount must be greater than 0 when Cash-on-Delivery is enabled.",
          path: ["payment_details", "cod_amount"],
        });
      } else if (data.payment_details.cod_amount > data.payment_details.shipment_total_value) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Collectible amount cannot exceed the total shipment value.",
          path: ["payment_details", "cod_amount"],
        });
      }
    }

    // Rule E: Address selection check for Pickup Location
    if (!data.pickup_address_id && (!data.new_pickup_address || !data.new_pickup_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new pickup location.",
        path: ["pickup_address_id"],
      });
    }

    // Rule F: Address selection check for Delivery Location
    if (!data.delivery_address_id && (!data.new_delivery_address || !data.new_delivery_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new delivery location.",
        path: ["delivery_address_id"],
      });
    }
  });

// Specialized Reverse Returns Shipment Schema
export const reverseShipmentSchema = z
  .object({
    order_reference_id: z.string().optional().or(z.literal("")),
    // Delhivery flow: the booking form has no pickup options. The page sends
    // today's date silently; the real pickup date/slot is chosen on the Pickup Request.
    requested_pickup_date: z.string().optional(),
    pickup_time_slot: z.nativeEnum(PickupTimeSlot).optional(),
    service_type: z.nativeEnum(ServiceType),
    shipment_type: z.literal(ShipmentType.REVERSE),
    reason_for_return: z.string().min(3, "Reason is required for reverse pickups (min 3 chars)"),
    product_category: z.nativeEnum(ProductCategory, {
      message: "Please select a product category",
    }),
    other_category_description: z.string().optional(),
    qc_required: z.boolean().default(false),
    qc_notes: z.string().optional(),
    payment_details: z.object({
      freight_payment_mode: z.nativeEnum(FreightPaymentMode),
      is_cod: z.boolean().default(false),
      cod_amount: z.number().min(0, "COD amount cannot be negative").default(0),
      add_shipping_to_cod: z.boolean().default(false),
      shipment_value: z.number().min(0, "Shipment value cannot be negative"),
      shipment_tax_value: z.number().default(0),
      shipment_total_value: z.number().default(0),
      tax_amount: z.number().default(0),
      base_freight: z.number().default(0),
      total_logistics_cost: z.number().default(0),
    }),
    pickup_address_id: z.string().optional(),
    new_pickup_address: addressSchema.optional(),
    delivery_address_id: z.string().optional(),
    new_delivery_address: addressSchema.optional(),
    packages: z.array(packageSchema).min(1, "At least one package is required"),
    documents: z.array(documentSchema).optional(),
  })
  .superRefine((data, ctx) => {
    addPackageDimensionIssues(data.packages, ctx);

    // Rule A: ProductCategory OTHER requires description
    if (
      data.product_category === ProductCategory.OTHER &&
      (!data.other_category_description || data.other_category_description.trim() === "")
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please specify the custom category description.",
        path: ["other_category_description"],
      });
    }

    // Rule B: No Vehicles in Air Cargo
    if (
      data.service_type === ServiceType.AIR &&
      data.product_category === ProductCategory.VEHICLE
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Vehicles cannot be transported via Air Cargo. Please select a Surface service.",
        path: ["product_category"],
      });
    }

    // Rule C: COD cash collection requirements
    if (data.payment_details.is_cod === true) {
      if (data.payment_details.cod_amount <= 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "COD amount must be greater than 0 when Cash-on-Delivery is enabled.",
          path: ["payment_details", "cod_amount"],
        });
      } else if (data.payment_details.cod_amount > data.payment_details.shipment_total_value) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Collectible amount cannot exceed the total shipment value.",
          path: ["payment_details", "cod_amount"],
        });
      }
    }

    // Rule D: Address selection check for Pickup Location
    if (!data.pickup_address_id && (!data.new_pickup_address || !data.new_pickup_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new pickup location.",
        path: ["pickup_address_id"],
      });
    }

    // Rule E: Address selection check for Delivery Location
    if (!data.delivery_address_id && (!data.new_delivery_address || !data.new_delivery_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new delivery location.",
        path: ["delivery_address_id"],
      });
    }
  });

// Backward Compatible Discriminated Union Schema
export const shipmentFormSchema = z.discriminatedUnion("shipment_type", [
  forwardShipmentSchema,
  reverseShipmentSchema,
]);

export type ForwardShipmentFormValues = z.infer<typeof forwardShipmentSchema>;
export type ReverseShipmentFormValues = z.infer<typeof reverseShipmentSchema>;
export type ShipmentFormValues = Omit<ForwardShipmentFormValues, "shipment_type"> & {
  shipment_type: ShipmentType;
  reason_for_return?: string;
  qc_required?: boolean;
  qc_notes?: string;
};

/**
 * True when a stored reverse booking draft contains user-entered data rather than
 * untouched mount defaults (BUG-10: prevents a false "Recovered your unsaved reverse
 * booking draft." toast on first visit to `/shipments/new/reverse`).
 *
 * @param vals - Stored draft form values.
 * @returns Whether the draft has non-default user input worth restoring.
 */
export function hasMeaningfulReverseDraft(
  vals: Partial<ReverseShipmentFormValues> | null | undefined,
): boolean {
  if (!vals || typeof vals !== "object") return false;
  if (
    Boolean(vals.order_reference_id?.trim()) ||
    Boolean(vals.reason_for_return?.trim()) ||
    Boolean(vals.product_category) ||
    Boolean(vals.other_category_description?.trim()) ||
    Boolean(vals.qc_notes?.trim()) ||
    Boolean(vals.pickup_address_id?.trim()) ||
    Boolean(vals.delivery_address_id?.trim()) ||
    Boolean(vals.new_pickup_address?.name?.trim() || vals.new_pickup_address?.pincode?.trim()) ||
    Boolean(vals.new_delivery_address?.name?.trim() || vals.new_delivery_address?.pincode?.trim()) ||
    Number(vals.payment_details?.shipment_value || 0) > 0 ||
    (vals.documents?.length || 0) > 0
  ) {
    return true;
  }
  const pkgs = vals.packages;
  if (!Array.isArray(pkgs) || pkgs.length === 0) return false;
  if (pkgs.length > 1) return true;
  const first = pkgs[0];
  if (!first || typeof first !== "object") return false;
  return (
    Boolean(first.description?.trim()) ||
    Boolean(first.is_fragile) ||
    Number(first.box_count || 1) !== 1 ||
    Number(first.weight ?? 0.5) !== 0.5 ||
    Number(first.length ?? 10) !== 10 ||
    Number(first.breadth ?? 10) !== 10 ||
    Number(first.height ?? 10) !== 10
  );
}

/** Delhivery B2B allows up to 5 PO numbers on one LR, entered comma-separated. */
export const MAX_PO_NUMBERS = 5;

/**
 * Splits a comma-separated PO field into its non-empty PO numbers.
 *
 * @param value - Raw PO field text, e.g. `"PO-1, PO-2"`.
 * @returns Trimmed PO numbers, empty entries dropped.
 */
export function splitPoNumbers(value: string | null | undefined): string[] {
  return (value ?? "")
    .split(",")
    .map((po) => po.trim())
    .filter(Boolean);
}

/**
 * `when` predicate for the booking forms' cross-field rules.
 *
 * Zod 4 skips an object's `superRefine` as soon as any field has failed, so a half-filled
 * form showed only the first error (e.g. "select a category") and hid the missing addresses
 * and e-way bill until the next click. Running the rules on any value shaped like the form
 * reports every problem on the first "Compare rates".
 *
 * @param payload - Zod parse payload (`value` is the raw, possibly invalid form values).
 * @returns True when `value` has the objects/arrays the rules read.
 */
export function hasBookingFormShape(payload: { value: unknown }): boolean {
  const value = payload.value as Record<string, unknown> | null;
  return (
    typeof value === "object" &&
    value !== null &&
    typeof value.payment_details === "object" &&
    value.payment_details !== null &&
    Array.isArray(value.packages)
  );
}

// B2B Forward Shipment Schema
export const b2bForwardShipmentSchema = z
  .object({
    order_reference_id: z.string().optional().or(z.literal("")),
    // Delhivery flow: the booking form has no pickup options. The page sends
    // today's date silently; the real pickup date/slot is chosen on the Pickup Request.
    requested_pickup_date: z.string().optional(),
    pickup_time_slot: z.nativeEnum(PickupTimeSlot).optional(),
    service_type: z.nativeEnum(ServiceType),
    shipment_type: z.literal(ShipmentType.FORWARD),
    product_category: z.nativeEnum(ProductCategory, {
      message: "Please select a product category",
    }),
    other_category_description: z.string().optional(),
    
    // B2B Metadata
    po_number: z
      .string()
      .max(255, "PO number cannot exceed 255 characters")
      .refine((value) => splitPoNumbers(value).length <= MAX_PO_NUMBERS, {
        message: `Enter up to ${MAX_PO_NUMBERS} PO numbers, separated by commas.`,
      })
      .optional()
      .or(z.literal("")),
    po_date: z.string().optional().or(z.literal("")),
    appointment_id: z.string().max(100, "Appointment ID cannot exceed 100 characters").optional().or(z.literal("")),
    appointment_start: z.string().optional().or(z.literal("")),
    appointment_end: z.string().optional().or(z.literal("")),
    pickup_strategy: z.nativeEnum(PickupStrategy).default(PickupStrategy.DEFAULT),

    payment_details: z.object({
      freight_payment_mode: z.nativeEnum(FreightPaymentMode),
      is_cod: z.boolean().default(false),
      cod_amount: z.number().min(0, "COD amount cannot be negative").default(0),
      add_shipping_to_cod: z.boolean().default(false),
      shipment_value: z.number().min(0, "Shipment value cannot be negative"),
      shipment_tax_value: z.number().default(0),
      shipment_total_value: z.number().default(0),
      tax_amount: z.number().default(0),
      base_freight: z.number().default(0),
      total_logistics_cost: z.number().default(0),
      hsn_code: z.string().optional(),
      invoice_numbers: z.array(z.string()).default([]),
      invoice_date: z.string().optional(),
      eway_bill_numbers: z.array(z.string()).default([]),
      // Set from the backend valuation (D-06); never derived in the browser.
      eway_bill_required: z.boolean().default(false),
    }),
    pickup_address_id: z.string().optional(),
    new_pickup_address: addressSchema.optional(),
    delivery_address_id: z.string().optional(),
    new_delivery_address: addressSchema.optional(),
    packages: z.array(packageSchema).min(1, "At least one package is required"),
    documents: z.array(documentSchema).optional(),
    is_blind_pickup: z.boolean().default(false),
    estimated_box_count: z.number().min(1, "Estimated box count must be at least 1").optional().nullable(),
    is_carriers_risk: z.boolean().default(false),
    // Logismart Prime add-on: deliver to the receiver's door instead of the godown.
    door_delivery: z.boolean().default(false),
  })
  .superRefine((data, ctx) => {
    // Rule H: Blind Pickup validation
    if (data.is_blind_pickup && (!data.estimated_box_count || data.estimated_box_count < 1)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Estimated box count is required and must be at least 1 for blind pickups.",
        path: ["estimated_box_count"],
      });
    }
    if (!data.is_blind_pickup) addPackageDimensionIssues(data.packages, ctx);

    // Rule A: E-Way Bill required when the backend valuation says so (D-06)
    if (
      data.payment_details.eway_bill_required &&
      (!data.payment_details.eway_bill_numbers ||
        data.payment_details.eway_bill_numbers.length === 0 ||
        data.payment_details.eway_bill_numbers.every((num) => !num.trim()))
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "At least one E-Way Bill is required for this goods value.",
        path: ["payment_details", "eway_bill_numbers"],
      });
    }

    // Rule B: ProductCategory OTHER requires description
    if (
      data.product_category === ProductCategory.OTHER &&
      (!data.other_category_description || data.other_category_description.trim() === "")
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please specify the custom category description.",
        path: ["other_category_description"],
      });
    }

    // Rule C: No Vehicles in Air Cargo
    if (
      data.service_type === ServiceType.AIR &&
      data.product_category === ProductCategory.VEHICLE
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Vehicles cannot be transported via Air Cargo. Please select a Surface service.",
        path: ["product_category"],
      });
    }

    // Rule D: COD cash collection requirements
    if (data.payment_details.is_cod === true) {
      if (data.payment_details.cod_amount <= 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "COD amount must be greater than 0 when Cash-on-Delivery is enabled.",
          path: ["payment_details", "cod_amount"],
        });
      } else if (data.payment_details.cod_amount > data.payment_details.shipment_total_value) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Collectible amount cannot exceed the total shipment value.",
          path: ["payment_details", "cod_amount"],
        });
      }
    }

    // Rule E: Address selection check for Pickup Location
    if (!data.pickup_address_id && (!data.new_pickup_address || !data.new_pickup_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new pickup location.",
        path: ["pickup_address_id"],
      });
    }

    // Rule F: Address selection check for Delivery Location
    if (!data.delivery_address_id && (!data.new_delivery_address || !data.new_delivery_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new delivery location.",
        path: ["delivery_address_id"],
      });
    }

    // Rule G: Appointment Date Validation
    if (data.appointment_start && data.appointment_end) {
      const start = new Date(data.appointment_start);
      const end = new Date(data.appointment_end);
      if (isNaN(start.getTime())) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Invalid appointment start date/time format.",
          path: ["appointment_start"],
        });
      }
      if (isNaN(end.getTime())) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Invalid appointment end date/time format.",
          path: ["appointment_end"],
        });
      }
      if (start >= end) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Appointment end time must be after the start time.",
          path: ["appointment_end"],
        });
      }
    } else if (data.appointment_start && !data.appointment_end) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Both appointment start and end times must be specified.",
        path: ["appointment_end"],
      });
    } else if (!data.appointment_start && data.appointment_end) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Both appointment start and end times must be specified.",
        path: ["appointment_start"],
      });
    }
  }, { when: hasBookingFormShape });

/**
 * B2B LR booking form (create only): the shared LR rules plus the compliance fields the form
 * marks as required (Delhivery One `b2b-order-creation`: every B2B shipment needs a GST
 * invoice and its value). Kept off the edit schema so legacy LRs stay editable.
 */
export const b2bForwardBookingSchema = b2bForwardShipmentSchema.superRefine((data, ctx) => {
  if (!((data.payment_details.shipment_value ?? 0) > 0)) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Enter the goods (invoice) value.",
      path: ["payment_details", "shipment_value"],
    });
  }
  if (!(data.payment_details.invoice_numbers ?? []).some((num) => num.trim())) {
    ctx.addIssue({
      code: z.ZodIssueCode.custom,
      message: "Add at least one GST invoice number. Every B2B LR needs a GST invoice.",
      path: ["payment_details", "invoice_numbers"],
    });
  }
}, { when: hasBookingFormShape });

// B2B Reverse Shipment Schema
export const b2bReverseShipmentSchema = z
  .object({
    order_reference_id: z.string().optional().or(z.literal("")),
    // Delhivery flow: the booking form has no pickup options. The page sends
    // today's date silently; the real pickup date/slot is chosen on the Pickup Request.
    requested_pickup_date: z.string().optional(),
    pickup_time_slot: z.nativeEnum(PickupTimeSlot).optional(),
    service_type: z.nativeEnum(ServiceType),
    shipment_type: z.literal(ShipmentType.REVERSE),
    reason_for_return: z.string().min(3, "Reason is required for reverse pickups (min 3 chars)"),
    product_category: z.nativeEnum(ProductCategory, {
      message: "Please select a product category",
    }),
    other_category_description: z.string().optional(),
    qc_required: z.boolean().default(false),
    qc_notes: z.string().optional(),
    
    // B2B Metadata
    po_number: z
      .string()
      .max(255, "PO number cannot exceed 255 characters")
      .refine((value) => splitPoNumbers(value).length <= MAX_PO_NUMBERS, {
        message: `Enter up to ${MAX_PO_NUMBERS} PO numbers, separated by commas.`,
      })
      .optional()
      .or(z.literal("")),
    po_date: z.string().optional().or(z.literal("")),
    appointment_id: z.string().max(100, "Appointment ID cannot exceed 100 characters").optional().or(z.literal("")),
    appointment_start: z.string().optional().or(z.literal("")),
    appointment_end: z.string().optional().or(z.literal("")),
    pickup_strategy: z.nativeEnum(PickupStrategy).default(PickupStrategy.DEFAULT),

    payment_details: z.object({
      freight_payment_mode: z.nativeEnum(FreightPaymentMode),
      is_cod: z.boolean().default(false),
      cod_amount: z.number().min(0, "COD amount cannot be negative").default(0),
      add_shipping_to_cod: z.boolean().default(false),
      shipment_value: z.number().min(0, "Shipment value cannot be negative"),
      shipment_tax_value: z.number().default(0),
      shipment_total_value: z.number().default(0),
      tax_amount: z.number().default(0),
      base_freight: z.number().default(0),
      total_logistics_cost: z.number().default(0),
    }),
    pickup_address_id: z.string().optional(),
    new_pickup_address: addressSchema.optional(),
    delivery_address_id: z.string().optional(),
    new_delivery_address: addressSchema.optional(),
    packages: z.array(packageSchema).min(1, "At least one package is required"),
    documents: z.array(documentSchema).optional(),
  })
  .superRefine((data, ctx) => {
    // Rule B: ProductCategory OTHER requires description
    if (
      data.product_category === ProductCategory.OTHER &&
      (!data.other_category_description || data.other_category_description.trim() === "")
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please specify the custom category description.",
        path: ["other_category_description"],
      });
    }

    // Rule C: No Vehicles in Air Cargo
    if (
      data.service_type === ServiceType.AIR &&
      data.product_category === ProductCategory.VEHICLE
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Vehicles cannot be transported via Air Cargo. Please select a Surface service.",
        path: ["product_category"],
      });
    }

    // Rule D: COD cash collection requirements
    if (data.payment_details.is_cod === true) {
      if (data.payment_details.cod_amount <= 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "COD amount must be greater than 0 when Cash-on-Delivery is enabled.",
          path: ["payment_details", "cod_amount"],
        });
      } else if (data.payment_details.cod_amount > data.payment_details.shipment_total_value) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Collectible amount cannot exceed the total shipment value.",
          path: ["payment_details", "cod_amount"],
        });
      }
    }

    // Rule E: Address selection check for Pickup Location
    if (!data.pickup_address_id && (!data.new_pickup_address || !data.new_pickup_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new pickup location.",
        path: ["pickup_address_id"],
      });
    }

    // Rule F: Address selection check for Delivery Location
    if (!data.delivery_address_id && (!data.new_delivery_address || !data.new_delivery_address.name)) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Please select a saved address or add a new delivery location.",
        path: ["delivery_address_id"],
      });
    }

    // Rule G: Appointment Date Validation
    if (data.appointment_start && data.appointment_end) {
      const start = new Date(data.appointment_start);
      const end = new Date(data.appointment_end);
      if (isNaN(start.getTime())) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Invalid appointment start date/time format.",
          path: ["appointment_start"],
        });
      }
      if (isNaN(end.getTime())) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Invalid appointment end date/time format.",
          path: ["appointment_end"],
        });
      }
      if (start >= end) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Appointment end time must be after the start time.",
          path: ["appointment_end"],
        });
      }
    } else if (data.appointment_start && !data.appointment_end) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Both appointment start and end times must be specified.",
        path: ["appointment_end"],
      });
    } else if (!data.appointment_start && data.appointment_end) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Both appointment start and end times must be specified.",
        path: ["appointment_start"],
      });
    }
  });

export const b2bShipmentFormSchema = z.discriminatedUnion("shipment_type", [
  b2bForwardShipmentSchema,
  b2bReverseShipmentSchema,
]);

export type B2BForwardShipmentFormValues = z.infer<typeof b2bForwardShipmentSchema>;
export type B2BReverseShipmentFormValues = z.infer<typeof b2bReverseShipmentSchema>;
export type B2BShipmentFormValues = Omit<B2BForwardShipmentFormValues, "shipment_type"> & {
  shipment_type: ShipmentType;
  reason_for_return?: string;
  qc_required?: boolean;
  qc_notes?: string;
};
