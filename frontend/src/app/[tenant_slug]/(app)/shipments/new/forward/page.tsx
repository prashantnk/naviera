// src/app/[tenant_slug]/(app)/shipments/new/forward/page.tsx
"use client";

import {
  AddressesService,
  AddressRead,
  FreightPaymentMode,
  PickupTimeSlot,
  ServiceType,
  ShipmentType,
  DocumentType,
  ServiceQuote,
  PackageCreate,
  PickupCreate,
  AddressCreate,
  AddressScope,
  PickupDocumentCreate,
  ShipmentsService,
  BulkRateCalculationRequest,
} from "@/api_client";
import { getSupabaseClient } from "@/lib/supabase";
import { ForwardFormStep } from "../_components/forward-form-step";
import { RateShoppingStep } from "../_components/rate-shopping-step";
import { Button } from "@/components/ui/button";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useTenant } from "@/components/providers/tenant-provider";
import { forwardShipmentSchema, ForwardShipmentFormValues } from "@/lib/validations/shipment";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useState, useRef } from "react";
import { useForm, Resolver, useWatch, useFieldArray } from "react-hook-form";
import { toast } from "sonner";
import { formatTimeSlot } from "@/lib/utils";

export default function ForwardBookingSandbox() {
  const { routeTo, tenantSlug } = useTenant();
  const DRAFT_KEY = `shipment-draft-forward-${tenantSlug}`;

  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [addShippingToCod, setAddShippingToCod] = useState(false);
  const hasRecoveredRef = useRef(false);
  const isSubmittedRef = useRef(false);

  // Orchestration steps and carrier states
  const [currentStep, setCurrentStep] = useState(0); // 0: Specs, 1: Pricing
  const [rateQuotes, setRateQuotes] = useState<ServiceQuote[]>([]);
  const [selectedQuote, setSelectedQuote] = useState<ServiceQuote | null>(null);
  const [isLoadingRates, setIsLoadingRates] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Timezone-proof local Tomorrow date format (resolves UTC offsets)
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const yyyy = tomorrow.getFullYear();
  const mm = String(tomorrow.getMonth() + 1).padStart(2, "0");
  const dd = String(tomorrow.getDate()).padStart(2, "0");
  const defaultTomorrowString = `${yyyy}-${mm}-${dd}`;

  const form = useForm<ForwardShipmentFormValues>({
    resolver: zodResolver(forwardShipmentSchema) as unknown as Resolver<ForwardShipmentFormValues>,
    mode: "onChange",
    defaultValues: {
      order_reference_id: "",
      requested_pickup_date: defaultTomorrowString, // Smart default: Tomorrow
      pickup_time_slot: PickupTimeSlot._10_00_14_00, // Smart default: Slot 1
      service_type: ServiceType.SURFACE_ROAD,
      shipment_type: ShipmentType.FORWARD,
      product_category: undefined,
      other_category_description: "",
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
        invoice_date: "",
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

  const supabase = getSupabaseClient(tenantSlug);
  const [isUploading, setIsUploading] = useState(false);

  // Ingestion of saved address book and localStorage draft recovery
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const addresses = await AddressesService.listSavedAddresses();
        setSavedAddresses(addresses);

        const savedDraft = localStorage.getItem(DRAFT_KEY);
        if (savedDraft && !hasRecoveredRef.current) {
          hasRecoveredRef.current = true; // Prevent subsequent dual recovery triggers
          const parsed = JSON.parse(savedDraft);
          if (parsed.addShippingToCod !== undefined) {
            setAddShippingToCod(parsed.addShippingToCod);
          }
          if (parsed.values) {
            // Sanitise enums strictly before restoration (Safety Net #1)
            const vals = parsed.values;
            if (!Object.values(ServiceType).includes(vals.service_type)) {
              vals.service_type = ServiceType.SURFACE_ROAD;
            }
            if (!Object.values(FreightPaymentMode).includes(vals.payment_details?.freight_payment_mode)) {
              if (vals.payment_details) vals.payment_details.freight_payment_mode = FreightPaymentMode.PREPAID;
            }
            if (!Object.values(PickupTimeSlot).includes(vals.pickup_time_slot)) {
              vals.pickup_time_slot = PickupTimeSlot._10_00_14_00;
            }
            form.reset(vals);
          }
          toast.info("Recovered your unsaved booking draft.");
        }
      } catch (err) {
        console.error("Sandbox load error:", err);
      } finally {
        setIsLoading(false);
      }
    };

    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSlug]);

  // Auto-Save Draft on form updates with private browsing safety guards
  useEffect(() => {
    const subscription = form.watch((values) => {
      // Do not auto-save drafts during final booking submission or after completion
      if (isSubmitting || isSubmittedRef.current) return;

      try {
        localStorage.setItem(
          DRAFT_KEY,
          JSON.stringify({
            values,
            addShippingToCod,
          })
        );
      } catch (error) {
        console.warn("LocalStorage autosave blocked (likely Incognito/Private mode):", error);
      }
    });
    return () => subscription.unsubscribe();
  }, [form, DRAFT_KEY, addShippingToCod, isSubmitting]);

  const handleFileUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
    docType: DocumentType
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setIsUploading(true);
    try {
      const fileExt = file.name.split(".").pop();
      const fileName = `${Math.random().toString(36).substring(2, 15)}.${fileExt}`;
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

  // Dynamic calculation of total commercial value: shipment_total_value = shipment_value + shipment_tax_value
  const watchedShipmentValue = useWatch({
    control: form.control,
    name: "payment_details.shipment_value",
  });
  const watchedShipmentTaxValue = useWatch({
    control: form.control,
    name: "payment_details.shipment_tax_value",
  });

  useEffect(() => {
    const base = watchedShipmentValue || 0;
    const tax = watchedShipmentTaxValue || 0;
    const total = base + tax;
    if (base > 0 || tax > 0) {
      form.setValue("payment_details.shipment_total_value", total, { shouldValidate: true });
      if (form.getValues("payment_details.is_cod")) {
        form.setValue("payment_details.cod_amount", total, { shouldValidate: true });
      }
    }
  }, [watchedShipmentValue, watchedShipmentTaxValue, form]);

  // Transition step 1 to step 2: validate & load dynamic carrier rates in bulk
  const onCompareRates = async () => {
    const isStep1Valid = await form.trigger();
    if (!isStep1Valid) {
      console.error("Outbound specs validation fail:", form.formState.errors);
      toast.error("Please correct all validation errors in Shipment Specs first.");
      return;
    }

    const values = form.getValues();
    // Resolve coordinates/pincodes cleanly
    const pPincode = values.pickup_address_id
      ? savedAddresses.find((a) => a.id === values.pickup_address_id)?.pincode
      : values.new_pickup_address?.pincode;

    const dPincode = values.delivery_address_id
      ? savedAddresses.find((a) => a.id === values.delivery_address_id)?.pincode
      : values.new_delivery_address?.pincode;

    if (!pPincode || !dPincode) {
      toast.error("Pincode resolution failed. Please verify addresses contain valid postal codes.");
      return;
    }

    setIsLoadingRates(true);
    setCurrentStep(1); // Move to pricing view immediately, showing shimmer cards

    try {
      const bulkPayload: BulkRateCalculationRequest = {
        pickup_pincode: pPincode,
        delivery_pincode: dPincode,
        packages: values.packages as PackageCreate[],
        is_cod: values.payment_details.is_cod,
        cod_amount: values.payment_details.cod_amount || 0,
        shipment_total_value: values.payment_details.shipment_total_value,
        shipment_type: ShipmentType.FORWARD,
      };

      const res = await ShipmentsService.calculateBulkShippingRates(bulkPayload);
      setRateQuotes(res.quotes);
    } catch (error) {
      const err = error as Error;
      toast.error(err.message || "Pricing endpoint failure during bulk calculations.");
      setCurrentStep(0); // Rollback on error
    } finally {
      setIsLoadingRates(false);
    }
  };

  // Final booking action confirmation
  const onConfirmBooking = async () => {
    if (!selectedQuote || !selectedQuote.quote) {
      toast.error("Please select an active, serviceable delivery carrier speed.");
      return;
    }

    setIsSubmitting(true);
    try {
      const data = form.getValues();
      const quoteDetails = selectedQuote.quote;

      // Safety Net #4: Address scoping book mappings
      const newPickupAddress = data.pickup_address_id
        ? undefined
        : data.new_pickup_address
        ? ({
            ...data.new_pickup_address,
            is_saved: data.new_pickup_address.save_to_address_book,
            scope: data.new_pickup_address.is_shared_with_team
              ? AddressScope.TENANT
              : AddressScope.PRIVATE,
          } as unknown as AddressCreate)
        : undefined;

      const newDeliveryAddress = data.delivery_address_id
        ? undefined
        : data.new_delivery_address
        ? ({
            ...data.new_delivery_address,
            is_saved: data.new_delivery_address.save_to_address_book,
            scope: data.new_delivery_address.is_shared_with_team
              ? AddressScope.TENANT
              : AddressScope.PRIVATE,
          } as unknown as AddressCreate)
        : undefined;

      // Safety Net #3: Empty string nullifications for Pydantic specs
      const payload: PickupCreate = {
        order_reference_id: data.order_reference_id || undefined,
        shipment_type: ShipmentType.FORWARD,
        service_type: selectedQuote.service_type,
        requested_pickup_date: data.requested_pickup_date,
        pickup_time_slot: data.pickup_time_slot,
        product_category: data.product_category,
        other_category_description: data.other_category_description || undefined,
        pickup_address_id: data.pickup_address_id || undefined,
        new_pickup_address: newPickupAddress,
        delivery_address_id: data.delivery_address_id || undefined,
        new_delivery_address: newDeliveryAddress,
        packages: data.packages as PackageCreate[],
        payment_details: {
          freight_payment_mode: data.payment_details.freight_payment_mode,
          is_cod: data.payment_details.is_cod,
          cod_amount: data.payment_details.is_cod ? (data.payment_details.cod_amount || 0) : 0,
          add_shipping_to_cod: data.payment_details.freight_payment_mode === FreightPaymentMode.TO_PAY ? true : addShippingToCod,
          shipment_value: data.payment_details.shipment_value,
          shipment_tax_value: data.payment_details.shipment_tax_value,
          shipment_total_value: data.payment_details.shipment_total_value,
          base_freight: quoteDetails.base_charge,
          tax_amount: quoteDetails.tax_amount,
          total_logistics_cost: quoteDetails.total_amount,
          pricing_breakdown: quoteDetails.pricing_breakdown || {},
          hsn_code: data.payment_details.hsn_code || undefined,
          invoice_number: data.payment_details.invoice_number || undefined,
          invoice_date: data.payment_details.invoice_date || undefined,
          eway_bill_number: data.payment_details.eway_bill_number || undefined,
        },
        documents: data.documents ? (data.documents as PickupDocumentCreate[]) : undefined,
      };

      await ShipmentsService.createShipment(payload);
      isSubmittedRef.current = true; // Set flag to disable last-second draft writes
      localStorage.removeItem(DRAFT_KEY); // Clear localStorage on successful book (Safety Net #1)
      toast.success("Shipment booked successfully!");
      window.location.href = routeTo("/shipments");
    } catch (error) {
      const err = error as Error;
      toast.error(err.message || "Failed to finalize shipment booking.");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-20 px-4 md:px-6 animate-in fade-in duration-200">
      {/* Sandbox Header bar */}
      <div className="flex items-center gap-4">
        <Button variant="outline" size="icon" asChild className="h-9 w-9">
          <Link href={routeTo("/shipments")}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <span className="text-[10px] font-bold text-primary tracking-wider uppercase bg-primary/5 border border-primary/10 px-2 py-0.5 rounded animate-pulse flex items-center gap-1 w-fit">
            <Sparkles className="h-3 w-3" /> Forward Shipment Booking
          </span>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight mt-1">
            {currentStep === 0 ? "New Forward Shipment" : "Choose Shipping Rate"}
          </h1>
          <p className="text-slate-500 text-xs">
            {currentStep === 0 
              ? "Fill in the shipment details, addresses, and package info to check prices."
              : "Compare and select the shipping rate that works best for your delivery."
            }
          </p>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
        <Form {...form}>
          <form onSubmit={(e) => {
            e.preventDefault(); // Let internal buttons handle execution transitions cleanly
          }} className="space-y-8">
            
            {currentStep === 0 ? (
              <>
                {/* TOP ROW: Order ID Ref, Pickup Date & Pickup Windows */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 bg-slate-50/50 p-5 rounded-xl border border-slate-100">
                  <FormField
                    control={form.control}
                    name="order_reference_id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-bold text-slate-700">Order ID / Ref (Optional)</FormLabel>
                        <FormControl>
                          <Input placeholder="e.g. ORD-123" className="h-9 text-xs bg-white font-semibold" {...field} />
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
                        <FormLabel className="text-xs font-bold text-slate-700">Requested Pickup Date *</FormLabel>
                        <FormControl>
                          <Input type="date" className="h-9 text-xs bg-white" {...field} />
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
                        <FormLabel className="text-xs font-bold text-slate-700">Preferred Pickup Slot *</FormLabel>
                        <Select onValueChange={field.onChange} value={field.value}>
                          <FormControl>
                            <SelectTrigger className="h-9 text-xs bg-white">
                              <SelectValue placeholder="Choose slot" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {Object.values(PickupTimeSlot).map((slot) => (
                              <SelectItem key={slot} value={slot} className="text-xs">
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

                {/* MAIN DECOUPLED FORM STEP */}
                <ForwardFormStep
                  control={form.control}
                  savedAddresses={savedAddresses}
                  addShippingToCod={addShippingToCod}
                  setAddShippingToCod={setAddShippingToCod}
                  docFields={docFields}
                  removeDoc={removeDoc}
                  isUploading={isUploading}
                  handleFileUpload={handleFileUpload}
                />

                {/* SANDBOX FORM ACTION TRIGGERS */}
                <div className="border-t border-slate-100 pt-6 flex items-center justify-between">
                  <Button variant="ghost" type="button" onClick={() => form.reset()} className="cursor-pointer text-xs font-semibold text-slate-500 hover:bg-slate-100">
                    Reset Fields
                  </Button>
                  <Button
                    type="button"
                    onClick={onCompareRates}
                    className="cursor-pointer text-xs font-bold bg-slate-900 hover:bg-slate-800 text-white flex items-center gap-2 px-6 py-2 h-9 rounded-lg shadow-md"
                  >
                    Find Rates <Sparkles className="h-3.5 w-3.5 text-primary" />
                  </Button>
                </div>
              </>
            ) : (
              <RateShoppingStep
                rateQuotes={rateQuotes}
                isLoadingRates={isLoadingRates}
                selectedQuote={selectedQuote}
                setSelectedQuote={setSelectedQuote}
                onBack={() => setCurrentStep(0)}
                onSubmit={onConfirmBooking}
                isSubmitting={isSubmitting}
                isCod={!!form.watch("payment_details.is_cod")}
                addShippingToCod={addShippingToCod}
                savedAddresses={savedAddresses}
              />
            )}

          </form>
        </Form>
      </div>
    </div>
  );
}
