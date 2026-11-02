// src/app/[tenant_slug]/(app)/shipments/new/_components/reverse-form-step.tsx
"use client";

import {
  AddressRead,
  ProductCategory,
  FreightPaymentMode,
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
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { IconSelect } from "@/components/ui/icon-select";
import { InputAdornment, RequiredMark } from "@/components/ui/form-extras";
import {
  B2C_PRODUCT_CATEGORIES,
  DOCUMENT_TYPE_OPTIONS,
  FREIGHT_PAYMENT_MODE_OPTIONS,
  PRODUCT_CATEGORY_OPTIONS,
  RETURN_REASON_OPTIONS,
  getOptionMeta,
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
import { ReverseShipmentFormValues } from "@/lib/validations/shipment";
import { useShipmentValuation } from "@/components/booking/use-shipment-valuation";
import {
  FileText,
  Trash2,
  ClipboardList,
  Truck,
  ArrowUpRight,
  ArrowDownLeft,
  Boxes,
  ShieldCheck,
  RotateCcw,
} from "lucide-react";
import { toast } from "sonner";

/** Legacy preset strings (the exact text written into reason_for_return). */
export const RETURN_REASON_PRESETS: string[] = RETURN_REASON_OPTIONS.map((option) => option.value);

// B2C returns: no "Commercial Goods" (a B2B Cargo category, audit A-02).
const CATEGORY_SELECT_OPTIONS = toOptions(PRODUCT_CATEGORY_OPTIONS, B2C_PRODUCT_CATEGORIES);
/** Reverse pickups are always billed to the merchant (no To Pay). */
const RETURN_BILLING_MODES: readonly FreightPaymentMode[] = [
  FreightPaymentMode.PREPAID,
  FreightPaymentMode.POSTPAID,
];
const DOC_TYPE_SELECT_OPTIONS = toOptions(DOCUMENT_TYPE_OPTIONS);

interface ReverseFormStepProps {
  control: Control<ReverseShipmentFormValues>;
  savedAddresses: AddressRead[];
  docFields: FieldArrayWithId<ReverseShipmentFormValues, "documents">[];
  removeDoc: (index: number) => void;
  isUploading: boolean;
  handleFileUpload: (
    e: React.ChangeEvent<HTMLInputElement>,
    docType: DocumentType
  ) => Promise<void>;
}

export function ReverseFormStep({
  control,
  savedAddresses,
  docFields,
  removeDoc,
  isUploading,
  handleFileUpload,
}: ReverseFormStepProps) {
  // Merchants can't self-select POSTPAID (needs an approved credit account, decision D14).
  const { isAdmin } = useUser();
  const freightModeOptions = toOptions(FREIGHT_PAYMENT_MODE_OPTIONS, freightPaymentModesFor(isAdmin, RETURN_BILLING_MODES));

  const { setValue } = useFormContext<ReverseShipmentFormValues>();

  // D-06: the declared gross value comes from the backend valuation (value + tax).
  const watchedShipmentValue = useWatch({ control, name: "payment_details.shipment_value" });
  const watchedShipmentTaxValue = useWatch({ control, name: "payment_details.shipment_tax_value" });
  useShipmentValuation(watchedShipmentValue, watchedShipmentTaxValue, (valuation) => {
    setValue("payment_details.shipment_total_value", valuation.shipment_total_value);
  });

  const productCategoryValue = useWatch({
    control,
    name: "product_category",
  }) as ProductCategory | undefined;

  const qcRequiredValue = useWatch({
    control,
    name: "qc_required",
  }) as boolean | undefined;

  const watchedPackages = useWatch({
    control,
    name: "packages",
  }) as ReverseShipmentFormValues["packages"] | undefined;

  let configuredBoxCount = 0;
  for (const pkg of watchedPackages || []) {
    const countVal = Number(pkg?.box_count) || 0;
    configuredBoxCount = configuredBoxCount + countVal;
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
      {/* LEFT COLUMN: Return & QC + Category & Valuation */}
      <div className="lg:col-span-7 min-w-0 bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
        <div className="border-b border-slate-100 pb-3 flex items-center justify-between gap-2">
          <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2 min-w-0">
            <RotateCcw className="h-4 w-4 text-primary shrink-0" />
            <span className="truncate">Return & Doorstep Quality Check (QC)</span>
          </h3>
          <span className="text-[10px] font-bold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded uppercase tracking-wider shrink-0">
            DTO Reverse Pickup
          </span>
        </div>

        {/* Section A: Return & Doorstep Quality Check (QC) */}
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="min-w-0">
              <FormLabel className="text-xs font-semibold text-slate-700 block mb-2">
                Quick Return Reason Preset
              </FormLabel>
              <IconSelect
                aria-label="Quick return reason preset"
                options={RETURN_REASON_OPTIONS}
                onValueChange={(preset) => {
                  setValue("reason_for_return", preset, {
                    shouldValidate: true,
                  });
                }}
                placeholder="Choose a preset reason"
              />
              <p className="mt-1.5 text-[11px] text-slate-500">
                Fills the reason field; you can still edit it.
              </p>
            </div>

            <FormField
              control={control}
              name="reason_for_return"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Reason for Return
                    <RequiredMark />
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="Select preset or type custom reason"
                      className="h-9 text-xs bg-white"
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
          </div>

          {/* Doorstep QC Toggle Card */}
          <div className="bg-slate-50/70 border border-slate-200 rounded-xl p-4 space-y-4">
            <FormField
              control={control}
              name="qc_required"
              render={({ field }) => (
                <FormItem className="flex flex-row items-start justify-between gap-4 space-y-0">
                  <div className="space-y-1">
                    <FormLabel className="text-sm font-bold text-slate-900 flex items-center gap-1.5 cursor-pointer">
                      <ShieldCheck className="h-4 w-4 text-primary shrink-0" />
                      <span>Enable Doorstep Quality Check (QC)</span>
                    </FormLabel>
                    <FormDescription className="text-xs text-slate-500 leading-relaxed">
                      Pickup executive verifies item condition, brand tags, and
                      serial or IMEI before accepting the return
                    </FormDescription>
                  </div>
                  <FormControl>
                    <input
                      type="checkbox"
                      className="h-5 w-5 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-slate-900 mt-0.5 shrink-0"
                      checked={Boolean(field.value)}
                      onChange={(e) => field.onChange(e.target.checked)}
                    />
                  </FormControl>
                </FormItem>
              )}
            />

            {qcRequiredValue && (
              <FormField
                control={control}
                name="qc_notes"
                render={({ field }) => (
                  <FormItem className="pt-2 border-t border-slate-200/80 animate-in fade-in duration-150">
                    <FormLabel className="text-xs font-bold text-slate-800">
                      Doorstep QC Instructions for Field Executive
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g. Check IMEI on box, unbroken brand tag, no physical scratches"
                        className="h-9 text-xs bg-white"
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
            )}
          </div>
        </div>

        <hr className="border-slate-100" />

        {/* Section B: Product Category & Item Valuation */}
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <ClipboardList className="h-4 w-4 text-primary shrink-0" />
            <h4 className="text-xs font-bold text-slate-900 uppercase tracking-wider">
              Product Category & Item Valuation
            </h4>
          </div>

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
              name={
                "payment_details.freight_payment_mode" as const
              }
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Return Billing Mode
                  </FormLabel>
                  <FormControl>
                    <IconSelect
                      options={freightModeOptions}
                      value={field.value}
                      onValueChange={field.onChange}
                      placeholder="Choose billing mode"
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
                      Specify Custom Category
                    </FormLabel>
                    <FormControl>
                      <Input
                        placeholder="e.g. Custom Lifestyle Item"
                        className="h-9 text-xs bg-white"
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
            )}
          </div>

          {/* Item Valuation Fields */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-2">
            <FormField
              control={control}
              name="payment_details.shipment_value"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Declared Item Value
                  </FormLabel>
                  <InputAdornment prefix="₹">
                  <FormControl>
                    <Input
                      type="number"
                      min={0}
                      className="h-9 text-xs bg-white font-semibold"
                      name={field.name}
                      value={field.value ?? 0}
                      onBlur={field.onBlur}
                      ref={field.ref}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === "" ? 0 : Number(val));
                      }}
                    />
                  </FormControl>
                  </InputAdornment>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name={
                "payment_details.shipment_tax_value" as const
              }
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Item GST Value
                  </FormLabel>
                  <InputAdornment prefix="₹">
                  <FormControl>
                    <Input
                      type="number"
                      min={0}
                      className="h-9 text-xs bg-white"
                      name={field.name}
                      value={field.value ?? 0}
                      onBlur={field.onBlur}
                      ref={field.ref}
                      onChange={(e) => {
                        const val = e.target.value;
                        field.onChange(val === "" ? 0 : Number(val));
                      }}
                    />
                  </FormControl>
                  </InputAdornment>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name={
                "payment_details.shipment_total_value" as const
              }
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-bold text-slate-800">
                    Declared Gross Value
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
                      name={field.name}
                      value={field.value ?? 0}
                      onBlur={field.onBlur}
                      ref={field.ref}
                    />
                  </FormControl>
                  </InputAdornment>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          {/* Supporting Return Photos / Documents Uploader */}
          <div className="bg-slate-50/50 p-4 rounded-xl border border-slate-200/60 space-y-4 mt-2">
            <p className="text-xs text-slate-600 leading-relaxed">
              Upload customer return photos, unboxing images, or original invoice
              documents for doorstep QC verification.
            </p>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-1 min-w-0">
              <IconSelect
                aria-label="Document type"
                options={DOC_TYPE_SELECT_OPTIONS}
                onValueChange={(val) =>
                  document
                    .getElementById("reverse-sandbox-file-upload")
                    ?.setAttribute("data-type", val)
                }
                placeholder="Select document type"
                triggerClassName="w-full sm:w-[200px] sm:shrink-0"
              />

              <div className="flex-1 min-w-0 flex gap-2 items-center">
                <Input
                  id="reverse-sandbox-file-upload"
                  type="file"
                  disabled={isUploading}
                  className="w-full min-w-0 bg-white h-9 text-xs file:text-primary file:bg-primary/5 file:border-0 file:rounded-md file:px-3 file:py-1 cursor-pointer overflow-hidden"
                  onChange={(e) => {
                    const type = e.target.getAttribute(
                      "data-type"
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

          {docFields.length > 0 && (
            <div className="space-y-2 pt-2 animate-in fade-in duration-200">
              <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">
                Attached Return Documents ({docFields.length})
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
        </div>
      </div>

      {/* RIGHT COLUMN: Return Route Details (DTO — Customer to Warehouse) & Return Box Details */}
      <div className="lg:col-span-5 min-w-0 space-y-6">
        <div className="bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-3">
            <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2">
              <Truck className="h-4 w-4 text-primary shrink-0" />
              <span>Return Route Details (DTO)</span>
            </h3>
          </div>

          <div className="space-y-6">
            <div>
              <h4 className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 border-l-2 border-primary pl-2 flex items-center gap-1.5">
                <ArrowUpRight className="h-3.5 w-3.5 text-primary shrink-0" />
                <span>Pickup From (Customer Return Address)</span>
              </h4>
              <AddressFieldset
                control={control as unknown as Control<HasAddresses>}
                type="pickup"
                title="Pickup From (Customer Return Address)"
                savedAddresses={savedAddresses}
                minimal={true}
              />
            </div>

            <hr className="border-slate-100" />

            <div>
              <h4 className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 border-l-2 border-primary pl-2 flex items-center gap-1.5">
                <ArrowDownLeft className="h-3.5 w-3.5 text-primary shrink-0" />
                <span>Return To (Merchant Warehouse / Origin)</span>
              </h4>
              <AddressFieldset
                control={control as unknown as Control<HasAddresses>}
                type="delivery"
                title="Return To (Merchant Warehouse / Origin)"
                savedAddresses={savedAddresses}
                minimal={true}
              />
            </div>
          </div>
        </div>

        {/* Return Box Details Card */}
        <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-xs space-y-5 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-2">
            <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
              <Boxes className="h-4 w-4 text-primary shrink-0" />
              <span>Return Box Details</span>
            </h3>
          </div>

          <PackageFieldset
            control={control as unknown as Control<HasPackages>}
            isReverse={true}
          />

          {configuredBoxCount > 0 && (
            <div className="bg-slate-50 border border-slate-200/80 rounded-lg p-3.5 flex items-center justify-between text-xs text-slate-700 font-medium animate-in fade-in duration-200 shadow-3xs">
              <span className="flex items-center gap-1.5">
                <span>📦</span>
                <span>
                  Return Summary: <strong>{configuredBoxCount}</strong>{" "}
                  {configuredBoxCount === 1 ? "box" : "boxes"} configured
                </span>
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
