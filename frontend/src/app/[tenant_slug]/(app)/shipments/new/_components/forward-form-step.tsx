// src/app/[tenant_slug]/(app)/shipments/new/_components/forward-form-step.tsx
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import {
  Control,
  useWatch,
  useFormContext,
  FieldArrayWithId,
} from "react-hook-form";
import { ForwardShipmentFormValues } from "@/lib/validations/shipment";
import { useTenant } from "@/components/providers/tenant-provider";
import { Info, FileText, Trash2, ClipboardList, Truck, ArrowUpRight, ArrowDownLeft, Boxes, Banknote } from "lucide-react";
import { toast } from "sonner";

export const CATEGORY_LABELS: Record<ProductCategory, string> = {
  [ProductCategory.HOUSEHOLD_PERSONAL]: "Household / Personal",
  [ProductCategory.VEHICLE]: "Vehicle (Automotive)",
  [ProductCategory.DOCUMENTS]: "Documents / Letters",
  [ProductCategory.HAZARDOUS]: "Hazardous Material (HAZMAT)",
  [ProductCategory.COMMERCIAL]: "Commercial Goods / B2B",
  [ProductCategory.ELECTRONICS]: "Electronics & Gadgets",
  [ProductCategory.APPAREL]: "Apparel & Clothing",
  [ProductCategory.OTHER]: "Other (Custom Category)",
};

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
  const { tenant } = useTenant();
  const { setValue, getValues } = useFormContext<ForwardShipmentFormValues>();

  // Watch form fields for dynamic triggers & aggregates
  const watchedTotalValue = useWatch({
    control,
    name: "payment_details.shipment_total_value",
  }) as number | undefined;

  const productCategoryValue = useWatch({
    control,
    name: "product_category",
  }) as ProductCategory | undefined;

  const watchedFreightMode = useWatch({
    control,
    name: "payment_details.freight_payment_mode",
  }) as FreightPaymentMode | undefined;

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

  const showEWayBill = (watchedTotalValue || 0) > 50000;

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
      {/* LEFT COLUMN: Single Unified Shipment Details Card (Transactional Specs) */}
      <div className="lg:col-span-7 bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
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
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Product Category *
                  </FormLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger className="h-9 text-xs bg-white">
                        <SelectValue placeholder="Select Category" />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {Object.values(ProductCategory).map((cat) => (
                        <SelectItem key={cat} value={cat} className="text-xs">
                          {CATEGORY_LABELS[cat]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
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
                      className="h-9 text-xs bg-white"
                      {...field}
                      value={field.value || ""}
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
                      Specify Category *
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
            <div className="sm:col-span-3">
              <FormField
                control={control}
                name="payment_details.shipment_value"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Shipment Value (₹)
                    </FormLabel>
                    <FormControl>
                      <Input
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

            <div className="sm:col-span-3">
              <FormField
                control={control}
                name="payment_details.shipment_tax_value"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-semibold text-slate-700">
                      Tax Value (₹)
                    </FormLabel>
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

            <div className="sm:col-span-3">
              <FormField
                control={control}
                name="payment_details.shipment_total_value"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-bold text-slate-800">
                      Total Value (₹)
                    </FormLabel>
                    <FormControl>
                      <Input
                        type="number"
                        className="h-9 text-xs bg-slate-50 font-bold text-slate-900 border-slate-300"
                        {...field}
                        onChange={(e) => {
                          const val = e.target.value;
                          field.onChange(val === "" ? "" : Number(val));
                        }}
                      />
                    </FormControl>
                    <FormDescription className="text-[9px] text-slate-500 font-medium leading-snug mt-1">
                      Sum (auto-calculated).
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
                  <Select onValueChange={field.onChange} value={field.value}>
                    <FormControl>
                      <SelectTrigger className="h-9 text-xs bg-white">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem
                        value={FreightPaymentMode.PREPAID}
                        className="text-xs"
                      >
                        Prepaid (Sender pays)
                      </SelectItem>
                      <SelectItem
                        value={FreightPaymentMode.POSTPAID}
                        className="text-xs"
                      >
                        Postpaid (Sender account)
                      </SelectItem>
                      <SelectItem
                        value={FreightPaymentMode.TO_PAY}
                        className="text-xs"
                      >
                        To Pay (Receiver pays)
                      </SelectItem>
                    </SelectContent>
                  </Select>
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
                    <input
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
                      Collectible amount for sender (₹)
                    </FormLabel>
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
                    <FormDescription className="text-[9px] text-slate-400 leading-snug mt-1">
                      Defaulted to Shipment Total Value.
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <div
                onClick={() => {
                  if (watchedFreightMode !== FreightPaymentMode.TO_PAY) {
                    setAddShippingToCod(!addShippingToCod);
                  }
                }}
                className={`flex items-start p-3.5 rounded-xl border transition-all duration-150 justify-center flex-col select-none h-[78px] ${
                  watchedFreightMode === FreightPaymentMode.TO_PAY
                    ? "bg-slate-100 opacity-60 cursor-not-allowed border-slate-200"
                    : addShippingToCod
                    ? "bg-primary/5 border-primary/30 shadow-3xs"
                    : "bg-white border-slate-200 hover:border-slate-300 cursor-pointer"
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <input
                    id="addShippingToCodCheck"
                    type="checkbox"
                    className="h-4.5 w-4.5 rounded border-slate-300 text-primary focus:ring-primary cursor-pointer accent-primary shrink-0"
                    checked={
                      watchedFreightMode === FreightPaymentMode.TO_PAY
                        ? true
                        : addShippingToCod
                    }
                    disabled={watchedFreightMode === FreightPaymentMode.TO_PAY}
                    onChange={(e) => {
                      e.stopPropagation();
                      setAddShippingToCod(e.target.checked);
                    }}
                  />
                  <label
                    htmlFor="addShippingToCodCheck"
                    className={`text-xs font-extrabold select-none leading-tight cursor-pointer ${
                      watchedFreightMode === FreightPaymentMode.TO_PAY
                        ? "text-slate-500 cursor-not-allowed"
                        : "text-slate-900"
                    }`}
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

          {/* Info Banner for To Pay without COD */}
          {!watchedIsCod &&
            watchedFreightMode === FreightPaymentMode.TO_PAY && (
              <div className="bg-slate-50 border border-slate-200/60 p-3 rounded-lg flex items-start gap-2 text-slate-750 animate-in fade-in duration-200">
                <Info className="h-4 w-4 text-primary shrink-0 mt-0.5" />
                <p className="text-[10px] leading-relaxed">
                  <strong>Receiver Pays Shipping (To Pay Mode):</strong> The
                  receiver pays dynamic shipping costs at doorstep.
                </p>
              </div>
            )}
        </div>

        <hr className="border-slate-100" />

        {/* Section C: Invoicing & Compliance */}
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
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
                    <Input
                      type="date"
                      className="h-9 text-xs bg-white"
                      {...field}
                      value={field.value || ""}
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
                  <FormItem className="bg-slate-50 border border-slate-200/60 p-4 rounded-lg">
                    <FormLabel className="text-xs font-bold text-slate-900">
                      E-Way Bill Number <span className="text-red-500">*</span>
                    </FormLabel>
                    <FormControl>
                      <Input
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

          {/* Integrated Documents & Photos Uploader (Merged to left column under Compliance) */}
          <div className="bg-slate-50/50 p-4 rounded-xl border border-slate-200/60 space-y-4 mt-2">
            <p className="text-xs text-slate-600 leading-relaxed">
              Upload copies of invoices, E-Way bills, or{" "}
              <strong className="text-slate-800">photos of the packages</strong>{" "}
              to log their condition before dispatch.
            </p>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 pt-1">
              <Select
                onValueChange={(val) =>
                  document
                    .getElementById("sandbox-file-upload")
                    ?.setAttribute("data-type", val)
                }
              >
                <SelectTrigger className="w-full sm:w-[180px] bg-white h-9 text-xs">
                  <SelectValue placeholder="Select doc type" />
                </SelectTrigger>
                <SelectContent>
                  {Object.values(DocumentType).map((t) => (
                    <SelectItem key={t} value={t} className="text-xs">
                      {t.replace(/_/g, " ")}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <div className="flex-1 flex gap-2 items-center">
                <Input
                  id="sandbox-file-upload"
                  type="file"
                  disabled={isUploading}
                  className="bg-white h-9 text-xs file:text-primary file:bg-primary/5 file:border-0 file:rounded-md file:px-3 file:py-1 cursor-pointer"
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
                  className="flex items-center justify-between p-2.5 bg-slate-50/50 border border-slate-200 rounded-lg text-xs"
                >
                  <div className="flex items-center gap-2 overflow-hidden mr-4">
                    <FileText className="h-4 w-4 text-slate-400 shrink-0" />
                    <div className="min-w-0">
                      <p className="font-bold text-slate-800 truncate">
                        {doc.document_type.replace(/_/g, " ")}
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

      {/* RIGHT COLUMN: Logistics details (Unified Addresses Card, Cargo configurations & summary) */}
      <div className="lg:col-span-5 space-y-6">
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
