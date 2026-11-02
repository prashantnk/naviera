// src/app/[tenant_slug]/(app)/shipments/new/_components/forward-form-step.tsx
"use client";

import {
  AddressRead,
  ProductCategory,
  DocumentType,
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
  B2C_PRODUCT_CATEGORIES,
  DOCUMENT_TYPE_OPTIONS,
  FREIGHT_PAYMENT_MODE_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
  getOptionMeta,
  optionLabels,
  freightPaymentModesFor,
  toOptions,
} from "@/lib/form-options";
import { useUser } from "@/components/auth/auth-guard";
import { Button } from "@/components/ui/button";
import { useState } from "react";
import {
  Control,
  useWatch,
  useFormContext,
  FieldArrayWithId,
} from "react-hook-form";
import { ForwardShipmentFormValues } from "@/lib/validations/shipment";
import { useShipmentValuation } from "@/components/booking/use-shipment-valuation";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { FileText, Trash2, ClipboardList, Truck, ArrowUpRight, ArrowDownLeft, Boxes, Banknote, TriangleAlert, ChevronDown, ChevronUp, ShieldCheck } from "lucide-react";
import { toast } from "sonner";

/** Legacy label lookup kept for existing importers (detail and edit pages). */
export const CATEGORY_LABELS: Record<ProductCategory, string> = optionLabels(PRODUCT_CATEGORY_OPTIONS);

// B2C wizard: no "Commercial Goods" (a B2B Cargo category, audit A-02).
const CATEGORY_SELECT_OPTIONS = toOptions(PRODUCT_CATEGORY_OPTIONS, B2C_PRODUCT_CATEGORIES);
const DOC_TYPE_SELECT_OPTIONS = toOptions(DOCUMENT_TYPE_OPTIONS);

interface ForwardFormStepProps {
  control: Control<ForwardShipmentFormValues>;
  savedAddresses: AddressRead[];
  addShippingToCod: boolean;
  setAddShippingToCod: (val: boolean) => void;
  docFields: FieldArrayWithId<ForwardShipmentFormValues, "documents">[];
  removeDoc: (index: number) => void;
  isUploading: boolean;
  handleFileUpload: (
    e: React.ChangeEvent<HTMLInputElement>,
    docType: DocumentType,
  ) => Promise<void>;
}

