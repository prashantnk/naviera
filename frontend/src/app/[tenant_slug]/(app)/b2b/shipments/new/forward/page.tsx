// src/app/[tenant_slug]/(app)/b2b/shipments/new/forward/page.tsx
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
  PickupStrategy,
  ProductCategory,
} from "@/api_client";
import { getSupabaseClient } from "@/lib/supabase";
import { matchAddressByPincode, parseRateHandoff, type RateHandoff } from "@/lib/rate-handoff";
import { B2BForwardFormStep } from "./_components/b2b-forward-form-step";
import type { BookingPayload, QuoteOption } from "@/components/booking/booking-api";
import { buildPaymentInputs, buildQuoteRequest } from "@/components/booking/booking-inputs";
import { PriceChangedDialog } from "@/components/booking/price-changed-dialog";
import { QuoteStep } from "@/components/booking/quote-step";
import { useQuoteBooking } from "@/components/booking/use-quote-booking";
import { Button } from "@/components/ui/button";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { buildBookedOrderHref } from "@/components/pickups/next-add-to-pickup-banner";
import { todayApiDate } from "@/components/pickups/pickup-constants";
import { useTenant } from "@/components/providers/tenant-provider";
import { toIstIsoString } from "@/lib/utils";
import { b2bForwardBookingSchema, B2BForwardShipmentFormValues } from "@/lib/validations/shipment";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, Sparkles, Building2 } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState, useRef } from "react";
import { useForm, Resolver, useFieldArray } from "react-hook-form";
import { toast } from "sonner";
import { BOOKABLE_FREIGHT_PAYMENT_MODES } from "@/lib/form-options";


