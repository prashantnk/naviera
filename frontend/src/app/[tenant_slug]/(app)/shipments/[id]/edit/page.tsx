// frontend/src/app/[tenant_slug]/(app)/shipments/[id]/edit/page.tsx
"use client";

import {
  AddressCreate,
  AddressRead,
  AddressScope,
  ApiError,
  FreightPaymentMode,
  ProductCategory,
  PickupUpdate,
  ServiceOption,
  ServiceType,
  ShipmentsService,
  ShipmentType,
  DimensionUnit,
  WeightUnit,
} from "@/api_client";
import { IconSelect } from "@/components/ui/icon-select";
import { RequiredMark } from "@/components/ui/form-extras";
import {
  B2C_PRODUCT_CATEGORIES,
  BOOKABLE_FREIGHT_PAYMENT_MODES,
  FREIGHT_PAYMENT_MODE_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
  SERVICE_OPTION_OPTIONS,
  toOptions,
  withCurrentValue,
} from "@/lib/form-options";
import { hasChanges, isSameValue, pickChanged } from "@/components/shipments/changed-fields";
import {
  fetchRepricePreview,
  type RepricePreview,
} from "@/components/shipments/reprice-api";
import { RepricePreviewPanel } from "@/components/shipments/reprice-preview-panel";
import { useShipmentValuation } from "@/components/booking/use-shipment-valuation";
import { formatInr } from "@/components/shipments/shipment-money";
import { useEditPackageTestIds } from "@/components/shipments/use-edit-package-testids";
import { useRepricePreview } from "@/components/shipments/use-reprice-preview";

