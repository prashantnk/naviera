// src/app/[tenant_slug]/(app)/shipments/new/forward/page.tsx
"use client";

import {
  AddressesService,
  AddressRead,
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
  ProductCategory,
} from "@/api_client";
import { getSupabaseClient } from "@/lib/supabase";
import { matchAddressByPincode, parseRateHandoff, type RateHandoff } from "@/lib/rate-handoff";
import { B2C_PRODUCT_CATEGORIES, BOOKABLE_FREIGHT_PAYMENT_MODES } from "@/lib/form-options";
import { ForwardFormStep } from "../_components/forward-form-step";
import type { BookingPayload, QuoteOption } from "@/components/booking/booking-api";
import { buildPaymentInputs, buildQuoteRequest } from "@/components/booking/booking-inputs";
import { PriceChangedDialog } from "@/components/booking/price-changed-dialog";
import { QuoteStep } from "@/components/booking/quote-step";
import { useQuoteBooking } from "@/components/booking/use-quote-booking";
import { useUser } from "@/components/auth/auth-guard";
import { Button } from "@/components/ui/button";
import { ScreenGuideBanner, type GuideStep } from "@/components/ui/screen-guide-banner";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { buildBookedOrderHref } from "@/components/pickups/next-add-to-pickup-banner";
import { todayApiDate } from "@/components/pickups/pickup-constants";
import { useTenant } from "@/components/providers/tenant-provider";
import { forwardShipmentSchema, ForwardShipmentFormValues } from "@/lib/validations/shipment";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, Sparkles } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, useRef } from "react";
import { useForm, Resolver, useFieldArray } from "react-hook-form";
import { toast } from "sonner";

const B2C_CUSTOMER_GUIDE_STEPS: readonly GuideStep[] = [
  {
    title: "Addresses & Box Weight",
    description:
      "Pick sender and receiver addresses, then enter box weight and L × B × H dimensions.",
  },
  {
    title: "Category & Goods Value",
    description:
      "Select product category and enter shipment value (E-Way Bill is only needed above ₹50,000).",
  },
  {
    title: "Find Rates & Book",
    description:
      "Click Find Rates, pick Delhivery Surface or Express, and book directly from your wallet.",
  },
];

const B2C_STAFF_GUIDE_STEPS: readonly GuideStep[] = [
  {
    title: "Route & Package Specs",
    description:
      "Select pickup and delivery addresses and enter accurate box weight and dimensions.",
  },
  {
    title: "Value & Compliance (> ₹50k)",
    description:
      "Optional HSN/Invoice fields stay tucked away unless shipment value exceeds ₹50,000.",
  },
  {
    title: "Book & Link Carrier AWB",
    description:
      "Book the order, then link the Delhivery AWB or override the final price on Shipment Detail.",
  },
];

