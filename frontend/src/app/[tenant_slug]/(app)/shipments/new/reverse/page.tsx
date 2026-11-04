// src/app/[tenant_slug]/(app)/shipments/new/reverse/page.tsx
"use client";

import React, { Suspense, useCallback, useEffect, useState, useRef } from "react";
import {
  AddressRead,
  AddressCategory,
  FreightPaymentMode,
  ServiceFlow,
  ServiceType,
  ShipmentType,
  DocumentType,
  PackageCreate,
  AddressCreate,
  AddressScope,
  PickupDocumentCreate,
  PickupRead,
  ShipmentsService,
  DimensionUnit,
  WeightUnit,
} from "@/api_client";
import { getSupabaseClient } from "@/lib/supabase";
import { BOOKABLE_FREIGHT_PAYMENT_MODES } from "@/lib/form-options";
import { ReverseFormStep } from "../_components/reverse-form-step";
import type { BookingPayload, QuoteOption } from "@/components/booking/booking-api";
import { buildPaymentInputs, buildQuoteRequest } from "@/components/booking/booking-inputs";
import { PriceChangedDialog } from "@/components/booking/price-changed-dialog";
import { QuoteStep } from "@/components/booking/quote-step";
import { useQuoteBooking } from "@/components/booking/use-quote-booking";
import { Button } from "@/components/ui/button";
import {
  Form,
  FormField,
  FormItem,
  FormLabel,
  FormControl,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { buildBookedOrderHref } from "@/components/pickups/next-add-to-pickup-banner";
import { todayApiDate } from "@/components/pickups/pickup-constants";
import { useTenant } from "@/components/providers/tenant-provider";
import { fetchAddressesCached, getCachedAddresses } from "@/hooks/use-addresses";
import {
  hasMeaningfulReverseDraft,
  reverseShipmentSchema,
  ReverseShipmentFormValues,
} from "@/lib/validations/shipment";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, RotateCcw, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useForm, Resolver, useFieldArray } from "react-hook-form";
import { toast } from "sonner";

