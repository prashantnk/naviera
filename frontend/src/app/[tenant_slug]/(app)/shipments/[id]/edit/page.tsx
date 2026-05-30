/* eslint-disable @typescript-eslint/no-explicit-any */
// frontend/src/app/[tenant_slug]/(app)/shipments/[id]/edit/page.tsx
"use client";

import { PaymentMode, ShipmentsService, ShipmentType } from "@/api_client";
import { PackageFieldset } from "@/components/forms/package-fieldset";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

// 1. The Expanded Edit Schema
const editShipmentSchema = z.object({
  order_reference_id: z.string().optional().or(z.literal("")),
  requested_pickup_date: z.string().min(1, "Pickup date is required"),

  // Cargo & Value
  product_category: z.string().optional(),
  shipment_description: z.string().optional(),
  reason_for_return: z.string().optional(),
  payment_details: z
    .object({
      amount: z.number().min(0).optional(), // 🔥 Added Amount override
      declared_value: z.number().min(0, "Value cannot be negative"),
      tax_amount: z.number().default(0),
      payment_mode: z.nativeEnum(PaymentMode).optional(),
      hsn_code: z.string().optional(),
      invoice_number: z.string().optional(),
      invoice_date: z.string().optional(), // 🔥 Added Invoice Date
      eway_bill_number: z.string().optional(),
    })
    .optional(),

  // Packages
  packages: z
    .array(
      z.object({
        id: z.string().optional(),
        length: z.number().min(0).default(0),
        breadth: z.number().min(0).default(0),
        height: z.number().min(0).default(0),
        weight: z.number().min(0.1, "Weight is required"),
        box_count: z.number().min(1).default(1),
        is_fragile: z.boolean().default(false),
        description: z.string().optional(),
      })
    )
    .min(1, "At least one package is required"),

  comment: z
    .string()
    .min(5, "You must provide a reason for editing this shipment."),
});

type EditShipmentValues = z.infer<typeof editShipmentSchema>;