export default function ForwardBookingSandbox() {
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  const DRAFT_KEY = `shipment-draft-forward-${tenantSlug}`;

  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [addShippingToCod, setAddShippingToCod] = useState(false);
  const hasRecoveredRef = useRef(false);
  const isSubmittedRef = useRef(false);

  // Orchestration steps: 0 = shipment details, 1 = choose a service and book
  const [currentStep, setCurrentStep] = useState(0);

  /** Clears the draft and lands on the new order with the "Add to pickup" call to action. */
  const handleBooked = useCallback(
    (created: PickupRead) => {
      isSubmittedRef.current = true; // Disable last-second draft writes
      localStorage.removeItem(DRAFT_KEY);
      window.location.href = routeTo(
        created?.id ? buildBookedOrderHref(`/shipments/${created.id}`) : "/shipments"
      );
    },
    [DRAFT_KEY, routeTo]
  );
  const booking = useQuoteBooking({
    onBooked: handleBooked,
    bookingFailedMessage: "Failed to finalize shipment booking.",
  });
  const isSubmitting = booking.isSubmitting;

  const form = useForm<ForwardShipmentFormValues>({
    resolver: zodResolver(forwardShipmentSchema) as unknown as Resolver<ForwardShipmentFormValues>,
    mode: "onChange",
    defaultValues: {
      order_reference_id: "",
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
        eway_bill_required: false,
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

  /**
   * Pre-fills the wizard from the rate calculator's "Book This Shipment" hand-off.
   * Only raw inputs are applied (pincodes -> matching saved addresses, first box, category,
   * COD, declared value); the price is always re-quoted by the backend.
   */
  const applyRateHandoff = (handoff: RateHandoff, addresses: AddressRead[]) => {
    const opts = { shouldDirty: true, shouldValidate: false } as const;
    const pickupId = matchAddressByPincode(addresses, handoff.originPincode);
    const deliveryId = matchAddressByPincode(addresses, handoff.destinationPincode, pickupId);
    if (pickupId) form.setValue("pickup_address_id", pickupId, opts);
    if (deliveryId) form.setValue("delivery_address_id", deliveryId, opts);
    if (handoff.productCategory) {
      form.setValue("product_category", handoff.productCategory as ProductCategory, opts);
    }
    if (handoff.length) form.setValue("packages.0.length", handoff.length, opts);
    if (handoff.breadth) form.setValue("packages.0.breadth", handoff.breadth, opts);
    if (handoff.height) form.setValue("packages.0.height", handoff.height, opts);
    if (handoff.weightKg) form.setValue("packages.0.weight", handoff.weightKg, opts);
    if (handoff.boxCount) form.setValue("packages.0.box_count", handoff.boxCount, opts);
    if (handoff.shipmentValue) form.setValue("payment_details.shipment_value", handoff.shipmentValue, opts);
    if (handoff.isCod) {
      form.setValue("payment_details.is_cod", true, opts);
      if (handoff.codAmount) form.setValue("payment_details.cod_amount", handoff.codAmount, opts);
    }
    const missing = [
      !pickupId && handoff.originPincode ? `pickup (${handoff.originPincode})` : null,
      !deliveryId && handoff.destinationPincode ? `delivery (${handoff.destinationPincode})` : null,
    ].filter(Boolean);
    toast.info(
      missing.length
        ? `Pre-filled from the rate calculator. Choose or add the ${missing.join(" and ")} address.`
        : "Pre-filled from the rate calculator."
    );
  };

  const supabase = getSupabaseClient(tenantSlug);
  const [isUploading, setIsUploading] = useState(false);

  // Ingestion of saved address book and localStorage draft recovery
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const addresses = await AddressesService.listSavedAddresses();
        setSavedAddresses(addresses);

        // A fresh "Book This Shipment" hand-off from the rate calculator wins over an old local draft.
        const handoff = parseRateHandoff(window.location.search, B2C_PRODUCT_CATEGORIES);
        if (handoff && !hasRecoveredRef.current) {
          hasRecoveredRef.current = true;
          applyRateHandoff(handoff, addresses);
        }

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
            // Old drafts may carry TO_PAY, which is off for the MVP (WP0).
            if (!BOOKABLE_FREIGHT_PAYMENT_MODES.includes(vals.payment_details?.freight_payment_mode)) {
              if (vals.payment_details) vals.payment_details.freight_payment_mode = FreightPaymentMode.PREPAID;
            }
            // Old drafts may carry COMMERCIAL, a B2B-only category (A-02).
            if (!B2C_PRODUCT_CATEGORIES.includes(vals.product_category)) {
              vals.product_category = undefined;
            }
            // Old drafts may still carry pickup date/slot; pickups are scheduled later.
            delete vals.requested_pickup_date;
            delete vals.pickup_time_slot;
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
      toast.success(`${file.name} uploaded and attached to this shipment.`);
    } catch (error) {
      const err = error as Error;
      toast.error(err.message || "Failed to upload document");
    } finally {
      setIsUploading(false);
    }
  };

  /** Resolves the pickup and delivery pincodes from saved or new addresses. */
  const resolvePincodes = (values: ForwardShipmentFormValues) => ({
    pickup: values.pickup_address_id
      ? savedAddresses.find((a) => a.id === values.pickup_address_id)?.pincode
      : values.new_pickup_address?.pincode,
    delivery: values.delivery_address_id
      ? savedAddresses.find((a) => a.id === values.delivery_address_id)?.pincode
      : values.new_delivery_address?.pincode,
  });

  // Step 1 -> 2: validate, then price exactly the inputs the booking will send (A-03).
  const onCompareRates = async () => {
    const isStep1Valid = await form.trigger();
    if (!isStep1Valid) {
      toast.error("Please correct all validation errors in Shipment Specs first.");
      return;
    }

    const values = form.getValues();
    const pins = resolvePincodes(values);
    if (!pins.pickup || !pins.delivery) {
      toast.error("Pincode resolution failed. Please verify addresses contain valid postal codes.");
      return;
    }

    setCurrentStep(1); // Show the option cards (skeletons while loading)
    const quote = await booking.requestQuote(
      buildQuoteRequest({
        flow: ServiceFlow.B2C,
        shipmentType: ShipmentType.FORWARD,
        pickupPincode: pins.pickup,
        deliveryPincode: pins.delivery,
        packages: values.packages as PackageCreate[],
        payment: buildPaymentInputs(values.payment_details, addShippingToCod),
      })
    );
    if (!quote) {
      setCurrentStep(0);
      return;
    }
    // The valuation may not have caught up with the last keystroke: trust the quote.
    if (quote.eway_bill_required && !values.payment_details.eway_bill_number) {
      form.setValue("payment_details.shipment_total_value", quote.shipment_total_value);
      form.setValue("payment_details.eway_bill_required", true);
      setCurrentStep(0);
      await form.trigger("payment_details.eway_bill_number");
      toast.error("An E-Way Bill is required for this goods value. Please add it to continue.");
    }
  };

  /** Maps the chosen card + the form to the booking body (same inputs as the quote). */
  const buildBookingPayload = (option: QuoteOption): BookingPayload => {
    const data = form.getValues();

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
    return {
      service_flow: ServiceFlow.B2C,
      service_option: option.service_option,
      expected_total: option.total_amount ?? 0,
      order_reference_id: data.order_reference_id || undefined,
      shipment_type: ShipmentType.FORWARD,
      // Delhivery flow: the order is "manifested" today; the pickup date and
      // slot are chosen later on the Pickup Request ("Add to pickup").
      requested_pickup_date: todayApiDate(),
      product_category: data.product_category,
      other_category_description: data.other_category_description || undefined,
      pickup_address_id: data.pickup_address_id || undefined,
      new_pickup_address: newPickupAddress,
      delivery_address_id: data.delivery_address_id || undefined,
      new_delivery_address: newDeliveryAddress,
      packages: data.packages as PackageCreate[],
      payment_details: {
        ...buildPaymentInputs(data.payment_details, addShippingToCod),
        hsn_code: data.payment_details.hsn_code || undefined,
        invoice_numbers: data.payment_details.invoice_number ? [data.payment_details.invoice_number] : undefined,
        invoice_date: data.payment_details.invoice_date || undefined,
        eway_bill_numbers: data.payment_details.eway_bill_number ? [data.payment_details.eway_bill_number] : undefined,
      },
      documents: data.documents ? (data.documents as PickupDocumentCreate[]) : undefined,
    };
  };

  const onConfirmBooking = () => booking.book(buildBookingPayload);

  const formValues = form.getValues();
  const pickupAddress = formValues.pickup_address_id
    ? savedAddresses.find((a) => a.id === formValues.pickup_address_id)
    : formValues.new_pickup_address;
  const deliveryAddress = formValues.delivery_address_id
    ? savedAddresses.find((a) => a.id === formValues.delivery_address_id)
    : formValues.new_delivery_address;

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

      {currentStep === 0 && (
        <ScreenGuideBanner
          guideId="b2c-forward-booking"
          title="Quick Start: Book a B2C Parcel in 3 Simple Steps"
          staffTitle="Staff Guide: Fast B2C Booking & Compliance"
          delhiveryEquivalent="Delhivery One: Orders → Create Shipment"
          steps={B2C_CUSTOMER_GUIDE_STEPS}
          staffSteps={B2C_STAFF_GUIDE_STEPS}
          isStaff={capabilities.isStaff}
        />
      )}

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
        <Form {...form}>
          <form onSubmit={(e) => {
            e.preventDefault(); // Let internal buttons handle execution transitions cleanly
          }} className="space-y-8">
            
            {currentStep === 0 ? (
              <>
                {/* TOP ROW: Order ID only (no pickup options, like Delhivery) */}
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
                  <p className="md:col-span-2 self-end text-xs text-slate-500">
                    Pickup date and slot are chosen later, when you add this order to a pickup request.
                  </p>
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
                    data-testid="booking.actions.next"
                  >
                    Find Rates <Sparkles className="h-3.5 w-3.5 text-primary" />
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
                isCod={!!form.watch("payment_details.is_cod")}
                pickup={pickupAddress}
                delivery={deliveryAddress}
              />
            )}

          </form>
        </Form>
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
