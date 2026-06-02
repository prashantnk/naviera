// src/components/forms/address-fieldset.tsx
"use client";

import { AddressCategory, AddressRead } from "@/api_client";
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
}

export function AddressFieldset<TFieldValues extends HasAddresses>({
  control,
  type,
  title,
  savedAddresses = [],
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
    <div className="space-y-6 bg-slate-50/50 p-6 rounded-xl border border-slate-100">
      <div className="border-b border-slate-200 pb-4">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
      </div>

      {/* STATE 1 & 2: ADDRESS SUMMARY CARD */}
      {(activeSavedAddress || activeTransientAddress) ? (
        <div className="animate-in fade-in duration-200">
          <div className="bg-white border border-slate-200 rounded-xl p-5 shadow-sm space-y-3 relative hover:border-slate-300 transition-colors">
            {/* Header badges & quick actions */}
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 border border-indigo-100">
                  {activeSavedAddress?.category || activeTransientAddress?.category || AddressCategory.HOME}
                </span>
                {activeSavedAddress && (
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-slate-100 text-slate-700 border border-slate-200">
                    Saved Address
                  </span>
                )}
                {activeSavedAddress?.scope === "TENANT" && (
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-600 border border-emerald-100">
                    Team Shared
                  </span>
                )}
                {activeTransientAddress && (
                  <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-md bg-amber-50 text-amber-700 border border-amber-100">
                    New Address
                  </span>
                )}
              </div>

              {/* Actions */}
              <div className="flex items-center gap-1.5">
                {activeTransientAddress && (
                  <AddAddressDialog
                    onSaveTransient={handleSaveTransient}
                    defaultValues={activeTransientAddress as unknown as Partial<AddressFormValues>}
                    trigger={
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-8 text-xs font-semibold cursor-pointer text-slate-700 hover:bg-slate-100"
                      >
                        <Pencil className="h-3.5 w-3.5 mr-1.5" /> Edit
                      </Button>
                    }
                  />
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={handleClear}
                  className="h-8 text-xs font-semibold cursor-pointer text-red-600 hover:bg-red-50 hover:text-red-700"
                >
                  <Trash2 className="h-3.5 w-3.5 mr-1.5" /> Clear
                </Button>
              </div>
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
                <MapPin className="h-3.5 w-3.5 text-indigo-600 shrink-0" />
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
                  <FormItem className="flex flex-row items-start space-x-3 space-y-0">
                    <FormControl>
                      <input
                        type="checkbox"
                        className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900 cursor-pointer accent-slate-900 mt-0.5"
                        checked={!!field.value}
                        onChange={(e) => {
                          field.onChange(e.target.checked);
                          if (!e.target.checked) {
                            setValue(`${objectField}.is_shared_with_team` as Path<TFieldValues>, false as unknown as PathValue<TFieldValues, Path<TFieldValues>>);
                          }
                        }}
                      />
                    </FormControl>
                    <div className="space-y-1 leading-none">
                      <FormLabel className="text-sm font-medium text-slate-950 cursor-pointer select-none">
                        Save this address for future use
                      </FormLabel>
                      <p className="text-xs text-slate-500">
                        Add this entry to your address book so you can select it next time.
                      </p>
                    </div>
                  </FormItem>
                )}
              />

              {saveToAddressBook && isAdmin && (
                <FormField
                  control={control}
                  name={`${objectField}.is_shared_with_team` as Path<TFieldValues>}
                  render={({ field }) => (
                    <FormItem className="flex flex-row items-start space-x-3 space-y-0 animate-in fade-in slide-in-from-top-1 duration-150">
                      <FormControl>
                        <input
                          type="checkbox"
                          className="h-4 w-4 rounded border-slate-300 text-slate-900 focus:ring-slate-900 cursor-pointer accent-slate-900 mt-0.5"
                          checked={!!field.value}
                          onChange={field.onChange}
                        />
                      </FormControl>
                      <div className="space-y-1 leading-none">
                        <FormLabel className="text-sm font-medium text-slate-950 cursor-pointer select-none">
                          Share this address with my B2B team
                        </FormLabel>
                        <p className="text-xs text-slate-500">
                          Make this address visible to all colleagues in your B2B portal.
                        </p>
                      </div>
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
          <span className="text-sm font-semibold text-slate-700 pl-0.5">Select Address</span>
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
            <div className="flex-1">
              <FormField
                control={control}
                name={idField}
                render={({ field }) => (
                  <FormItem className="space-y-0">
                    <Select
                      onValueChange={field.onChange}
                      value={(field.value as string) || undefined}
                    >
                      <FormControl>
                        <SelectTrigger className="bg-white border-slate-200 shadow-sm h-11 text-sm">
                          <SelectValue placeholder="Choose from Saved Address Book..." />
                        </SelectTrigger>
                      </FormControl>
                      <SelectContent>
                        {savedAddresses.length === 0 && (
                          <div className="p-3 text-sm text-slate-500 italic text-center">
                            No saved addresses.
                          </div>
                        )}
                        {savedAddresses.map((addr) => (
                          <SelectItem key={addr.id} value={addr.id}>
                            <div className="flex items-center gap-2">
                              <span className="font-medium text-slate-900">{addr.name}</span>
                              <span className="text-slate-400 text-xs">
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
            </div>

            <span className="text-[10px] text-slate-400 uppercase font-bold tracking-widest shrink-0 self-center sm:self-auto py-1 sm:py-0">OR</span>

            <AddAddressDialog
              onSaveTransient={handleSaveTransient}
              trigger={
                <Button
                  type="button"
                  variant="outline"
                  className="bg-white border-slate-200 hover:bg-slate-50 text-slate-900 cursor-pointer font-bold h-11 px-4 flex items-center justify-center gap-2 rounded-lg shadow-sm hover:border-slate-300 transition-all shrink-0"
                >
                  <MapPinPlus className="h-4 w-4 text-indigo-600" /> Add New Address
                </Button>
              }
            />
          </div>
        </div>
      )}
    </div>
  );
}