export default function B2BForwardBookingWizard() {
  const { routeTo, tenantSlug } = useTenant();
  const DRAFT_KEY = `shipment-draft-b2b-forward-${tenantSlug}`;

  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const hasRecoveredRef = useRef(false);
  const isSubmittedRef = useRef(false);

  // Orchestration steps: 0 = cargo details, 1 = choose a service and book
  const [currentStep, setCurrentStep] = useState(0);

  /** Clears the draft and lands on the new LR with the "Add to pickup" call to action. */
  const handleBooked = useCallback(
    (created: PickupRead) => {
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      isSubmittedRef.current = true;
      localStorage.removeItem(DRAFT_KEY);
      window.location.href = routeTo(
        created?.id ? buildBookedOrderHref(`/b2b/shipments/${created.id}`) : "/b2b/shipments"
      );
    },
    [DRAFT_KEY, routeTo]
  );
  const booking = useQuoteBooking({
    onBooked: handleBooked,
    bookingFailedMessage: "Failed to finalize B2B shipment booking.",
  });
  const isSubmitting = booking.isSubmitting;

  const form = useForm<B2BForwardShipmentFormValues>({
    resolver: zodResolver(b2bForwardBookingSchema) as unknown as Resolver<B2BForwardShipmentFormValues>,
    mode: "onChange",
    defaultValues: {
      order_reference_id: "",
      service_type: ServiceType.SURFACE_ROAD,
      shipment_type: ShipmentType.FORWARD,
      product_category: undefined,
      other_category_description: "",
      po_number: "",
      po_date: "",
      appointment_id: "",
      appointment_start: "",
      appointment_end: "",
      pickup_strategy: PickupStrategy.DEFAULT,
      is_blind_pickup: false,
      estimated_box_count: null,
      is_carriers_risk: false,
      door_delivery: false,
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
        hsn_code: "",
        invoice_numbers: [],
        invoice_date: "",
        eway_bill_numbers: [],
        eway_bill_required: false,
      },
      packages: [
        {
          length: 0,
          breadth: 0,
          height: 0,
          weight: 10.0, // Default to 10.0 kg B2B floor
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
    if (handoff.description) form.setValue("packages.0.description", handoff.description, opts);
    if (handoff.shipmentValue) form.setValue("payment_details.shipment_value", handoff.shipmentValue, opts);
    if (handoff.doorDelivery !== undefined) form.setValue("door_delivery", handoff.doorDelivery, opts);
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
        const handoff = parseRateHandoff(window.location.search, Object.values(ProductCategory));
        if (handoff && !hasRecoveredRef.current) {
          hasRecoveredRef.current = true;
          applyRateHandoff(handoff, addresses);
        }

        const savedDraft = localStorage.getItem(DRAFT_KEY);
        if (savedDraft && !hasRecoveredRef.current) {
          hasRecoveredRef.current = true;
          const parsed = JSON.parse(savedDraft);
          if (parsed.values) {
            const vals = parsed.values;
            // Sanitise enums strictly before restoration
            if (vals.service_type && !Object.values(ServiceType).includes(vals.service_type)) {
              vals.service_type = ServiceType.SURFACE_ROAD;
            }
            // Old drafts may carry TO_PAY, which is off for the MVP (WP0).
            if (vals.payment_details?.freight_payment_mode && !BOOKABLE_FREIGHT_PAYMENT_MODES.includes(vals.payment_details.freight_payment_mode)) {
              vals.payment_details.freight_payment_mode = FreightPaymentMode.PREPAID;
            }
            // Old drafts may still carry pickup date/slot; pickups are scheduled later.
            delete vals.requested_pickup_date;
            delete vals.pickup_time_slot;
            if (vals.pickup_strategy && !Object.values(PickupStrategy).includes(vals.pickup_strategy)) {
              vals.pickup_strategy = PickupStrategy.DEFAULT;
            }
            form.reset(vals);
          }
          toast.info("Recovered your unsaved B2B booking draft.");
        }
      } catch (err) {
        console.error("B2B Wizard load error:", err);
      } finally {
        setIsLoading(false);
      }
    };

    loadInitialData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantSlug]);

  // Auto-Save Draft on form updates
  useEffect(() => {
    const subscription = form.watch((values) => {
      if (isSubmitting || isSubmittedRef.current) return;

      try {
        localStorage.setItem(
          DRAFT_KEY,
          JSON.stringify({ values })
        );
      } catch (error) {
        console.warn("LocalStorage autosave blocked:", error);
      }
    });
    return () => subscription.unsubscribe();
  }, [form, DRAFT_KEY, isSubmitting]);

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
      toast.success("Document safely uploaded and logged");
    } catch (error) {
      const err = error as Error;
      toast.error(err.message || "Failed to upload document");
    } finally {
      setIsUploading(false);
    }
  };

  /** Resolves the pickup and delivery addresses (saved or new). */
  const resolveAddresses = (values: B2BForwardShipmentFormValues) => ({
    pickup: values.pickup_address_id
      ? savedAddresses.find((a) => a.id === values.pickup_address_id)
      : values.new_pickup_address,
    delivery: values.delivery_address_id
      ? savedAddresses.find((a) => a.id === values.delivery_address_id)
      : values.new_delivery_address,
  });

  /** Logismart Prime has no COD at launch (pricing Q9), so B2B LRs are always prepaid/postpaid. */
  const buildB2BPaymentInputs = (values: B2BForwardShipmentFormValues) =>
    buildPaymentInputs({ ...values.payment_details, is_cod: false }, false);

  /** Blind pickups send no boxes (counted at pickup); otherwise the measured boxes. */
  const packagesFor = (values: B2BForwardShipmentFormValues): PackageCreate[] =>
    values.is_blind_pickup ? [] : (values.packages as PackageCreate[]);

  // Step 1 -> 2: validate, then price exactly the inputs the booking will send (A-03).
  const onCompareRates = async () => {
    const isStep1Valid = await form.trigger();
    if (!isStep1Valid) {
      toast.error("Please correct all validation errors in Cargo Specs first.");
      return;
    }

    const values = form.getValues();
    const { pickup, delivery } = resolveAddresses(values);
    if (!pickup?.pincode || !delivery?.pincode) {
      toast.error("Pincode resolution failed. Please verify addresses contain valid postal codes.");
      return;
    }

    setCurrentStep(1);
    const quote = await booking.requestQuote(
      buildQuoteRequest({
        flow: ServiceFlow.B2B,
        shipmentType: ShipmentType.FORWARD,
        pickupPincode: pickup.pincode,
        deliveryPincode: delivery.pincode,
        packages: packagesFor(values),
        payment: buildB2BPaymentInputs(values),
        isBlindPickup: values.is_blind_pickup,
        estimatedBoxCount: values.is_blind_pickup ? values.estimated_box_count : null,
        doorDelivery: values.door_delivery,
        isCarriersRisk: values.is_carriers_risk,
      })
    );
    if (!quote) {
      setCurrentStep(0);
      return;
    }
    // The valuation may not have caught up with the last keystroke: trust the quote.
    const hasEwayBill = values.payment_details.eway_bill_numbers.some((num) => num.trim());
    if (quote.eway_bill_required && !hasEwayBill) {
      form.setValue("payment_details.shipment_total_value", quote.shipment_total_value);
      form.setValue("payment_details.eway_bill_required", true);
      setCurrentStep(0);
      await form.trigger("payment_details.eway_bill_numbers");
      toast.error("An E-Way Bill is required for this goods value. Please add it to continue.");
    }
  };

  /** Maps the chosen card + the form to the booking body (same inputs as the quote). */
  const buildBookingPayload = (option: QuoteOption): BookingPayload => {
    const data = form.getValues();

    // Address scoping
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

    return {
      service_flow: ServiceFlow.B2B,
      service_option: option.service_option,
      expected_total: option.total_amount ?? 0,
      door_delivery: data.door_delivery,
      order_reference_id: data.order_reference_id || undefined,
      shipment_type: ShipmentType.FORWARD,
      // Delhivery flow: no pickup options at booking; the pickup date and slot
      // are chosen on the Pickup Request ("Add to pickup").
      requested_pickup_date: todayApiDate(),
      po_number: data.po_number || undefined,
      po_date: data.po_date || undefined,
      appointment_id: data.appointment_id || undefined,
      appointment_start: toIstIsoString(data.appointment_start),
      appointment_end: toIstIsoString(data.appointment_end),
      pickup_strategy: data.pickup_strategy || undefined,
      is_blind_pickup: data.is_blind_pickup,
      estimated_box_count: data.is_blind_pickup ? data.estimated_box_count : undefined,
      is_carriers_risk: data.is_carriers_risk,
      product_category: data.product_category,
      other_category_description: data.other_category_description || undefined,
      pickup_address_id: data.pickup_address_id || undefined,
      new_pickup_address: newPickupAddress,
      delivery_address_id: data.delivery_address_id || undefined,
      new_delivery_address: newDeliveryAddress,
      packages: packagesFor(data),
      payment_details: {
        ...buildB2BPaymentInputs(data),
        hsn_code: data.payment_details.hsn_code || undefined,
        invoice_numbers: data.payment_details.invoice_numbers.length > 0 ? data.payment_details.invoice_numbers : undefined,
        invoice_date: data.payment_details.invoice_date || undefined,
        eway_bill_numbers: data.payment_details.eway_bill_numbers.length > 0 ? data.payment_details.eway_bill_numbers : undefined,
      },
      documents: data.documents ? (data.documents as PickupDocumentCreate[]) : undefined,
    };
  };

  const onConfirmBooking = () => booking.book(buildBookingPayload);
  const routeAddresses = resolveAddresses(form.getValues());
  const watchedDoorDelivery = Boolean(form.watch("door_delivery"));

  /** Switches between Door Delivery and Godown Self-Pickup in Step 2 and immediately re-quotes. */
  const handleDoorDeliveryChange = async (nextDoorDelivery: boolean) => {
    form.setValue("door_delivery", nextDoorDelivery, { shouldDirty: true });
    const values = { ...form.getValues(), door_delivery: nextDoorDelivery };
    const { pickup, delivery } = resolveAddresses(values);
    if (!pickup?.pincode || !delivery?.pincode) return;
    await booking.requestQuote(
      buildQuoteRequest({
        flow: ServiceFlow.B2B,
        shipmentType: ShipmentType.FORWARD,
        pickupPincode: pickup.pincode,
        deliveryPincode: delivery.pincode,
        packages: packagesFor(values),
        payment: buildB2BPaymentInputs(values),
        isBlindPickup: values.is_blind_pickup,
        estimatedBoxCount: values.is_blind_pickup ? values.estimated_box_count : null,
        doorDelivery: nextDoorDelivery,
        isCarriersRisk: values.is_carriers_risk,
      }),
    );
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
      {/* Wizard Header */}
      <div className="flex items-center gap-4">
        <Button variant="outline" size="icon" asChild className="h-9 w-9">
          <Link href={routeTo("/b2b/shipments")}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <span className="text-[10px] font-bold text-primary tracking-wider uppercase bg-primary/10 border border-primary/20 px-2.5 py-0.5 rounded flex items-center gap-1.5 w-fit">
            <Building2 className="h-3.5 w-3.5" /> B2B Forward Booking Wizard
          </span>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight mt-1">
            {currentStep === 0 ? "New B2B Shipment Specs" : "Choose a Service"}
          </h1>
          <p className="text-slate-500 text-xs">
            {currentStep === 0 
              ? "Specify your corporate client shipment details, invoices, and logistics strategy."
              : "Choose a service for this LR and book it."
            }
          </p>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
        <Form {...form}>
          <form onSubmit={(e) => {
            e.preventDefault();
          }} className="space-y-8">
            
            {currentStep === 0 ? (
              <>
                {/* TOP ROW: Order Reference only (no pickup options, like Delhivery) */}
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 bg-slate-50/50 p-5 rounded-xl border border-slate-100">
                  <FormField
                    control={form.control}
                    name="order_reference_id"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-bold text-slate-700">Client Reference / Order ID <span className="font-normal text-slate-400">(Optional)</span></FormLabel>
                        <FormControl>
                          <Input placeholder="e.g. B2B-ORD-9982" className="h-9 text-xs bg-white font-semibold" {...field} />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  <p className="md:col-span-2 self-end text-xs text-slate-500">
                    Pickup date and slot are chosen later, when you add this LR to a pickup request.
                  </p>
                </div>

                {/* B2B FORM STEP */}
                <B2BForwardFormStep
                  control={form.control}
                  savedAddresses={savedAddresses}
                  docFields={docFields}
                  removeDoc={removeDoc}
                  isUploading={isUploading}
                  handleFileUpload={handleFileUpload}
                />

                {/* ACTIONS */}
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
                    Compare B2B Rates <Sparkles className="h-3.5 w-3.5 text-primary" />
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
                doorDelivery={watchedDoorDelivery}
                onDoorDeliveryChange={handleDoorDeliveryChange}
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
