// frontend/src/lib/validations/shipment.ts
import {
  DocumentType,
  FreightPaymentMode,
  PickupTimeSlot,
  ProductCategory,
  ServiceType,
  ShipmentType,
} from "@/api_client";
import * as z from "zod";

const addressSchema = z.object({
  name: z.string().min(2, "Name is required").optional().or(z.literal("")),
  phone: z
    .string()
    .min(10, "Phone number must be at least 10 digits")
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
    .min(6, "Valid Pincode required")
    .optional()
    .or(z.literal("")),
});

const packageSchema = z.object({
  length: z.number().min(0, "Cannot be negative").default(0),
  breadth: z.number().min(0, "Cannot be negative").default(0),
  height: z.number().min(0, "Cannot be negative").default(0),
  weight: z.number().min(0.1, "Weight is required"),
  box_count: z.number().min(1).default(1),
  is_fragile: z.boolean().default(false),
  description: z.string().optional(),
});

const documentSchema = z.object({
  document_type: z.nativeEnum(DocumentType),
  file_url: z.string(),
  file_name: z.string(),
});

export const shipmentFormSchema = z
  .object({
    order_reference_id: z.string().optional().or(z.literal("")),
    requested_pickup_date: z.string().min(1, "Please select a pickup date"),
    pickup_time_slot: z.nativeEnum(PickupTimeSlot, {
      message: "Please select a pickup time slot",
    }),

    // We keep nativeEnum, but we will strictly control the default values in the page.tsx file
    service_type: z.nativeEnum(ServiceType),
    shipment_type: z.nativeEnum(ShipmentType),
    reason_for_return: z.string().optional(),

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
    }),

    pickup_address_id: z.string().optional(),
    new_pickup_address: addressSchema.optional(),
    delivery_address_id: z.string().optional(),
    new_delivery_address: addressSchema.optional(),

    packages: z.array(packageSchema).min(1, "At least one package is required"),
    documents: z.array(documentSchema).optional(),
  })
  .superRefine((data, ctx) => {
    // Reverse shipments need a reason
    if (
      data.shipment_type === ShipmentType.REVERSE &&
      (!data.reason_for_return || data.reason_for_return.length < 3)
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Reason is required for reverse pickups",
        path: ["reason_for_return"],
      });
    }
    // E-Way Bill is only mandatory for FORWARD shipments > 50k
    if (
      data.shipment_type === ShipmentType.FORWARD &&
      data.payment_details.shipment_total_value > 50000 &&
      !data.payment_details.eway_bill_number
    ) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "E-Way Bill is mandatory for values over ₹50,000",
        path: ["payment_details", "eway_bill_number"],
      });
    }

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

    // Rule B: No Vehicles in Air Cargo speed
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
    if (data.payment_details.is_cod === true && data.payment_details.cod_amount <= 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "COD amount must be greater than 0 when Cash-on-Delivery is enabled.",
        path: ["payment_details", "cod_amount"],
      });
    }
  });

export type ShipmentFormValues = z.infer<typeof shipmentFormSchema>;
