// frontend/src/app/[tenant_slug]/(app)/shipments/new/page.tsx
"use client";

import {
  AddressesService,
  AddressCreate,
  AddressRead,
  AddressScope,
  ApiError,
  DocumentType,
  PackageCreate,
  FreightPaymentMode,
  PickupCreate,
  PickupDocumentCreate,
  PickupTimeSlot,
  ProductCategory,
  RateCalculationResponse,
  ServiceType,
  ShipmentsService,
  ShipmentType,
  WeightUnit,
} from "@/api_client";
import { AddressFieldset } from "@/components/forms/address-fieldset";
import { PackageFieldset } from "@/components/forms/package-fieldset";
import { useTenant } from "@/components/providers/tenant-provider";
import { EWayBillBanner } from "@/components/forms/eway-bill-banner";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
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
import { getSupabaseClient } from "@/lib/supabase";
import {
  shipmentFormSchema,
  ShipmentFormValues,
} from "@/lib/validations/shipment";
import { formatTimeSlot } from "@/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowLeft,
  CheckCircle2,
  CloudUpload,
  FileText,
  Info,
  Loader2,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Path, Resolver, useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";

const STEPS = [
  { id: 0, name: "Order Specs" },
  { id: 1, name: "Cargo & Value" },
  { id: 2, name: "Addresses" },
  { id: 3, name: "Packages & Docs" },
  { id: 4, name: "Review Booking" },
];

export const CATEGORY_LABELS: Record<ProductCategory, string> = {
  [ProductCategory.HOUSEHOLD_PERSONAL]: "Household / Personal",
  [ProductCategory.VEHICLE]: "Vehicle (Automotive)",
  [ProductCategory.DOCUMENTS]: "Documents / Letters",
  [ProductCategory.HAZARDOUS]: "Hazardous Material (HAZMAT)",
  [ProductCategory.COMMERCIAL]: "Commercial Goods / B2B",
  [ProductCategory.ELECTRONICS]: "Electronics & Gadgets",
  [ProductCategory.APPAREL]: "Apparel & Clothing",
  [ProductCategory.OTHER]: "Other (Custom Category)",
};

