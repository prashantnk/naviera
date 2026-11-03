// frontend/src/app/[tenant_slug]/(app)/b2b/rate-calculator/page.tsx
"use client";

import React, { useState, useEffect } from "react";
import { useForm, useFieldArray } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import * as z from "zod";
import {
  ProductCategory,
  FreightPaymentMode,
  DimensionUnit,
  WeightUnit,
  PackageCreate,
  ServiceFlow,
  ShipmentType,
} from "@/api_client";
import { fetchQuotes, type QuoteResponse, type ServiceOption } from "@/components/booking/booking-api";
import { buildPaymentInputs, buildQuoteRequest } from "@/components/booking/booking-inputs";
import {
  DeliveryModeToggleBar,
  PriceBreakup,
  ServiceOptionCard,
  defaultSelection,
  findSelectedOption,
} from "@/components/booking/quote-step";
import { extractApiErrorMessage } from "@/lib/utils";
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
import { IconSelect } from "@/components/ui/icon-select";
import { RequiredMark } from "@/components/ui/form-extras";
import {
  B2C_PRODUCT_CATEGORIES,
  BOOKABLE_FREIGHT_PAYMENT_MODES,
  FREIGHT_PAYMENT_MODE_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
  toOptions,
} from "@/lib/form-options";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Calculator,
  Loader2,
  AlertCircle,
  Box,
  Plus,
  Trash2,
  Truck,
  IndianRupee,
  ArrowRight,
  Warehouse,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { buildRateHandoffQuery } from "@/lib/rate-handoff";

/**
 * This page serves both `/b2b/rate-calculator` (B2B Cargo, LTL) and
 * `/rate-calculator` (B2C Express, which re-exports it). The active flow is
 * derived from the URL so B2C merchants get B2C pricing (no 10 kg cargo floor
 * or docket charge) and are routed to the B2C booking wizard.
 */
const B2B_PATH_SEGMENT = "/b2b/";

/**
 * Returns true when the current pathname belongs to the B2B Cargo flow.
 *
 * @param pathname - Current browser pathname (path mode or subdomain mode).
 * @returns Whether the calculator should quote B2B cargo rates.
 */
function isB2BCalculatorPath(pathname: string | null): boolean {
  return (pathname || "").includes(B2B_PATH_SEGMENT);
}

/**
 * Serialises the calculator inputs (not prices) for the booking wizard hand-off.
 * Only the first box type is passed; the wizard lets the merchant add more.
 *
 * @param values - Current calculator form values.
 * @returns Query string understood by `parseRateHandoff`.
 */
function buildBookingHandoffQuery(values: RateCalculatorFormValues): string {
  const firstBox = values.is_blind_pickup ? undefined : values.packages[0];
  return buildRateHandoffQuery({
    originPincode: values.pickup_pincode,
    destinationPincode: values.delivery_pincode,
    length: firstBox?.length,
    breadth: firstBox?.breadth,
    height: firstBox?.height,
    weightKg: firstBox?.weight,
    boxCount: firstBox?.box_count,
    productCategory: values.product_category,
    isCod: values.is_cod,
    codAmount: values.cod_amount,
    shipmentValue: values.shipment_total_value,
    doorDelivery: values.door_delivery,
  });
}

// --- Category Labels ---
const B2B_CATEGORY_SELECT_OPTIONS = toOptions(PRODUCT_CATEGORY_OPTIONS);
// B2C calculator: no "Commercial Goods" (a B2B Cargo category, audit A-02).
const B2C_CATEGORY_SELECT_OPTIONS = toOptions(PRODUCT_CATEGORY_OPTIONS, B2C_PRODUCT_CATEGORIES);
// TO_PAY is off for the MVP (WP0).
const PAYER_SELECT_OPTIONS = toOptions(FREIGHT_PAYMENT_MODE_OPTIONS, BOOKABLE_FREIGHT_PAYMENT_MODES);

// --- Volumetric Safety Net Defaults ---
const CATEGORY_DEFAULTS: Record<
  string,
  { length: number; breadth: number; height: number; weight: number }
> = {
  [ProductCategory.ELECTRONICS]: {
    length: 30,
    breadth: 25,
    height: 15,
    weight: 1.0,
  },
  [ProductCategory.APPAREL]: {
    length: 30,
    breadth: 25,
    height: 5,
    weight: 0.5,
  },
  [ProductCategory.DOCUMENTS]: {
    length: 25,
    breadth: 15,
    height: 1,
    weight: 0.1,
  },
};

// --- Zod Validation Schema ---
const calculatorPackageSchema = z.object({
  length: z.number().min(0.1, "Length must be > 0"),
  breadth: z.number().min(0.1, "Breadth must be > 0"),
  height: z.number().min(0.1, "Height must be > 0"),
  dimension_unit: z.nativeEnum(DimensionUnit),
  weight: z.number().min(0.1, "Weight must be at least 0.1 kg"),
  weight_unit: z.nativeEnum(WeightUnit),
  box_count: z.number().min(1, "Must be at least 1 box"),
  is_fragile: z.boolean(),
  description: z.string().optional().or(z.literal("")),
});

