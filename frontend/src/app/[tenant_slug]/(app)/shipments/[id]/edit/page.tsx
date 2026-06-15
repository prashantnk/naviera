// frontend/src/app/[tenant_slug]/(app)/shipments/[id]/edit/page.tsx
"use client";

import {
  AddressesService,
  AddressCreate,
  AddressRead,
  AddressScope,
  ApiError,
  FreightPaymentMode,
  ProductCategory,
  PickupUpdate,
  ServiceType,
  ShipmentsService,
  ShipmentType,
  DimensionUnit,
  WeightUnit,
  RateCalculationResponse,
  PackageCreate,
} from "@/api_client";
import { CATEGORY_LABELS } from "../../new/page";
import { PackageFieldset } from "@/components/forms/package-fieldset";
import { EWayBillBanner } from "@/components/forms/eway-bill-banner";
import { AddressFieldset } from "@/components/forms/address-fieldset";
import { addressSchema, ShipmentFormValues } from "@/lib/validations/shipment";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
import { DatePicker } from "@/components/ui/date-picker";
import { format, parseISO } from "date-fns";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Info, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Control, Resolver, useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

// 1. The Expanded Edit Schema
const editShipmentSchema = z.object({
  order_reference_id: z.string().optional().or(z.literal("")),
  requested_pickup_date: z.string().min(1, "Pickup date is required"),

  // Cargo & Value
  product_category: z.nativeEnum(ProductCategory, {
    message: "Please select a product category",
  }),
  other_category_description: z.string().optional(),
  service_type: z.nativeEnum(ServiceType).optional(),

  reason_for_return: z.string().optional(),
  payment_details: z
    .object({
      freight_payment_mode: z.nativeEnum(FreightPaymentMode).optional(),
      is_cod: z.boolean().optional(),
      cod_amount: z.number().min(0).optional(),
      base_freight: z.number().min(0).optional(),
      tax_amount: z.number().default(0),
      total_logistics_cost: z.number().min(0).optional(),
      shipment_value: z.number().min(0, "Value cannot be negative"),
      shipment_tax_value: z.number().default(0),
      shipment_total_value: z.number().default(0),
      add_shipping_to_cod: z.boolean().default(false),
      hsn_code: z.string().optional(),
      invoice_number: z.string().optional(),
      invoice_date: z.string().optional(), // 🔥 Added Invoice Date
      eway_bill_number: z.string().optional(),
      pricing_breakdown: z.any().optional(),
    })
    .optional(),

  // Addresses
  pickup_address_id: z.string().optional(),
  new_pickup_address: addressSchema.optional(),
  delivery_address_id: z.string().optional(),
  new_delivery_address: addressSchema.optional(),

  // Packages
  packages: z
    .array(
      z.object({
        id: z.string().optional(),
        length: z.number().min(0).default(0),
        breadth: z.number().min(0).default(0),
        height: z.number().min(0).default(0),
        dimension_unit: z.nativeEnum(DimensionUnit).default(DimensionUnit.CM),
        weight: z.number().min(0.1, "Weight is required"),
        weight_unit: z.nativeEnum(WeightUnit).default(WeightUnit.KG),
        box_count: z.number().min(1).default(1),
        is_fragile: z.boolean().default(false),
        description: z.string().optional(),
      })
    )
    .min(1, "At least one package is required"),

  comment: z
    .string()
    .min(5, "You must provide a reason for editing this shipment."),
}).superRefine((data, ctx) => {
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
});

type EditShipmentValues = z.infer<typeof editShipmentSchema>;

