// frontend/src/app/[tenant_slug]/(app)/b2b/shipments/new/reverse/_components/b2b-reverse-form-step.tsx
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
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
  FormDescription,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { DatePicker } from "@/components/ui/date-picker";
import { format, parseISO } from "date-fns";
import { IconSelect } from "@/components/ui/icon-select";
import { RequiredMark } from "@/components/ui/form-extras";
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
import { toIstDateTimeLocalValue, toIstIsoString } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Control,
  useWatch,
  useFormContext,
  FieldArrayWithId,
} from "react-hook-form";
import { B2BReverseShipmentFormValues } from "@/lib/validations/shipment";
import { FileText, Loader2, Trash2, ClipboardList, Truck, ArrowUpRight, ArrowDownLeft, Boxes, Calendar } from "lucide-react";
import { toast } from "sonner";
import { useRef, useEffect } from "react";

/** Legacy label lookup (toasts and existing importers). */
export const CATEGORY_LABELS: Record<ProductCategory, string> = optionLabels(PRODUCT_CATEGORY_OPTIONS);

const CATEGORY_SELECT_OPTIONS = toOptions(PRODUCT_CATEGORY_OPTIONS);
const STRATEGY_SELECT_OPTIONS = toOptions(PICKUP_STRATEGY_OPTIONS);
const DOC_TYPE_SELECT_OPTIONS = toOptions(DOCUMENT_TYPE_OPTIONS);

// Volumetric Safety Net Dimensions Defaults
export const CATEGORY_DEFAULT_DIMENSIONS: Record<
  string,
  { length: number; breadth: number; height: number }
> = {
  [ProductCategory.ELECTRONICS]: { length: 30, breadth: 25, height: 15 },
  [ProductCategory.DOCUMENTS]: { length: 25, breadth: 15, height: 1 },
  [ProductCategory.APPAREL]: { length: 30, breadth: 25, height: 5 },
};

interface B2BReverseFormStepProps {
  control: Control<B2BReverseShipmentFormValues>;
  savedAddresses: AddressRead[];
  docFields: FieldArrayWithId<B2BReverseShipmentFormValues, "documents">[];
  removeDoc: (index: number) => void;
  isUploading: boolean;
  handleFileUpload: (
    e: React.ChangeEvent<HTMLInputElement>,
    docType: DocumentType,
  ) => Promise<void>;
}