export default function EditShipmentPage() {
  const params = useParams();
  const router = useRouter();
  const shipmentId = params.id as string;
  const { routeTo } = useTenant();

  const [loading, setLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [shipmentType, setShipmentType] = useState<ShipmentType | null>(null);

  const form = useForm<EditShipmentValues>({
    resolver: zodResolver(editShipmentSchema) as any,
    defaultValues: {
      order_reference_id: "",
      requested_pickup_date: "",
      product_category: "",
      shipment_description: "",
      reason_for_return: "",
      payment_details: {
        declared_value: 0,
        tax_amount: 0,
        invoice_number: "",
        eway_bill_number: "",
      },
      packages: [],
      comment: "",
    },
  });

  useEffect(() => {
    const fetchShipment = async () => {
      try {
        const data = await ShipmentsService.getShipmentDetails(shipmentId);
        setShipmentType(data.shipment_type);

        form.reset({
          order_reference_id: data.order_reference_id || "",
          requested_pickup_date: data.requested_pickup_date,
          product_category: data.product_category || "",
          shipment_description: data.shipment_description || "",
          reason_for_return: data.reason_for_return || "",
          payment_details: data.payment_details
            ? {
                amount: data.payment_details.amount, // 🔥 Load Amount
                declared_value: data.payment_details.declared_value,
                tax_amount: data.payment_details.tax_amount,
                payment_mode: data.payment_details.payment_mode,
                hsn_code: data.payment_details.hsn_code || "",
                invoice_number: data.payment_details.invoice_number || "",
                invoice_date: data.payment_details.invoice_date || "", // 🔥 Load Date
                eway_bill_number: data.payment_details.eway_bill_number || "",
              }
            : {
                amount: 0,
                declared_value: 0,
                tax_amount: 0,
                payment_mode: PaymentMode.PREPAID,
                invoice_number: "",
                invoice_date: "",
                eway_bill_number: "",
                hsn_code: "",
              },
          packages: data.packages.map((p) => ({
            id: p.id,
            length: p.length,
            breadth: p.breadth,
            height: p.height,
            weight: p.weight,
            box_count: p.box_count,
            is_fragile: p.is_fragile,
            description: p.description || "",
          })),
          comment: "",
        });
      } catch (error) {
        toast.error("Failed to load shipment details.");
      } finally {
        setLoading(false);
      }
    };
    fetchShipment();
  }, [shipmentId, form]);

  const onSubmit = async (data: EditShipmentValues) => {
    setIsSubmitting(true);
    try {
      // 🔥 FIX 1: Sanitize empty strings to undefined so FastAPI doesn't reject them
      const sanitizedPaymentDetails = data.payment_details
        ? {
            ...data.payment_details,
            hsn_code: data.payment_details.hsn_code || undefined,
            invoice_number: data.payment_details.invoice_number || undefined,
            invoice_date: data.payment_details.invoice_date || undefined,
            eway_bill_number:
              data.payment_details.eway_bill_number || undefined,
          }
        : undefined;

      await ShipmentsService.updateShipment(shipmentId, {
        order_reference_id: data.order_reference_id,
        requested_pickup_date: data.requested_pickup_date,
        product_category: data.product_category || undefined,
        shipment_description: data.shipment_description || undefined,
        reason_for_return: data.reason_for_return || undefined,
        payment_details: sanitizedPaymentDetails as any,
        packages: data.packages,
        comment: data.comment,
        is_public: false, // Internal Edit Log
      });

      toast.success("Shipment updated successfully!");
      router.push(routeTo(`/shipments/${shipmentId}`));
    } catch (error: any) {
      // 🔥 FIX 2: Safely parse FastAPI 422 Error Arrays into a readable string!
      let msg = "Failed to update shipment.";
      if (error.body?.detail) {
        if (Array.isArray(error.body.detail)) {
          msg = error.body.detail
            .map((err: any) => `${err.loc.at(-1)}: ${err.msg}`)
            .join(" | ");
        } else if (typeof error.body.detail === "string") {
          msg = error.body.detail;
        }
      }
      toast.error(msg);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  const isReverse = shipmentType === ShipmentType.REVERSE;
  const watchValue = form.watch("payment_details.declared_value") || 0;

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-12 animate-in fade-in">
      <div className="flex items-center gap-4 border-b border-slate-200 pb-4">
        <Button variant="outline" size="icon" asChild className="h-9 w-9">
          <Link href={routeTo(`/shipments/${shipmentId}`)}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Edit Shipment
          </h1>
          <p className="text-slate-500 text-sm mt-1">
            Update details for {shipmentId}
          </p>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-slate-50 p-6 rounded-xl border border-slate-100">
              <FormField
                control={form.control}
                name="order_reference_id"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Order Reference ID</FormLabel>
                    <FormControl>
                      <Input {...field} className="bg-white" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="requested_pickup_date"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Requested Pickup Date</FormLabel>
                    <FormControl>
                      <Input type="date" {...field} className="bg-white" />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              {isReverse && (
                <FormField
                  control={form.control}
                  name="reason_for_return"
                  render={({ field }) => (
                    <FormItem className="md:col-span-2">
                      <FormLabel>Reason for Return</FormLabel>
                      <FormControl>
                        <Textarea {...field} className="bg-white" />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <FormField
                control={form.control}
                name="product_category"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Product Category</FormLabel>
                    <FormControl>
                      <Input {...field} value={field.value || ""} />
                    </FormControl>
                  </FormItem>
                )}
              />
              <FormField
                control={form.control}
                name="shipment_description"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Description of Goods</FormLabel>
                    <FormControl>
                      <Input {...field} value={field.value || ""} />
                    </FormControl>
                  </FormItem>
                )}
              />
            </div>

            <div className="bg-slate-50 p-6 rounded-xl border border-slate-100 space-y-6">
              <h3 className="font-semibold text-slate-900 border-b pb-2">
                Financials & Taxation
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                {/* 🔥 NEW: Amount Override for Admins */}
                <FormField
                  control={form.control}
                  name="payment_details.amount"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Shipping Charge (₹)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          {...field}
                          onChange={(e) =>
                            field.onChange(e.target.valueAsNumber || 0)
                          }
                          className="bg-white font-bold text-primary"
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="payment_details.declared_value"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        {isReverse ? "Package Value" : "Total Item Value"} (₹)
                      </FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          {...field}
                          onChange={(e) =>
                            field.onChange(e.target.valueAsNumber || 0)
                          }
                          className="bg-white"
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="payment_details.hsn_code"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>HSN Code (Optional)</FormLabel>
                      <FormControl>
                        <Input
                          {...field}
                          value={field.value || ""}
                          className="bg-white"
                        />
                      </FormControl>
                    </FormItem>
                  )}
                />

                {!isReverse && (
                  <>
                    <FormField
                      control={form.control}
                      name="payment_details.tax_amount"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Tax Applied (₹)</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              {...field}
                              onChange={(e) =>
                                field.onChange(e.target.valueAsNumber || 0)
                              }
                              className="bg-white"
                            />
                          </FormControl>
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="payment_details.payment_mode"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Payment Mode</FormLabel>
                          <Select
                            onValueChange={field.onChange}
                            value={field.value}
                          >
                            <FormControl>
                              <SelectTrigger className="bg-white">
                                <SelectValue />
                              </SelectTrigger>
                            </FormControl>
                            <SelectContent>
                              <SelectItem value={PaymentMode.PREPAID}>
                                Prepaid
                              </SelectItem>
                              <SelectItem value={PaymentMode.COD}>
                                Cash on Delivery (COD)
                              </SelectItem>
                            </SelectContent>
                          </Select>
                        </FormItem>
                      )}
                    />
                  </>
                )}
              </div>
              {!isReverse && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <FormField
                    control={form.control}
                    name="payment_details.invoice_number"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Invoice Number</FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            value={field.value || ""}
                            className="bg-white"
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="payment_details.invoice_date"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Invoice Date</FormLabel>
                        <FormControl>
                          <Input
                            type="date"
                            {...field}
                            value={field.value || ""}
                            className="bg-white"
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="payment_details.eway_bill_number"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel
                          className={
                            watchValue > 50000 ? "text-red-600 font-bold" : ""
                          }
                        >
                          E-Way Bill Number {watchValue > 50000 && "*"}
                        </FormLabel>
                        <FormControl>
                          <Input
                            {...field}
                            value={field.value || ""}
                            className="bg-white"
                          />
                        </FormControl>
                        {watchValue > 50000 && (
                          <FormDescription className="text-red-500 text-[10px]">
                            Legally required for this cargo value.
                          </FormDescription>
                        )}
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              )}
            </div>

            <div>
              <h3 className="text-lg font-semibold text-slate-900 mb-4">
                Package Dimensions
              </h3>
              <PackageFieldset control={form.control} isReverse={isReverse} />
            </div>

            <div className="border-t border-slate-200 pt-6">
              <FormField
                control={form.control}
                name="comment"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>
                      Reason for Edit (Audit Log){" "}
                      <span className="text-red-500">*</span>
                    </FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="e.g. Corrected actual weight after warehouse scan."
                        className="resize-none"
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="flex justify-end pt-4">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving...
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" /> Save Changes
                  </>
                )}
              </Button>
            </div>
          </form>
        </Form>
      </div>
    </div>
  );
}
