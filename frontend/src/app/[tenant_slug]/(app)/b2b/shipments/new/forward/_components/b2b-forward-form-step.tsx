// frontend/src/app/[tenant_slug]/(app)/b2b/shipments/new/forward/_components/b2b-forward-form-step.tsx
"use client";

import {
  AddressRead,
  ProductCategory,
  DocumentType,
  PickupStrategy,
} from "@/api_client";
import {
  AddressFieldset,
  HasAddresses,
} from "@/components/forms/address-fieldset";
import {
  PackageFieldset,
  HasPackages,
} from "@/components/forms/package-fieldset";
import { EWayBillBanner } from "@/components/forms/eway-bill-banner";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { DatePicker } from "@/components/ui/date-picker";
import { format, parseISO } from "date-fns";
import { IconSelect } from "@/components/ui/icon-select";
import { InputAdornment, RequiredMark } from "@/components/ui/form-extras";
import {
  DOCUMENT_TYPE_OPTIONS,
  FREIGHT_PAYMENT_MODE_OPTIONS,
  PICKUP_STRATEGY_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
  getOptionMeta,
  optionLabels,
  freightPaymentModesFor,
  toOptions,
} from "@/lib/form-options";
import { useUser } from "@/components/auth/auth-guard";
import { Button } from "@/components/ui/button";
import {
  Control,
  useWatch,
  useFormContext,
  FieldArrayWithId,
} from "react-hook-form";
import { B2BForwardShipmentFormValues, MAX_PO_NUMBERS } from "@/lib/validations/shipment";
import { useShipmentValuation } from "@/components/booking/use-shipment-valuation";
import { useTenant } from "@/components/providers/tenant-provider";
import { toIstDateTimeLocalValue, toIstIsoString } from "@/lib/utils";
import { FileText, Trash2, ClipboardList, Truck, Warehouse, ArrowUpRight, ArrowDownLeft, Boxes, Banknote, ShieldCheck, ShieldAlert, Plus, Calendar, TriangleAlert } from "lucide-react";
import { toast } from "sonner";

/** Legacy label lookup (toasts and existing importers). */
export const CATEGORY_LABELS: Record<ProductCategory, string> = optionLabels(PRODUCT_CATEGORY_OPTIONS);

const CATEGORY_SELECT_OPTIONS = toOptions(PRODUCT_CATEGORY_OPTIONS);
const STRATEGY_SELECT_OPTIONS = toOptions(PICKUP_STRATEGY_OPTIONS);
const DOC_TYPE_SELECT_OPTIONS = toOptions(DOCUMENT_TYPE_OPTIONS);

interface B2BForwardFormStepProps {
  control: Control<B2BForwardShipmentFormValues>;
  savedAddresses: AddressRead[];
  docFields: FieldArrayWithId<B2BForwardShipmentFormValues, "documents">[];
  removeDoc: (index: number) => void;
  isUploading: boolean;
  handleFileUpload: (
    e: React.ChangeEvent<HTMLInputElement>,
    docType: DocumentType,
  ) => Promise<void>;
}