export default function CreateShipmentWizard() {
  const { routeTo, tenantSlug, tenant } = useTenant();
  const router = useRouter();
  const supabase = getSupabaseClient(tenantSlug);

  const [currentStep, setCurrentStep] = useState(0);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isCalculating, setIsCalculating] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [rateQuote, setRateQuote] = useState<RateCalculationResponse | null>(
    null
  );
  const [isDraftLoaded, setIsDraftLoaded] = useState(false);
  const [addShippingToCod, setAddShippingToCod] = useState(false);

  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>([]);

  useEffect(() => {
    AddressesService.listSavedAddresses()
      .then(setSavedAddresses)
      .catch(console.error);
  }, []);

  const form = useForm<ShipmentFormValues>({
    resolver: zodResolver(shipmentFormSchema) as unknown as Resolver<ShipmentFormValues>,
    mode: "onChange",
    defaultValues: {
      order_reference_id: "",
      requested_pickup_date: "",
      pickup_time_slot: undefined,
      // 🔥 CRITICAL FIX 1: Explicitly defining defaults so the UI never starts blank
      service_type: ServiceType.SURFACE_ROAD,
      shipment_type: ShipmentType.FORWARD,
      product_category: undefined as unknown as ProductCategory,
      other_category_description: "",

      reason_for_return: "",
      payment_details: {
        freight_payment_mode: FreightPaymentMode.PREPAID,
        is_cod: false,
        cod_amount: 0,
        add_shipping_to_cod: false,
        shipment_value: 0,
        shipment_tax_value: 0,
        shipment_total_value: 0,
        tax_amount: 0,
        base_freight: 0,
        total_logistics_cost: 0,
        invoice_number: "",
        eway_bill_number: "",
      },
      packages: [
        {
          length: 0,
          breadth: 0,
          height: 0,
          weight: 0.1,
          box_count: 1,
          is_fragile: false,
          description: "",
        },
      ],
      documents: [],
      pickup_address_id: "",
      delivery_address_id: "",
    },
  });

  const {
    fields: docFields,
    append: appendDoc,
    remove: removeDoc,
  } = useFieldArray({ control: form.control, name: "documents" });

  const DRAFT_KEY = `shipment-draft-${tenantSlug}`;

  // 1. Auto-Load Draft (Runs ONLY ONCE on mount)
  useEffect(() => {
    const savedDraft = localStorage.getItem(DRAFT_KEY);
    if (savedDraft) {
      try {
        const parsed = JSON.parse(savedDraft);
        if (parsed.step !== undefined) {
          let restoredStep = parsed.step;
          // Fallback to Step 4 if draft was saved at Step 5 (Review Booking)
          // so the user can trigger a fresh calculate-rate quote and avoid empty screens
          if (restoredStep === 4) {
            restoredStep = 3;
          }
          setCurrentStep(restoredStep);
        }
        if (parsed.addShippingToCod !== undefined) setAddShippingToCod(parsed.addShippingToCod);

        if (parsed.values) {
          const currentDefaults = form.getValues();
          const mergedValues = { ...currentDefaults, ...parsed.values };

          // 🔥 THE ANTIDOTE: If the draft contains "", null, or undefined, force it back to a valid Enum!
          if (
            !Object.values(ShipmentType).includes(mergedValues.shipment_type)
          ) {
            mergedValues.shipment_type = ShipmentType.FORWARD;
          }
          if (!Object.values(ServiceType).includes(mergedValues.service_type)) {
            mergedValues.service_type = ServiceType.SURFACE_ROAD;
          }
          if (
            !Object.values(FreightPaymentMode).includes(
              mergedValues.payment_details?.freight_payment_mode
            )
          ) {
            if (!mergedValues.payment_details)
              mergedValues.payment_details = currentDefaults.payment_details;
            mergedValues.payment_details.freight_payment_mode = FreightPaymentMode.PREPAID;
          }
          if (mergedValues.payment_details?.is_cod === undefined) {
            if (!mergedValues.payment_details)
              mergedValues.payment_details = currentDefaults.payment_details;
            mergedValues.payment_details.is_cod = false;
            mergedValues.payment_details.cod_amount = 0;
          }

          // Safely inject the perfectly sanitized data
          form.reset(mergedValues);
        }
        if (parsed.step > 0)
          toast.info("Recovered your unsaved booking draft.");
      } catch (e) {
        console.error("Failed to restore draft", e);
      }
    }
    // 🔥 Open the Mount Gate!
    setIsDraftLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Dynamic Smart Math Assist for COD & TO_PAY calculations
  const watchedFreightMode = form.watch("payment_details.freight_payment_mode");
  const watchedIsCod = form.watch("payment_details.is_cod");
  const watchedShipmentValue = form.watch("payment_details.shipment_value");
  const watchedShipmentTaxValue = form.watch("payment_details.shipment_tax_value");
  const watchedShipmentTotalValue = form.watch("payment_details.shipment_total_value");
  const watchedPackages = form.watch("packages");

  // Client-side simple sum of actual cargo weights & boxes
  const cargoTotals = (watchedPackages || []).reduce(
    (acc, pkg) => {
      const count = Number(pkg?.box_count) || 0;
      const weight = Number(pkg?.weight) || 0;
      const isGrams = pkg?.weight_unit === WeightUnit.G;
      const weightInKg = isGrams ? weight / 1000 : weight;

      acc.boxCount += count;
      acc.actualWeightKg += weightInKg * count;
      return acc;
    },
    { boxCount: 0, actualWeightKg: 0 }
  );

  // Dynamic calculation of total commercial value: shipment_total_value = shipment_value + shipment_tax_value
  useEffect(() => {
    const base = watchedShipmentValue || 0;
    const tax = watchedShipmentTaxValue || 0;
    if (base > 0 || tax > 0) {
      form.setValue("payment_details.shipment_total_value", base + tax, { shouldValidate: true });
    }
  }, [watchedShipmentValue, watchedShipmentTaxValue, form]);

  // 2. Auto-Save Draft (Reacts to form keystrokes and step changes)
  useEffect(() => {
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({
        step: currentStep,
        values: form.getValues(),
        addShippingToCod,
      })
    );

    const subscription = form.watch(() => {
      localStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({
          step: currentStep,
          values: form.getValues(),
          addShippingToCod,
        })
      );
    });

    return () => subscription.unsubscribe();
  }, [currentStep, form, DRAFT_KEY, addShippingToCod]);

  const handleFileUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
    docType: DocumentType
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    try {
      const fileExt = file.name.split(".").pop();
      const fileName = `${Math.random()
        .toString(36)
        .substring(2, 15)}.${fileExt}`;
      const filePath = `${tenantSlug}/${fileName}`;
      const { error: uploadError } = await supabase.storage
        .from("documents")
        .upload(filePath, file);
      if (uploadError) throw uploadError;
      appendDoc({
        document_type: docType,
        file_name: file.name,
        file_url: filePath,
      });
      toast.success("Document safely encrypted and uploaded");
    } catch (error) {
      const err = error as Error;
      toast.error(err.message || "Failed to upload document");
    } finally {
      setIsUploading(false);
    }
  };

  const nextStep = async () => {
    let fieldsToValidate: Array<Path<ShipmentFormValues>> = [];
    if (currentStep === 0)
      fieldsToValidate = [
        "order_reference_id",
        "requested_pickup_date",
        "pickup_time_slot",
        "shipment_type",
        "reason_for_return",
        "service_type",
      ];
    if (currentStep === 1)
      fieldsToValidate = [
        "product_category",
        "payment_details",
      ];
    if (currentStep === 2)
      fieldsToValidate = [
        "pickup_address_id",
        "new_pickup_address",
        "delivery_address_id",
        "new_delivery_address",
      ];

    const isStepValid = await form.trigger(fieldsToValidate);

    // 🔥 CRITICAL FIX 3: Actually tell the user why the button isn't working!
    if (!isStepValid) {
      toast.error("Please fill out all required fields correctly.");
      console.error("Validation Errors:", form.formState.errors);
      return;
    }

    if (currentStep === 3) {
      if (form.getValues("shipment_type") === ShipmentType.REVERSE) {
        const pkgs = form.getValues("packages");
        pkgs.forEach((_, idx) => {
          form.setValue(`packages.${idx}.length`, 0);
          form.setValue(`packages.${idx}.breadth`, 0);
          form.setValue(`packages.${idx}.height`, 0);
          form.setValue(`packages.${idx}.weight`, 0.1);
        });
      }

      setIsCalculating(true);
      try {
        const values = form.getValues();
        const isStep3Valid = await form.trigger(["packages"]);

        if (!isStep3Valid) {
          console.error("Zod Package Errors:", form.formState.errors.packages);
          throw new Error("Please check package dimensions.");
        }

        const pPincode =
          values.new_pickup_address?.pincode ||
          savedAddresses.find((a) => a.id === values.pickup_address_id)?.pincode;
        const dPincode =
          values.new_delivery_address?.pincode ||
          savedAddresses.find((a) => a.id === values.delivery_address_id)
            ?.pincode;

        if (!pPincode || !dPincode)
          throw new Error(
            "Cannot calculate rate: Missing pincodes in Address step."
          );

        const quote = await ShipmentsService.calculateShippingRate({
          pickup_pincode: pPincode,
          delivery_pincode: dPincode,
          packages: values.packages as PackageCreate[],
          service_type: values.service_type,
          is_cod: values.payment_details.is_cod,
          cod_amount: values.payment_details.cod_amount,
          shipment_total_value: values.payment_details.shipment_total_value,
          shipment_type: values.shipment_type,
          is_rto: values.shipment_type === ShipmentType.REVERSE,
        });

        if (quote.serviceable === false) {
          throw new Error(quote.error_message || "This destination is not serviceable for the selected shipping speed.");
        }

        setRateQuote(quote);
        setCurrentStep((prev) => prev + 1);
      } catch (error) {
        const apiError = error as ApiError;
        let msg = apiError.message || "Failed to calculate rates.";
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
        return;
      } finally {
        setIsCalculating(false);
      }
      return;
    }
    setCurrentStep((prev) => prev + 1);
  };

  const onSubmit = async (data: ShipmentFormValues) => {
    if (currentStep < STEPS.length - 1) {
      nextStep();
      return;
    }
    setIsSubmitting(true);
    try {
      const totalItemValue = data.payment_details?.shipment_total_value || 0;
      const computedFinalCodAmount = data.payment_details.is_cod
        ? (data.payment_details.cod_amount || 0)
        : 0;

      const payload: PickupCreate = {
        order_reference_id: data.order_reference_id || undefined,
        shipment_type: data.shipment_type,
        service_type: data.service_type,
        requested_pickup_date: data.requested_pickup_date,
        pickup_time_slot: data.pickup_time_slot,
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
        packages: data.packages as PackageCreate[],
        payment_details: data.payment_details
          ? {
              freight_payment_mode: data.payment_details.freight_payment_mode,
              is_cod: data.payment_details.is_cod,
              cod_amount: computedFinalCodAmount,
              add_shipping_to_cod: data.payment_details.freight_payment_mode === FreightPaymentMode.TO_PAY ? true : addShippingToCod,
              shipment_value: data.payment_details.shipment_value,
              shipment_tax_value: data.payment_details.shipment_tax_value,
              shipment_total_value: totalItemValue,
              base_freight: rateQuote?.base_charge || 0,
              tax_amount: rateQuote?.tax_amount || 0,
              total_logistics_cost: rateQuote?.total_amount || 0,
              pricing_breakdown: rateQuote?.pricing_breakdown || {},
              hsn_code: data.payment_details.hsn_code || undefined,
              invoice_number: data.payment_details.invoice_number || undefined,
              invoice_date: data.payment_details.invoice_date || undefined,
              eway_bill_number: data.payment_details.eway_bill_number || undefined,
            }
          : undefined,
        documents: data.documents ? (data.documents as PickupDocumentCreate[]) : undefined,
      };

      await ShipmentsService.createShipment(payload);
      localStorage.removeItem(DRAFT_KEY);
      toast.success("Shipment booked successfully!");
      router.push(routeTo("/shipments"));
    } catch (error: unknown) {
      let errorMessage = "Failed to create shipment.";
      const apiError = error as ApiError;
      if (apiError && typeof apiError === "object" && "body" in apiError) {
        const body = apiError.body as { detail?: unknown } | undefined;
        if (body && body.detail) {
          if (Array.isArray(body.detail)) {
            errorMessage = body.detail
              .map((err: { loc?: unknown[]; msg?: string }) => {
                const lastLoc = err.loc?.at(-1);
                return `${lastLoc ? String(lastLoc) : "field"}: ${err.msg || "invalid value"}`;
              })
              .join(" | ");
          } else if (typeof body.detail === "string") {
            errorMessage = body.detail;
          }
        }
      }
      toast.error(errorMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  const isReverse = form.watch("shipment_type") === ShipmentType.REVERSE;
  const productCategoryValue = form.watch("product_category");

  if (!isDraftLoaded) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-20">
      <div className="flex items-center gap-4">
        <Button variant="outline" size="icon" asChild className="h-9 w-9">
          <Link href={routeTo("/shipments")}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight">
            Create Booking
          </h1>
          <p className="text-slate-500 mt-1">
            Step {currentStep + 1}: {STEPS[currentStep].name}
          </p>
        </div>
      </div>

      <div className="w-full bg-slate-200 h-2 rounded-full overflow-hidden">
        <div
          className="bg-primary h-full transition-all duration-300"
          style={{ width: `${((currentStep + 1) / STEPS.length) * 100}%` }}
        />
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
        <Form {...form}>
          <form
            onSubmit={form.handleSubmit(onSubmit, (errors) => {
              console.error("Validation Errors:", errors);
              toast.error("Form validation failed.");
            })}
            className="space-y-8"
          >
            {/* STEP 1: LOGISTICS TYPE */}
            {currentStep === 0 && (
              <div className="space-y-6 animate-in fade-in">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-slate-50 p-6 rounded-xl border border-slate-100">
                  <FormField
                    control={form.control}
                    name="shipment_type"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Logistics Flow</FormLabel>
                        {/* 🔥 FIX: Removed || "" so Radix UI can bind perfectly */}
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
                            <SelectItem value={ShipmentType.FORWARD}>
                              Forward (Delivery)
                            </SelectItem>
                            <SelectItem value={ShipmentType.REVERSE}>
                              Reverse (Pickup/Return)
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="service_type"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Service Speed</FormLabel>
                        {/* 🔥 FIX: Removed || "" */}
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
                            <SelectItem value={ServiceType.SURFACE_ROAD}>
                              Surface Road (Truck)
                            </SelectItem>
                            <SelectItem value={ServiceType.SURFACE_TRAIN}>
                              Surface Train (Rail)
                            </SelectItem>
                            <SelectItem value={ServiceType.AIR}>
                              Air Cargo (Flight)
                            </SelectItem>
                          </SelectContent>
                        </Select>
                      </FormItem>
                    )}
                  />
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                  <FormField
                    control={form.control}
                    name="order_reference_id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Order ID / Ref (Optional)</FormLabel>
                        <FormControl>
                          <Input placeholder="ORD-123" {...field} />
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
                          <Input type="date" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="pickup_time_slot"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Preferred Pickup Window</FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          value={field.value}
                        >
                          <FormControl>
                            <SelectTrigger className="bg-white">
                              <SelectValue placeholder="Select time slot" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {Object.values(PickupTimeSlot).map((slot) => (
                              <SelectItem key={slot} value={slot}>
                                {formatTimeSlot(slot)}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
                {isReverse && (
                  <FormField
                    control={form.control}
                    name="reason_for_return"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>
                          Reason for Return{" "}
                          <span className="text-red-500">*</span>
                        </FormLabel>
                        <FormControl>
                          <Textarea
                            placeholder="Customer rejected item..."
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}
              </div>
            )}

            {/* STEP 2: CARGO & VALUE */}
            {currentStep === 1 && (
              <div className="space-y-6 animate-in fade-in">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-slate-50 p-6 rounded-xl border border-slate-100">
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
                  
                  {/* Core Financials grid */}
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
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
                                  Prepaid (Sender pays)
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
                                    setAddShippingToCod(false);
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
                              <FormDescription className="text-[10px] text-slate-500">
                                Defaulted to Shipment Total Value. This amount will be collected at doorstep and sent back to the sender.
                              </FormDescription>
                              <FormMessage />
                            </FormItem>
                          )}
                        />

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
                                checked={watchedFreightMode === FreightPaymentMode.TO_PAY ? true : addShippingToCod}
                                disabled={watchedFreightMode === FreightPaymentMode.TO_PAY}
                                onChange={(e) => setAddShippingToCod(e.target.checked)}
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
                                  Add the final dynamic freight cost to the receiver&apos;s doorstep COD collection.
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Compliance and Invoicing */}
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
                                <Input
                                  type="date"
                                  {...field}
                                  value={field.value || ""}
                                  className="bg-white"
                                />
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      </div>

                      {/* E-Way Bill Compliance Card (Pops up when Gross Value > 50k) */}
                      {((watchedShipmentTotalValue || 0) > 50000) && (
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
              </div>
            )}

            {/* STEP 3: ADDRESSES */}
            {currentStep === 2 && (
              <div className="space-y-6 animate-in fade-in">
                <AddressFieldset
                  control={form.control}
                  type="pickup"
                  title="Sender Details (Pickup Location)"
                  savedAddresses={savedAddresses}
                />
                <AddressFieldset
                  control={form.control}
                  type="delivery"
                  title="Receiver Details (Delivery Location)"
                  savedAddresses={savedAddresses}
                />
              </div>
            )}

            {/* STEP 4: PACKAGES & DOCS */}
            {currentStep === 3 && (
              <div className="space-y-8 animate-in fade-in">
                 <PackageFieldset control={form.control} isReverse={isReverse} />

                {!isReverse && cargoTotals.actualWeightKg > 0 && (
                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-2 shadow-xs animate-in fade-in duration-200">
                    <div className="flex items-center gap-2 text-slate-600 text-xs sm:text-sm">
                      <span className="text-base">📦</span>
                      <span>
                        Cargo Summary: <strong>{cargoTotals.boxCount}</strong> {cargoTotals.boxCount === 1 ? "box" : "boxes"} configured
                      </span>
                    </div>
                    <div className="text-xs sm:text-sm text-slate-500">
                      Total Actual Weight:{" "}
                      <strong className="text-slate-900 text-sm sm:text-base font-bold pl-1">
                        {cargoTotals.actualWeightKg.toFixed(2)} kg
                      </strong>
                    </div>
                  </div>
                )}


                <div className="bg-blue-50/50 p-6 rounded-xl border border-blue-100 mt-8">
                  <h3 className="font-semibold text-slate-900 mb-2 flex items-center gap-2">
                    <CloudUpload className="h-5 w-5 text-blue-600" /> Upload
                    Documents & Photos
                  </h3>
                  <p className="text-sm text-slate-600 mb-6">
                    Upload invoices, E-Way bills, or{" "}
                    <strong className="text-slate-800">
                      photos of the boxes
                    </strong>{" "}
                    to document their condition before dispatch.
                  </p>

                  <div className="flex gap-4 items-end mb-6">
                    <div className="flex-1 w-full sm:w-auto">
                      <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                        <Select
                          onValueChange={(val) =>
                            document
                              .getElementById("file-upload")
                              ?.setAttribute("data-type", val)
                          }
                        >
                          <SelectTrigger className="w-full sm:w-[200px] bg-white">
                            <SelectValue placeholder="Select Doc Type" />
                          </SelectTrigger>
                          <SelectContent>
                            {Object.values(DocumentType).map((t) => (
                              <SelectItem key={t} value={t}>
                                {t.replace(/_/g, " ")}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <Input
                          id="file-upload"
                          type="file"
                          className="bg-white file:text-primary file:bg-blue-50 file:border-0 file:rounded-md file:px-4 cursor-pointer"
                          disabled={isUploading}
                          onChange={(e) => {
                            const type = e.target.getAttribute(
                              "data-type"
                            ) as DocumentType;
                            if (!type) {
                              toast.error(
                                "Please select a document type first!"
                              );
                              e.target.value = "";
                              return;
                            }
                            handleFileUpload(e, type);
                          }}
                        />
                      </div>
                    </div>
                  </div>

                  {docFields.length > 0 && (
                    <div className="space-y-2">
                      {docFields.map((doc, idx) => (
                        <div
                          key={doc.id}
                          className="flex items-center justify-between p-3 bg-white border border-slate-200 rounded-lg shadow-sm"
                        >
                          <div className="flex items-center gap-3 overflow-hidden">
                            <FileText className="h-5 w-5 text-slate-400 shrink-0" />
                            <div className="min-w-0">
                              <p className="text-sm font-bold truncate">
                                {doc.document_type.replace(/_/g, " ")}
                              </p>
                              <p className="text-xs text-slate-500 truncate">
                                {doc.file_name}
                              </p>
                            </div>
                          </div>
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="text-red-500 shrink-0"
                            onClick={() => removeDoc(idx)}
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* STEP 5: REVIEW */}
            {currentStep === 4 && rateQuote && (() => {
              const totalItemValue = watchedShipmentTotalValue || 0;
              const computedFinalCodAmount = watchedIsCod
                ? totalItemValue + ((watchedFreightMode === FreightPaymentMode.TO_PAY || addShippingToCod) ? rateQuote.total_amount : 0)
                : (watchedFreightMode === FreightPaymentMode.TO_PAY ? rateQuote.total_amount : 0);

              return (
                <div className="max-w-2xl mx-auto space-y-6 animate-in fade-in duration-300">
                  {/* Section Title & Success Badge */}
                  <div className="text-center space-y-2">
                    <div className="inline-flex items-center justify-center h-12 w-12 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-500 mb-2">
                      <CheckCircle2 className="h-6 w-6 animate-bounce" />
                    </div>
                    <h3 className="text-2xl font-extrabold text-slate-900 tracking-tight">Verify Shipping & COD Ledger</h3>
                    <p className="text-slate-500 text-sm max-w-md mx-auto">
                      Review the dynamic pricing quote and final door collection instructions before booking.
                    </p>
                  </div>

                  {/* 1. Total Chargeable Weight Header Card */}
                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-5 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="space-y-1">
                      <div className="text-xs font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5">
                        Total Chargeable Weight <Info className="h-3.5 w-3.5 text-slate-400" />
                      </div>
                      <p className="text-3xl font-black text-slate-900 tracking-tight">
                        {rateQuote.chargeable_weight} kg
                      </p>
                    </div>
                    {rateQuote.pricing_breakdown && (
                      <div className="flex gap-4 text-xs text-slate-500 sm:border-l sm:pl-6 border-slate-200">
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block">Actual Weight</span>
                          <strong className="text-slate-700 font-bold text-sm">{rateQuote.pricing_breakdown.total_actual_weight} kg</strong>
                        </div>
                        <div className="space-y-0.5">
                          <span className="text-slate-400 block">Volumetric Weight</span>
                          <strong className="text-slate-700 font-bold text-sm">{rateQuote.pricing_breakdown.total_volumetric_weight} kg</strong>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* 2. Two Column Grid for Pricing & COD */}
                  <div className="grid grid-cols-1 md:grid-cols-12 gap-6 items-stretch">
                    
                    {/* Left Column: Selected Service Card & Breakup (col-span-7) */}
                    <div className="md:col-span-7 space-y-4 flex flex-col justify-between">
                      {/* Selected Service Speed Premium Card */}
                      <div className="bg-primary/[0.03] border border-primary/20 rounded-xl p-5 shadow-xs relative overflow-hidden">
                        <div className="absolute top-0 right-0 w-24 h-24 bg-primary/[0.03] rounded-full -mr-8 -mt-8" />
                        <div className="text-[10px] font-bold text-primary uppercase tracking-wider">
                          Selected Shipping Mode
                        </div>
                        <h4 className="text-md font-bold text-slate-800 mt-1">
                          {form.getValues("service_type").replace(/_/g, " ")}
                        </h4>
                        <div className="flex items-baseline gap-1 mt-3">
                          <span className="text-xs font-bold text-slate-500">₹</span>
                          <span className="text-3xl font-black text-primary tracking-tight">
                            {rateQuote.total_amount.toFixed(2)}
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-400 mt-1.5">
                          Estimated Delivery in {rateQuote.estimated_days} {rateQuote.estimated_days === 1 ? "day" : "days"}
                        </p>
                      </div>

                      {/* Shipping Cost Breakup Table */}
                      <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-xs space-y-4">
                        <h5 className="text-xs font-bold text-slate-400 uppercase tracking-wider border-b pb-2 mb-1">
                          Shipping Cost Breakup
                        </h5>
                        <div className="space-y-2 text-sm">
                          <div className="flex justify-between text-slate-600">
                            <span>Freight Base Charge</span>
                            <span className="font-medium">₹{rateQuote.base_charge.toFixed(2)}</span>
                          </div>
                          
                          {rateQuote.pricing_breakdown && (
                            <>
                              {rateQuote.pricing_breakdown.service_surcharge > 0 && (
                                <div className="flex justify-between text-xs text-slate-500 pl-2">
                                  <span>Speed Premium</span>
                                  <span>+ ₹{rateQuote.pricing_breakdown.service_surcharge.toFixed(2)}</span>
                                </div>
                              )}
                              {rateQuote.pricing_breakdown.fuel_surcharge > 0 && (
                                <div className="flex justify-between text-xs text-slate-500 pl-2">
                                  <span>Fuel Surcharge & DPH</span>
                                  <span>+ ₹{rateQuote.pricing_breakdown.fuel_surcharge.toFixed(2)}</span>
                                </div>
                              )}
                              {rateQuote.pricing_breakdown.network_surcharge > 0 && (
                                <div className="flex justify-between text-xs text-slate-500 pl-2">
                                  <span>Network Surcharge</span>
                                  <span>+ ₹{rateQuote.pricing_breakdown.network_surcharge.toFixed(2)}</span>
                                </div>
                              )}
                              {rateQuote.pricing_breakdown.oversized_surcharge > 0 && (
                                <div className="flex justify-between text-xs text-amber-600 font-semibold pl-2">
                                  <span>Oversized Cargo Surcharge</span>
                                  <span>+ ₹{rateQuote.pricing_breakdown.oversized_surcharge.toFixed(2)}</span>
                                </div>
                              )}
                              {rateQuote.pricing_breakdown.cod_fee > 0 && (
                                <div className="flex justify-between text-xs text-slate-500 pl-2">
                                  <span>COD Processing Fee</span>
                                  <span>+ ₹{rateQuote.pricing_breakdown.cod_fee.toFixed(2)}</span>
                                </div>
                              )}
                            </>
                          )}

                          <div className="flex justify-between text-slate-600 border-t pt-2 mt-1">
                            <span>GST (18%)</span>
                            <span className="font-medium">₹{rateQuote.tax_amount.toFixed(2)}</span>
                          </div>
                          <div className="flex justify-between font-bold text-slate-900 border-t border-double border-slate-200 pt-2.5 mt-2 text-base">
                            <span>Total cost</span>
                            <span>₹{rateQuote.total_amount.toFixed(2)}</span>
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Right Column: Doorstep Cash Collection fintech card (col-span-5) */}
                    <div className="md:col-span-5 flex flex-col justify-between bg-white border border-slate-200 rounded-xl shadow-xs overflow-hidden">
                      <div className="p-5 space-y-3 flex-1">
                        <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400 border-b pb-2 mb-1">
                          Doorstep Cash Details
                        </h4>
                        {computedFinalCodAmount > 0 ? (
                          <div className="space-y-3.5">
                            <p className="text-xs text-slate-500 leading-relaxed">
                              The logistics agent will collect the following total cash amount from the receiver at delivery:
                            </p>
                            <div className="space-y-2 bg-slate-50 p-3 rounded-lg border border-slate-100 text-xs text-slate-600">
                              {watchedIsCod && (
                                <div className="flex justify-between">
                                  <span>Goods Value (COD)</span>
                                  <span className="font-semibold text-slate-800">₹{totalItemValue.toFixed(2)}</span>
                                </div>
                              )}
                              {(watchedFreightMode === FreightPaymentMode.TO_PAY || (watchedIsCod && addShippingToCod)) && (
                                <div className="flex justify-between text-amber-700 font-semibold">
                                  <span>Shipping Freight</span>
                                  <span>+ ₹{rateQuote.total_amount.toFixed(2)}</span>
                                </div>
                              )}
                            </div>
                          </div>
                        ) : (
                          <div className="flex h-full flex-col justify-center items-center text-center py-6 space-y-3 text-slate-500">
                            <span className="text-3xl">🕊️</span>
                            <div>
                              <p className="text-sm font-bold text-slate-700">No Doorstep Collection</p>
                              <p className="text-xs text-slate-400 mt-1 leading-normal">
                                This is a Prepaid/Postpaid shipment. Package will be delivered directly.
                              </p>
                            </div>
                          </div>
                        )}
                      </div>

                      {computedFinalCodAmount > 0 && (
                        <div className="bg-emerald-50 border-t border-emerald-100 p-5 flex flex-col justify-center">
                          <div className="text-[10px] font-bold text-emerald-700 uppercase tracking-wider">
                            Door Collect Amount
                          </div>
                          <div className="flex items-baseline justify-between mt-1">
                            <span className="text-xs font-semibold text-slate-700">Total Cash</span>
                            <span className="text-2xl font-black text-emerald-700 tracking-tight">
                              ₹{computedFinalCodAmount.toFixed(2)}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })()}

            {/* FOOTER */}
            <div className="flex items-center justify-between pt-4 border-t border-slate-100">
              <Button
                type="button"
                variant="outline"
                onClick={() => setCurrentStep((prev) => prev - 1)}
                disabled={currentStep === 0 || isSubmitting || isCalculating}
              >
                Back
              </Button>
              {currentStep === STEPS.length - 1 ? (
                <Button type="submit" disabled={isSubmitting}>
                  {isSubmitting ? (
                    <>
                      <Loader2 className="mr-2 animate-spin" /> Booking...
                    </>
                  ) : (
                    "Confirm & Book"
                  )}
                </Button>
              ) : (
                <Button
                  type="button"
                  onClick={nextStep}
                  disabled={isCalculating}
                >
                  {isCalculating ? (
                    <>
                      <Loader2 className="mr-2 animate-spin" /> Calculating...
                    </>
                  ) : (
                    "Next Step"
                  )}
                </Button>
              )}
            </div>
          </form>
        </Form>
      </div>
    </div>
  );
}