const rateCalculatorSchema = z
  .object({
    pickup_pincode: z
      .string()
      .min(1, "Pickup pincode is required")
      .regex(
        /^[1-9][0-9]{5}$/,
        "Must be a valid 6-digit Indian pincode (cannot start with 0)",
      ),
    delivery_pincode: z
      .string()
      .min(1, "Delivery pincode is required")
      .regex(
        /^[1-9][0-9]{5}$/,
        "Must be a valid 6-digit Indian pincode (cannot start with 0)",
      ),
    product_category: z.nativeEnum(ProductCategory, {
      message: "Product category is required",
    }),
    is_blind_pickup: z.boolean(),
    // Logismart Prime add-on (B2B): deliver to the receiver's door instead of the godown.
    door_delivery: z.boolean(),
    // B2B insurance (Delhivery One "Owner's Risk" vs "Delhivery's Insurance"): priced by Delhivery B2B.
    is_carriers_risk: z.boolean(),
    estimated_box_count: z.number().optional().nullable(),
    packages: z.array(calculatorPackageSchema),
    shipment_total_value: z
      .number()
      .min(0, "Shipment value cannot be negative"),
    freight_payment_mode: z.nativeEnum(FreightPaymentMode),
    is_cod: z.boolean(),
    cod_amount: z.number().min(0, "COD amount cannot be negative"),
  })
  .superRefine((data, ctx) => {
    // 1. If is_blind_pickup is checked, estimated_box_count must be >= 1
    if (data.is_blind_pickup) {
      if (!data.estimated_box_count || data.estimated_box_count < 1) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "Estimated box count must be at least 1 for blind pickups",
          path: ["estimated_box_count"],
        });
      }
    } else {
      // If NOT is_blind_pickup, packages array must contain at least 1 package
      if (!data.packages || data.packages.length === 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message:
            "At least one package is required when blind pickup is disabled",
          path: ["packages"],
        });
      }
    }

    // 2. If Carrier's risk is enabled, shipment_total_value must be > 0
    if (data.is_carriers_risk && data.shipment_total_value <= 0) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: "Declared shipment value must be greater than 0 for Carrier's risk insurance",
        path: ["shipment_total_value"],
      });
    }

    // 3. If is_cod is checked, cod_amount is required and must not exceed shipment_total_value
    if (data.is_cod) {
      if (data.cod_amount <= 0) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message:
            "COD amount must be greater than 0 when Cash-on-Delivery is enabled",
          path: ["cod_amount"],
        });
      } else if (data.cod_amount > data.shipment_total_value) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: "COD amount cannot exceed the shipment total value",
          path: ["cod_amount"],
        });
      }
    }
  }, { when: () => true });

type RateCalculatorFormValues = z.infer<typeof rateCalculatorSchema>;