export function B2BForwardFormStep({
  control,
  savedAddresses,
  docFields,
  removeDoc,
  isUploading,
  handleFileUpload,
}: B2BForwardFormStepProps) {
  // Merchants can't self-select POSTPAID (needs an approved credit account, decision D14).
  const { isAdmin } = useUser();
  const freightModeOptions = toOptions(FREIGHT_PAYMENT_MODE_OPTIONS, freightPaymentModesFor(isAdmin));

  const { tenant } = useTenant();
  const { setValue, formState } = useFormContext<B2BForwardShipmentFormValues>();
  // Set by the booking schema when no GST invoice number was entered (create only).
  const invoiceNumbersError = formState.errors.payment_details?.invoice_numbers?.message;

  // D-06: the cargo total and the e-way bill rule come from the backend valuation.
  const watchedShipmentValue = useWatch({ control, name: "payment_details.shipment_value" });
  const watchedShipmentTaxValue = useWatch({ control, name: "payment_details.shipment_tax_value" });
  const showEWayBill = Boolean(useWatch({ control, name: "payment_details.eway_bill_required" }));
  useShipmentValuation(watchedShipmentValue, watchedShipmentTaxValue, (valuation) => {
    setValue("payment_details.shipment_total_value", valuation.shipment_total_value);
    setValue("payment_details.eway_bill_required", valuation.eway_bill_required);
  });

  const productCategoryValue = useWatch({
    control,
    name: "product_category",
  }) as ProductCategory | undefined;

  const watchedPackages = useWatch({
    control,
    name: "packages",
  }) as B2BForwardShipmentFormValues["packages"] | undefined;

  const isBlindPickup = useWatch({
    control,
    name: "is_blind_pickup",
  }) as boolean | undefined;

  const isCarriersRisk = useWatch({
    control,
    name: "is_carriers_risk",
  }) as boolean | undefined;

  const invoiceNumbers = useWatch({
    control,
    name: "payment_details.invoice_numbers",
  }) as string[] | undefined || [];

  const ewayBillNumbers = useWatch({
    control,
    name: "payment_details.eway_bill_numbers",
  }) as string[] | undefined || [];

  // Reactive calculation of cargo totals (only if not blind pickup)
  const cargoTotals = (watchedPackages || []).reduce(
    (acc, pkg) => {
      const count = Number(pkg?.box_count) || 0;
      const weight = Number(pkg?.weight) || 0;
      const isGrams = pkg?.weight_unit === "G";
      const weightInKg = isGrams ? weight / 1000 : weight;

      acc.boxCount += count;
      acc.actualWeightKg += weightInKg * count;
      return acc;
    },
    { boxCount: 0, actualWeightKg: 0 },
  );


  // Invoice array controls
  const addInvoiceNumber = () => {
    setValue("payment_details.invoice_numbers", [...invoiceNumbers, ""]);
  };

  const removeInvoiceNumber = (idx: number) => {
    setValue("payment_details.invoice_numbers", invoiceNumbers.filter((_, i) => i !== idx));
  };

  const updateInvoiceNumber = (idx: number, val: string) => {
    const updated = [...invoiceNumbers];
    updated[idx] = val;
    // Re-validate only while the "add an invoice" error is on screen, so it clears as you type.
    setValue("payment_details.invoice_numbers", updated, { shouldValidate: Boolean(invoiceNumbersError) });
  };

  // E-Way Bill array controls
  const addEwayBillNumber = () => {
    setValue("payment_details.eway_bill_numbers", [...ewayBillNumbers, ""]);
  };

  const removeEwayBillNumber = (idx: number) => {
    setValue("payment_details.eway_bill_numbers", ewayBillNumbers.filter((_, i) => i !== idx));
  };

  const updateEwayBillNumber = (idx: number, val: string) => {
    const updated = [...ewayBillNumbers];
    updated[idx] = val;
    setValue("payment_details.eway_bill_numbers", updated);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
      {/* LEFT COLUMN: Unified B2B Shipment Details Card */}
      <div className="lg:col-span-7 min-w-0 bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
        <div className="border-b border-slate-100 pb-3 flex justify-between items-center gap-2">
          <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2 min-w-0">
            <ClipboardList className="h-4 w-4 text-primary shrink-0" /> <span className="truncate">B2B Cargo Specifications</span>
          </h3>
          <span className="text-[10px] font-black text-slate-500 bg-slate-100 px-2 py-0.5 rounded border border-slate-200 shrink-0">
            LTL / FTL Cargo
          </span>
        </div>

        {/* Section A: Classification & PO Metadata */}
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FormField
              control={control}
              name="product_category"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Product Category
                    <RequiredMark />
                  </FormLabel>
                  <FormControl>
                    <IconSelect
                      data-testid="booking.shipment.category"
                                options={CATEGORY_SELECT_OPTIONS}
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
              control={control}
              name="payment_details.hsn_code"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    HSN Code (Optional)
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. 8517"
                      className="h-9 text-xs bg-white font-mono"
                      {...field}
                      value={field.value || ""}
                    />
                  </FormControl>
                  {field.value && ![4, 6, 8].includes(field.value.length) && (
                    <p className="flex items-center gap-1.5 text-[11px] font-medium text-amber-600 mt-1.5">
                      <TriangleAlert className="h-3.5 w-3.5" />
                      Standard HSN codes are 4, 6, or 8 digits.
                    </p>
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            {productCategoryValue === ProductCategory.OTHER && (
              <FormField
                control={control}
                name="other_category_description"
                render={({ field }) => (
                  <FormItem className="sm:col-span-2 animate-in fade-in duration-150">
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Specify Category
                      <RequiredMark />
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g. Specialized Medical Equipment"
                        className="h-9 text-xs bg-white"
                        {...field}
                        value={field.value || ""}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            )}

            <FormField
              control={control}
              name="po_number"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Purchase Order (PO) Numbers
                  </FormLabel>
                  <FormControl>
                    <Input data-testid="booking.shipment.po-number"
                      placeholder="e.g. PO-98721, PO-98722"
                      className="h-9 text-xs bg-white"
                      {...field}
                      value={field.value || ""}
                    />
                  </FormControl>
                  <FormDescription className="text-[10px] text-slate-400">
                    Up to {MAX_PO_NUMBERS}, separated by commas.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name="po_date"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    PO Date
                  </FormLabel>
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
        </div>

        <hr className="border-slate-100" />

        {/* Section B: Financials & B2B Carrier's Risk */}
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-11 gap-4 items-start">
            <div className="sm:col-span-3 min-w-0">
              <FormField
                control={control}
                name="payment_details.shipment_value"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Cargo Value
                      <RequiredMark />
                    </FormLabel>
                    <InputAdornment prefix="₹">
                    <FormControl>
                      <Input
                        data-testid="booking.payment.goods-value"
                        type="number"
                        min={0}
                        className="h-9 text-xs bg-white font-semibold"
                        {...field}
                        onChange={(e) => {
                          const val = e.target.value;
                          field.onChange(val === "" ? "" : Number(val));
                        }}
                      />
                    </FormControl>
                    </InputAdornment>
                    <FormDescription className="text-[9px] text-slate-400 leading-snug mt-1">
                      Base net invoice cost.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="hidden sm:flex justify-center items-center text-slate-400 font-black text-lg h-9 mt-5 select-none">
              +
            </div>

            <div className="sm:col-span-3 min-w-0">
              <FormField
                control={control}
                name="payment_details.shipment_tax_value"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Product Tax
                    </FormLabel>
                    <InputAdornment prefix="₹">
                    <FormControl>
                      <Input
                        type="number"
                        min={0}
                        className="h-9 text-xs bg-white"
                        {...field}
                        onChange={(e) => {
                          const val = e.target.value;
                          field.onChange(val === "" ? "" : Number(val));
                        }}
                      />
                    </FormControl>
                    </InputAdornment>
                    <FormDescription className="text-[9px] text-slate-400 leading-snug mt-1">
                      Product GST applied.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>

            <div className="hidden sm:flex justify-center items-center text-slate-400 font-black text-lg h-9 mt-5 select-none">
              =
            </div>

            <div className="sm:col-span-3 min-w-0">
              <FormField
                control={control}
                name="payment_details.shipment_total_value"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-bold text-slate-800">
                      Total Cargo Value
                    </FormLabel>
                    <InputAdornment prefix="₹">
                    <FormControl>
                      <Input data-testid="booking.payment.goods-total"
                        type="number"
                        className="h-9 text-xs bg-slate-50 font-bold text-slate-900 border-slate-300"
                        {...field}
                        readOnly
                      />
                    </FormControl>
                    </InputAdornment>
                    <FormDescription className="text-[9px] text-slate-500 font-medium leading-snug mt-1">
                      Value + tax, calculated for you.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </div>

          {/* Carrier's Risk Surcharge Toggler (Phase 3 Spec) */}
          <FormField
            control={control}
            name="is_carriers_risk"
            render={({ field }) => (
              <FormItem className={`flex flex-row items-start space-x-3 space-y-0 rounded-xl border p-4 transition-all duration-150 select-none cursor-pointer ${
                field.value 
                  ? "bg-primary/5 border-primary/30 shadow-3xs" 
                  : "bg-white border-slate-200 hover:border-slate-350"
              }`}
              onClick={() => field.onChange(!field.value)}
              >
                <FormControl>
                  <input data-testid="booking.shipment.carriers-risk"
                    type="checkbox"
                    className="h-4.5 w-4.5 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0 mt-0.5"
                    checked={!!field.value}
                    onChange={(e) => {
                      e.stopPropagation();
                      field.onChange(e.target.checked);
                    }}
                  />
                </FormControl>
                <div className="space-y-1 leading-none">
                  <FormLabel className="text-xs font-extrabold text-slate-900 flex items-center gap-1.5 cursor-pointer">
                    <ShieldCheck className={`h-4 w-4 ${field.value ? "text-primary" : "text-slate-500"}`} />
                    Carrier&apos;s Risk (Goods Insurance & Liability Coverage)
                  </FormLabel>
                  <FormDescription className="text-[10px] text-slate-500 leading-normal pt-0.5">
                    <strong>Checked (Carrier&apos;s Risk):</strong> the carrier is liable for the goods in transit; any extra charge shows in the price breakup.<br />
                    <strong>Unchecked (Owner&apos;s Risk):</strong> you bear the transit risk.
                  </FormDescription>
                </div>
              </FormItem>
            )}
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            <FormField
              control={control}
              name="payment_details.freight_payment_mode"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    B2B Billing Mode
                  </FormLabel>
                  <FormControl>
                    <IconSelect
                      data-testid="booking.payment.mode"
                                options={freightModeOptions}
                      value={field.value}
                      onValueChange={field.onChange}
                      placeholder="Choose billing mode"
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            {/* Logismart Prime has no Cash on Delivery at launch (pricing decision Q9). */}
            <div
              className="flex items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50/40 p-2 px-3 min-h-9 self-end mt-6 text-xs text-slate-600"
              data-testid="booking.payment.cod-unavailable"
            >
              <Banknote className="h-4 w-4 text-slate-400 shrink-0" />
              Cash on Delivery isn&apos;t available for B2B cargo yet. LRs are billed to your wallet.
            </div>
          </div>

          {/* Logismart Prime Delivery Mode: Door Delivery vs Godown / Hub Self-Pickup */}
          <FormField
            control={control}
            name="door_delivery"
            render={({ field }) => {
              const isDoor = Boolean(field.value);
              return (
                <FormItem className="space-y-2" data-testid="b2b-delivery-mode-selector">
                  <div className="flex items-center justify-between">
                    <FormLabel className="text-xs font-extrabold text-slate-900">
                      B2B Delivery Type (Doorstep vs Destination Godown)
                    </FormLabel>
                    <span className="text-[10px] font-bold text-slate-500">
                      Affects Logismart Prime pricing
                    </span>
                  </div>
                  <FormControl>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3" role="radiogroup" aria-label="B2B Delivery Type">
                      {/* Card 1: Door Delivery */}
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
                        className={`flex flex-row items-start space-x-3 rounded-xl border p-4 transition-all duration-150 select-none cursor-pointer ${
                          isDoor
                            ? "bg-primary/5 border-primary ring-1 ring-primary/20 shadow-3xs"
                            : "bg-white border-slate-200 hover:border-slate-300"
                        }`}
                      >
                        <input
                          data-testid="booking.shipment.door-delivery"
                          type="radio"
                          readOnly
                          className="h-4.5 w-4.5 rounded-full border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0 mt-0.5"
                          checked={isDoor}
                          onClick={(e) => {
                            e.stopPropagation();
                            field.onChange(true);
                          }}
                        />
                        <div className="space-y-1 leading-none">
                          <span className="text-xs font-extrabold text-slate-900 flex items-center gap-1.5">
                            <Truck className={`h-4 w-4 shrink-0 ${isDoor ? "text-primary" : "text-slate-500"}`} />
                            Door Delivery (To Consignee Doorstep)
                          </span>
                          <p className="text-[10px] text-slate-500 leading-normal pt-0.5">
                            Deliver directly to consignee&apos;s address (lane Door Delivery charge applies)
                          </p>
                        </div>
                      </div>

                      {/* Card 2: Godown / Hub Pickup */}
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
                        className={`flex flex-row items-start space-x-3 rounded-xl border p-4 transition-all duration-150 select-none cursor-pointer ${
                          !isDoor
                            ? "bg-emerald-50/60 border-emerald-400 ring-1 ring-emerald-200 shadow-3xs"
                            : "bg-white border-slate-200 hover:border-slate-300"
                        }`}
                      >
                        <input
                          type="radio"
                          readOnly
                          checked={!isDoor}
                          onClick={(e) => {
                            e.stopPropagation();
                            field.onChange(false);
                          }}
                          className="h-4.5 w-4.5 rounded-full border-slate-300 text-emerald-600 focus:ring-emerald-600 cursor-pointer accent-emerald-600 shrink-0 mt-0.5"
                        />
                        <div className="space-y-1 leading-none">
                          <span className="text-xs font-extrabold text-slate-900 flex items-center gap-1.5">
                            <Warehouse className={`h-4 w-4 shrink-0 ${!isDoor ? "text-emerald-700" : "text-slate-500"}`} />
                            Godown / Hub Pickup (Self-Pickup at Destination Hub)
                          </span>
                          <p className="text-[10px] text-slate-500 leading-normal pt-0.5">
                            Consignee collects from destination transport godown (₹0 Door Delivery fee)
                          </p>
                        </div>
                      </div>
                    </div>
                  </FormControl>
                </FormItem>
              );
            }}
          />
        </div>

        <hr className="border-slate-100" />

        {/* Section C: Multiple Invoicing & Compliance */}
        <div className="space-y-4">
          <div>
            <div className="flex justify-between items-center mb-2">
              <FormLabel className="text-xs font-bold text-slate-900">
                GST Commercial Invoices
                <RequiredMark />
              </FormLabel>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addInvoiceNumber}
                className="h-7 text-[10px] font-extrabold px-2.5"
                data-testid="booking.payment.add-invoice"
              >
                <Plus className="h-3 w-3 mr-1" /> Add Invoice
              </Button>
            </div>

            {invoiceNumbers.length === 0 ? (
              <div className="text-center p-4 bg-slate-50 rounded-lg border border-dashed border-slate-250 text-xs text-slate-500">
                No invoices added. Click &quot;Add Invoice&quot; to specify compliance records.
              </div>
            ) : (
              <div className="space-y-2 max-h-40 overflow-y-auto pr-1">
                {invoiceNumbers.map((invNum, idx) => (
                  <div key={idx} className="flex items-center gap-2 animate-in fade-in duration-100">
                    <span className="text-[10px] font-bold text-slate-400 w-6">#{idx + 1}</span>
                    <Input
                      data-testid={`booking.payment.invoice-number-${idx}`}
                      placeholder="e.g. INV-2026-001"
                      className="h-8 text-xs font-mono bg-white flex-1"
                      value={invNum}
                      onChange={(e) => updateInvoiceNumber(idx, e.target.value)}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-red-500 hover:bg-red-50"
                      onClick={() => removeInvoiceNumber(idx)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            <FormDescription className="text-[9px] text-slate-400 mt-1">
              Provide commercial billing invoices linked to this shipment.
            </FormDescription>
            {invoiceNumbersError && (
              <p className="text-[0.8rem] font-medium text-destructive" data-testid="booking.payment.invoice-error">
                {invoiceNumbersError}
              </p>
            )}
          </div>

          <FormField
            control={control}
            name="payment_details.invoice_date"
            render={({ field }) => (
              <FormItem className="w-full sm:w-1/2">
                <FormLabel className="text-xs font-semibold text-slate-700">
                  Consolidated Invoice Date
                </FormLabel>
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

          {/* E-Way Bills compliance list */}
          <div className="space-y-3 pt-2">
            {showEWayBill && <EWayBillBanner tenant={tenant} />}
            
            <div className="flex justify-between items-center mb-1">
              <FormLabel className="text-xs font-bold text-slate-900">
                E-Way Bill Numbers {showEWayBill && <RequiredMark />}
              </FormLabel>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={addEwayBillNumber}
                className="h-7 text-[10px] font-extrabold px-2.5"
                data-testid="booking.payment.add-eway-bill"
              >
                <Plus className="h-3 w-3 mr-1" /> Add E-Way Bill
              </Button>
            </div>

            {ewayBillNumbers.length === 0 ? (
              <div className="text-center p-4 bg-slate-50 rounded-lg border border-dashed border-slate-250 text-xs text-slate-500">
                No E-Way Bills configured.
              </div>
            ) : (
              <div className="space-y-2 max-h-40 overflow-y-auto pr-1">
                {ewayBillNumbers.map((ewayNum, idx) => (
                  <div key={idx} className="flex items-center gap-2 animate-in fade-in duration-100">
                    <span className="text-[10px] font-bold text-slate-400 w-6">#{idx + 1}</span>
                    <Input
                      data-testid="booking.payment.eway-bill"
                      placeholder="12-digit E-Way Bill Number"
                      className="h-8 text-xs font-mono bg-white flex-1 tracking-wider"
                      value={ewayNum}
                      maxLength={12}
                      onChange={(e) => updateEwayBillNumber(idx, e.target.value.replace(/\D/g, ""))}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-red-500 hover:bg-red-50"
                      onClick={() => removeEwayBillNumber(idx)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
              </div>
            )}
            {showEWayBill && ewayBillNumbers.length === 0 && (
              <p className="text-[10px] font-bold text-red-500">
                * An E-Way Bill is mandatory since commercial total exceeds ₹50,000.
              </p>
            )}
          </div>

          {/* Integrated Documents & Photos Uploader */}
          <div className="bg-slate-50/50 p-4 rounded-xl border border-slate-200/60 space-y-4 mt-2">
            <p className="text-xs text-slate-600 leading-relaxed">
              Upload copies of invoices, PO copies, E-Way bills, or package condition photos to log their state.
            </p>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-1 min-w-0">
              <IconSelect
                aria-label="Document type"
                options={DOC_TYPE_SELECT_OPTIONS}
                onValueChange={(val) =>
                  document
                    .getElementById("b2b-file-upload")
                    ?.setAttribute("data-type", val)
                }
                placeholder="Select document type"
                triggerClassName="w-full sm:w-[200px] sm:shrink-0"
              />

              <div className="flex-1 min-w-0 flex gap-2 items-center">
                <Input
                  id="b2b-file-upload"
                  type="file"
                  disabled={isUploading}
                  className="w-full min-w-0 bg-white h-9 text-xs file:text-primary file:bg-primary/5 file:border-0 file:rounded-md file:px-3 file:py-1 cursor-pointer overflow-hidden"
                  onChange={(e) => {
                    const type = e.target.getAttribute("data-type") as DocumentType;
                    if (!type) {
                      toast.error("Please select a document type first!");
                      e.target.value = "";
                      return;
                    }
                    handleFileUpload(e, type);
                  }}
                />
              </div>
            </div>
          </div>

          {/* Uploaded documents list */}
          {docFields.length > 0 && (
            <div className="space-y-2 pt-2 animate-in fade-in duration-200">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
                Attached Documents ({docFields.length})
              </span>
              {docFields.map((doc, idx) => (
                <div
                  key={doc.id}
                  className="flex items-center justify-between p-2.5 bg-slate-50/50 border border-slate-200 rounded-lg text-xs"
                >
                  <div className="flex items-center gap-2 overflow-hidden mr-4">
                    <FileText className="h-4 w-4 text-slate-400 shrink-0" />
                    <div className="min-w-0">
                      <p className="font-bold text-slate-800 truncate">
                        {getOptionMeta(DOCUMENT_TYPE_OPTIONS, doc.document_type)?.label ?? doc.document_type}
                      </p>
                      <p className="text-[10px] text-slate-500 truncate">
                        {doc.file_name}
                      </p>
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() => removeDoc(idx)}
                    className="h-7 w-7 text-red-500 hover:text-red-700 hover:bg-red-50 shrink-0 cursor-pointer"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}

          {(!docFields || !docFields.some(d => d.document_type === DocumentType.GST_INVOICE)) && (
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-amber-600 mt-2">
              <TriangleAlert className="h-3.5 w-3.5" />
              Missing invoice document. It is recommended to upload an invoice file.
            </p>
          )}
        </div>
      </div>

      {/* RIGHT COLUMN: Logistics details (Unified Addresses, B2B Operational Flags, Box Details) */}
      <div className="lg:col-span-5 min-w-0 space-y-6">
        {/* Symmetrical Unified Route Addresses Card */}
        <div className="bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-3">
            <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2">
              <Truck className="h-4 w-4 text-primary shrink-0" /> Route Address Details
            </h3>
          </div>

          <div className="space-y-6">
            <div>
              <h4 className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 border-l-2 border-primary pl-2 flex items-center gap-1.5">
                <ArrowUpRight className="h-3.5 w-3.5 text-primary shrink-0" /> B2B Origin (Pickup Address)
              </h4>
              <AddressFieldset
                control={control as unknown as Control<HasAddresses>}
                type="pickup"
                title="B2B Origin (Pickup Address)"
                savedAddresses={savedAddresses}
                minimal={true}
              />
            </div>

            <hr className="border-slate-100" />

            <div>
              <h4 className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 border-l-2 border-primary pl-2 flex items-center gap-1.5">
                <ArrowDownLeft className="h-3.5 w-3.5 text-primary shrink-0" /> B2B Destination (Delivery Address)
              </h4>
              <AddressFieldset
                control={control as unknown as Control<HasAddresses>}
                type="delivery"
                title="B2B Destination (Delivery Address)"
                savedAddresses={savedAddresses}
                minimal={true}
              />
            </div>
          </div>
        </div>

        {/* Appointment Scheduler & Strategy Card (Phase 3 Spec) */}
        <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-sm space-y-5 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-2 flex items-center gap-2">
            <Calendar className="h-4 w-4 text-primary shrink-0" />
            <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider">
              B2B Dispatch & Appointment
            </h3>
          </div>

          <div className="space-y-4">
            <FormField
              control={control}
              name="pickup_strategy"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Pickup Strategy
                  </FormLabel>
                  <FormControl>
                    <IconSelect
                      options={STRATEGY_SELECT_OPTIONS}
                      value={field.value || PickupStrategy.DEFAULT}
                      onValueChange={field.onChange}
                    />
                  </FormControl>
                  <FormDescription className="text-[9px] text-slate-400 mt-1">
                    {getOptionMeta(PICKUP_STRATEGY_OPTIONS, field.value || PickupStrategy.DEFAULT)?.description}
                  </FormDescription>
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name="appointment_id"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Warehouse Appointment Reference ID
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. APPT-872A"
                      className="h-9 text-xs bg-white"
                      {...field}
                      value={field.value || ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              <FormField
                control={control}
                name="appointment_start"
                render={({ field }) => (
                  <FormItem className="min-w-0">
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Window Start (IST)
                    </FormLabel>
                    <FormControl>
                      <Input
                        type="datetime-local"
                        className="w-full min-w-0 h-9 text-xs bg-white"
                        name={field.name}
                        ref={field.ref}
                        onBlur={field.onBlur}
                        value={toIstDateTimeLocalValue(field.value)}
                        onChange={(e) =>
                          field.onChange(toIstIsoString(e.target.value) || "")
                        }
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={control}
                name="appointment_end"
                render={({ field }) => (
                  <FormItem className="min-w-0">
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Window End (IST)
                    </FormLabel>
                    <FormControl>
                      <Input
                        type="datetime-local"
                        className="w-full min-w-0 h-9 text-xs bg-white"
                        name={field.name}
                        ref={field.ref}
                        onBlur={field.onBlur}
                        value={toIstDateTimeLocalValue(field.value)}
                        onChange={(e) =>
                          field.onChange(toIstIsoString(e.target.value) || "")
                        }
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          </div>
        </div>

        {/* B2B Cargo Configuration (Standard or Blind Pickup) */}
        <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-sm space-y-5 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-2 flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
              <Boxes className="h-4 w-4 text-primary shrink-0" /> Box Configuration
            </h3>

            {/* Blind Pickup Switcher (Phase 3 Spec) */}
            <FormField
              control={control}
              name="is_blind_pickup"
              render={({ field }) => (
                <div className="flex items-center gap-1.5">
                  <input
                    id="blindPickupCheck"
                    type="checkbox"
                    className="h-4 w-4 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary"
                    checked={!!field.value}
                    onChange={(e) => {
                      field.onChange(e.target.checked);
                      if (e.target.checked) {
                        // Clear packages state to force default construction
                        setValue("estimated_box_count", 1);
                      } else {
                        setValue("estimated_box_count", null);
                      }
                    }}
                  />
                  <label
                    htmlFor="blindPickupCheck"
                    className="text-[10px] font-black text-slate-700 uppercase tracking-wider cursor-pointer"
                  >
                    Blind Pickup
                  </label>
                </div>
              )}
            />
          </div>

          {/* Conditional rendering based on Blind Pickup */}
          {isBlindPickup ? (
            <div className="bg-amber-50/20 border border-amber-200 p-4 rounded-xl space-y-4 animate-in fade-in duration-200">
              <div className="flex items-start gap-2 text-amber-800">
                <ShieldAlert className="h-4.5 w-4.5 shrink-0 text-amber-600 mt-0.5" />
                <p className="text-[10px] leading-relaxed font-semibold">
                  <strong>Blind Pickup Mode Active:</strong> Dimensional specifications ($L \times B \times H$) and individual box weights are hidden from sender.
                  The shipment will be billed strictly on actual arrival weight. Please specify estimated boxes for courier labels.
                </p>
              </div>

              <FormField
                control={control}
                name="estimated_box_count"
                render={({ field }) => (
                  <FormItem className="bg-white p-3 rounded-lg border border-slate-200">
                    <FormLabel className="text-xs font-bold text-slate-800">
                      Estimated Box Count
                      <RequiredMark />
                    </FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        min={1}
                        className="h-9 text-xs bg-white font-bold"
                        {...field}
                        value={field.value || ""}
                        onChange={(e) => {
                          const val = e.target.value;
                          field.onChange(val === "" ? "" : Number(val));
                        }}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
            </div>
          ) : (
            <>
              <PackageFieldset
                control={control as unknown as Control<HasPackages>}
                isReverse={false}
              />

              {/* Dynamic Cargo Summary Banner */}
              {cargoTotals.actualWeightKg > 0 && (
                <div className="bg-slate-50 border border-slate-200/80 rounded-lg p-3.5 flex items-center justify-between text-xs text-slate-700 font-medium animate-in fade-in duration-200 shadow-3xs">
                  <span className="flex items-center gap-1.5">
                    <span>📦</span>
                    <span>
                      Cargo: <strong>{cargoTotals.boxCount}</strong> {cargoTotals.boxCount === 1 ? "box" : "boxes"}
                    </span>
                  </span>
                  <span className="text-slate-500">
                    Total Weight:{" "}
                    <strong className="text-slate-900 font-bold">
                      {cargoTotals.actualWeightKg.toFixed(2)} kg
                    </strong>
                  </span>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