export function ForwardFormStep({
  control,
  savedAddresses,
  addShippingToCod,
  setAddShippingToCod,
  docFields,
  removeDoc,
  isUploading,
  handleFileUpload,
}: ForwardFormStepProps) {
  // Merchants can't self-select POSTPAID (needs an approved credit account, decision D14).
  const { isAdmin } = useUser();
  const freightModeOptions = toOptions(FREIGHT_PAYMENT_MODE_OPTIONS, freightPaymentModesFor(isAdmin));

  const { tenant } = useTenant();
  const { setValue, getValues } = useFormContext<ForwardShipmentFormValues>();

  // D-06: the goods total and the e-way bill rule come from the backend valuation.
  const watchedShipmentValue = useWatch({ control, name: "payment_details.shipment_value" });
  const watchedShipmentTaxValue = useWatch({ control, name: "payment_details.shipment_tax_value" });
  const showEWayBill = Boolean(useWatch({ control, name: "payment_details.eway_bill_required" }));
  const watchedHsnCode = useWatch({ control, name: "payment_details.hsn_code" });
  const watchedInvoiceNumber = useWatch({ control, name: "payment_details.invoice_number" });
  const watchedInvoiceDate = useWatch({ control, name: "payment_details.invoice_date" });
  const watchedEwayBillNumber = useWatch({ control, name: "payment_details.eway_bill_number" });
  const [manualComplianceOpen, setManualComplianceOpen] = useState(false);

  const hasSavedComplianceData = Boolean(
    watchedHsnCode ||
      watchedInvoiceNumber ||
      watchedInvoiceDate ||
      watchedEwayBillNumber ||
      docFields.length > 0
  );
  const isComplianceOpen = manualComplianceOpen || showEWayBill || hasSavedComplianceData;

  useShipmentValuation(watchedShipmentValue, watchedShipmentTaxValue, (valuation) => {
    setValue("payment_details.shipment_total_value", valuation.shipment_total_value);
    setValue("payment_details.eway_bill_required", valuation.eway_bill_required);
  });

  const productCategoryValue = useWatch({
    control,
    name: "product_category",
  }) as ProductCategory | undefined;

  const watchedIsCod = useWatch({
    control,
    name: "payment_details.is_cod",
  }) as boolean | undefined;

  const watchedPackages = useWatch({
    control,
    name: "packages",
  }) as ForwardShipmentFormValues["packages"] | undefined;

  // Reactive calculation of cargo totals for standard summary
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


  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
      {/* LEFT COLUMN: Single Unified Shipment Details Card (Transactional Specs) */}
      <div className="lg:col-span-7 min-w-0 bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
        <div className="border-b border-slate-100 pb-3">
          <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary shrink-0" /> Shipment Details
          </h3>
        </div>

        {/* Section A: Classification */}
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <FormField
              control={control}
              name="product_category"
              render={({ field }) => (
                <FormItem className="sm:col-span-2">
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
                        placeholder="e.g. Grandfather Clock"
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
          </div>
        </div>

        <hr className="border-slate-100" />

        {/* Section B: Financials & Valuation */}
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-11 gap-4 items-start">
            <div className="sm:col-span-3 min-w-0">
              <FormField
                control={control}
                name="payment_details.shipment_value"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Shipment Value
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
                      Base net commercial cost.
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
                      Tax Value
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
                      Commercial tax applied.
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
                      Total Value
                    </FormLabel>
                    <InputAdornment prefix="₹">
                    <FormControl>
                      <Input
                        data-testid="booking.payment.goods-total"
                        type="number"
                        readOnly
                        tabIndex={-1}
                        aria-readonly="true"
                        className="h-9 text-xs bg-slate-50 font-bold text-slate-900 border-slate-300 cursor-default"
                        {...field}
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

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            <FormField
              control={control}
              name="payment_details.freight_payment_mode"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Who pays for shipping?
                  </FormLabel>
                  <FormControl>
                    <IconSelect
                      data-testid="booking.payment.mode"
                                options={freightModeOptions}
                      value={field.value}
                      onValueChange={field.onChange}
                      placeholder="Choose who pays"
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name="payment_details.is_cod"
              render={({ field }) => (
                <FormItem className="flex flex-row items-center justify-between rounded-lg border border-slate-200 bg-slate-50/40 p-2 px-3 h-9 self-end mt-6">
                  <div className="flex items-center gap-1.5">
                    <Banknote className="h-4 w-4 text-slate-500 shrink-0" />
                    <span className="text-xs font-semibold text-slate-700">
                      Cash on Delivery (COD)
                    </span>
                  </div>
                  <FormControl>
                    <input data-testid="booking.payment.cod-toggle"
                      type="checkbox"
                      className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900 cursor-pointer accent-slate-900"
                      checked={field.value}
                      onChange={(e) => {
                        field.onChange(e.target.checked);
                        if (e.target.checked) {
                          const total =
                            getValues("payment_details.shipment_total_value") ||
                            0;
                          setValue("payment_details.cod_amount", total, {
                            shouldValidate: true,
                          });
                        } else {
                          setValue("payment_details.cod_amount", 0);
                          setAddShippingToCod(false);
                        }
                      }}
                    />
                  </FormControl>
                </FormItem>
              )}
            />
          </div>

          {/* Dynamic COD Settings Card */}
          {watchedIsCod && (
            <div className="bg-slate-50/50 border border-slate-200/60 p-4 rounded-lg grid grid-cols-1 sm:grid-cols-2 gap-4 items-center animate-in fade-in duration-200">
              <FormField
                control={control}
                name="payment_details.cod_amount"
                render={({ field }) => (
                  <FormItem className="bg-white p-3 rounded-lg border border-slate-200">
                    <FormLabel className="text-[11px] font-semibold text-slate-800 block mb-1">
                      Collectible amount for sender
                    </FormLabel>
                    <InputAdornment prefix="₹">
                    <FormControl>
                      <Input
                        type="number"
                        min={0}
                        className="h-8 text-xs bg-white font-bold"
                        {...field}
                        onChange={(e) => {
                          const val = e.target.value;
                          field.onChange(val === "" ? "" : Number(val));
                        }}
                      />
                    </FormControl>
                    </InputAdornment>
                    <FormDescription className="text-[9px] text-slate-400 leading-snug mt-1">
                      Defaulted to Shipment Total Value.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div
                onClick={() => setAddShippingToCod(!addShippingToCod)}
                className={`flex items-start p-3.5 rounded-xl border transition-all duration-150 justify-center flex-col select-none h-[78px] ${
                  addShippingToCod
                    ? "bg-primary/5 border-primary/30 shadow-3xs"
                    : "bg-white border-slate-200 hover:border-slate-300 cursor-pointer"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <input
                    id="addShippingToCodCheck"
                    type="checkbox"
                    className="h-4.5 w-4.5 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0"
                    checked={addShippingToCod}
                    onClick={(e) => e.stopPropagation()}
                    onChange={(e) => setAddShippingToCod(e.target.checked)}
                  />
                  <label
                    htmlFor="addShippingToCodCheck"
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs font-extrabold select-none leading-tight cursor-pointer text-slate-900"
                  >
                    Add shipping charges to customer&apos;s COD
                  </label>
                </div>
                <p className="text-[10px] text-slate-400 leading-snug mt-1 pl-7">
                  Add final dynamic freight to COD.
                </p>
              </div>
            </div>
          )}

        </div>

        <hr className="border-slate-100" />

        {/* Section C: Progressive Disclosure — Optional Tax, Invoice & Compliance */}
        <div
          className="rounded-xl border border-slate-200 bg-slate-50/60 p-4 space-y-4"
          data-testid="booking.compliance.section"
        >
          <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
            <div className="space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                <ShieldCheck className="h-4 w-4 text-primary shrink-0" />
                <span className="text-xs font-extrabold text-slate-900 uppercase tracking-wide">
                  Optional Tax, Invoice &amp; Compliance Details
                </span>
                <Badge
                  variant="outline"
                  data-testid="booking.compliance.badge"
                  className={
                    showEWayBill
                      ? "border-amber-300 bg-amber-50 text-[10px] font-bold text-amber-900"
                      : "border-slate-200 bg-white text-[10px] font-semibold text-slate-600"
                  }
                >
                  {showEWayBill
                    ? "Required above ₹50,000 (E-Way Bill)"
                    : "Optional (Required only above ₹50,000)"}
                </Badge>
              </div>
              <p className="text-[11px] text-slate-500">
                HSN code, seller invoice number/date, E-Way Bill (above ₹50,000), and package photos.
              </p>
            </div>

            {!showEWayBill && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setManualComplianceOpen((prev) => !prev)}
                data-testid="booking.compliance.toggle"
                className="h-8 shrink-0 bg-white text-xs font-semibold"
              >
                {isComplianceOpen ? (
                  <>
                    <span>Hide Optional Details</span>
                    <ChevronUp className="ml-1.5 h-3.5 w-3.5" />
                  </>
                ) : (
                  <>
                    <span>Add HSN / Invoice / Photos</span>
                    <ChevronDown className="ml-1.5 h-3.5 w-3.5" />
                  </>
                )}
              </Button>
            )}
          </div>

          {isComplianceOpen && (
            <div
              className="space-y-4 border-t border-slate-200/80 pt-4 animate-in fade-in duration-150"
              data-testid="booking.compliance.content"
            >
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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

                <FormField
                  control={control}
                  name="payment_details.invoice_number"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-xs font-semibold text-slate-700">
                        Invoice Number (Optional)
                      </FormLabel>
                      <FormControl>
                        <Input
                          placeholder="e.g. INV-992"
                          className="h-9 text-xs bg-white font-mono"
                          {...field}
                          value={field.value || ""}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={control}
                  name="payment_details.invoice_date"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-xs font-semibold text-slate-700">
                        Invoice Date (Optional)
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

              {/* E-Way Bill Number inputs */}
              {showEWayBill && (
                <div className="space-y-3 pt-2 animate-in fade-in slide-in-from-top-1 duration-200">
                  <EWayBillBanner tenant={tenant} />
                  <FormField
                    control={control}
                    name="payment_details.eway_bill_number"
                    render={({ field }) => (
                      <FormItem className="bg-white border border-slate-200/80 p-4 rounded-lg">
                        <FormLabel className="text-xs font-bold text-slate-900">
                          E-Way Bill Number
                          <RequiredMark />
                        </FormLabel>
                        <FormControl>
                          <Input
                            data-testid="booking.payment.eway-bill"
                            placeholder="Enter 12-digit E-Way Bill number"
                            className="h-9 bg-white font-mono tracking-widest text-sm"
                            {...field}
                            value={field.value || ""}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              )}

              {/* Integrated Documents & Photos Uploader */}
              <div className="bg-white p-4 rounded-xl border border-slate-200/80 space-y-4">
                <p className="text-xs text-slate-600 leading-relaxed">
                  Upload copies of invoices, E-Way bills, or{" "}
                  <strong className="text-slate-800">photos of the packages</strong>{" "}
                  to log their condition before dispatch.
                </p>

                <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-1 min-w-0">
                  <IconSelect
                    aria-label="Document type"
                    options={DOC_TYPE_SELECT_OPTIONS}
                    onValueChange={(val) =>
                      document
                        .getElementById("sandbox-file-upload")
                        ?.setAttribute("data-type", val)
                    }
                    placeholder="Select document type"
                    triggerClassName="w-full sm:w-[200px] sm:shrink-0"
                  />

                  <div className="flex-1 min-w-0 flex gap-2 items-center">
                    <Input
                      id="sandbox-file-upload"
                      type="file"
                      disabled={isUploading}
                      className="w-full min-w-0 bg-white h-9 text-xs file:text-primary file:bg-primary/5 file:border-0 file:rounded-md file:px-3 file:py-1 cursor-pointer overflow-hidden"
                      onChange={(e) => {
                        const type = e.target.getAttribute(
                          "data-type",
                        ) as DocumentType;
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
                      className="flex items-center justify-between p-2.5 bg-white border border-slate-200 rounded-lg text-xs"
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
            </div>
          )}
        </div>
      </div>

      {/* RIGHT COLUMN: Logistics details (Unified Addresses Card, Cargo configurations & summary) */}
      <div className="lg:col-span-5 min-w-0 space-y-6">
        {/* Symmetrical Unified Route Addresses Card */}
        <div className="bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-3">
            <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2">
              <Truck className="h-4 w-4 text-primary shrink-0" /> Delivery Details
            </h3>
          </div>

          <div className="space-y-6">
            <div>
              <h4 className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 border-l-2 border-primary pl-2 flex items-center gap-1.5">
                <ArrowUpRight className="h-3.5 w-3.5 text-primary shrink-0" /> Sender Details (Pickup Location)
              </h4>
              <AddressFieldset
                control={control as unknown as Control<HasAddresses>}
                type="pickup"
                title="Sender Details (Pickup Location)"
                savedAddresses={savedAddresses}
                minimal={true}
              />
            </div>

            <hr className="border-slate-100" />

            <div>
              <h4 className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 border-l-2 border-primary pl-2 flex items-center gap-1.5">
                <ArrowDownLeft className="h-3.5 w-3.5 text-primary shrink-0" /> Receiver Details (Delivery Location)
              </h4>
              <AddressFieldset
                control={control as unknown as Control<HasAddresses>}
                type="delivery"
                title="Receiver Details (Delivery Location)"
                savedAddresses={savedAddresses}
                minimal={true}
              />
            </div>
          </div>
        </div>

        {/* Cargo Configurations Card */}
        <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-xs space-y-5 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-2">
            <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
              <Boxes className="h-4 w-4 text-primary shrink-0" /> Box Details
            </h3>
          </div>

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
                  Cargo Summary: <strong>{cargoTotals.boxCount}</strong>{" "}
                  {cargoTotals.boxCount === 1 ? "box" : "boxes"} configured
                </span>
              </span>
              <span className="text-slate-500">
                Total Actual Weight:{" "}
                <strong className="text-slate-900 font-bold">
                  {cargoTotals.actualWeightKg.toFixed(2)} kg
                </strong>
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