const B2C_SERVICE_OPTIONS: readonly ServiceOption[] = [
  ServiceOption.DELHIVERY_SURFACE,
  ServiceOption.DELHIVERY_EXPRESS,
];
const TEST_ID = "shipment-edit";
import { PackageFieldset } from "@/components/forms/package-fieldset";
import { EWayBillBanner } from "@/components/forms/eway-bill-banner";
import { AddressFieldset } from "@/components/forms/address-fieldset";
import { addressSchema, ShipmentFormValues } from "@/lib/validations/shipment";
import { useTenant } from "@/components/providers/tenant-provider";
import { fetchAddressesCached, getCachedAddresses } from "@/hooks/use-addresses";
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
import { DatePicker } from "@/components/ui/date-picker";
import { format, parseISO } from "date-fns";
import { Textarea } from "@/components/ui/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Info, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { Control, Resolver, useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { extractApiErrorMessage } from "@/lib/utils";
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
  service_option: z.nativeEnum(ServiceOption).optional(),

  reason_for_return: z.string().optional(),
  payment_details: z
    .object({
      freight_payment_mode: z.nativeEnum(FreightPaymentMode).optional(),
      is_cod: z.boolean().optional(),
      cod_amount: z.number().min(0).optional(),
      shipment_value: z.number().min(0, "Value cannot be negative"),
      shipment_tax_value: z.number().default(0),
      shipment_total_value: z.number().default(0),
      add_shipping_to_cod: z.boolean().default(false),
      hsn_code: z.string().optional(),
      invoice_number: z.string().optional(),
      invoice_date: z.string().optional(), // 🔥 Added Invoice Date
      eway_bill_number: z.string().optional(),
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

  comment: z.string().optional(),
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
    (data.service_type === ServiceType.AIR ||
      data.service_option === ServiceOption.DELHIVERY_EXPRESS) &&
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
type EditPaymentValues = NonNullable<EditShipmentValues["payment_details"]>;
type EditAddressValues = NonNullable<EditShipmentValues["new_pickup_address"]>;

/** Header fields sent as-is when changed. */
const HEADER_FIELDS = [
  "order_reference_id",
  "requested_pickup_date",
  "product_category",
  "other_category_description",
  "service_type",
  "service_option",
  "reason_for_return",
] as const satisfies readonly (keyof EditShipmentValues)[];

/** Payment inputs (never the price columns: those are computed by the backend). */
const PAYMENT_FIELDS = [
  "freight_payment_mode",
  "is_cod",
  "cod_amount",
  "add_shipping_to_cod",
  "shipment_value",
  "shipment_tax_value",
  "shipment_total_value",
  "hsn_code",
  "invoice_date",
] as const satisfies readonly (keyof EditPaymentValues)[];

/**
 * Maps a transient address from the form to the API shape (address book flags included).
 *
 * @param address - Address entered in the dialog.
 * @returns `AddressCreate` for the PickupUpdate payload.
 */
function _toAddressCreate(address: EditAddressValues): AddressCreate {
  return {
    ...address,
    is_saved: address.save_to_address_book,
    scope: address.is_shared_with_team ? AddressScope.TENANT : AddressScope.PRIVATE,
  } as unknown as AddressCreate;
}

/**
 * Builds the address part of the update for one side (pickup or delivery).
 *
 * @param initial - Loaded values.
 * @param current - Values at submit time.
 * @param side - Which address.
 * @returns The changed address keys only (empty when untouched).
 */
function _changedAddress(
  initial: EditShipmentValues,
  current: EditShipmentValues,
  side: "pickup" | "delivery",
): Partial<PickupUpdate> {
  const idKey = `${side}_address_id` as const;
  const newKey = `new_${side}_address` as const;
  if (isSameValue(initial[idKey], current[idKey]) && isSameValue(initial[newKey], current[newKey])) {
    return {};
  }
  const savedId = current[idKey];
  const transient = current[newKey];
  if (savedId) return { [idKey]: savedId };
  return transient ? { [newKey]: _toAddressCreate(transient) } : {};
}

/**
 * Builds the payment part of the update: changed inputs only, with the read-model
 * singular invoice / e-way bill fields mapped to the API's list fields.
 *
 * @param initial - Loaded payment values.
 * @param current - Payment values at submit time.
 * @returns Changed payment fields, or undefined when nothing changed.
 */
function _changedPayment(
  initial: EditPaymentValues | undefined,
  current: EditPaymentValues | undefined,
): PickupUpdate["payment_details"] {
  if (!current) return undefined;
  const before = initial ?? ({} as EditPaymentValues);
  const changed: Record<string, unknown> = pickChanged(before, current, PAYMENT_FIELDS);
  if (!isSameValue(before.invoice_number, current.invoice_number)) {
    changed.invoice_numbers = current.invoice_number ? [current.invoice_number] : [];
  }
  if (!isSameValue(before.eway_bill_number, current.eway_bill_number)) {
    changed.eway_bill_numbers = current.eway_bill_number ? [current.eway_bill_number] : [];
  }
  for (const key of ["hsn_code", "invoice_date"] as const) {
    if (key in changed && !changed[key]) changed[key] = null;
  }
  return hasChanges(changed) ? (changed as PickupUpdate["payment_details"]) : undefined;
}

/**
 * Diffs the form against the loaded snapshot and returns a PickupUpdate holding only what
 * changed (plan B14: "send only changed fields"). The audit comment is always attached.
 *
 * @param initial - Values loaded from the API.
 * @param current - Values at submit time.
 * @returns The update and whether any business field changed.
 */
function _buildEditChange(
  initial: EditShipmentValues,
  current: EditShipmentValues,
): { change: PickupUpdate; changed: boolean } {
  const header = pickChanged(initial, current, HEADER_FIELDS) as Partial<PickupUpdate>;
  if ("other_category_description" in header && !header.other_category_description) {
    header.other_category_description = null;
  }
  const payment = _changedPayment(initial.payment_details, current.payment_details);
  const packages = isSameValue(initial.packages, current.packages)
    ? undefined
    : current.packages.map((pkg) => ({ ...pkg, id: pkg.id || null }));
  const body: PickupUpdate = {
    ...header,
    ..._changedAddress(initial, current, "pickup"),
    ..._changedAddress(initial, current, "delivery"),
    ...(payment ? { payment_details: payment } : {}),
    ...(packages ? { packages } : {}),
  };
  return {
    change: {
      ...body,
      comment: current.comment?.trim() || "Order details updated",
      is_public: false,
    },
    changed: hasChanges(body as Record<string, unknown>),
  };
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

export default function EditShipmentPage() {
  const params = useParams();
  const router = useRouter();
  const shipmentId = params.id as string;
  const { routeTo, tenant, tenantSlug } = useTenant();
  const formRef = useRef<HTMLFormElement>(null);

  const [loading, setLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [shipmentType, setShipmentType] = useState<ShipmentType | null>(null);
  const [savedAddresses, setSavedAddresses] = useState<AddressRead[]>(
    () => getCachedAddresses(tenantSlug) ?? []
  );

  // Snapshot of the loaded values: the diff base for "send only changed fields".
  const [initialValues, setInitialValues] = useState<EditShipmentValues | null>(null);
  const [currentCharges, setCurrentCharges] = useState<number | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);

  useEditPackageTestIds(formRef, !loading, TEST_ID);

  useEffect(() => {
    fetchAddressesCached(tenantSlug)
      .then(setSavedAddresses)
      .catch(console.error);
  }, [tenantSlug]);

  const form = useForm<EditShipmentValues>({
    resolver: zodResolver(editShipmentSchema) as unknown as Resolver<EditShipmentValues>,
    defaultValues: {
      order_reference_id: "",
      requested_pickup_date: "",
      product_category: undefined as unknown as ProductCategory,
      other_category_description: "",
      service_type: undefined,
      service_option: undefined,

      reason_for_return: "",
      payment_details: {
        shipment_value: 0,
        shipment_tax_value: 0,
        shipment_total_value: 0,
        add_shipping_to_cod: false,
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

  const watchedValues = useWatch({ control: form.control }) as EditShipmentValues;
  // D-06: the goods total and the e-way bill rule come from the backend valuation.
  const { valuation } = useShipmentValuation(
    form.watch("payment_details.shipment_value"),
    form.watch("payment_details.shipment_tax_value"),
    (result) => form.setValue("payment_details.shipment_total_value", result.shipment_total_value),
  );
  const watchedFreightMode = form.watch("payment_details.freight_payment_mode");

  // Only bookable choices (no TO_PAY: WP0; no "Commercial" on B2C: A-02), plus the
  // shipment's own saved value so a legacy booking still renders.
  const savedCategory = initialValues?.product_category;
  const savedFreightMode = initialValues?.payment_details?.freight_payment_mode;
  const savedServiceOption = initialValues?.service_option;
  const categorySelectOptions = useMemo(
    () => toOptions(PRODUCT_CATEGORY_OPTIONS, withCurrentValue(B2C_PRODUCT_CATEGORIES, savedCategory)),
    [savedCategory],
  );
  const payerSelectOptions = useMemo(
    () => toOptions(FREIGHT_PAYMENT_MODE_OPTIONS, withCurrentValue(BOOKABLE_FREIGHT_PAYMENT_MODES, savedFreightMode)),
    [savedFreightMode],
  );
  const serviceOptionSelectOptions = useMemo(
    () => toOptions(SERVICE_OPTION_OPTIONS, withCurrentValue(B2C_SERVICE_OPTIONS, savedServiceOption)),
    [savedServiceOption],
  );
  const watchedIsCod = form.watch("payment_details.is_cod");

  const liveChange = useMemo(() => {
    if (!initialValues || !watchedValues?.packages) return null;
    const { change, changed } = _buildEditChange(initialValues, watchedValues);
    if (!changed || !_isReadyForPreview(change)) return null;
    return change;
  }, [initialValues, watchedValues]);

  const livePreview = useRepricePreview(shipmentId, liveChange, tenantSlug);

  // We no longer calculate shipment_total_value dynamically on the frontend.
  // The frontend solely reads these values from the backend API payload.

  useEffect(() => {
    // Ignore a response that arrives after this effect was torn down (React Strict Mode
    // runs effects twice in dev): a late reset would wipe what the user already typed.
    let cancelled = false;
    const fetchShipment = async () => {
      try {
        const data = await ShipmentsService.getShipmentDetails(shipmentId);
        if (cancelled) return;
        setShipmentType(data.shipment_type);

        setCurrentCharges(data.payment_details?.total_logistics_cost ?? null);

        // Cast: the API returns optional dimensions / address scope that the form schema
        // fills with defaults on validation; this snapshot is only the diff base.
        const loadedValues = {
          order_reference_id: data.order_reference_id || "",
          requested_pickup_date: data.requested_pickup_date,
          product_category: data.product_category,
          other_category_description: data.other_category_description || "",
          service_type: data.service_type,
          service_option:
            data.service_option ??
            (data.service_type === ServiceType.AIR
              ? ServiceOption.DELHIVERY_EXPRESS
              : ServiceOption.DELHIVERY_SURFACE),

          reason_for_return: data.reason_for_return || "",
          payment_details: data.payment_details
            ? {
                freight_payment_mode: data.payment_details.freight_payment_mode,
                is_cod: data.payment_details.is_cod,
                cod_amount: data.payment_details.cod_amount,
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
            dimension_unit: p.dimension_unit as DimensionUnit,
            weight: p.weight,
            weight_unit: p.weight_unit as WeightUnit,
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
        } as EditShipmentValues;
        form.reset(loadedValues);
        setInitialValues(loadedValues);
        setLoading(false);
      } catch {
        if (cancelled) return;
        toast.error("Failed to load shipment details.");
        setLoading(false);
      }
    };
    fetchShipment();
    return () => {
      cancelled = true;
    };
  }, [shipmentId, form]);

  /**
   * Saves the changed fields. The backend re-prices only when a price input changed.
   *
   * @param change - PickupUpdate holding only the changed fields.
   */
  const saveChange = async (change: PickupUpdate) => {
    setIsSubmitting(true);
    try {
      await ShipmentsService.updateShipment(shipmentId, change);
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      toast.success("Shipment updated successfully!");
      router.push(routeTo(`/shipments/${shipmentId}`));
    } catch (error) {
      const apiError = error as ApiError;
      // FastAPI 422 arrays become one readable line; H-7 / H-8 / H-12 refusals arrive as `detail`.
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

  /**
   * Shows each backend refusal next to its field when the field exists in this form.
   *
   * @param result - Server preview.
   */
  const flagRejectedFields = (result: RepricePreview) => {
    for (const item of result.rejected_fields) {
      form.setError(item.field as keyof EditShipmentValues, { type: item.rule, message: item.message });
      if (item.field === "service_type") {
        form.setError("service_option", { type: item.rule, message: item.message });
      }
    }
  };

  const onSubmit = async (data: EditShipmentValues) => {
    if (!initialValues) return;
    const { change, changed } = _buildEditChange(initialValues, data);
    if (!changed) {
      toast.info("No changes to save.");
      return;
    }
    setIsPreviewing(true);
    try {
      const result = livePreview.preview ?? (await fetchRepricePreview(shipmentId, change, tenantSlug));
      if (result.rejected_fields.length > 0) {
        flagRejectedFields(result);
        toast.error(result.rejected_fields.map((item) => item.message).join(" | "));
        return;
      }
    } catch (err) {
      toast.error(extractApiErrorMessage(err, "Could not check the revised charges."));
      return;
    } finally {
      setIsPreviewing(false);
    }
    await saveChange(change);
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
          <form ref={formRef} onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">
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
              <FormField
                control={form.control}
                name="service_option"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Shipping Mode</FormLabel>
                    <div
                      data-testid={`${TEST_ID}.form.service-type`}
                      data-service-option-testid={`${TEST_ID}.form.service-option`}
                    >
                      <IconSelect
                        options={serviceOptionSelectOptions}
                        value={field.value}
                        onValueChange={field.onChange}
                        placeholder="Select shipping mode"
                      />
                    </div>
                    <FormDescription className="text-[10px] text-slate-400">
                      Can be changed only before pickup.
                    </FormDescription>
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
                    <FormLabel>
                      Product Category
                      <RequiredMark />
                    </FormLabel>
                    <FormControl>
                      <IconSelect
                        options={categorySelectOptions}
                        value={field.value}
                        onValueChange={field.onChange}
                        placeholder="Select category"
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
                      <FormLabel>Custom Category Description <RequiredMark /></FormLabel>
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
                <div className="space-y-2">
                  <span className="text-sm font-medium leading-none">Shipping Charges</span>
                  <div className="flex h-9 items-center rounded-md border border-slate-200 bg-white px-3">
                    <span
                      data-testid={`${TEST_ID}.financials.current-charges`}
                      className="font-bold text-primary"
                    >
                      {formatInr(currentCharges)}
                    </span>
                  </div>
                  <p className="text-[10px] text-slate-400">
                    Worked out by the system. Changes are shown for review before saving.
                  </p>
                </div>

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
                          readOnly
                          tabIndex={-1}
                          aria-readonly="true"
                          data-testid={`${TEST_ID}.form.goods-total`}
                          className="bg-slate-50 font-bold text-slate-800 border-slate-300 cursor-default"
                          {...field}
                        />
                      </FormControl>
                      <FormDescription className="text-[10px] text-slate-500 font-semibold">
                        Goods value + goods tax, calculated for you.
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
                        <FormControl>
                          <IconSelect
                            options={payerSelectOptions}
                            value={field.value}
                            onValueChange={field.onChange}
                            placeholder="Choose who pays"
                          />
                        </FormControl>
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
                <div className="bg-sky-50 border border-sky-200/60 p-4 rounded-lg flex items-start space-x-3 text-sky-800 animate-in fade-in duration-200">
                  <Info className="h-5 w-5 text-sky-600 shrink-0 mt-0.5" />
                  <div className="text-xs space-y-1">
                    <p className="font-bold">Receiver Pays Shipping Charges (To Pay Mode)</p>
                    <p className="text-sky-700">
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
                              data-testid={`${TEST_ID}.form.cod-amount`}
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
                                  <span className="text-[10px] font-semibold text-sky-600 block mt-0.5">
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

                  {/* E-Way Bill card: shown when the backend valuation requires one (D-06) */}
                  {valuation?.eway_bill_required && (
                    <div className="space-y-4 mt-4">
                      <EWayBillBanner tenant={tenant} />
                      <FormField
                        control={form.control}
                        name="payment_details.eway_bill_number"
                        render={({ field }) => (
                          <FormItem className="bg-white p-4 rounded-lg border border-slate-200">
                            <FormLabel className="text-slate-900 font-semibold">
                              E-Way Bill Number <RequiredMark />
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
              <div data-testid={`${TEST_ID}.form.packages`}>
                <PackageFieldset
                  control={form.control}
                  isReverse={isReverse}
                  testIdPrefix={`${TEST_ID}.form`}
                />
              </div>
            </div>

            <div className="border-t border-slate-200 pt-6">
              <FormField
                control={form.control}
                name="comment"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Reason for Edit (Audit Log)</FormLabel>
                    <FormControl>
                      <Textarea
                        placeholder="e.g. Corrected actual weight after warehouse scan."
                        className="resize-none"
                        data-testid={`${TEST_ID}.form.comment`}
                        {...field}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            {/* Revised charges preview (server preview, Zero Frontend Math) */}
            <RepricePreviewPanel
              preview={livePreview.preview}
              loading={livePreview.loading}
              error={livePreview.error}
              testIdPrefix={`${TEST_ID}.preview`}
            />

            <div className="flex justify-end pt-4">
              <Button
                type="submit"
                data-testid={`${TEST_ID}.actions.save`}
                disabled={
                  isSubmitting ||
                  isPreviewing ||
                  Boolean(livePreview.preview?.rejected_fields.length)
                }
                className="w-full sm:w-auto"
              >
                {isSubmitting || isPreviewing ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    {isPreviewing ? "Checking charges" : "Saving"}
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
