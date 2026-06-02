// src/components/forms/address-fieldset.tsx
"use client";

import { AddressRead } from "@/api_client";
import { Button } from "@/components/ui/button";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { User, Building2, Pencil, Trash2, MapPin, MapPinPlus } from "lucide-react";
import { useMemo } from "react";
import { Control, Path, PathValue, useFormContext, useWatch, FieldValues } from "react-hook-form";
import { useUser } from "@/components/auth/auth-guard";
import { AddAddressDialog, AddressFormValues } from "@/components/forms/add-address-dialog";

export interface AddressFormValue {
  name?: string;
  company_name?: string;
  phone?: string;
  alternate_phone?: string;
  email?: string;
  gstin?: string;
  address_line1?: string;
  address_line2?: string;
  landmark?: string;
  city?: string;
  state?: string;
  pincode?: string;
  category?: string;
  scope?: string;
  save_to_address_book?: boolean;
  is_shared_with_team?: boolean;
}

export interface HasAddresses extends FieldValues {
  pickup_address_id?: string;
  delivery_address_id?: string;
  new_pickup_address?: AddressFormValue;
  new_delivery_address?: AddressFormValue;
}

interface AddressFieldsetProps<TFieldValues extends HasAddresses> {
  control: Control<TFieldValues>;
  type: "pickup" | "delivery";
  title: string;
  savedAddresses: AddressRead[];
  minimal?: boolean;
}

