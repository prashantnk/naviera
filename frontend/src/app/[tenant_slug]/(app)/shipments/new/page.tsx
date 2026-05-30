// frontend/src/app/[tenant_slug]/(app)/shipments/new/page.tsx
"use client";

import {
  AddressesService,
  AddressRead,
  AddressType,
  DocumentType,
  PaymentMode,
  RateCalculationResponse,
  ServiceType,
  ShipmentsService,
  ShipmentType,
} from "@/api_client";
import { AddressFieldset } from "@/components/forms/address-fieldset";
import { PackageFieldset } from "@/components/forms/package-fieldset";
import { useTenant } from "@/components/providers/tenant-provider";
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
import { zodResolver } from "@hookform/resolvers/zod";
import {
  ArrowLeft,
  ArrowRight,
  CheckCircle2,
  CloudUpload,
  FileText,
  Loader2,
  Save,
  UploadCloud,
  Trash2,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";

const STEPS = [
  { id: 0, name: "Order Specs" },
  { id: 1, name: "Cargo & Value" },
  { id: 2, name: "Addresses" },
  { id: 3, name: "Packages & Docs" },
  { id: 4, name: "Review Booking" },
];

export default function CreateShipmentWizard() {
  const { routeTo, tenantSlug } = useTenant();
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

  const [warehouses, setWarehouses] = useState<AddressRead[]>([]);
  const [customers, setCustomers] = useState<AddressRead[]>([]);

  useEffect(() => {
    AddressesService.listSavedAddresses(AddressType.WAREHOUSE)
      .then(setWarehouses)
      .catch(console.error);
    AddressesService.listSavedAddresses(AddressType.CUSTOMER)
      .then(setCustomers)
      .catch(console.error);
  }, []);

  const form = useForm<ShipmentFormValues>({
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    resolver: zodResolver(shipmentFormSchema) as any,
    mode: "onChange",
    defaultValues: {
      order_reference_id: "",
      requested_pickup_date: "",
      // 🔥 CRITICAL FIX 1: Explicitly defining defaults so the UI never starts blank
      service_type: ServiceType.SURFACE_ROAD,
      shipment_type: ShipmentType.FORWARD,
      product_category: "",
      shipment_description: "",
      reason_for_return: "",
      payment_details: {
        payment_mode: PaymentMode.PREPAID, // 🔥 CRITICAL FIX 1
        declared_value: 0,
        tax_amount: 0,
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
        if (parsed.step !== undefined) setCurrentStep(parsed.step);

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
            !Object.values(PaymentMode).includes(
              mergedValues.payment_details?.payment_mode
            )
          ) {
            if (!mergedValues.payment_details)
              mergedValues.payment_details = currentDefaults.payment_details;
            mergedValues.payment_details.payment_mode = PaymentMode.PREPAID;
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

  // 2. Auto-Save Draft (Reacts to form keystrokes and step changes)
  useEffect(() => {
    // Save when the step changes
    localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ step: currentStep, values: form.getValues() })
    );

    // Save when any form field changes
    const subscription = form.watch((value) => {
      localStorage.setItem(
        DRAFT_KEY,
        JSON.stringify({ step: currentStep, values: form.getValues() })
      );
    });

    return () => subscription.unsubscribe();
  }, [currentStep, form, DRAFT_KEY]);

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
    } catch (error: any) {
      toast.error(error.message || "Failed to upload document");
    } finally {
      setIsUploading(false);
    }
  };

  const nextStep = async () => {
    let fieldsToValidate: any[] = [];
    if (currentStep === 0)
      fieldsToValidate = [
        "order_reference_id",
        "requested_pickup_date",
        "shipment_type",
        "reason_for_return",
        "service_type",
      ];
    if (currentStep === 1)
      fieldsToValidate = [
        "product_category",
        "shipment_description",
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

        const allAddresses = [...warehouses, ...customers];
        const pPincode =
          values.new_pickup_address?.pincode ||
          allAddresses.find((a) => a.id === values.pickup_address_id)?.pincode;
        const dPincode =
          values.new_delivery_address?.pincode ||
          allAddresses.find((a) => a.id === values.delivery_address_id)
            ?.pincode;

        if (!pPincode || !dPincode)
          throw new Error(
            "Cannot calculate rate: Missing pincodes in Address step."
          );

        const quote = await ShipmentsService.calculateShippingRate({
          pickup_pincode: pPincode,
          delivery_pincode: dPincode,
          packages: values.packages as any,
          service_type: values.service_type,
        });
        setRateQuote(quote);
        setCurrentStep((prev) => prev + 1);
      } catch (error: any) {
        let msg = error.message || "Failed to calculate rates.";
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
        return;
      } finally {
        setIsCalculating(false);
      }
      return;
    }
    setCurrentStep((prev) => prev + 1);
  };

  const onSubmit = async (data: ShipmentFormValues) => {
    setIsSubmitting(true);
    try {
      const payload: any = { ...data };
      if (payload.pickup_address_id) delete payload.new_pickup_address;
      if (payload.delivery_address_id) delete payload.new_delivery_address;
      payload.pickup_address_id = payload.pickup_address_id || undefined;
      payload.delivery_address_id = payload.delivery_address_id || undefined;

      // 🔥 FIX: Secretly inject the calculated shipping amount into the payload!
      if (!payload.payment_details) payload.payment_details = {};
      payload.payment_details.amount = rateQuote?.total_amount || 0;

      await ShipmentsService.createShipment(payload);
      localStorage.removeItem(DRAFT_KEY);
      toast.success("Shipment booked successfully!");
      router.push(routeTo("/shipments"));
    } catch (error: any) {
      toast.error(error.body?.detail || "Failed to create shipment.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const watchValue = form.watch("payment_details.declared_value");
  const isReverse = form.watch("shipment_type") === ShipmentType.REVERSE;

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
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <FormField
                    control={form.control}
                    name="order_reference_id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Channel Order ID / Ref</FormLabel>
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
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <FormField
                    control={form.control}
                    name="product_category"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Product Category (Optional)</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="e.g. Electronics"
                            {...field}
                            value={field.value || ""}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="shipment_description"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Description (Optional)</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="e.g. 2 Laptops"
                            {...field}
                            value={field.value || ""}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                <div className="bg-slate-50 p-6 rounded-xl border border-slate-100 space-y-6">
                  <h3 className="font-semibold text-slate-900 border-b pb-2">
                    Financials & Taxation
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                    <FormField
                      control={form.control}
                      name="payment_details.declared_value"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel>
                            {isReverse ? "Package Value" : "Total Item Value"}{" "}
                            (₹)
                          </FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              {...field}
                              onChange={(e) =>
                                field.onChange(e.target.valueAsNumber || 0)
                              }
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
                            <Input {...field} value={field.value || ""} />
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
                              <Input {...field} value={field.value || ""} />
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
                                watchValue > 50000
                                  ? "text-red-600 font-bold"
                                  : ""
                              }
                            >
                              E-Way Bill Number {watchValue > 50000 && "*"}
                            </FormLabel>
                            <FormControl>
                              <Input
                                placeholder={
                                  watchValue > 50000
                                    ? "Mandatory for >₹50k"
                                    : "Optional"
                                }
                                {...field}
                                value={field.value || ""}
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
              </div>
            )}

            {/* STEP 3: ADDRESSES */}
            {currentStep === 2 && (
              <div className="space-y-6 animate-in fade-in">
                <AddressFieldset
                  control={form.control}
                  type="pickup"
                  title={
                    isReverse
                      ? "1. Pickup Location (Customer)"
                      : "1. Origin (Warehouse)"
                  }
                  savedAddresses={isReverse ? customers : warehouses}
                />
                <AddressFieldset
                  control={form.control}
                  type="delivery"
                  title={
                    isReverse
                      ? "2. Drop Location (Warehouse)"
                      : "2. Destination (Customer)"
                  }
                  savedAddresses={isReverse ? warehouses : customers}
                />
              </div>
            )}

            {/* STEP 4: PACKAGES & DOCS */}
            {currentStep === 3 && (
              <div className="space-y-8 animate-in fade-in">
                <PackageFieldset control={form.control} isReverse={isReverse} />

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
            {currentStep === 4 && rateQuote && (
              <div className="max-w-md mx-auto text-center space-y-6 animate-in fade-in">
                <CheckCircle2 className="h-12 w-12 text-green-500 mx-auto" />
                <h3 className="text-2xl font-bold">Review Pricing</h3>
                <div className="bg-slate-50 p-6 rounded-xl border border-slate-200 text-left space-y-4">
                  <div className="flex justify-between">
                    <span>Chargeable Weight</span>
                    <span className="font-bold">
                      {rateQuote.chargeable_weight} kg
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Base Charge</span>
                    <span className="font-bold">
                      ₹{rateQuote.base_charge.toFixed(2)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span>Taxes</span>
                    <span className="font-bold">
                      ₹{rateQuote.tax_amount.toFixed(2)}
                    </span>
                  </div>
                  <div className="border-t pt-4 flex justify-between text-lg font-black">
                    <span>Total Estimate</span>
                    <span>₹{rateQuote.total_amount.toFixed(2)}</span>
                  </div>
                </div>
              </div>
            )}

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