function ReverseBookingContent() {
  const { routeTo, tenantSlug } = useTenant();
  const router = useRouter();
  const searchParams = useSearchParams();
  const fromShipmentId = searchParams.get("from_shipment_id");
  const DRAFT_KEY = `shipment-draft-reverse-${tenantSlug}`;

  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>(
    () => getCachedAddresses(tenantSlug) ?? []
  );
  const [isLoading, setIsLoading] = useState<boolean>(() => Boolean(fromShipmentId));
  const [sourceTrackingId, setSourceTrackingId] = useState<string | null>(null);
  const hasRecoveredRef = useRef(false);
  const isSubmittedRef = useRef(false);

  const [currentStep, setCurrentStep] = useState(0);

  /** Clears the draft and lands on the new return with the "Add to pickup" call to action. */
  const handleBooked = useCallback(
    (created: PickupRead) => {
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      isSubmittedRef.current = true;
      localStorage.removeItem(DRAFT_KEY);
      router.push(
        routeTo(created?.id ? buildBookedOrderHref(`/shipments/${created.id}`) : "/shipments")
      );
    },
    [DRAFT_KEY, routeTo, router]
  );
  const booking = useQuoteBooking({
    onBooked: handleBooked,
    bookingFailedMessage: "Failed to finalize reverse return shipment booking.",
  });
  const isSubmitting = booking.isSubmitting;

  const form = useForm<ReverseShipmentFormValues>({
    resolver: zodResolver(
      reverseShipmentSchema
    ) as unknown as Resolver<ReverseShipmentFormValues>,
    mode: "onChange",
    defaultValues: {
      order_reference_id: "",
      service_type: ServiceType.SURFACE_ROAD,
      shipment_type: ShipmentType.REVERSE,
      reason_for_return: "",
      product_category: undefined,
      other_category_description: "",
      qc_required: true,
      qc_notes: "",
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
      },
      packages: [
        {
          length: 10,
          breadth: 10,
          height: 10,
          dimension_unit: DimensionUnit.CM,
          weight: 0.5,
          weight_unit: WeightUnit.KG,
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

  useEffect(() => {
    const warmAddresses = getCachedAddresses(tenantSlug);
    if (warmAddresses !== null) {
      setSavedAddresses(warmAddresses);
    }
    const loadInitialData = async () => {
      try {
        const addresses = await fetchAddressesCached(tenantSlug, {
          force: warmAddresses !== null,
        });
        setSavedAddresses(addresses);

        if (fromShipmentId) {
          const source = await ShipmentsService.getShipmentDetails(
            fromShipmentId
          );
          setSourceTrackingId(
            source.tracking_id || source.order_reference_id || source.id
          );

          // Swap Customer delivery_address -> Reverse pickup_address
          const custAddr = source.delivery_address;
          const isCustSaved = Boolean(
            custAddr.is_saved &&
              addresses.some((a) => a.id === custAddr.id)
          );

          // Swap Merchant pickup_address -> Reverse delivery_address
          const whAddr = source.pickup_address;
          const isWhSaved = Boolean(
            whAddr.is_saved && addresses.some((a) => a.id === whAddr.id)
          );

          const mappedPackages =
            source.packages && source.packages.length > 0
              ? source.packages.map((pkg) => ({
                  length: pkg.length || 10,
                  breadth: pkg.breadth || 10,
                  height: pkg.height || 10,
                  dimension_unit:
                    (pkg.dimension_unit as DimensionUnit) || DimensionUnit.CM,
                  weight: pkg.weight > 0 ? pkg.weight : 0.5,
                  weight_unit:
                    (pkg.weight_unit as WeightUnit) || WeightUnit.KG,
                  box_count: pkg.box_count || 1,
                  is_fragile: Boolean(pkg.is_fragile),
                  description: pkg.description || "",
                }))
              : [
                  {
                    length: 10,
                    breadth: 10,
                    height: 10,
                    dimension_unit: DimensionUnit.CM,
                    weight: 0.5,
                    weight_unit: WeightUnit.KG,
                    box_count: 1,
                    is_fragile: false,
                    description: "",
                  },
                ];

          form.reset({
            order_reference_id: `RET-${
              source.tracking_id || source.order_reference_id || ""
            }`,
            service_type: source.service_type || ServiceType.SURFACE_ROAD,
            shipment_type: ShipmentType.REVERSE,
            reason_for_return: "Defective / Damaged Item",
            product_category: source.product_category,
            other_category_description:
              source.other_category_description || "",
            qc_required: true,
            qc_notes:
              "Verify item condition, original brand tag, and serial number before pickup",
            pickup_address_id: isCustSaved ? custAddr.id : "",
            new_pickup_address: isCustSaved
              ? undefined
              : {
                  name: custAddr.name || "",
                  phone: custAddr.phone || "",
                  email: custAddr.email || "",
                  company_name: custAddr.company_name || "",
                  gstin: custAddr.gstin || "",
                  address_line1: custAddr.address_line1 || "",
                  address_line2: custAddr.address_line2 || "",
                  landmark: custAddr.landmark || "",
                  city: custAddr.city || "",
                  state: custAddr.state || "",
                  pincode: custAddr.pincode || "",
                  category:
                    (custAddr.category as AddressCategory) ||
                    AddressCategory.HOME,
                  scope: AddressScope.PRIVATE,
                  save_to_address_book: false,
                  is_shared_with_team: false,
                },
            delivery_address_id: isWhSaved ? whAddr.id : "",
            new_delivery_address: isWhSaved
              ? undefined
              : {
                  name: whAddr.name || "",
                  phone: whAddr.phone || "",
                  email: whAddr.email || "",
                  company_name: whAddr.company_name || "",
                  gstin: whAddr.gstin || "",
                  address_line1: whAddr.address_line1 || "",
                  address_line2: whAddr.address_line2 || "",
                  landmark: whAddr.landmark || "",
                  city: whAddr.city || "",
                  state: whAddr.state || "",
                  pincode: whAddr.pincode || "",
                  category:
                    (whAddr.category as AddressCategory) ||
                    AddressCategory.WAREHOUSE,
                  scope: AddressScope.PRIVATE,
                  save_to_address_book: false,
                  is_shared_with_team: false,
                },
            packages: mappedPackages,
            payment_details: {
              freight_payment_mode: FreightPaymentMode.PREPAID,
              is_cod: false,
              cod_amount: 0,
              add_shipping_to_cod: false,
              shipment_value:
                source.payment_details?.shipment_value || 0,
              shipment_tax_value:
                source.payment_details?.shipment_tax_value || 0,
              shipment_total_value:
                source.payment_details?.shipment_total_value || 0,
              tax_amount: 0,
              base_freight: 0,
              total_logistics_cost: 0,
            },
            documents: [],
          });
          toast.success(
            "Pre-filled reverse return details from forward shipment!"
          );
          return;
        }

        const savedDraft = localStorage.getItem(DRAFT_KEY);
        if (savedDraft && !hasRecoveredRef.current) {
          hasRecoveredRef.current = true;
          const parsed = JSON.parse(savedDraft);
          if (parsed.values && hasMeaningfulReverseDraft(parsed.values)) {
            const vals = parsed.values;
            if (!Object.values(ServiceType).includes(vals.service_type)) {
              vals.service_type = ServiceType.SURFACE_ROAD;
            }
            // Old drafts may carry TO_PAY, which is off for the MVP (WP0).
            if (
              !BOOKABLE_FREIGHT_PAYMENT_MODES.includes(
                vals.payment_details?.freight_payment_mode
              )
            ) {
              if (vals.payment_details) {
                vals.payment_details.freight_payment_mode =
                  FreightPaymentMode.PREPAID;
              }
            }
            // Old drafts may still carry pickup date/slot; pickups are scheduled later.
            delete vals.requested_pickup_date;
            delete vals.pickup_time_slot;
            form.reset(vals);
            toast.info("Recovered your unsaved reverse booking draft.");
          } else {
            localStorage.removeItem(DRAFT_KEY);
          }
        }
      } catch (err) {
        console.error("Reverse wizard load error:", err);
      } finally {
        setIsLoading(false);
      }
    };

    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSlug, fromShipmentId]);

  useEffect(() => {
    const subscription = form.watch((values) => {
      if (isLoading || isSubmitting || isSubmittedRef.current || fromShipmentId) return;
      if (!hasMeaningfulReverseDraft(values as Partial<ReverseShipmentFormValues>)) return;
      try {
        localStorage.setItem(DRAFT_KEY, JSON.stringify({ values }));
      } catch (error) {
        console.warn("LocalStorage autosave blocked:", error);
      }
    });
    return () => subscription.unsubscribe();
  }, [form, DRAFT_KEY, isLoading, isSubmitting, fromShipmentId]);

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
      toast.success("Return document uploaded");
    } catch (error) {
      const err = error as Error;
      toast.error(err.message || "Failed to upload document");
    } finally {
      setIsUploading(false);
    }
  };

  /** Resolves the pickup and return pincodes from saved or new addresses. */
  const resolveAddresses = (values: ReverseShipmentFormValues) => ({
    pickup: values.pickup_address_id
      ? savedAddresses.find((a) => a.id === values.pickup_address_id)
      : values.new_pickup_address,
    delivery: values.delivery_address_id
      ? savedAddresses.find((a) => a.id === values.delivery_address_id)
      : values.new_delivery_address,
  });

  // Step 1 -> 2: validate, then price exactly the inputs the booking will send (A-03).
  const onCompareRates = async () => {
    const isStep1Valid = await form.trigger();
    if (!isStep1Valid) {
      toast.error(
        "Please fill out all required return fields and addresses first."
      );
      return;
    }

    const values = form.getValues();
    const { pickup, delivery } = resolveAddresses(values);
    if (!pickup?.pincode || !delivery?.pincode) {
      toast.error(
        "Pincode resolution failed. Please verify pickup and return addresses contain valid 6-digit pincodes."
      );
      return;
    }

    setCurrentStep(1);
    const quote = await booking.requestQuote(
      buildQuoteRequest({
        flow: ServiceFlow.B2C,
        shipmentType: ShipmentType.REVERSE,
        pickupPincode: pickup.pincode,
        deliveryPincode: delivery.pincode,
        packages: values.packages as PackageCreate[],
        payment: buildPaymentInputs({ ...values.payment_details, is_cod: false }, false),
      })
    );
    if (!quote) setCurrentStep(0);
  };

  /** Sanitizes blank optional strings on one-off addresses before API submission (D-16). */
  const sanitizeTransientAddress = (
    addr: ReverseShipmentFormValues["new_pickup_address"],
  ): AddressCreate | undefined => {
    if (!addr) return undefined;
    return {
      ...addr,
      email: addr.email?.trim() ? addr.email.trim() : undefined,
      gstin: addr.gstin?.trim() ? addr.gstin.trim() : undefined,
      company_name: addr.company_name?.trim() ? addr.company_name.trim() : undefined,
      address_line2: addr.address_line2?.trim() ? addr.address_line2.trim() : undefined,
      landmark: addr.landmark?.trim() ? addr.landmark.trim() : undefined,
      is_saved: addr.save_to_address_book,
      scope: addr.is_shared_with_team
        ? AddressScope.TENANT
        : AddressScope.PRIVATE,
    } as unknown as AddressCreate;
  };

  /** Maps the chosen card + the form to the booking body (same inputs as the quote). */
  const buildBookingPayload = (option: QuoteOption): BookingPayload => {
    const data = form.getValues();

    const newPickupAddress = data.pickup_address_id
      ? undefined
      : sanitizeTransientAddress(data.new_pickup_address);

    const newDeliveryAddress = data.delivery_address_id
      ? undefined
      : sanitizeTransientAddress(data.new_delivery_address);

    return {
      service_flow: ServiceFlow.B2C,
      service_option: option.service_option,
      expected_total: option.total_amount ?? 0,
      order_reference_id: data.order_reference_id || undefined,
      shipment_type: ShipmentType.REVERSE,
      // Delhivery flow: no pickup options at booking; the pickup date and slot
      // are chosen on the Pickup Request.
      requested_pickup_date: todayApiDate(),
      product_category: data.product_category,
      other_category_description:
        data.other_category_description || undefined,
      reason_for_return: data.reason_for_return,
      qc_required: Boolean(data.qc_required),
      qc_notes: data.qc_notes || undefined,
      pickup_address_id: data.pickup_address_id || undefined,
      new_pickup_address: newPickupAddress,
      delivery_address_id: data.delivery_address_id || undefined,
      new_delivery_address: newDeliveryAddress,
      packages: data.packages as PackageCreate[],
      payment_details: buildPaymentInputs({ ...data.payment_details, is_cod: false }, false),
      documents: data.documents
        ? (data.documents as PickupDocumentCreate[])
        : undefined,
    };
  };

  const onConfirmBooking = () => booking.book(buildBookingPayload);
  const routeAddresses = resolveAddresses(form.getValues());

  if (isLoading) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6 pb-20 px-4 md:px-6 animate-in fade-in duration-200">
      {/* Header Bar */}
      <div className="flex items-center gap-4">
        <Button variant="outline" size="icon" asChild className="h-9 w-9">
          <Link href={routeTo("/shipments")}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <span className="text-[10px] font-bold text-amber-700 tracking-wider uppercase bg-amber-50 border border-amber-200 px-2 py-0.5 rounded flex items-center gap-1 w-fit">
            <RotateCcw className="h-3 w-3" /> B2C Reverse Return (DTO) Booking
          </span>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight mt-1">
            {currentStep === 0
              ? "New Reverse Return (DTO)"
              : "Choose Return Shipping Rate"}
          </h1>
          <p className="text-slate-500 text-xs">
            {currentStep === 0
              ? "Schedule a doorstep return pickup from your customer back to your origin warehouse."
              : "Compare and select the return carrier speed with reverse pickup and QC handling."}
          </p>
        </div>
      </div>

      {/* 1-Click DTO Prefill Banner */}
      {sourceTrackingId && (
        <div className="bg-amber-50/90 border border-amber-200 rounded-xl p-4 flex items-center gap-3 text-amber-900 shadow-2xs animate-in fade-in">
          <div className="h-9 w-9 rounded-lg bg-amber-100 border border-amber-200 flex items-center justify-center shrink-0">
            <RotateCcw className="h-4 w-4 text-amber-700" />
          </div>
          <div className="text-xs leading-relaxed">
            <strong>
              Initiating Return (DTO) for Forward Shipment {sourceTrackingId}
            </strong>{" "}
            — Customer pickup and Warehouse drop addresses have been
            automatically swapped.
          </div>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
        {React.createElement(
          Form as React.ComponentType<
            typeof form & { children: React.ReactNode }
          >,
          Object.assign({}, form, {
            children: (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                }}
                className="space-y-8"
              >
                {currentStep === 0 ? (
                  <>
                    {/* TOP ROW: Return Order Ref only (no pickup options, like Delhivery) */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-6 bg-slate-50/50 p-5 rounded-xl border border-slate-100">
                      <FormField
                        control={form.control}
                        name="order_reference_id"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel className="text-xs font-bold text-slate-700">
                              Return Order Ref (Optional)
                            </FormLabel>
                            <FormControl>
                              <Input
                                placeholder="e.g. RET-101"
                                className="h-9 text-xs bg-white font-semibold"
                                name={field.name}
                                value={field.value || ""}
                                onChange={field.onChange}
                                onBlur={field.onBlur}
                                ref={field.ref}
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      <p className="md:col-span-2 self-end text-xs text-slate-500">
                        Pickup date and slot are chosen later, when you add this return to a pickup request.
                      </p>
                    </div>

                    <ReverseFormStep
                      control={form.control}
                      savedAddresses={savedAddresses}
                      docFields={docFields}
                      removeDoc={removeDoc}
                      isUploading={isUploading}
                      handleFileUpload={handleFileUpload}
                    />

                    <div className="border-t border-slate-100 pt-6 flex items-center justify-between">
                      <Button
                        variant="ghost"
                        type="button"
                        onClick={() => form.reset()}
                        className="cursor-pointer text-xs font-semibold text-slate-500 hover:bg-slate-100"
                      >
                        Reset Fields
                      </Button>
                      <Button
                        type="button"
                        onClick={onCompareRates}
                        className="cursor-pointer text-xs font-bold bg-slate-900 hover:bg-slate-800 text-white flex items-center gap-2 px-6 py-2 h-9 rounded-lg shadow-md"
                      >
                        <span>Find Return Rates</span>
                        <Sparkles className="h-3.5 w-3.5 text-primary" />
                      </Button>
                    </div>
                  </>
                ) : (
                  <QuoteStep
                    quote={booking.quote}
                    isLoading={booking.isQuoting}
                    selectedOption={booking.selectedOption}
                    onSelect={booking.selectOption}
                    onBack={() => setCurrentStep(0)}
                    onSubmit={onConfirmBooking}
                    isSubmitting={isSubmitting}
                    isCod={false}
                    pickup={routeAddresses.pickup}
                    delivery={routeAddresses.delivery}
                  />
                )}
              </form>
            ),
          })
        )}
      </div>
      <PriceChangedDialog
        change={booking.priceChange}
        isSubmitting={isSubmitting}
        onConfirm={booking.confirmPriceChange}
        onCancel={booking.cancelPriceChange}
      />
    </div>
  );
}

export default function ReverseBookingPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-[60vh] items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
        </div>
      }
    >
      <ReverseBookingContent />
    </Suspense>
  );
}
