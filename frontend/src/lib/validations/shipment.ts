// src/lib/validations/shipment.ts
import * as z from "zod";

const addressSchema = z.object({
  name: z.string().min(2, "Name must be at least 2 characters"),
  phone: z.string().min(10, "Phone number must be at least 10 digits"),
  address_line1: z.string().min(5, "Please enter a complete address"),
  city: z.string().min(2, "City is required"),
  state: z.string().min(2, "State is required"),
  pincode: z.string().min(6, "Valid Pincode required"),
});

const packageSchema = z.object({
  // Strictly require a number, without the confusing config object!
  length: z.number().min(0.1, "Length must be > 0"),
  breadth: z.number().min(0.1, "Breadth must be > 0"),
  height: z.number().min(0.1, "Height must be > 0"),
  weight: z.number().min(0.1, "Weight must be > 0"),
  description: z.string().optional(),
});

export const shipmentFormSchema = z.object({
  order_reference_id: z.string().min(3, "Order Reference is required"),
  requested_pickup_date: z.string().min(1, "Please select a pickup date"),
  
  new_pickup_address: addressSchema,
  new_delivery_address: addressSchema,
  
  packages: z.array(packageSchema).min(1, "At least one package is required"),
});

export type ShipmentFormValues = z.infer<typeof shipmentFormSchema>;