export default function B2BRateCalculatorPage() {
  const { routeTo } = useTenant();
  const isB2BFlow = isB2BCalculatorPath(usePathname());
  const flowLabel = isB2BFlow ? "B2B" : "B2C";
  const [isCalculating, setIsCalculating] = useState(false);
  const [quotesResponse, setQuotesResponse] = useState<QuoteResponse | null>(null);
  const [selectedOption, setSelectedOption] = useState<ServiceOption | null>(null);
  const selectedQuote = findSelectedOption(quotesResponse, selectedOption);
  const [calculationError, setCalculationError] = useState<string | null>(null);

  const form = useForm<RateCalculatorFormValues>({
    resolver: zodResolver(rateCalculatorSchema),
    mode: "onChange",
    defaultValues: {
      pickup_pincode: "",
      delivery_pincode: "",
      product_category: undefined,
      is_blind_pickup: false,
      door_delivery: false,
      is_carriers_risk: false,
      estimated_box_count: 1,
      packages: [
        {
          length: 0,
          breadth: 0,
          height: 0,
          dimension_unit: DimensionUnit.CM,
          weight: 0.1,
          weight_unit: WeightUnit.KG,
          box_count: 1,
          is_fragile: false,
          description: "",
        },
      ],
      shipment_total_value: 0,
      freight_payment_mode: FreightPaymentMode.PREPAID,
      is_cod: false,
      cod_amount: 0,
    },
  });

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "packages",
  });

  const watchedCategory = form.watch("product_category");
  const watchedIsBlind = form.watch("is_blind_pickup");
  const watchedIsCod = form.watch("is_cod");
  const watchedDoorDelivery = Boolean(form.watch("door_delivery"));

  // --- Volumetric Safety Net Logic ---
  useEffect(() => {
    if (!watchedCategory || watchedIsBlind) return;

    const defaults = CATEGORY_DEFAULTS[watchedCategory];
    if (!defaults) return;

    const currentPackages = form.getValues("packages") || [];

    if (currentPackages.length === 0) {
      form.setValue("packages", [
        {
          length: defaults.length,
          breadth: defaults.breadth,
          height: defaults.height,
          dimension_unit: DimensionUnit.CM,
          weight: defaults.weight,
          weight_unit: WeightUnit.KG,
          box_count: 1,
          is_fragile: false,
          description: "",
        },
      ]);
    } else {
      // Intelligently pre-populate package dimensions if they match another category's defaults or are 0/empty
      const updatedPackages = currentPackages.map((pkg) => {
        const isLengthDefault =
          !pkg.length ||
          pkg.length === 0 ||
          Object.values(CATEGORY_DEFAULTS).some((d) => d.length === pkg.length);
        const isBreadthDefault =
          !pkg.breadth ||
          pkg.breadth === 0 ||
          Object.values(CATEGORY_DEFAULTS).some(
            (d) => d.breadth === pkg.breadth,
          );
        const isHeightDefault =
          !pkg.height ||
          pkg.height === 0 ||
          Object.values(CATEGORY_DEFAULTS).some((d) => d.height === pkg.height);
        const isWeightDefault =
          !pkg.weight ||
          pkg.weight === 0.1 ||
          Object.values(CATEGORY_DEFAULTS).some((d) => d.weight === pkg.weight);

        return {
          ...pkg,
          length: isLengthDefault ? defaults.length : pkg.length,
          breadth: isBreadthDefault ? defaults.breadth : pkg.breadth,
          height: isHeightDefault ? defaults.height : pkg.height,
          weight: isWeightDefault ? defaults.weight : pkg.weight,
        };
      });

      form.setValue("packages", updatedPackages);
    }
  }, [watchedCategory, watchedIsBlind, form]);

  // Clean packages array if is_blind_pickup status changes
  useEffect(() => {
    if (!watchedIsBlind) {
      const currentPackages = form.getValues("packages") || [];
      if (currentPackages.length === 0) {
        const defaults = watchedCategory
          ? CATEGORY_DEFAULTS[watchedCategory]
          : null;
        form.setValue("packages", [
          {
            length: defaults?.length || 10,
            breadth: defaults?.breadth || 10,
            height: defaults?.height || 10,
            dimension_unit: DimensionUnit.CM,
            weight: defaults?.weight || 0.5,
            weight_unit: WeightUnit.KG,
            box_count: 1,
            is_fragile: false,
            description: "",
          },
        ]);
      }
    }
  }, [watchedIsBlind, watchedCategory, form]);

  // --- API Submit Handler ---
  // Prices the same inputs the booking wizard sends (A-03); every number shown comes
  // from `POST /api/v1/quotes` (Zero Frontend Math).
  const onSubmit = async (values: RateCalculatorFormValues) => {
    setIsCalculating(true);
    setCalculationError(null);
    setQuotesResponse(null);

    try {
      const packagesPayload: PackageCreate[] = values.is_blind_pickup
        ? []
        : values.packages.map((pkg) => ({
            length: pkg.length,
            breadth: pkg.breadth,
            height: pkg.height,
            dimension_unit: pkg.dimension_unit,
            weight: pkg.weight,
            weight_unit: pkg.weight_unit,
            box_count: pkg.box_count,
            is_fragile: pkg.is_fragile,
            description: pkg.description || null,
          }));

      // B2B (Logismart Prime) has no COD at launch; B2C parcels are prepaid or COD.
      const isCod = !isB2BFlow && values.is_cod;
      const response = await fetchQuotes(
        buildQuoteRequest({
          flow: isB2BFlow ? ServiceFlow.B2B : ServiceFlow.B2C,
          shipmentType: ShipmentType.FORWARD,
          pickupPincode: values.pickup_pincode,
          deliveryPincode: values.delivery_pincode,
          packages: packagesPayload,
          payment: buildPaymentInputs(
            {
              freight_payment_mode: values.freight_payment_mode,
              is_cod: isCod,
              cod_amount: values.cod_amount,
              shipment_value: values.shipment_total_value,
              shipment_tax_value: 0,
            },
            false,
          ),
          isBlindPickup: isB2BFlow && values.is_blind_pickup,
          estimatedBoxCount: values.is_blind_pickup ? values.estimated_box_count : null,
          doorDelivery: isB2BFlow && values.door_delivery,
          isCarriersRisk: isB2BFlow && values.is_carriers_risk,
        }),
      );
      setQuotesResponse(response);
      setSelectedOption((previous) => defaultSelection(response, previous));
    } catch (error: unknown) {
      const errMsg = extractApiErrorMessage(
        error,
        `Failed to calculate ${flowLabel} rates. Please check your inputs.`,
      );
      setCalculationError(errMsg);
      toast.error(errMsg);
    } finally {
      setIsCalculating(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-slate-100 pb-5">
        <div className="space-y-1">
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight flex items-center gap-2">
            <Calculator className="h-8 w-8 text-primary" />{" "}
            {isB2BFlow ? "B2B Cargo Rate Calculator" : "Rate Calculator"}
          </h1>
          <p className="text-slate-500">
            {isB2BFlow
              ? "Check Logismart Prime and Delhivery B2B Cargo serviceability and the full price breakup before you book."
              : "Check serviceability and estimate shipping charges for your parcel before you book."}
          </p>
        </div>
        <Badge
          variant="secondary"
          className="px-3 py-1 text-xs font-bold uppercase tracking-wider bg-slate-100 text-slate-700"
        >
          {isB2BFlow ? "B2B Cargo" : "B2C Express"}
        </Badge>
      </div>

      {/* Main 2-Column Bento Layout */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        {/* Left Column: Form (7 Cols) */}
        <div className="lg:col-span-7 min-w-0 space-y-6">
          <Card className="border-slate-200 shadow-sm bg-white rounded-xl">
            <CardHeader className="border-b border-slate-100 py-4 px-6">
              <CardTitle className="text-lg font-bold text-slate-900">
                Search Tariff & Configuration
              </CardTitle>
              <CardDescription>
                Enter pincodes, category, and operational parameters to fetch
                quotes.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-6">
              <Form {...form}>
                <form
                  onSubmit={form.handleSubmit(onSubmit)}
                  className="space-y-6"
                >
                  {/* Pincode Row */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <FormField
                      control={form.control}
                      name="pickup_pincode"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Pickup Pincode
                            <RequiredMark />
                          </FormLabel>
                          <FormControl>
                            <Input
                              placeholder="e.g. 110001"
                              maxLength={6}
                              className="bg-slate-50 text-sm h-10"
                              {...field}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={form.control}
                      name="delivery_pincode"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs font-bold text-slate-700">
                            Delivery Pincode
                            <RequiredMark />
                          </FormLabel>
                          <FormControl>
                            <Input
                              placeholder="e.g. 400001"
                              maxLength={6}
                              className="bg-slate-50 text-sm h-10"
                              {...field}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>

                  {/* Product Category */}
                  <FormField
                    control={form.control}
                    name="product_category"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-bold text-slate-700">
                          Product Category
                          <RequiredMark />
                        </FormLabel>
                        <FormControl>
                          <IconSelect
                            options={isB2BFlow ? B2B_CATEGORY_SELECT_OPTIONS : B2C_CATEGORY_SELECT_OPTIONS}
                            value={field.value}
                            onValueChange={field.onChange}
                            placeholder="Select a category"
                            triggerClassName="h-10 bg-slate-50"
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />

                  {/* B2B Operational Flags (B2B Cargo flow only) */}
                  {isB2BFlow && (
                  <div className="bg-slate-50/60 p-4 rounded-xl border border-slate-100 space-y-4">
                    <h3 className="text-xs font-bold text-slate-800 tracking-wide uppercase">
                      B2B Operational Settings
                    </h3>

                    {/* Delivery Type: Door Delivery vs Godown Pickup (Logismart Prime) */}
                    <FormField
                      control={form.control}
                      name="door_delivery"
                      render={({ field }) => {
                        const isDoor = Boolean(field.value);
                        return (
                          <FormItem className="space-y-2" data-testid="b2b-delivery-mode-selector">
                            <FormLabel className="text-xs font-extrabold text-slate-900">
                              B2B Delivery Type (Doorstep vs Destination Godown)
                            </FormLabel>
                            <FormControl>
                              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" role="radiogroup" aria-label="B2B Delivery Type">
                                <div
                                  role="radio"
                                  aria-checked={isDoor}
                                  tabIndex={0}
                                  data-testid="b2b-delivery-mode-door"
                                  onClick={() => field.onChange(true)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" || e.key === " ") {
                                      e.preventDefault();
                                      field.onChange(true);
                                    }
                                  }}
                                  className={cn(
                                    "flex items-start gap-3 p-3 rounded-lg border transition-all cursor-pointer select-none bg-white",
                                    isDoor
                                      ? "border-primary bg-primary/5 ring-1 ring-primary/20 shadow-2xs"
                                      : "border-slate-200 hover:border-slate-300",
                                  )}
                                >
                                  <input
                                    type="radio"
                                    readOnly
                                    className="h-4 w-4 rounded-full border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0 mt-0.5"
                                    checked={isDoor}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      field.onChange(true);
                                    }}
                                  />
                                  <div className="space-y-0.5">
                                    <span className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                                      <Truck className="h-3.5 w-3.5 text-primary shrink-0" />
                                      Door Delivery
                                    </span>
                                    <p className="text-[10px] text-slate-500 font-medium">
                                      Deliver directly to consignee&apos;s address (lane Door Delivery charge applies)
                                    </p>
                                  </div>
                                </div>

                                <div
                                  role="radio"
                                  aria-checked={!isDoor}
                                  tabIndex={0}
                                  data-testid="b2b-delivery-mode-godown"
                                  onClick={() => field.onChange(false)}
                                  onKeyDown={(e) => {
                                    if (e.key === "Enter" || e.key === " ") {
                                      e.preventDefault();
                                      field.onChange(false);
                                    }
                                  }}
                                  className={cn(
                                    "flex items-start gap-3 p-3 rounded-lg border transition-all cursor-pointer select-none bg-white",
                                    !isDoor
                                      ? "border-emerald-400 bg-emerald-50/60 ring-1 ring-emerald-200 shadow-2xs"
                                      : "border-slate-200 hover:border-slate-300",
                                  )}
                                >
                                  <input
                                    type="radio"
                                    readOnly
                                    checked={!isDoor}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      field.onChange(false);
                                    }}
                                    className="h-4 w-4 rounded-full border-slate-300 text-emerald-600 focus:ring-emerald-600 cursor-pointer accent-emerald-600 shrink-0 mt-0.5"
                                  />
                                  <div className="space-y-0.5">
                                    <span className="text-xs font-bold text-slate-900 flex items-center gap-1.5">
                                      <Warehouse className="h-3.5 w-3.5 text-emerald-700 shrink-0" />
                                      Godown / Hub Pickup
                                    </span>
                                    <p className="text-[10px] text-slate-500 font-medium">
                                      Consignee collects from destination transport godown (₹0 Door Delivery fee)
                                    </p>
                                  </div>
                                </div>
                              </div>
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        );
                      }}
                    />

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {/* Blind Pickup Checkbox */}
                      <FormField
                        control={form.control}
                        name="is_blind_pickup"
                        render={({ field }) => (
                          <FormItem className="space-y-0">
                            <FormControl>
                              <div
                                onClick={() => field.onChange(!field.value)}
                                className={cn(
                                  "flex items-center gap-3 p-3 rounded-lg border transition-all cursor-pointer select-none bg-white",
                                  field.value
                                    ? "border-primary/40 bg-primary/5 shadow-2xs"
                                    : "border-slate-200 hover:border-slate-300",
                                )}
                              >
                                <input
                                  type="checkbox"
                                  className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0"
                                  checked={!!field.value}
                                  onChange={(e) => {
                                    e.stopPropagation();
                                    field.onChange(e.target.checked);
                                  }}
                                />
                                <div className="space-y-0.5">
                                  <span className="text-xs font-bold text-slate-900">
                                    Blind Pickup
                                  </span>
                                  <p className="text-[10px] text-slate-500 font-medium">
                                    Truck sent before boxes are manifested
                                  </p>
                                </div>
                              </div>
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      {/* Insurance (Delhivery One: Owner's Risk vs Delhivery's Insurance) */}
                      <FormField
                        control={form.control}
                        name="is_carriers_risk"
                        render={({ field }) => (
                          <FormItem className="space-y-0">
                            <FormControl>
                              <div
                                onClick={() => field.onChange(!field.value)}
                                data-testid="rate-calculator.carriers-risk"
                                className={cn(
                                  "flex items-center gap-3 p-3 rounded-lg border transition-all cursor-pointer select-none bg-white",
                                  field.value
                                    ? "border-primary/40 bg-primary/5 shadow-2xs"
                                    : "border-slate-200 hover:border-slate-300",
                                )}
                              >
                                <input
                                  type="checkbox"
                                  className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0"
                                  checked={!!field.value}
                                  onChange={(e) => {
                                    e.stopPropagation();
                                    field.onChange(e.target.checked);
                                  }}
                                />
                                <div className="space-y-0.5">
                                  <span className="text-xs font-bold text-slate-900">
                                    Carrier&apos;s risk (insurance)
                                  </span>
                                  <p className="text-[10px] text-slate-500 font-medium">
                                    Unticked = owner&apos;s risk. Needs the shipment value.
                                  </p>
                                </div>
                              </div>
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    </div>

                    {/* Conditional Estimated Box Count */}
                    {watchedIsBlind && (
                      <FormField
                        control={form.control}
                        name="estimated_box_count"
                        render={({ field }) => (
                          <FormItem className="animate-in fade-in duration-300">
                            <FormLabel className="text-xs font-bold text-slate-700">
                              Estimated Box Count
                              <RequiredMark />
                            </FormLabel>
                            <FormControl>
                              <Input
                                type="number"
                                min={1}
                                className="bg-white h-10 text-sm"
                                placeholder="Number of boxes"
                                {...field}
                                value={field.value || ""}
                                onChange={(e) =>
                                  field.onChange(
                                    e.target.value === ""
                                      ? 0
                                      : Number(e.target.value),
                                  )
                                }
                              />
                            </FormControl>
                            <FormDescription className="text-[10px] text-slate-500 font-medium">
                              Required for blind pickups. Volumetric safety net
                              defaults will apply to each box.
                            </FormDescription>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                    )}
                  </div>
                  )}

                  {/* Packages Dynamic Array (Hidden if Blind Pickup is checked) */}
                  {!watchedIsBlind && (
                    <div className="space-y-4 border-t border-slate-100 pt-5">
                      <div className="flex items-center justify-between">
                        <div className="space-y-0.5">
                          <h3 className="text-sm font-bold text-slate-900 flex items-center gap-2">
                            <Box className="h-4 w-4 text-primary" /> Cargo
                            Dimensions & Weights
                          </h3>
                          <p className="text-xs text-slate-500 font-medium">
                            Add, remove, or modify package details manually.
                          </p>
                        </div>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-8 border-dashed hover:bg-slate-50 text-xs font-semibold text-slate-600"
                          onClick={() =>
                            append({
                              length: watchedCategory
                                ? CATEGORY_DEFAULTS[watchedCategory]?.length ||
                                  10
                                : 10,
                              breadth: watchedCategory
                                ? CATEGORY_DEFAULTS[watchedCategory]?.breadth ||
                                  10
                                : 10,
                              height: watchedCategory
                                ? CATEGORY_DEFAULTS[watchedCategory]?.height ||
                                  10
                                : 10,
                              dimension_unit: DimensionUnit.CM,
                              weight: watchedCategory
                                ? CATEGORY_DEFAULTS[watchedCategory]?.weight ||
                                  1.0
                                : 1.0,
                              weight_unit: WeightUnit.KG,
                              box_count: 1,
                              is_fragile: false,
                              description: "",
                            })
                          }
                        >
                          <Plus className="h-3.5 w-3.5 mr-1" /> Add Box Type
                        </Button>
                      </div>

                      <div className="space-y-4 min-w-0">
                        {fields.map((field, index) => (
                          <div
                            key={field.id}
                            className="relative bg-slate-50/50 p-4 sm:p-5 rounded-xl border border-slate-200 shadow-3xs min-w-0 overflow-hidden animate-in fade-in slide-in-from-bottom-2"
                          >
                            <div className="flex items-center justify-between gap-2 mb-3 border-b border-slate-200/60 pb-2 min-w-0">
                              <span className="text-xs font-extrabold text-slate-700 flex items-center gap-1.5 min-w-0 truncate">
                                <Box className="h-3.5 w-3.5 text-slate-500 shrink-0" />{" "}
                                <span className="truncate">Package Configuration #{index + 1}</span>
                              </span>
                              {fields.length > 1 && (
                                <Button
                                  type="button"
                                  variant="ghost"
                                  size="sm"
                                  className="h-7 text-xs text-red-600 hover:bg-red-50 hover:text-red-700 rounded-md px-2 shrink-0"
                                  onClick={() => remove(index)}
                                >
                                  <Trash2 className="h-3.5 w-3.5 mr-1" /> Remove
                                </Button>
                              )}
                            </div>

                            <div className="space-y-4 min-w-0">
                              {/* Dimensions Row */}
                              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                                <FormField
                                  control={form.control}
                                  name={`packages.${index}.length`}
                                  render={({ field: lengthField }) => (
                                    <FormItem>
                                      <FormLabel className="text-[10px] font-bold text-slate-600 uppercase">
                                        Length (cm)
                                      </FormLabel>
                                      <FormControl>
                                        <Input
                                          type="number"
                                          step="0.1"
                                          placeholder="0.0"
                                          className="bg-white h-9 text-xs"
                                          {...lengthField}
                                          value={lengthField.value || ""}
                                          onChange={(e) =>
                                            lengthField.onChange(
                                              e.target.value === ""
                                                ? 0
                                                : Number(e.target.value),
                                            )
                                          }
                                        />
                                      </FormControl>
                                      <FormMessage />
                                    </FormItem>
                                  )}
                                />
                                <FormField
                                  control={form.control}
                                  name={`packages.${index}.breadth`}
                                  render={({ field: breadthField }) => (
                                    <FormItem>
                                      <FormLabel className="text-[10px] font-bold text-slate-600 uppercase">
                                        Breadth (cm)
                                      </FormLabel>
                                      <FormControl>
                                        <Input
                                          type="number"
                                          step="0.1"
                                          placeholder="0.0"
                                          className="bg-white h-9 text-xs"
                                          {...breadthField}
                                          value={breadthField.value || ""}
                                          onChange={(e) =>
                                            breadthField.onChange(
                                              e.target.value === ""
                                                ? 0
                                                : Number(e.target.value),
                                            )
                                          }
                                        />
                                      </FormControl>
                                      <FormMessage />
                                    </FormItem>
                                  )}
                                />
                                <FormField
                                  control={form.control}
                                  name={`packages.${index}.height`}
                                  render={({ field: heightField }) => (
                                    <FormItem>
                                      <FormLabel className="text-[10px] font-bold text-slate-600 uppercase">
                                        Height (cm)
                                      </FormLabel>
                                      <FormControl>
                                        <Input
                                          type="number"
                                          step="0.1"
                                          placeholder="0.0"
                                          className="bg-white h-9 text-xs"
                                          {...heightField}
                                          value={heightField.value || ""}
                                          onChange={(e) =>
                                            heightField.onChange(
                                              e.target.value === ""
                                                ? 0
                                                : Number(e.target.value),
                                            )
                                          }
                                        />
                                      </FormControl>
                                      <FormMessage />
                                    </FormItem>
                                  )}
                                />
                                <FormField
                                  control={form.control}
                                  name={`packages.${index}.weight`}
                                  render={({ field: weightField }) => (
                                    <FormItem>
                                      <FormLabel className="text-[10px] font-bold text-slate-600 uppercase">
                                        Weight (kg)
                                      </FormLabel>
                                      <FormControl>
                                        <Input
                                          type="number"
                                          step="0.1"
                                          placeholder="0.0"
                                          className="bg-white h-9 text-xs"
                                          {...weightField}
                                          value={weightField.value || ""}
                                          onChange={(e) =>
                                            weightField.onChange(
                                              e.target.value === ""
                                                ? 0
                                                : Number(e.target.value),
                                            )
                                          }
                                        />
                                      </FormControl>
                                      <FormMessage />
                                    </FormItem>
                                  )}
                                />
                              </div>

                              {/* Box Count & Description Row */}
                              <div className="grid grid-cols-1 sm:grid-cols-12 gap-3 items-end">
                                <div className="sm:col-span-3 min-w-0">
                                  <FormField
                                    control={form.control}
                                    name={`packages.${index}.box_count`}
                                    render={({ field: countField }) => (
                                      <FormItem>
                                        <FormLabel className="text-[10px] font-bold text-slate-600 uppercase">
                                          Boxes
                                        </FormLabel>
                                        <FormControl>
                                          <Input
                                            type="number"
                                            min={1}
                                            className="bg-white h-9 text-xs"
                                            {...countField}
                                            value={countField.value || 1}
                                            onChange={(e) =>
                                              countField.onChange(
                                                e.target.value === ""
                                                  ? 1
                                                  : Number(e.target.value),
                                              )
                                            }
                                          />
                                        </FormControl>
                                        <FormMessage />
                                      </FormItem>
                                    )}
                                  />
                                </div>

                                <div className="sm:col-span-9 min-w-0">
                                  <FormField
                                    control={form.control}
                                    name={`packages.${index}.description`}
                                    render={({ field: descField }) => (
                                      <FormItem>
                                        <FormLabel className="text-[10px] font-bold text-slate-600 uppercase">
                                          Contents Description
                                        </FormLabel>
                                        <FormControl>
                                          <Input
                                            placeholder="e.g. Laptops, Garments..."
                                            className="bg-white h-9 text-xs"
                                            {...descField}
                                          />
                                        </FormControl>
                                        <FormMessage />
                                      </FormItem>
                                    )}
                                  />
                                </div>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Commercial details */}
                  <div className="space-y-4 border-t border-slate-100 pt-5">
                    <h3 className="text-xs font-bold text-slate-800 tracking-wide uppercase">
                      Commercial & Payment Details
                    </h3>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                      {/* Shipment Value (Required if carriers risk or COD is checked) */}
                      {!isB2BFlow && watchedIsCod && (
                        <FormField
                          control={form.control}
                          name="shipment_total_value"
                          render={({ field }) => (
                            <FormItem className="animate-in fade-in duration-300">
                              <FormLabel className="text-xs font-bold text-slate-700">
                                Goods value (INR)
                                <RequiredMark />
                              </FormLabel>
                              <FormControl>
                                <div className="relative">
                                  <IndianRupee className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
                                  <Input
                                    type="number"
                                    min={1}
                                    placeholder="Declared value"
                                    className="bg-slate-50 pl-9 text-sm h-10"
                                    {...field}
                                    value={field.value || ""}
                                    onChange={(e) =>
                                      field.onChange(
                                        e.target.value === ""
                                          ? 0
                                          : Number(e.target.value),
                                      )
                                    }
                                  />
                                </div>
                              </FormControl>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      )}

                      {/* Freight Payment Mode (B2B Cargo only; B2C parcels are Prepaid or COD) */}
                      {isB2BFlow && (
                      <FormField
                        control={form.control}
                        name="freight_payment_mode"
                        render={({ field }) => (
                          <FormItem>
                            <FormLabel className="text-xs font-bold text-slate-700">
                              Who pays for shipping?
                              <RequiredMark />
                            </FormLabel>
                            <FormControl>
                              <IconSelect
                                options={PAYER_SELECT_OPTIONS}
                                value={field.value}
                                onValueChange={field.onChange}
                                placeholder="Choose who pays"
                                triggerClassName="h-10 bg-slate-50"
                              />
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />
                      )}
                    </div>

                    {/* COD settings (B2C only: Logismart Prime has no COD at launch) */}
                    {isB2BFlow ? (
                      <p className="text-xs text-slate-500" data-testid="rate-calculator.cod-unavailable">
                        Cash on Delivery isn&apos;t available for B2B cargo yet.
                      </p>
                    ) : (
                    <div className="bg-slate-50/60 p-4 rounded-xl border border-slate-100 space-y-4">
                      <FormField
                        control={form.control}
                        name="is_cod"
                        render={({ field }) => (
                          <FormItem className="space-y-0">
                            <FormControl>
                              <div
                                onClick={() => field.onChange(!field.value)}
                                className={cn(
                                  "flex items-center gap-3 p-3 rounded-lg border transition-all cursor-pointer select-none bg-white",
                                  field.value
                                    ? "border-primary/40 bg-primary/5 shadow-2xs"
                                    : "border-slate-200 hover:border-slate-300",
                                )}
                              >
                                <input
                                  type="checkbox"
                                  className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0"
                                  checked={!!field.value}
                                  onChange={(e) => {
                                    e.stopPropagation();
                                    field.onChange(e.target.checked);
                                  }}
                                />
                                <div className="space-y-0.5">
                                  <span className="text-xs font-bold text-slate-900">
                                    Cash-on-Delivery (COD)
                                  </span>
                                  <p className="text-[10px] text-slate-500 font-medium">
                                    Collect cash payment upon delivery from
                                    receiver
                                  </p>
                                </div>
                              </div>
                            </FormControl>
                            <FormMessage />
                          </FormItem>
                        )}
                      />

                      {/* COD Amount */}
                      {watchedIsCod && (
                        <FormField
                          control={form.control}
                          name="cod_amount"
                          render={({ field }) => (
                            <FormItem className="animate-in fade-in duration-300">
                              <FormLabel className="text-xs font-bold text-slate-700">
                                COD Collection Amount (INR)
                                <RequiredMark />
                              </FormLabel>
                              <FormControl>
                                <div className="relative">
                                  <IndianRupee className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
                                  <Input
                                    type="number"
                                    min={1}
                                    placeholder="COD amount"
                                    className="bg-white pl-9 text-sm h-10"
                                    {...field}
                                    value={field.value || ""}
                                    onChange={(e) =>
                                      field.onChange(
                                        e.target.value === ""
                                          ? 0
                                          : Number(e.target.value),
                                      )
                                    }
                                  />
                                </div>
                              </FormControl>
                              <FormDescription className="text-[10px] text-slate-500 font-medium">
                                Must be greater than 0 and cannot exceed the
                                declared goods value (₹
                                {form.watch("shipment_total_value")}).
                              </FormDescription>
                              <FormMessage />
                            </FormItem>
                          )}
                        />
                      )}
                    </div>
                    )}
                  </div>

                  {/* Submit button */}
                  <Button
                    type="submit"
                    className="w-full h-11 font-bold shadow-md text-sm rounded-lg"
                    disabled={isCalculating}
                  >
                    {isCalculating ? (
                      <>
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />{" "}
                        Calculating {flowLabel} Rates...
                      </>
                    ) : (
                      <>
                        <Calculator className="mr-2 h-4 w-4" /> Calculate{" "}
                        {flowLabel} Rates
                      </>
                    )}
                  </Button>
                </form>
              </Form>
            </CardContent>
          </Card>
        </div>

        {/* Right Column: Comparison Matrix & Ledger (5 Cols) */}
        <div className="lg:col-span-5 min-w-0 space-y-6">
          {/* Service Comparison Matrix */}
          <Card className="border-slate-200 shadow-sm bg-white rounded-xl">
            <CardHeader className="border-b border-slate-100 py-4 px-6">
              <CardTitle className="text-lg font-bold text-slate-900">
                Available services
              </CardTitle>
              <CardDescription>
                Prices include GST. Pick one to see the breakup.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-6">
              {/* General API Error State */}
              {calculationError && (
                <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex gap-3 text-red-800 animate-in fade-in duration-300">
                  <AlertCircle className="h-5 w-5 text-red-600 shrink-0 mt-0.5" />
                  <div className="space-y-1">
                    <p className="text-xs font-bold">Calculation Failed</p>
                    <p className="text-[11px] font-medium leading-normal">
                      {calculationError}
                    </p>
                  </div>
                </div>
              )}

              {/* Initial / Empty State */}
              {!isCalculating && !quotesResponse && !calculationError && (
                <div className="flex flex-col items-center justify-center py-16 text-center space-y-3">
                  <div className="h-12 w-12 rounded-full bg-slate-50 flex items-center justify-center text-slate-400 border border-slate-100">
                    <Calculator className="h-6 w-6" />
                  </div>
                  <div className="space-y-1 max-w-xs">
                    <p className="text-xs font-bold text-slate-950">
                      Ready to calculate
                    </p>
                    <p className="text-[11px] text-slate-500 font-medium">
                      Enter the origin, destination, and package configurations
                      on the left, then click &quot;Calculate&quot;.
                    </p>
                  </div>
                </div>
              )}

              {/* Loading State */}
              {isCalculating && (
                <div className="flex flex-col items-center justify-center py-24 text-center space-y-4">
                  <Loader2 className="h-8 w-8 animate-spin text-primary" />
                  <div className="space-y-1">
                    <p className="text-xs font-bold text-slate-950">
                      Calculating rates...
                    </p>
                    <p className="text-[11px] text-slate-500 font-medium">
                      Checking serviceability and pricing for this route.
                    </p>
                  </div>
                </div>
              )}

              {/* Service option cards */}
              {!isCalculating && quotesResponse && (
                <div className="space-y-3">
                  {isB2BFlow && (
                    <DeliveryModeToggleBar
                      doorDelivery={watchedDoorDelivery}
                      isLoading={isCalculating}
                      onChange={(nextDoor) => {
                        form.setValue("door_delivery", nextDoor, { shouldDirty: true });
                        void onSubmit({ ...form.getValues(), door_delivery: nextDoor });
                      }}
                    />
                  )}
                  {isB2BFlow === false && quotesResponse.cod_available === false && watchedIsCod && (
                    <p className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                      <strong>Cash on Delivery isn&apos;t available.</strong>{" "}
                      {quotesResponse.cod_unavailable_reason || "COD is not enabled for this account yet."}
                    </p>
                  )}
                  {quotesResponse.options.map((option) => (
                    <ServiceOptionCard
                      key={option.service_option}
                      option={option}
                      isSelected={selectedQuote?.service_option === option.service_option}
                      onSelect={setSelectedOption}
                      doorDelivery={isB2BFlow ? watchedDoorDelivery : undefined}
                    />
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Price breakup of the selected option */}
          {!isCalculating && selectedQuote && (
            <PriceBreakup
              option={selectedQuote}
              footer={
                <Button
                  asChild
                  className="mt-3 w-full font-bold bg-primary text-primary-foreground hover:bg-primary/90 h-10 shadow-md"
                >
                  <Link
                    href={routeTo(
                      `${isB2BFlow ? "/b2b" : ""}/shipments/new/forward?${buildBookingHandoffQuery(form.getValues())}`
                    )}
                  >
                    Book This Shipment <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              }
            />
          )}
        </div>
      </div>
    </div>
  );
}