export function AddressFieldset<TFieldValues extends HasAddresses>({
  control,
  type,
  title,
  savedAddresses = [],
  minimal = false,
}: AddressFieldsetProps<TFieldValues>) {
  const { isAdmin } = useUser();
  const { setValue } = useFormContext<TFieldValues>();

  const idField = (
    type === "pickup" ? "pickup_address_id" : "delivery_address_id"
  ) as Path<TFieldValues>;
  const objectField = (
    type === "pickup" ? "new_pickup_address" : "new_delivery_address"
  ) as Path<TFieldValues>;

  // Watch active selections
  const selectedAddressId = useWatch<TFieldValues>({
    name: idField,
  }) as unknown as string | undefined;

  const transientAddress = useWatch<TFieldValues>({
    name: objectField,
  }) as unknown as AddressFormValue | undefined;

  const saveToAddressBook = useWatch<TFieldValues>({
    name: `${objectField}.save_to_address_book` as unknown as Path<TFieldValues>,
    defaultValue: true as unknown as never,
  }) as unknown as boolean;

  // Determine if we have a saved address active
  const activeSavedAddress = useMemo(() => {
    if (!selectedAddressId) return null;
    return savedAddresses.find((addr) => addr.id === selectedAddressId) || null;
  }, [selectedAddressId, savedAddresses]);

  // Determine if we have a custom transient address active
  const activeTransientAddress = useMemo(() => {
    if (selectedAddressId || !transientAddress || !transientAddress.name) return null;
    return transientAddress;
  }, [selectedAddressId, transientAddress]);

  const handleSaveTransient = (data: Omit<AddressFormValue, "save_to_address_book" | "is_shared_with_team">) => {
    // Clear selected saved ID to prioritize transient payload
    setValue(idField, "" as unknown as PathValue<TFieldValues, Path<TFieldValues>>, { shouldValidate: true });
    
    // Spreading defaults strictly and type-casting to PathValue to avoid any union warnings or 'any' usage
    const payload = {
      ...data,
      save_to_address_book: true,
      is_shared_with_team: false,
    } as unknown as PathValue<TFieldValues, Path<TFieldValues>>;

    // Write full transient data into form state
    setValue(objectField, payload, { shouldValidate: true });
  };

  const handleClear = () => {
    setValue(idField, "" as unknown as PathValue<TFieldValues, Path<TFieldValues>>, { shouldValidate: true });
    setValue(objectField, undefined as unknown as PathValue<TFieldValues, Path<TFieldValues>>, { shouldValidate: true });
  };

  return (
    <div className={minimal ? "space-y-4" : "space-y-6 bg-slate-50/50 p-6 rounded-xl border border-slate-100"}>
      {!minimal && (
        <div className="border-b border-slate-200 pb-4">
          <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        </div>
      )}

      {/* STATE 1 & 2: ADDRESS SUMMARY CARD */}
      {(activeSavedAddress || activeTransientAddress) ? (
        <div className="animate-in fade-in duration-200">
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-3 relative hover:border-slate-300 transition-colors pr-16">
            {/* Absolute actions in the top-right */}
            <div className="absolute top-4 right-4 flex items-center gap-1.5 z-10">
              {activeTransientAddress && (
                <AddAddressDialog
                  onSaveTransient={handleSaveTransient}
                  defaultValues={activeTransientAddress as unknown as Partial<AddressFormValues>}
                  trigger={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-md shrink-0 cursor-pointer flex items-center justify-center"
                      title="Edit custom address"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  }
                />
              )}
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={handleClear}
                className="h-7 w-7 text-red-500 hover:text-red-700 hover:bg-red-50/80 rounded-md shrink-0 cursor-pointer flex items-center justify-center"
                title="Remove address selection"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>

            {/* Content Info */}
            <div className="space-y-1.5 text-sm">
              <div className="font-semibold text-slate-950 flex items-center gap-1.5">
                <User className="h-4 w-4 text-slate-400 shrink-0" />
                <span>{activeSavedAddress?.name || activeTransientAddress?.name}</span>
                <span className="font-mono text-slate-500 font-normal text-xs ml-1">
                  ({activeSavedAddress?.phone || activeTransientAddress?.phone})
                </span>
              </div>

              {(activeSavedAddress?.company_name || activeTransientAddress?.company_name || activeSavedAddress?.gstin || activeTransientAddress?.gstin) && (
                <div className="text-xs text-slate-500 flex items-center gap-1.5 pl-5.5">
                  <Building2 className="h-3.5 w-3.5 text-slate-400 shrink-0" />
                  <span>{activeSavedAddress?.company_name || activeTransientAddress?.company_name}</span>
                  {(activeSavedAddress?.gstin || activeTransientAddress?.gstin) && (
                    <span className="font-mono bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded text-[10px] uppercase border border-slate-200">
                      GST: {activeSavedAddress?.gstin || activeTransientAddress?.gstin}
                    </span>
                  )}
                </div>
              )}

              <div className="text-slate-600 pl-5.5 leading-relaxed text-xs md:text-sm">
                {activeSavedAddress?.address_line1 || activeTransientAddress?.address_line1}
                {(activeSavedAddress?.address_line2 || activeTransientAddress?.address_line2) && `, ${activeSavedAddress?.address_line2 || activeTransientAddress?.address_line2}`}
                {(activeSavedAddress?.landmark || activeTransientAddress?.landmark) && ` (Landmark: ${activeSavedAddress?.landmark || activeTransientAddress?.landmark})`}
              </div>

              <div className="font-semibold text-slate-900 pl-5.5 flex items-center gap-1.5 text-xs md:text-sm">
                <MapPin className="h-3.5 w-3.5 text-primary shrink-0" />
                <span>
                  {activeSavedAddress?.city || activeTransientAddress?.city}, {activeSavedAddress?.state || activeTransientAddress?.state} - {activeSavedAddress?.pincode || activeTransientAddress?.pincode}
                </span>
                <span className="text-[10px] font-bold text-emerald-600 flex items-center gap-0.5">
                  ✓ Verified
                </span>
              </div>
            </div>
          </div>

          {/* Address Book Save & Shared Scoping Checkboxes (Only for Transient Address) */}
          {activeTransientAddress && (
            <div className="border-t border-slate-200/60 pt-4 mt-4 space-y-3 animate-in fade-in duration-150">
              <FormField
                control={control}
                name={`${objectField}.save_to_address_book` as Path<TFieldValues>}
                render={({ field }) => (
                  <FormItem className="flex flex-row items-center space-x-2.5 space-y-0">
                    <FormControl>
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900 cursor-pointer accent-slate-900 shrink-0"
                        checked={!!field.value}
                        onChange={(e) => {
                          field.onChange(e.target.checked);
                          if (!e.target.checked) {
                            setValue(`${objectField}.is_shared_with_team` as Path<TFieldValues>, false as unknown as PathValue<TFieldValues, Path<TFieldValues>>);
                          }
                        }}
                      />
                    </FormControl>
                    <FormLabel className="text-xs font-bold text-slate-800 cursor-pointer select-none leading-none">
                      Save this address for future use
                    </FormLabel>
                  </FormItem>
                )}
              />

              {saveToAddressBook && isAdmin && (
                <FormField
                  control={control}
                  name={`${objectField}.is_shared_with_team` as Path<TFieldValues>}
                  render={({ field }) => (
                    <FormItem className="flex flex-row items-center space-x-2.5 space-y-0 animate-in fade-in slide-in-from-top-1 duration-150">
                      <FormControl>
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900 cursor-pointer accent-slate-900 shrink-0"
                          checked={!!field.value}
                          onChange={field.onChange}
                        />
                      </FormControl>
                      <FormLabel className="text-xs font-bold text-slate-800 cursor-pointer select-none leading-none">
                        Share this address with my B2B team
                      </FormLabel>
                    </FormItem>
                  )}
                />
              )}
            </div>
          )}
        </div>
      ) : (
        /* STATE 3: EMPTY SELECTOR SLATE */
        <div className="space-y-2 animate-in fade-in duration-200">
          <span className="text-xs font-bold text-slate-700 pl-0.5">Select Address</span>
          <div className="flex flex-col gap-3 pt-1 pb-0.5">
            <FormField
              control={control}
              name={idField}
              render={({ field }) => (
                <FormItem className="space-y-0 w-full">
                  <Select
                    onValueChange={field.onChange}
                    value={(field.value as string) || undefined}
                  >
                    <FormControl>
                      <SelectTrigger className="bg-white border-slate-200 shadow-3xs h-10 text-xs w-full">
                        <SelectValue placeholder="Choose from Saved Address Book..." />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      {savedAddresses.length === 0 && (
                        <div className="p-3 text-xs text-slate-500 italic text-center">
                          No saved addresses.
                        </div>
                      )}
                      {savedAddresses.map((addr) => (
                        <SelectItem key={addr.id} value={addr.id} className="text-xs">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-slate-900">{addr.name}</span>
                            <span className="text-slate-400 text-[10px]">
                              ({addr.category} - {addr.city}, {addr.state} - {addr.pincode})
                            </span>
                          </div>
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <FormMessage />
                </FormItem>
              )}
            />

            <div className="relative flex py-1 items-center w-full">
              <div className="grow border-t border-slate-200/80"></div>
              <span className="shrink mx-3 text-[9px] font-bold uppercase tracking-widest text-slate-400/80">OR</span>
              <div className="grow border-t border-slate-200/80"></div>
            </div>

            <AddAddressDialog
              onSaveTransient={handleSaveTransient}
              trigger={
                <Button
                  type="button"
                  variant="outline"
                  className="bg-white border-slate-200 hover:bg-slate-50 text-slate-900 cursor-pointer font-bold h-10 w-full flex items-center justify-center gap-2 rounded-lg shadow-3xs hover:border-slate-300 transition-all text-xs shrink-0"
                >
                  <MapPinPlus className="h-4 w-4 text-primary" /> Add New Address
                </Button>
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}
