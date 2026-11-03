"use client";

import {
  AddressesService,
  AddressCreate,
  AddressRead,
  ShipmentsService,
  PickupUpdate,
  PickupRead,
  DocumentType,
  ShipmentType,
  FreightPaymentMode,
  DimensionUnit,
  WeightUnit,
} from "@/api_client";
import { getSupabaseClient } from "@/lib/supabase";
import { B2BForwardFormStep } from "../../new/forward/_components/b2b-forward-form-step";
import { B2BReverseFormStep } from "../../new/reverse/_components/b2b-reverse-form-step";
import { Button } from "@/components/ui/button";
import { Form, FormField, FormItem, FormLabel, FormControl, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { RequiredMark } from "@/components/ui/form-extras";
import { DatePicker } from "@/components/ui/date-picker";
import { format, parseISO } from "date-fns";
import { useTenant } from "@/components/providers/tenant-provider";
import {
  b2bForwardShipmentSchema,
  b2bReverseShipmentSchema,
  B2BForwardShipmentFormValues,
  B2BReverseShipmentFormValues,
} from "@/lib/validations/shipment";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, Save, Building2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm, Resolver, useFieldArray, Control, FieldArrayWithId, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { extractApiErrorMessage, toIstIsoString } from "@/lib/utils";
import { hasChanges, isSameValue, pickChanged } from "@/components/shipments/changed-fields";
import {
  fetchRepricePreview,
} from "@/components/shipments/reprice-api";
import { RepricePreviewPanel } from "@/components/shipments/reprice-preview-panel";
import { useEditPackageTestIds } from "@/components/shipments/use-edit-package-testids";
import { useRepricePreview } from "@/components/shipments/use-reprice-preview";

const TEST_ID = "shipment-edit";

/**
 * One form serves forward and reverse LRs: validate with the schema that matches
 * the loaded `shipment_type` (reverse LRs need `reason_for_return`, have no e-way bill rule).
 */
const forwardResolver = zodResolver(b2bForwardShipmentSchema) as unknown as Resolver<B2BForwardShipmentFormValues>;
const reverseResolver = zodResolver(b2bReverseShipmentSchema) as unknown as Resolver<B2BForwardShipmentFormValues>;
const b2bEditResolver: Resolver<B2BForwardShipmentFormValues> = (values, context, options) =>
  (values as { shipment_type?: ShipmentType }).shipment_type === ShipmentType.REVERSE
    ? reverseResolver(values, context, options)
    : forwardResolver(values, context, options);

/**
 * Blind pickups have no manifested boxes. The form schema still needs one package row,
 * so we hold a hidden placeholder (the B2B floor weight) that is never sent to the API.
 */
const BLIND_PLACEHOLDER_WEIGHT_KG = 10;
const BLIND_PLACEHOLDER_PACKAGE = {
  length: 0,
  breadth: 0,
  height: 0,
  dimension_unit: DimensionUnit.CM,
  weight: BLIND_PLACEHOLDER_WEIGHT_KG,
  weight_unit: WeightUnit.KG,
  box_count: 1,
  is_fragile: false,
  description: "",
};

/** Form values incl. the reverse-only fields this page also edits. */
type B2BEditValues = B2BForwardShipmentFormValues &
  Partial<Omit<B2BReverseShipmentFormValues, "shipment_type">> & {
    pickup_qc_params?: string[] | null;
  };
type B2BPaymentValues = B2BEditValues["payment_details"];

/** Header fields sent as-is when changed. */
const HEADER_FIELDS = [
  "order_reference_id",
  "requested_pickup_date",
  "pickup_time_slot",
  "service_type",
  "product_category",
  "other_category_description",
  "po_number",
  "po_date",
  "appointment_id",
  "appointment_start",
  "appointment_end",
  "pickup_strategy",
  "is_blind_pickup",
  "estimated_box_count",
  "is_carriers_risk",
  "reason_for_return",
  "qc_required",
  "qc_notes",
  "pickup_qc_params",
  "documents",
] as const satisfies readonly (keyof B2BEditValues)[];

/** Payment inputs (never the price columns: those are computed by the backend). */
const PAYMENT_FIELDS = [
  "freight_payment_mode",
  "is_cod",
  "cod_amount",
  "shipment_value",
  "shipment_tax_value",
  "shipment_total_value",
  "hsn_code",
  "invoice_numbers",
  "invoice_date",
  "eway_bill_numbers",
] as const satisfies readonly (keyof B2BPaymentValues)[];

/**
 * Address part of the update for one side: the saved id or the transient address,
 * only when that side changed.
 *
 * @param initial - Loaded values.
 * @param current - Values at submit time.
 * @param side - Which address.
 * @returns Changed address keys (empty when untouched).
 */
function _changedAddress(
  initial: B2BEditValues,
  current: B2BEditValues,
  side: "pickup" | "delivery",
): Partial<PickupUpdate> {
  const idKey = `${side}_address_id` as const;
  const newKey = `new_${side}_address` as const;
  if (isSameValue(initial[idKey], current[idKey]) && isSameValue(initial[newKey], current[newKey])) {
    return {};
  }
  if (current[idKey]) return { [idKey]: current[idKey] };
  return current[newKey] ? { [newKey]: current[newKey] as unknown as AddressCreate } : {};
}

/**
 * Diffs the form against the loaded snapshot (plan B14: send only changed fields).
 * Blind LRs never send the hidden placeholder package.
 *
 * @param initial - Values loaded from the API.
 * @param current - Values at submit time.
 * @param addShippingToCod - Current "add shipping to COD" toggle (kept outside the form).
 * @returns The PickupUpdate and whether anything changed.
 */
function _buildB2BChange(
  initial: B2BEditValues,
  current: B2BEditValues,
  addShippingToCod: boolean,
): { change: PickupUpdate; changed: boolean } {
  const header = pickChanged(initial, current, HEADER_FIELDS) as Partial<PickupUpdate>;
  const payment: Record<string, unknown> = pickChanged(
    initial.payment_details,
    current.payment_details,
    PAYMENT_FIELDS,
  );
  if (!isSameValue(initial.payment_details.add_shipping_to_cod, addShippingToCod)) {
    payment.add_shipping_to_cod = addShippingToCod;
  }
  const packagesChanged = !current.is_blind_pickup && !isSameValue(initial.packages, current.packages);
  const change: PickupUpdate = {
    ...header,
    ..._changedAddress(initial, current, "pickup"),
    ..._changedAddress(initial, current, "delivery"),
    ...(hasChanges(payment) ? { payment_details: payment as PickupUpdate["payment_details"] } : {}),
    ...(packagesChanged ? { packages: current.packages as PickupUpdate["packages"] } : {}),
  };
  return { change, changed: hasChanges(change as Record<string, unknown>) };
}

/**
 * Ensures changed package fields are valid numbers before firing a live preview request,
 * avoiding transient HTTP 422s while the user is mid-keystroke.
 */
function _isReadyForPreview(change: PickupUpdate): boolean {
  if (!change.packages) return true;
  if (change.packages.length === 0) return false;
  return change.packages.every(
    (pkg) =>
      typeof pkg.weight === "number" &&
      Number.isFinite(pkg.weight) &&
      pkg.weight > 0 &&
      typeof pkg.box_count === "number" &&
      pkg.box_count >= 1 &&
      typeof pkg.length === "number" &&
      pkg.length >= 0 &&
      typeof pkg.breadth === "number" &&
      pkg.breadth >= 0 &&
      typeof pkg.height === "number" &&
      pkg.height >= 0,
  );
}

export default function B2BForwardEditPage() {
  const params = useParams();
  const shipmentId = params.id as string;
  const router = useRouter();
  const { routeTo, tenantSlug } = useTenant();
  const formRef = useRef<HTMLFormElement>(null);

  const [shipment, setShipment] = useState<PickupRead | null>(null);
  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [addShippingToCod, setAddShippingToCod] = useState(false);

  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);

  // Snapshot of the loaded values: the diff base for "send only changed fields".
  const [initialValues, setInitialValues] = useState<B2BEditValues | null>(null);

  useEditPackageTestIds(formRef, !isLoading, TEST_ID);

  const form = useForm<B2BForwardShipmentFormValues>({
    resolver: b2bEditResolver,
    mode: "onChange",
  });
  const isReverse = shipment?.shipment_type === ShipmentType.REVERSE;
  const watchedValues = useWatch({ control: form.control }) as B2BEditValues;

  const liveChange = useMemo(() => {
    if (!initialValues || !watchedValues?.packages) return null;
    const { change, changed } = _buildB2BChange(initialValues, watchedValues, addShippingToCod);
    if (!changed || !_isReadyForPreview(change)) return null;
    return change;
  }, [initialValues, watchedValues, addShippingToCod]);

  const livePreview = useRepricePreview(shipmentId, liveChange, tenantSlug);

  const { fields: docFields, remove: removeDoc, append: appendDoc } = useFieldArray({
    control: form.control,
    name: "documents",
  });
  
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    async function init() {
      try {
        const [addresses, shipData] = await Promise.all([
          AddressesService.listSavedAddresses(null, tenantSlug),
          ShipmentsService.getShipmentDetails(shipmentId, tenantSlug),
        ]);
        setSavedAddresses(addresses);
        setShipment(shipData);
        
        // Populate form (including reverse-only fields when editing a B2B Reverse LR)
        const resetValues = Object.assign(
          {
            order_reference_id: shipData.order_reference_id || "",
            requested_pickup_date: shipData.requested_pickup_date?.split("T")[0] || "",
            pickup_time_slot: shipData.pickup_time_slot || undefined,
            service_type: shipData.service_type,
            shipment_type: (shipData.shipment_type || ShipmentType.FORWARD) as ShipmentType.FORWARD,
            product_category: shipData.product_category,
            other_category_description: shipData.other_category_description || "",
            po_number: shipData.po_number || "",
            po_date: shipData.po_date?.split("T")[0] || "",
            appointment_id: shipData.appointment_id || "",
            appointment_start: toIstIsoString(shipData.appointment_start) || "",
            appointment_end: toIstIsoString(shipData.appointment_end) || "",
            pickup_strategy: shipData.pickup_strategy || undefined,
            is_blind_pickup: shipData.is_blind_pickup,
            estimated_box_count: shipData.estimated_box_count || null,
            is_carriers_risk: shipData.is_carriers_risk,
            payment_details: {
              freight_payment_mode: shipData.payment_details?.freight_payment_mode || FreightPaymentMode.PREPAID,
              is_cod: shipData.payment_details?.is_cod || false,
              cod_amount: shipData.payment_details?.cod_amount || 0,
              add_shipping_to_cod: shipData.payment_details?.add_shipping_to_cod || false,
              shipment_value: shipData.payment_details?.shipment_value || 0,
              shipment_tax_value: shipData.payment_details?.shipment_tax_value || 0,
              shipment_total_value: shipData.payment_details?.shipment_total_value || 0,
              tax_amount: shipData.payment_details?.tax_amount || 0,
              base_freight: shipData.payment_details?.base_freight || 0,
              total_logistics_cost: shipData.payment_details?.total_logistics_cost || 0,
              hsn_code: shipData.payment_details?.hsn_code || "",
              invoice_numbers: shipData.payment_details?.invoice_numbers || [],
              invoice_date: shipData.payment_details?.invoice_date || "",
              eway_bill_numbers: shipData.payment_details?.eway_bill_numbers || [],
            },
            pickup_address_id: shipData.pickup_address?.is_saved ? shipData.pickup_address.id : undefined,
            delivery_address_id: shipData.delivery_address?.is_saved ? shipData.delivery_address.id : undefined,
            new_pickup_address:
              shipData.pickup_address && !shipData.pickup_address.is_saved
                ? {
                    name: shipData.pickup_address.name,
                    company_name: shipData.pickup_address.company_name || "",
                    phone: shipData.pickup_address.phone,
                    email: shipData.pickup_address.email || "",
                    address_line1: shipData.pickup_address.address_line1,
                    address_line2: shipData.pickup_address.address_line2 || "",
                    city: shipData.pickup_address.city,
                    state: shipData.pickup_address.state,
                    pincode: shipData.pickup_address.pincode,
                    gstin: shipData.pickup_address.gstin || "",
                  }
                : undefined,
            new_delivery_address:
              shipData.delivery_address && !shipData.delivery_address.is_saved
                ? {
                    name: shipData.delivery_address.name,
                    company_name: shipData.delivery_address.company_name || "",
                    phone: shipData.delivery_address.phone,
                    email: shipData.delivery_address.email || "",
                    address_line1: shipData.delivery_address.address_line1,
                    address_line2: shipData.delivery_address.address_line2 || "",
                    city: shipData.delivery_address.city,
                    state: shipData.delivery_address.state,
                    pincode: shipData.delivery_address.pincode,
                    gstin: shipData.delivery_address.gstin || "",
                  }
                : undefined,
            packages:
              shipData.is_blind_pickup && shipData.packages.length === 0
                ? [BLIND_PLACEHOLDER_PACKAGE]
                : shipData.packages.map((pkg) => ({
                    length: pkg.length,
                    breadth: pkg.breadth,
                    height: pkg.height,
                    weight: pkg.weight,
                    dimension_unit: pkg.dimension_unit,
                    weight_unit: pkg.weight_unit,
                    box_count: pkg.box_count || 1,
                    description: pkg.description || "",
                  })),
            documents:
              shipData.documents?.map((doc) => ({
                document_type: doc.document_type as DocumentType,
                file_url: doc.file_url,
                file_name: doc.file_name,
              })) || [],
          },
          {
            reason_for_return: shipData.reason_for_return || "",
            qc_required: Boolean(shipData.qc_required),
            qc_notes: shipData.qc_notes || "",
            pickup_qc_params: (shipData as PickupRead & { pickup_qc_params?: string[] | null }).pickup_qc_params || undefined,
          },
        );
        form.reset(resetValues);
        setInitialValues(resetValues as B2BEditValues);
        setAddShippingToCod(shipData.payment_details?.add_shipping_to_cod || false);
      } catch (error) {
        console.error("Failed to load shipment details", error);
        toast.error("Could not load shipment details.");
      } finally {
        setIsLoading(false);
      }
    }
    init();
  }, [shipmentId, tenantSlug, form]);

  const handleFileUpload = async (
    e: React.ChangeEvent<HTMLInputElement>,
    docType: DocumentType = DocumentType.OTHER,
  ) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      toast.error("File size must be under 5MB");
      return;
    }

    setIsUploading(true);
    try {
      const supabase = getSupabaseClient(tenantSlug);
      const cleanFileName = file.name.replace(/[^a-zA-Z0-9.-]/g, "_");
      const fileName = `${Date.now()}_${cleanFileName}`;
      const filePath = `${tenantSlug}/${fileName}`;

      const { error } = await supabase.storage.from("documents").upload(filePath, file, { upsert: true });

      if (error) throw error;

      appendDoc({
        document_type: docType,
        file_url: filePath,
        file_name: file.name,
      });
      toast.success("Document uploaded to preview stack");
    } catch (err: unknown) {
      console.error(err);
      toast.error("Failed to upload document: " + extractApiErrorMessage(err, "Upload failed"));
    } finally {
      setIsUploading(false);
    }
  };

  /**
   * Saves the changed fields. The backend re-prices only when a price input changed.
   *
   * @param change - PickupUpdate holding only the changed fields.
   */
  const saveChange = async (change: PickupUpdate) => {
    setIsSubmitting(true);
    try {
      await ShipmentsService.updateShipment(shipmentId, change, tenantSlug);
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      toast.success("Shipment updated successfully.");
      router.push(routeTo(`/b2b/shipments/${shipmentId}`));
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to update shipment."));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleSaveChanges = async () => {
    const valid = await form.trigger();
    if (!valid) {
      toast.error("Please fill all required fields correctly.");
      return;
    }
    if (!initialValues) return;

    const { change, changed } = _buildB2BChange(
      initialValues,
      form.getValues() as B2BEditValues,
      addShippingToCod,
    );
    if (!changed) {
      toast.info("No changes to save.");
      return;
    }

    setIsPreviewing(true);
    try {
      const result = livePreview.preview ?? (await fetchRepricePreview(shipmentId, change, tenantSlug));
      if (result.rejected_fields.length > 0) {
        toast.error(result.rejected_fields.map((item) => item.message).join(" | "));
        return;
      }
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Could not check the revised charges."));
      return;
    } finally {
      setIsPreviewing(false);
    }
    await saveChange(change);
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
      <div className="flex items-center gap-4">
        <Button variant="outline" size="icon" asChild className="h-9 w-9">
          <Link href={routeTo(`/b2b/shipments/${shipmentId}`)}>
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div>
          <span className="text-[10px] font-bold text-primary tracking-wider uppercase bg-primary/10 border border-primary/20 px-2.5 py-0.5 rounded flex items-center gap-1.5 w-fit">
            <Building2 className="h-3.5 w-3.5" /> Edit Shipment
          </span>
          <h1 className="text-2xl font-bold text-slate-900 tracking-tight mt-1">
            Editing B2B Shipment: {shipment?.tracking_id}
          </h1>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
        <Form {...form}>
          <form ref={formRef} onSubmit={(e) => { e.preventDefault(); handleSaveChanges(); }} className="space-y-8">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6 bg-slate-50/50 p-5 rounded-xl border border-slate-100">
              <FormField control={form.control} name="order_reference_id" render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-bold text-slate-700">Client Reference / Order ID <RequiredMark /></FormLabel>
                    <FormControl><Input className="h-9 text-xs bg-white font-semibold" {...field} value={field.value || ""} /></FormControl>
                    <FormMessage />
                  </FormItem>
                )} />

              <FormField control={form.control} name="requested_pickup_date" render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-bold text-slate-700">Requested Pickup Date <RequiredMark /></FormLabel>
                    <FormControl>
                      <DatePicker date={field.value ? parseISO(field.value) : undefined} setDate={(date) => field.onChange(date ? format(date, "yyyy-MM-dd") : "")} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )} />
            </div>

            {isReverse ? (
              <B2BReverseFormStep
                control={form.control as unknown as Control<B2BReverseShipmentFormValues>}
                savedAddresses={savedAddresses}
                docFields={docFields as unknown as FieldArrayWithId<B2BReverseShipmentFormValues, "documents">[]}
                removeDoc={removeDoc}
                isUploading={isUploading}
                handleFileUpload={handleFileUpload}
              />
            ) : (
              <B2BForwardFormStep
                control={form.control}
                savedAddresses={savedAddresses}
                docFields={docFields}
                removeDoc={removeDoc}
                isUploading={isUploading}
                handleFileUpload={handleFileUpload}
              />
            )}

            <RepricePreviewPanel
              preview={livePreview.preview}
              loading={livePreview.loading}
              error={livePreview.error}
              testIdPrefix={`${TEST_ID}.preview`}
            />

            <div className="border-t border-slate-100 pt-6 flex items-center justify-end">
              <Button
                type="submit"
                data-testid={`${TEST_ID}.actions.save`}
                disabled={
                  isPreviewing ||
                  isSubmitting ||
                  Boolean(livePreview.preview?.rejected_fields.length)
                }
                className="font-bold bg-slate-900 hover:bg-slate-800 text-white flex items-center justify-center gap-2 px-6 py-2 h-9 rounded-lg shadow-md w-full sm:w-auto"
              >
                {(isPreviewing || isSubmitting) ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {isPreviewing ? "Checking charges" : "Save Changes"}
              </Button>
            </div>
          </form>
        </Form>
      </div>
    </div>
  );
}