export function B2BReverseFormStep({
  control,
  savedAddresses,
  docFields,
  removeDoc,
  isUploading,
  handleFileUpload,
}: B2BReverseFormStepProps) {
  // Merchants can't self-select POSTPAID (needs an approved credit account, decision D14).
  const { isAdmin } = useUser();
  const freightModeOptions = toOptions(FREIGHT_PAYMENT_MODE_OPTIONS, freightPaymentModesFor(isAdmin));

  const { setValue, getValues } = useFormContext<B2BReverseShipmentFormValues>();
  const prevCategoryRef = useRef<ProductCategory | undefined>(undefined);

  // Watch form fields for UI reactivity
  const productCategoryValue = useWatch({
    control,
    name: "product_category",
  }) as ProductCategory | undefined;

  useEffect(() => {
    if (productCategoryValue && prevCategoryRef.current === undefined) {
      prevCategoryRef.current = productCategoryValue;
    }
  }, [productCategoryValue]);

  const watchedPackages = useWatch({
    control,
    name: "packages",
  }) as B2BReverseShipmentFormValues["packages"] | undefined;

  // Reactive calculation of cargo totals
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

  // Volumetric Safety Net: Reactive pre-population on category change
  const handleCategoryChange = (newCategory: ProductCategory) => {
    const prevCategory = prevCategoryRef.current;
    const defaults = CATEGORY_DEFAULT_DIMENSIONS[newCategory];

    if (defaults) {
      const currentPackages = getValues("packages") || [];

      currentPackages.forEach((pkg, index) => {
        // A field is considered unedited if it is 0 or matches the old category's default
        const isLengthUnedited =
          pkg.length === 0 ||
          (prevCategory &&
            pkg.length === CATEGORY_DEFAULT_DIMENSIONS[prevCategory]?.length);

        const isBreadthUnedited =
          pkg.breadth === 0 ||
          (prevCategory &&
            pkg.breadth === CATEGORY_DEFAULT_DIMENSIONS[prevCategory]?.breadth);

        const isHeightUnedited =
          pkg.height === 0 ||
          (prevCategory &&
            pkg.height === CATEGORY_DEFAULT_DIMENSIONS[prevCategory]?.height);

        // Update ONLY if the field has not been customized by the user
        let updatedAny = false;
        if (isLengthUnedited) {
          setValue(`packages.${index}.length`, defaults.length, {
            shouldValidate: true,
          });
          updatedAny = true;
        }
        if (isBreadthUnedited) {
          setValue(`packages.${index}.breadth`, defaults.breadth, {
            shouldValidate: true,
          });
          updatedAny = true;
        }
        if (isHeightUnedited) {
          setValue(`packages.${index}.height`, defaults.height, {
            shouldValidate: true,
          });
          updatedAny = true;
        }

        if (updatedAny) {
          toast.info(
            `Pre-populated default dimensions for ${CATEGORY_LABELS[newCategory]}: ${defaults.length}x${defaults.breadth}x${defaults.height} cm.`
          );
        }
      });
    }

    prevCategoryRef.current = newCategory;
    setValue("product_category", newCategory, { shouldValidate: true });
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
      {/* LEFT COLUMN: B2B Cargo Specifications Card */}
      <div className="lg:col-span-7 min-w-0 bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
        <div className="border-b border-slate-100 pb-3 flex justify-between items-center gap-2">
          <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2 min-w-0">
            <ClipboardList className="h-4 w-4 text-primary shrink-0" /> <span className="truncate">B2B Reverse Cargo Specs</span>
          </h3>
          <span className="text-[10px] font-black text-slate-500 bg-slate-100 px-2 py-0.5 rounded border border-slate-200 shrink-0">
            Reverse Logistics Mode
          </span>
        </div>

        <div className="space-y-4">
          {/* Reason for Return (Mandatory) */}
          <FormField
            control={control}
            name="reason_for_return"
            render={({ field }) => (
              <FormItem className="animate-in fade-in duration-150">
                <FormLabel className="text-xs font-bold text-slate-700">
                  Reason for Return
                  <RequiredMark />
                </FormLabel>
                <FormControl>
                  <Textarea
                    placeholder="Specify the reason for returning these items (minimum 3 characters)..."
                    className="bg-white text-xs min-h-[80px]"
                    {...field}
                  />
                </FormControl>
                <FormDescription className="text-[9px] text-slate-400 leading-snug">
                  Mandatory for all reverse shipments.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Product Category Dropdown */}
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
                      onValueChange={handleCategoryChange}
                      placeholder="Select category"
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            {/* Billing Mode / Payment Mode */}
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
                      options={freightModeOptions}
                      value={field.value}
                      onValueChange={field.onChange}
                      placeholder="Choose billing mode"
                    />
                  </FormControl>
                </FormItem>
              )}
            />
          </div>

          {/* Custom Category Description */}
          {productCategoryValue === ProductCategory.OTHER && (
            <FormField
              control={control}
              name="other_category_description"
              render={({ field }) => (
                <FormItem className="animate-in fade-in duration-150">
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Specify Custom Category
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

          {/* Purchase Order Details */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-2">
            <FormField
              control={control}
              name="po_number"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    Purchase Order (PO) Number (Optional)
                  </FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. PO-98721"
                      className="h-9 text-xs bg-white"
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
              name="po_date"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-xs font-semibold text-slate-700">
                    PO Date (Optional)
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

        {/* Optional Document Uploads */}
        <div className="space-y-4">
          <FormLabel className="text-xs font-bold text-slate-900 block">
            Attached Documents (Optional)
          </FormLabel>
          <div className="bg-slate-50/50 p-4 rounded-xl border border-slate-200/60 space-y-4">
            <p className="text-[11px] text-slate-500 leading-relaxed">
              Upload copies of return authorization forms, parcel condition photos, or other transit records.
            </p>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3 min-w-0">
              <IconSelect
                aria-label="Document type"
                options={DOC_TYPE_SELECT_OPTIONS}
                onValueChange={(val) =>
                  document
                    .getElementById("b2b-reverse-file-upload")
                    ?.setAttribute("data-type", val)
                }
                placeholder="Select document type"
                triggerClassName="w-full sm:w-[200px] sm:shrink-0"
              />

              <div className="flex-1 min-w-0 flex gap-2 items-center">
                <Input
                  id="b2b-reverse-file-upload"
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
                {isUploading && (
                  <span
                    className="inline-flex shrink-0 items-center gap-1 text-xs text-muted-foreground"
                    role="status"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />
                    Uploading…
                  </span>
                )}
              </div>
            </div>
          </div>

          {/* Attached documents list */}
          {docFields.length > 0 && (
            <div className="space-y-2 pt-1 animate-in fade-in duration-200">
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

      {/* RIGHT COLUMN: Route & Box Configuration */}
      <div className="lg:col-span-5 min-w-0 space-y-6">
        {/* Symmetrical Route Addresses Card */}
        <div className="bg-white border border-slate-200 p-6 rounded-xl shadow-sm space-y-6 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-3">
            <h3 className="text-base font-bold text-slate-950 uppercase tracking-wider flex items-center gap-2">
              <Truck className="h-4 w-4 text-primary shrink-0" /> Route Address Details
            </h3>
          </div>

          <div className="space-y-6">
            <div>
              <h4 className="text-[11px] font-bold text-slate-900 uppercase tracking-wider mb-2 border-l-2 border-primary pl-2 flex items-center gap-1.5">
                <ArrowUpRight className="h-3.5 w-3.5 text-primary shrink-0" /> B2B Return Origin (Customer Pickup)
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
                <ArrowDownLeft className="h-3.5 w-3.5 text-primary shrink-0" /> B2B Return Destination (Merchant Warehouse)
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

        {/* Appointment Scheduler & Strategy Card */}
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

        {/* Box Configuration (Mandatory package dimensions & weight) */}
        <div className="bg-white border border-slate-200 p-5 rounded-xl shadow-sm space-y-5 animate-in fade-in duration-200">
          <div className="border-b border-slate-100 pb-2 flex items-center justify-between">
            <h3 className="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center gap-2">
              <Boxes className="h-4 w-4 text-primary shrink-0" /> Package Configuration
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
        </div>
      </div>
    </div>
  );
}