export default function EditShipmentPage() {
  const params = useParams();
  const router = useRouter();
  const shipmentId = params.id as string;
  const { routeTo, tenant } = useTenant();

  const [loading, setLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [shipmentType, setShipmentType] = useState<ShipmentType | null>(null);
  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>([]);

  // Pricing Change States
  const [originalPricing, setOriginalPricing] = useState<{
    pickup_pincode: string;
    delivery_pincode: string;
    service_type: ServiceType;
    packages: {
      length: number;
      breadth: number;
      height: number;
      weight: number;
      box_count: number;
      dimension_unit: DimensionUnit;
      weight_unit: WeightUnit;
    }[];
    total_cost: number;
  } | null>(null);

  const [newPriceQuote, setNewPriceQuote] = useState<RateCalculationResponse | null>(null);
  const [isRecalculating, setIsRecalculating] = useState(false);
  const [showPriceChangeDialog, setShowPriceChangeDialog] = useState(false);
  const [pendingFormValues, setPendingFormValues] = useState<EditShipmentValues | null>(null);

  useEffect(() => {
    AddressesService.listSavedAddresses()
      .then(setSavedAddresses)
      .catch(console.error);
  }, []);

  const form = useForm<EditShipmentValues>({
    resolver: zodResolver(editShipmentSchema) as unknown as Resolver<EditShipmentValues>,
    defaultValues: {
      order_reference_id: "",
      requested_pickup_date: "",
      product_category: undefined as unknown as ProductCategory,
      other_category_description: "",
      service_type: undefined,

      reason_for_return: "",
      payment_details: {
        shipment_value: 0,
        shipment_tax_value: 0,
        shipment_total_value: 0,
        add_shipping_to_cod: false,
        tax_amount: 0,
        invoice_number: "",
        eway_bill_number: "",
      },
      packages: [],
      comment: "",
      pickup_address_id: "",
      new_pickup_address: undefined,
      delivery_address_id: "",
      new_delivery_address: undefined,
    },
  });

  const watchedShipmentValue = form.watch("payment_details.shipment_value");
  const watchedShipmentTaxValue = form.watch("payment_details.shipment_tax_value");
  const watchedShipmentTotalValue = form.watch("payment_details.shipment_total_value");
  const watchedFreightMode = form.watch("payment_details.freight_payment_mode");
  const watchedIsCod = form.watch("payment_details.is_cod");

  useEffect(() => {
    const base = watchedShipmentValue || 0;
    const tax = watchedShipmentTaxValue || 0;
    if (base > 0 || tax > 0) {
      form.setValue("payment_details.shipment_total_value", base + tax, { shouldValidate: true });
    }
  }, [watchedShipmentValue, watchedShipmentTaxValue, form]);

  useEffect(() => {
    const fetchShipment = async () => {
      try {
        const data = await ShipmentsService.getShipmentDetails(shipmentId);
        setShipmentType(data.shipment_type);

        setOriginalPricing({
          pickup_pincode: data.pickup_address.pincode,
          delivery_pincode: data.delivery_address.pincode,
          service_type: data.service_type || ServiceType.SURFACE_ROAD,
          packages: data.packages.map((p) => ({
            length: p.length || 0,
            breadth: p.breadth || 0,
            height: p.height || 0,
            weight: p.weight,
            box_count: p.box_count || 1,
            dimension_unit: p.dimension_unit as DimensionUnit,
            weight_unit: p.weight_unit as WeightUnit,
          })),
          total_cost: data.payment_details?.total_logistics_cost || 0,
        });

        form.reset({
          order_reference_id: data.order_reference_id || "",
          requested_pickup_date: data.requested_pickup_date,
          product_category: data.product_category,
          other_category_description: data.other_category_description || "",
          service_type: data.service_type,

          reason_for_return: data.reason_for_return || "",
          payment_details: data.payment_details
            ? {
                freight_payment_mode: data.payment_details.freight_payment_mode,
                is_cod: data.payment_details.is_cod,
                cod_amount: data.payment_details.cod_amount,
                base_freight: data.payment_details.base_freight,
                tax_amount: data.payment_details.tax_amount,
                total_logistics_cost: data.payment_details.total_logistics_cost,
                shipment_value: data.payment_details.shipment_value || 0,
                shipment_tax_value: data.payment_details.shipment_tax_value || 0,
                shipment_total_value: data.payment_details.shipment_total_value || 0,
                add_shipping_to_cod: data.payment_details.add_shipping_to_cod || false,
                hsn_code: data.payment_details.hsn_code || "",
                invoice_number: data.payment_details.invoice_number || "",
                invoice_date: data.payment_details.invoice_date || "",
                eway_bill_number: data.payment_details.eway_bill_number || "",
              }
            : {
                freight_payment_mode: FreightPaymentMode.PREPAID,
                is_cod: false,
                cod_amount: 0,
                base_freight: 0,
                tax_amount: 0,
                total_logistics_cost: 0,
                shipment_value: 0,
                shipment_tax_value: 0,
                shipment_total_value: 0,
                add_shipping_to_cod: false,
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
          pickup_address_id: data.pickup_address?.is_saved ? data.pickup_address.id : "",
          new_pickup_address: data.pickup_address && !data.pickup_address.is_saved
            ? {
                name: data.pickup_address.name,
                company_name: data.pickup_address.company_name || "",
                phone: data.pickup_address.phone,
                alternate_phone: data.pickup_address.alternate_phone || "",
                email: data.pickup_address.email || "",
                address_line1: data.pickup_address.address_line1,
                address_line2: data.pickup_address.address_line2 || "",
                landmark: data.pickup_address.landmark || "",
                city: data.pickup_address.city,
                state: data.pickup_address.state,
                pincode: data.pickup_address.pincode,
                category: data.pickup_address.category,
                gstin: data.pickup_address.gstin || "",
                save_to_address_book: false,
                is_shared_with_team: false,
              }
            : undefined,
          delivery_address_id: data.delivery_address?.is_saved ? data.delivery_address.id : "",
          new_delivery_address: data.delivery_address && !data.delivery_address.is_saved
            ? {
                name: data.delivery_address.name,
                company_name: data.delivery_address.company_name || "",
                phone: data.delivery_address.phone,
                alternate_phone: data.delivery_address.alternate_phone || "",
                email: data.delivery_address.email || "",
                address_line1: data.delivery_address.address_line1,
                address_line2: data.delivery_address.address_line2 || "",
                landmark: data.delivery_address.landmark || "",
                city: data.delivery_address.city,
                state: data.delivery_address.state,
                pincode: data.delivery_address.pincode,
                category: data.delivery_address.category,
                gstin: data.delivery_address.gstin || "",
                save_to_address_book: false,
                is_shared_with_team: false,
              }
            : undefined,
        });
      } catch {
        toast.error("Failed to load shipment details.");
      } finally {
        setLoading(false);
      }
    };
    fetchShipment();
  }, [shipmentId, form]);

  const hasPricingParametersChanged = (values: EditShipmentValues) => {
    if (!originalPricing) return false;

    const pPincode =
      values.new_pickup_address?.pincode ||
      savedAddresses.find((a) => a.id === values.pickup_address_id)?.pincode ||
      originalPricing.pickup_pincode;

    const dPincode =
      values.new_delivery_address?.pincode ||
      savedAddresses.find((a) => a.id === values.delivery_address_id)?.pincode ||
      originalPricing.delivery_pincode;

    if (pPincode !== originalPricing.pickup_pincode) return true;
    if (dPincode !== originalPricing.delivery_pincode) return true;
    if (values.service_type !== originalPricing.service_type) return true;

    if (values.packages.length !== originalPricing.packages.length) return true;

    for (let i = 0; i < values.packages.length; i++) {
      const p1 = values.packages[i];
      const p2 = originalPricing.packages[i];
      if (!p2) return true;
      if (
        p1.length !== p2.length ||
        p1.breadth !== p2.breadth ||
        p1.height !== p2.height ||
        p1.weight !== p2.weight ||
        p1.box_count !== p2.box_count ||
        p1.dimension_unit !== p2.dimension_unit ||
        p1.weight_unit !== p2.weight_unit
      ) {
        return true;
      }
    }

    return false;
  };

  const handleApproveAndSave = async () => {
    if (!pendingFormValues || !newPriceQuote) return;
    setShowPriceChangeDialog(false);
    await onSubmit(pendingFormValues);
  };

  const handleCloseDialog = () => {
    setShowPriceChangeDialog(false);
    setNewPriceQuote(null);
    setPendingFormValues(null);
  };

  const onSubmit = async (data: EditShipmentValues) => {
    // Check if any pricing parameters have changed and if we haven't fetched a fresh quote yet
    if (hasPricingParametersChanged(data) && !newPriceQuote) {
      setIsRecalculating(true);
      setPendingFormValues(data);
      setShowPriceChangeDialog(true);
      try {
        const pPincode =
          data.new_pickup_address?.pincode ||
          savedAddresses.find((a) => a.id === data.pickup_address_id)?.pincode ||
          originalPricing?.pickup_pincode;

        const dPincode =
          data.new_delivery_address?.pincode ||
          savedAddresses.find((a) => a.id === data.delivery_address_id)?.pincode ||
          originalPricing?.delivery_pincode;

        if (!pPincode || !dPincode) {
          throw new Error("Cannot calculate rate: Missing pickup or delivery pincode.");
        }

        const quote = await ShipmentsService.calculateShippingRate({
          pickup_pincode: pPincode,
          delivery_pincode: dPincode,
          packages: data.packages as PackageCreate[],
          service_type: data.service_type || ServiceType.SURFACE_ROAD,
        });
        setNewPriceQuote(quote);
      } catch (err) {
        console.error(err);
        toast.error("Failed to recalculate shipping rates for changes. Please check inputs.");
        setShowPriceChangeDialog(false);
      } finally {
        setIsRecalculating(false);
      }
      return; // Halt standard submit
    }

    setIsSubmitting(true);
    try {
      // If a new quote was verified and approved, inject the updated values
      let finalPaymentDetails = data.payment_details;
      if (newPriceQuote) {
        finalPaymentDetails = {
          ...data.payment_details,
          base_freight: newPriceQuote.base_charge,
          tax_amount: newPriceQuote.tax_amount,
          total_logistics_cost: newPriceQuote.total_amount,
          pricing_breakdown: newPriceQuote.pricing_breakdown || {},
          shipment_total_value: data.payment_details?.shipment_total_value ?? 0,
          shipment_value: data.payment_details?.shipment_value ?? 0,
          shipment_tax_value: data.payment_details?.shipment_tax_value ?? 0,
          eway_bill_number: data.payment_details?.eway_bill_number ?? undefined,
          invoice_number: data.payment_details?.invoice_number ?? undefined,
          invoice_date: data.payment_details?.invoice_date ?? undefined,
          hsn_code: data.payment_details?.hsn_code ?? undefined,
          add_shipping_to_cod: data.payment_details?.add_shipping_to_cod ?? false,
        };
      }

      // 🔥 FIX 1: Sanitize empty strings to undefined so FastAPI doesn't reject them
      const sanitizedPaymentDetails = finalPaymentDetails
        ? {
            ...finalPaymentDetails,
            add_shipping_to_cod: finalPaymentDetails.freight_payment_mode === FreightPaymentMode.TO_PAY ? true : (finalPaymentDetails.add_shipping_to_cod || false),
            hsn_code: finalPaymentDetails.hsn_code || undefined,
            invoice_number: finalPaymentDetails.invoice_number || undefined,
            invoice_date: finalPaymentDetails.invoice_date || undefined,
            eway_bill_number:
              finalPaymentDetails.eway_bill_number || undefined,
          }
        : undefined;

      const payload: PickupUpdate = {
        order_reference_id: data.order_reference_id,
        requested_pickup_date: data.requested_pickup_date,
        product_category: data.product_category,
        other_category_description: data.other_category_description || undefined,

        reason_for_return: data.reason_for_return || undefined,
        pickup_address_id: data.pickup_address_id || undefined,
        new_pickup_address: data.pickup_address_id
          ? undefined
          : data.new_pickup_address
          ? ({
              ...data.new_pickup_address,
              is_saved: data.new_pickup_address.save_to_address_book,
              scope: data.new_pickup_address.is_shared_with_team
                ? AddressScope.TENANT
                : AddressScope.PRIVATE,
            } as unknown as AddressCreate)
          : undefined,
        delivery_address_id: data.delivery_address_id || undefined,
        new_delivery_address: data.delivery_address_id
          ? undefined
          : data.new_delivery_address
          ? ({
              ...data.new_delivery_address,
              is_saved: data.new_delivery_address.save_to_address_book,
              scope: data.new_delivery_address.is_shared_with_team
                ? AddressScope.TENANT
                : AddressScope.PRIVATE,
            } as unknown as AddressCreate)
          : undefined,
        payment_details: sanitizedPaymentDetails,
        packages: data.packages.map((p) => ({
          ...p,
          id: p.id || null,
        })),
        comment: data.comment,
        is_public: false, // Internal Edit Log
      };

      await ShipmentsService.updateShipment(shipmentId, payload);

      toast.success("Shipment updated successfully!");
      // Reset pricing validation states
      setNewPriceQuote(null);
      setPendingFormValues(null);
      router.push(routeTo(`/shipments/${shipmentId}`));
    } catch (error) {
      const apiError = error as ApiError;
      // 🔥 FIX 2: Safely parse FastAPI 422 Error Arrays into a readable string!
      let msg = "Failed to update shipment.";
      if (apiError.body?.detail) {
        if (Array.isArray(apiError.body.detail)) {
          msg = apiError.body.detail
            .map((err: { loc: string[]; msg: string }) => `${err.loc.at(-1)}: ${err.msg}`)
            .join(" | ");
        } else if (typeof apiError.body.detail === "string") {
          msg = apiError.body.detail;
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
  const productCategoryValue = form.watch("product_category");

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
                      <DatePicker 
                        date={field.value ? parseISO(field.value) : undefined}
                        setDate={(date) => field.onChange(date ? format(date, "yyyy-MM-dd") : "")}
                      />
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

            <div className="space-y-6 border-t border-slate-200 pt-6">
              <h3 className="text-lg font-semibold text-slate-900">Addresses</h3>
              <AddressFieldset
                control={form.control as unknown as Control<ShipmentFormValues>}
                type="pickup"
                title="Sender Details (Pickup Location)"
                savedAddresses={savedAddresses}
              />
              <AddressFieldset
                control={form.control as unknown as Control<ShipmentFormValues>}
                type="delivery"
                title="Receiver Details (Delivery Location)"
                savedAddresses={savedAddresses}
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <FormField
                control={form.control}
                name="product_category"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Product Category <span className="text-red-500">*</span></FormLabel>
                    <Select
                      onValueChange={field.onChange}
                      value={field.value}
                    >
                      <FormControl>
                        <SelectTrigger className="bg-white">
                          <SelectValue placeholder="Select a category..." />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {Object.values(ProductCategory).map((cat) => (
                          <SelectItem key={cat} value={cat}>
                            {CATEGORY_LABELS[cat]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
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
                      <Input placeholder="e.g. 8517" {...field} value={field.value || ""} />
                    </FormControl>
                    <FormDescription className="text-[10px] text-slate-400">
                      Harmonized System Nomenclature for customs & tax rates.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {productCategoryValue === ProductCategory.OTHER && (
                <FormField
                  control={form.control}
                  name="other_category_description"
                  render={({ field }) => (
                    <FormItem className="md:col-span-2">
                      <FormLabel>Custom Category Description <span className="text-red-500">*</span></FormLabel>
                      <FormControl>
                        <Input
                          placeholder="e.g. Vintage Grandfather Clock"
                          {...field}
                          value={field.value || ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </div>

            <div className="bg-slate-50 p-6 rounded-xl border border-slate-100 space-y-6">
              <h3 className="font-semibold text-slate-900 border-b pb-2">
                Financials & Taxation
              </h3>
              
              {/* Core Financials Grid */}
              <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                <FormField
                  control={form.control}
                  name="payment_details.total_logistics_cost"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Shipping Charge (₹)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          value={field.value || 0}
                          onChange={(e) => {
                            const val = e.target.value;
                            field.onChange(val === "" ? "" : Number(val));
                          }}
                          className="bg-white font-bold text-primary"
                        />
                      </FormControl>
                      <FormDescription className="text-[10px] text-slate-400">
                        Final logistics/freight price.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="payment_details.shipment_value"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Shipment Value (₹)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={0}
                          {...field}
                          onChange={(e) => {
                            const val = e.target.value;
                            field.onChange(val === "" ? "" : Number(val));
                          }}
                          className="bg-white"
                        />
                      </FormControl>
                      <FormDescription className="text-[10px] text-slate-400">
                        Base net commercial cost of items.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="payment_details.shipment_tax_value"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Tax Value (₹)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          min={0}
                          {...field}
                          onChange={(e) => {
                            const val = e.target.value;
                            field.onChange(val === "" ? "" : Number(val));
                          }}
                          className="bg-white"
                        />
                      </FormControl>
                      <FormDescription className="text-[10px] text-slate-400">
                        Commercial tax applied on items.
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="payment_details.shipment_total_value"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Total Value (₹)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          className="bg-white font-bold text-slate-800 border-slate-300"
                          {...field}
                          onChange={(e) => {
                            const val = e.target.value;
                            field.onChange(val === "" ? "" : Number(val));
                          }}
                        />
                      </FormControl>
                      <FormDescription className="text-[10px] text-slate-500 font-semibold">
                        Shipment Value + Tax Value (auto-calculated, but editable).
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </div>

              {/* Payment Mode and COD Toggle */}
              {!isReverse && (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 border-t border-slate-200/60 pt-6">
                  <FormField
                    control={form.control}
                    name="payment_details.freight_payment_mode"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Who pays for shipping?</FormLabel>
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
                            <SelectItem value={FreightPaymentMode.PREPAID}>
                              Prepaid (Sender wallet)
                            </SelectItem>
                            <SelectItem value={FreightPaymentMode.POSTPAID}>
                              Postpaid (Sender account billing)
                            </SelectItem>
                            <SelectItem value={FreightPaymentMode.TO_PAY}>
                              To Pay (Receiver pays)
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </FormItem>
                    )}
                  />

                  <FormField
                    control={form.control}
                    name="payment_details.is_cod"
                    render={({ field }) => (
                      <FormItem className="flex flex-row items-center justify-between rounded-lg border border-slate-200 bg-white p-4 shadow-xs">
                        <div className="space-y-0.5">
                          <FormLabel className="text-base font-semibold text-slate-900">Cash on Delivery (COD)</FormLabel>
                          <div className="text-xs text-slate-500">
                            Collect cash for the item value from receiver at delivery.
                          </div>
                        </div>
                        <FormControl>
                          <input
                            type="checkbox"
                            className="h-5 w-5 cursor-pointer accent-slate-900"
                            checked={field.value}
                            onChange={(e) => {
                              field.onChange(e.target.checked);
                              if (e.target.checked) {
                                const total = form.getValues("payment_details.shipment_total_value") || 0;
                                form.setValue("payment_details.cod_amount", total, { shouldValidate: true });
                              } else {
                                form.setValue("payment_details.cod_amount", 0);
                              }
                            }}
                          />
                        </FormControl>
                      </FormItem>
                    )}
                  />
                </div>
              )}

              {/* Info Banner for To Pay without COD */}
              {!isReverse && !watchedIsCod && watchedFreightMode === FreightPaymentMode.TO_PAY && (
                <div className="bg-blue-50 border border-blue-200/60 p-4 rounded-lg flex items-start space-x-3 text-blue-800 animate-in fade-in duration-200">
                  <Info className="h-5 w-5 text-blue-600 shrink-0 mt-0.5" />
                  <div className="text-xs space-y-1">
                    <p className="font-bold">Receiver Pays Shipping Charges (To Pay Mode)</p>
                    <p className="text-blue-700">
                      Although Cash on Delivery (COD) is off, the receiver will still be required to pay the shipping charges at delivery.
                    </p>
                  </div>
                </div>
              )}

              {/* COD Specific Settings Card */}
              {!isReverse && watchedIsCod && (
                <div className="bg-slate-100/80 border border-slate-200/80 p-5 rounded-xl space-y-4 animate-in fade-in slide-in-from-top-2 duration-200">
                  <div className="flex items-center justify-between border-b border-slate-200 pb-2 mb-2">
                    <span className="text-[11px] font-bold text-slate-500 tracking-wider uppercase">
                      COD Collection Configuration
                    </span>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                    <FormField
                      control={form.control}
                      name="payment_details.cod_amount"
                      render={({ field }) => (
                        <FormItem className="bg-white p-4 rounded-lg border border-slate-200">
                          <FormLabel className="text-slate-800 font-medium">Collectible amount for sender (₹)</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              min={0}
                              {...field}
                              onChange={(e) => {
                                const val = e.target.value;
                                field.onChange(val === "" ? "" : Number(val));
                              }}
                              className="bg-white font-semibold"
                            />
                          </FormControl>
                          <FormDescription className="text-[10px] text-slate-505">
                            Defaulted to Shipment Total Value. This amount will be collected at doorstep and sent back to the sender.
                          </FormDescription>
                          <FormMessage />
                        </FormItem>
                      )}
                    />

                    <FormField
                      control={form.control}
                      name="payment_details.add_shipping_to_cod"
                      render={({ field }) => (
                        <div className="flex flex-col justify-center">
                          <div className={`flex flex-row items-start space-x-3 rounded-lg border p-4 shadow-xs transition-all duration-150 ${
                            watchedFreightMode === FreightPaymentMode.TO_PAY
                              ? "bg-slate-50 border-slate-200 opacity-80 cursor-not-allowed"
                              : "bg-white border-slate-200 hover:border-slate-300 cursor-pointer"
                          }`}>
                            <div className="flex items-center h-5">
                              <input
                                id="addShippingToCodCheckbox"
                                type="checkbox"
                                className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900 cursor-pointer accent-slate-900 disabled:cursor-not-allowed"
                                checked={watchedFreightMode === FreightPaymentMode.TO_PAY ? true : field.value}
                                disabled={watchedFreightMode === FreightPaymentMode.TO_PAY}
                                onChange={(e) => field.onChange(e.target.checked)}
                              />
                            </div>
                            <div className="space-y-1 leading-none">
                              <label 
                                htmlFor="addShippingToCodCheckbox" 
                                className={`font-semibold text-sm text-slate-900 select-none ${
                                  watchedFreightMode === FreightPaymentMode.TO_PAY ? "cursor-not-allowed text-slate-500" : "cursor-pointer"
                                }`}
                              >
                                Add shipping charges to customer&apos;s COD
                                {watchedFreightMode === FreightPaymentMode.TO_PAY && (
                                  <span className="text-[10px] font-semibold text-blue-600 block mt-0.5">
                                    Enabled automatically in &quot;To Pay&quot; mode
                                  </span>
                                )}
                              </label>
                              {watchedFreightMode !== FreightPaymentMode.TO_PAY && (
                                <p className="text-xs text-slate-500">
                                  Calculate & add the final dynamic freight cost to the receiver&apos;s COD invoice.
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      )}
                    />
                  </div>
                </div>
              )}

              {/* Compliance & Invoicing */}
              {!isReverse && (
                <>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6 pt-6 border-t border-slate-200">
                    <FormField
                      control={form.control}
                      name="payment_details.invoice_number"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>Invoice Number</FormLabel>
                          <FormControl>
                            <Input {...field} value={field.value || ""} className="bg-white" />
                          </FormControl>
                          <FormMessage />
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
                            <DatePicker 
                              date={field.value ? parseISO(field.value) : undefined}
                              setDate={(date) => field.onChange(date ? format(date, "yyyy-MM-dd") : "")}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  {/* E-Way Bill Compliance Card (Pops up when Gross Value > 50k) */}
                  {((watchedShipmentTotalValue || 0) >= 50000) && (
                    <div className="space-y-4 mt-4">
                      <EWayBillBanner tenant={tenant} />
                      <FormField
                        control={form.control}
                        name="payment_details.eway_bill_number"
                        render={({ field }) => (
                          <FormItem className="bg-white p-4 rounded-lg border border-slate-200">
                            <FormLabel className="text-slate-900 font-semibold">
                              E-Way Bill Number <span className="text-red-500">*</span>
                            </FormLabel>
                            <FormControl>
                              <Input
                                placeholder="Enter 12-digit E-Way Bill Number"
                                {...field}
                                value={field.value || ""}
                                className="bg-white font-mono tracking-wider"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>
                  )}
                </>
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

      {/* Cost Adjustment Confirmation Dialog */}
      <Dialog open={showPriceChangeDialog} onOpenChange={(open) => { if (!open) handleCloseDialog(); }}>
        <DialogContent className="max-w-md sm:max-w-lg p-6 bg-white rounded-2xl shadow-xl border border-slate-200">
          <DialogHeader className="space-y-2">
            <DialogTitle className="text-lg font-black text-slate-900 tracking-tight flex items-center gap-2.5">
              <span className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
              Cost Adjustment Required
            </DialogTitle>
            <DialogDescription className="text-slate-500 text-sm leading-relaxed">
              Your recent edits to package specifications or address details have triggered a dynamic shipping rate recalculation. Please review the cost updates below before saving.
            </DialogDescription>
          </DialogHeader>

          {isRecalculating ? (
            <div className="flex flex-col items-center justify-center py-8 space-y-3">
              <Loader2 className="h-8 w-8 animate-spin text-primary" />
              <p className="text-xs font-semibold text-slate-400 tracking-wider uppercase animate-pulse">
                Recalculating rates...
              </p>
            </div>
          ) : newPriceQuote ? (
            <div className="space-y-5 my-3 animate-in fade-in zoom-in-95 duration-200">
              {/* Price Comparison Box */}
              <div className="grid grid-cols-2 gap-4 p-4 rounded-xl bg-slate-50 border border-slate-200/60">
                <div className="space-y-0.5">
                  <span className="text-[10px] font-bold uppercase text-slate-400 tracking-wider block">Original Cost</span>
                  <span className="text-xl font-black text-slate-400 line-through">
                    ₹{originalPricing?.total_cost.toFixed(2) || "0.00"}
                  </span>
                </div>
                <div className="space-y-0.5 border-l border-slate-200/80 pl-4">
                  <span className="text-[10px] font-bold uppercase text-primary tracking-wider block">Updated Cost</span>
                  <span className="text-2xl font-black text-primary tracking-tight">
                    ₹{newPriceQuote.total_amount.toFixed(2)}
                  </span>
                </div>
              </div>

              {/* Detailed Billing Ledger */}
              <div className="space-y-3 rounded-xl border border-slate-200 p-4 bg-white shadow-xs">
                <h5 className="text-xs font-bold text-slate-400 uppercase tracking-wider border-b pb-2">
                  New Shipping Breakdown
                </h5>
                <div className="space-y-2 text-xs text-slate-600">
                  <div className="flex justify-between text-slate-700 text-sm font-medium">
                    <span>Base Freight</span>
                    <span>₹{newPriceQuote.base_charge.toFixed(2)}</span>
                  </div>
                  
                  {newPriceQuote.pricing_breakdown && (
                    <>
                      {(newPriceQuote.pricing_breakdown.service_surcharge ?? 0) > 0 && (
                        <div className="flex justify-between pl-2">
                          <span>Speed Premium</span>
                          <span>+ ₹{Number(newPriceQuote.pricing_breakdown.service_surcharge).toFixed(2)}</span>
                        </div>
                      )}
                      {(newPriceQuote.pricing_breakdown.fuel_surcharge ?? 0) > 0 && (
                        <div className="flex justify-between pl-2">
                          <span>Fuel Surcharge & DPH</span>
                          <span>+ ₹{Number(newPriceQuote.pricing_breakdown.fuel_surcharge).toFixed(2)}</span>
                        </div>
                      )}
                      {(newPriceQuote.pricing_breakdown.network_surcharge ?? 0) > 0 && (
                        <div className="flex justify-between pl-2">
                          <span>Network Surcharge</span>
                          <span>+ ₹{Number(newPriceQuote.pricing_breakdown.network_surcharge).toFixed(2)}</span>
                        </div>
                      )}
                      {(newPriceQuote.pricing_breakdown.oversized_surcharge ?? 0) > 0 && (
                        <div className="flex justify-between text-amber-600 font-semibold pl-2">
                          <span>Oversized Cargo Surcharge</span>
                          <span>+ ₹{Number(newPriceQuote.pricing_breakdown.oversized_surcharge).toFixed(2)}</span>
                        </div>
                      )}
                      {(newPriceQuote.pricing_breakdown.cod_fee ?? 0) > 0 && (
                        <div className="flex justify-between pl-2">
                          <span>COD Processing Fee</span>
                          <span>+ ₹{Number(newPriceQuote.pricing_breakdown.cod_fee).toFixed(2)}</span>
                        </div>
                      )}
                    </>
                  )}

                  <div className="flex justify-between text-slate-600 border-t pt-2 mt-1">
                    <span>GST (18%)</span>
                    <span className="font-medium">₹{newPriceQuote.tax_amount.toFixed(2)}</span>
                  </div>
                  <div className="flex justify-between font-bold text-slate-900 border-t border-double border-slate-300 pt-2.5 mt-1.5 text-sm uppercase tracking-wider">
                    <span>Total Cost</span>
                    <span>₹{newPriceQuote.total_amount.toFixed(2)}</span>
                  </div>
                </div>
              </div>

              {/* Doorstep Cash Collection Note */}
              {Number(newPriceQuote.pricing_breakdown?.cod_amount ?? 0) > 0 && (
                <div className="p-3.5 rounded-lg bg-emerald-50 border border-emerald-100 text-emerald-850 space-y-1">
                  <span className="text-[10px] font-bold uppercase tracking-widest block text-emerald-800">Doorstep COD Collection Impact</span>
                  <p className="text-xs text-emerald-700 font-medium">
                    The cash collected at delivery will automatically be adjusted to ₹{Number(newPriceQuote.pricing_breakdown?.cod_amount ?? 0).toFixed(2)} to reflect updated logistics metrics.
                  </p>
                </div>
              )}
            </div>
          ) : (
            <div className="py-6 text-center text-sm text-slate-400 italic">
              Failed to compute updated pricing. Please re-verify dimensions.
            </div>
          )}

          <DialogFooter className="mt-4 border-t border-slate-100 pt-4 flex flex-col-reverse sm:flex-row gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleCloseDialog}
              className="w-full sm:w-auto font-bold cursor-pointer border-slate-200 hover:bg-slate-50"
            >
              Cancel & Review
            </Button>
            <Button
              type="button"
              onClick={handleApproveAndSave}
              disabled={isRecalculating || !newPriceQuote}
              className="w-full sm:w-auto font-bold cursor-pointer"
            >
              Approve & Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
