// src/components/forms/add-address-dialog.tsx
"use client";

import { AddressesService, AddressCategory, AddressScope } from "@/api_client";
import { Button } from "@/components/ui/button";
import { useUser } from "@/components/auth/auth-guard";
import {
    Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
    Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { IconSelect } from "@/components/ui/icon-select";
import { FormSection, RequiredMark } from "@/components/ui/form-extras";
import { ADDRESS_CATEGORY_OPTIONS, ADDRESS_SCOPE_OPTIONS, toOptions } from "@/lib/form-options";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Plus, User, Building2, Phone, Mail, MapPin, Tag, Eye, Contact } from "lucide-react";
import { useState, useEffect } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { invalidateAddressesCache } from "@/hooks/use-addresses";
import { usePincodeLocator } from "@/hooks/use-pincode-locator";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { extractApiErrorMessage } from "@/lib/utils";
import * as z from "zod";

// The Upgraded Enterprise Schema
const addressSchema = z.object({
    name: z.string().min(2, "Contact name is required"),
    company_name: z.string().optional(),
    phone: z
        .string()
        .refine((val) => /^[6-9]\d{9}$/.test(val), {
            message: "Must be a 10-digit mobile number starting with 6-9",
        }),
    alternate_phone: z
        .string()
        .refine((val) => !val || /^[6-9]\d{9}$/.test(val), {
            message: "Must be a 10-digit mobile number starting with 6-9",
        })
        .optional()
        .or(z.literal("")),
    email: z.string().email("Invalid email").optional().or(z.literal("")),
    gstin: z
        .string()
        .refine((val) => !val || /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$/.test(val), {
            message: "Invalid Indian GSTIN format (e.g., 27AAAAA1111A1Z1)",
        })
        .optional()
        .or(z.literal("")),

    category: z.nativeEnum(AddressCategory),
    scope: z.nativeEnum(AddressScope),

    address_line1: z.string().min(5, "Please enter a complete address"),
    address_line2: z.string().optional(),
    landmark: z.string().optional(),

    city: z.string().min(2, "City is required"),
    state: z.string().min(2, "State is required"),
    pincode: z
        .string()
        .refine((val) => /^[1-9][0-9]{5}$/.test(val), {
            message: "Must be a valid 6-digit Indian pincode (cannot start with 0)",
        }),
});

export type AddressFormValues = z.infer<typeof addressSchema>;

/** Category and sharing-scope dropdown options (icon + label + helper text). */
const CATEGORY_SELECT_OPTIONS = toOptions(ADDRESS_CATEGORY_OPTIONS);
const SCOPE_SELECT_OPTIONS = toOptions(ADDRESS_SCOPE_OPTIONS);

interface AddAddressDialogProps {
    testIdPrefix?: string;
    onSuccess?: () => void;
    onSaveTransient?: (data: AddressFormValues) => void;
    trigger?: React.ReactNode;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    defaultValues?: Partial<AddressFormValues>;
}

export function AddAddressDialog({
    onSuccess,
    onSaveTransient,
    trigger,
    open: controlledOpen,
    onOpenChange: controlledOnOpenChange,
    defaultValues,
    testIdPrefix,
}: AddAddressDialogProps) {
    const [localOpen, setLocalOpen] = useState(false);
    const isControlled = controlledOpen !== undefined;
    const open = isControlled ? controlledOpen : localOpen;
    const setOpen = isControlled ? controlledOnOpenChange! : setLocalOpen;

    const { pending: isSubmitting, run } = useSingleFlight();
    const { isAdmin } = useUser();

    const form = useForm<AddressFormValues>({
        resolver: zodResolver(addressSchema),
        defaultValues: {
            name: "", company_name: "", phone: "", alternate_phone: "", email: "",
            address_line1: "", address_line2: "", landmark: "",
            city: "", state: "", pincode: "",
            category: AddressCategory.HOME,
            scope: AddressScope.PRIVATE,
            gstin: "",
        },
    });

    // Reset form when defaultValues change or when modal opens in transient mode
    useEffect(() => {
        if (open && defaultValues) {
            form.reset({
                name: defaultValues.name || "",
                company_name: defaultValues.company_name || "",
                phone: defaultValues.phone || "",
                alternate_phone: defaultValues.alternate_phone || "",
                email: defaultValues.email || "",
                address_line1: defaultValues.address_line1 || "",
                address_line2: defaultValues.address_line2 || "",
                landmark: defaultValues.landmark || "",
                city: defaultValues.city || "",
                state: defaultValues.state || "",
                pincode: defaultValues.pincode || "",
                category: defaultValues.category || AddressCategory.HOME,
                scope: defaultValues.scope || AddressScope.PRIVATE,
                gstin: defaultValues.gstin || "",
            });
        } else if (open && !defaultValues) {
            // If opening blank, make sure we clear any old residue
            form.reset({
                name: "", company_name: "", phone: "", alternate_phone: "", email: "",
                address_line1: "", address_line2: "", landmark: "",
                city: "", state: "", pincode: "",
                category: AddressCategory.HOME,
                scope: AddressScope.PRIVATE,
                gstin: "",
            });
        }
    }, [open, defaultValues, form]);

    const pincodeValue = useWatch({
        control: form.control,
        name: "pincode",
    });

    const { isLocating, geoVerified, geoError } = usePincodeLocator<AddressFormValues>({
        pincodeValue,
        setValue: form.setValue,
        cityField: "city",
        stateField: "state",
    });

    const onSubmit = (data: AddressFormValues) =>
        run(async () => {
            try {
                // Sanitize empty strings to undefined for strict backend validation
                const payload = {
                    ...data,
                    email: data.email === "" ? undefined : data.email,
                    company_name: data.company_name === "" ? undefined : data.company_name,
                    alternate_phone: data.alternate_phone === "" ? undefined : data.alternate_phone,
                    address_line2: data.address_line2 === "" ? undefined : data.address_line2,
                    landmark: data.landmark === "" ? undefined : data.landmark,
                    gstin: data.gstin === "" ? undefined : data.gstin,
                    // Force PRIVATE if user is not an Admin/Owner
                    scope: isAdmin ? data.scope : AddressScope.PRIVATE,
                };

                if (onSaveTransient) {
                    onSaveTransient(payload);
                    setOpen(false);
                    form.reset();
                    return;
                }

                await AddressesService.createSavedAddress(payload);
                invalidateAddressesCache();
                toast.success("Address saved successfully!");
                setOpen(false);
                form.reset();
                onSuccess?.();
            } catch (error: unknown) {
                console.error("Failed to save address:", error);
                toast.error(
                    extractApiErrorMessage(error, "Failed to save address. Please check your inputs.")
                );
            }
        });

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                {trigger || (
                    <Button className="bg-slate-900 hover:bg-slate-800 text-white transition-colors font-semibold shadow-sm cursor-pointer">
                        <Plus className="mr-2 h-4 w-4" /> Add Address
                    </Button>
                )}
            </DialogTrigger>

            <DialogContent 
                className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto rounded-xl shadow-lg border border-slate-200"
                onPointerDownOutside={(e) => e.preventDefault()}
            >
                <DialogHeader className="border-b border-slate-100 pb-4">
                    <DialogTitle className="text-xl font-bold text-slate-950 flex items-center gap-2">
                        <MapPin className="h-5.5 w-5.5 text-slate-900 shrink-0" /> Add New Address
                    </DialogTitle>
                    <DialogDescription className="text-slate-500 text-sm mt-1">
                        {isAdmin 
                          ? "Save a B2B shared warehouse or customer address for quicker booking suggestions."
                          : "Save a private customer or office address for quicker booking suggestions."}
                    </DialogDescription>
                </DialogHeader>

                <Form {...form}>
                    <form 
                        onSubmit={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            form.handleSubmit(onSubmit)(e);
                        }} 
                        className="space-y-5 pt-4"
                    >

                        {/* Section 1: Identity */}
                        <FormSection
                            icon={Contact}
                            title="Contact details"
                            description="Who should the courier call at this address?"
                        >
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-50/50 p-4 rounded-xl border border-slate-100">
                                <FormField control={form.control} name="name" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5"><User className="h-3.5 w-3.5 text-slate-400" /> Contact Name <RequiredMark /></FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.name` : undefined} placeholder="John Doe" className="bg-white" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="phone" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5"><Phone className="h-3.5 w-3.5 text-slate-400" /> Phone Number <RequiredMark /></FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.phone` : undefined} placeholder="9876543210" className="bg-white font-mono" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="email" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5"><Mail className="h-3.5 w-3.5 text-slate-400" /> Email Address</FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.email` : undefined} placeholder="john.doe@example.com" className="bg-white" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="alternate_phone" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5"><Phone className="h-3.5 w-3.5 text-slate-400" /> Alternate Phone</FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.alternate_phone` : undefined} placeholder="9876543211" className="bg-white font-mono" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="company_name" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5"><Building2 className="h-3.5 w-3.5 text-slate-400" /> Company Name</FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.company_name` : undefined} placeholder="e.g. Acme Corp" className="bg-white" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                                <FormField control={form.control} name="gstin" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5"><Building2 className="h-3.5 w-3.5 text-slate-400" /> GSTIN</FormLabel>
                                        <FormControl>
                                            <Input 
                                                placeholder="27AAAAA1111A1Z1" 
                                                className="bg-white font-mono uppercase" 
                                                {...field} 
                                                value={(field.value as string)?.toUpperCase() || ""}
                                            />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />
                            </div>
                        </FormSection>

                        {/* Section 2: Physical address */}
                        <FormSection
                            icon={MapPin}
                            title="Physical address"
                            description="Enter the pincode first; city and state fill in automatically."
                        >
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-50/50 p-4 rounded-xl border border-slate-100">
                                <FormField control={form.control} name="category" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5"><Tag className="h-3.5 w-3.5 text-slate-400" /> Address Category</FormLabel>
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
                                )} />

                                <FormField control={form.control} name="pincode" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel className="flex items-center gap-1.5">
                                            Pincode
                                            <RequiredMark />
                                            {isLocating && <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />}
                                            {geoVerified && <span className="text-[10px] font-bold text-emerald-600 flex items-center gap-0.5">✓ Verified</span>}
                                        </FormLabel>
                                        <FormControl>
                                            <Input data-testid={testIdPrefix ? `${testIdPrefix}.pincode` : undefined} placeholder="400001" className="bg-white" {...field} />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />

                                <FormField control={form.control} name="address_line1" render={({ field }) => (
                                    <FormItem className="md:col-span-2">
                                        <FormLabel>Address Line 1 <RequiredMark /></FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.address-line1` : undefined} placeholder="Flat, Building, Street" className="bg-white" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />

                                <FormField control={form.control} name="address_line2" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>Address Line 2</FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.address-line2` : undefined} placeholder="Area, Sector (Optional)" className="bg-white" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />

                                <FormField control={form.control} name="landmark" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>Landmark</FormLabel>
                                        <FormControl><Input data-testid={testIdPrefix ? `${testIdPrefix}.landmark` : undefined} placeholder="Near Apollo Hospital (Optional)" className="bg-white" {...field} /></FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />

                                <FormField control={form.control} name="city" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>City <RequiredMark /></FormLabel>
                                        <FormControl>
                                            <Input 
                                                data-testid={testIdPrefix ? `${testIdPrefix}.city` : undefined}
                                                placeholder="Mumbai" 
                                                className="bg-white" 
                                                {...field} 
                                                disabled={geoVerified}
                                            />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />

                                <FormField control={form.control} name="state" render={({ field }) => (
                                    <FormItem>
                                        <FormLabel>State <RequiredMark /></FormLabel>
                                        <FormControl>
                                            <Input 
                                                data-testid={testIdPrefix ? `${testIdPrefix}.state` : undefined}
                                                placeholder="MH" 
                                                className="bg-white" 
                                                {...field} 
                                                disabled={geoVerified}
                                            />
                                        </FormControl>
                                        <FormMessage />
                                    </FormItem>
                                )} />

                                {isAdmin && !onSaveTransient && (
                                    <FormField control={form.control} name="scope" render={({ field }) => (
                                        <FormItem className="md:col-span-2 animate-in fade-in duration-150">
                                            <FormLabel className="flex items-center gap-1.5"><Eye className="h-3.5 w-3.5 text-slate-400" /> Sharing Scope</FormLabel>
                                            <FormControl>
                                                <IconSelect
                                                    options={SCOPE_SELECT_OPTIONS}
                                                    value={field.value}
                                                    onValueChange={field.onChange}
                                                    placeholder="Select scope"
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )} />
                                )}

                                {geoError && (
                                    <div className="md:col-span-2 text-[11px] text-amber-600 font-medium bg-amber-50 border border-amber-100 p-2.5 rounded-lg flex items-center gap-1.5 animate-in fade-in duration-150">
                                        <span className="text-xs">⚠</span> {geoError}
                                    </div>
                                )}
                            </div>
                        </FormSection>

                        <div className="flex justify-end gap-3 pt-4 border-t border-slate-100">
                            <Button type="button" variant="outline" className="cursor-pointer" onClick={() => setOpen(false)}>Cancel</Button>
                            <Button data-testid={testIdPrefix ? `${testIdPrefix}.save` : undefined} type="submit" className="bg-slate-900 hover:bg-slate-800 text-white font-semibold px-5 cursor-pointer" disabled={isSubmitting}>
                                {isSubmitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving...</> : "Save Address"}
                            </Button>
                        </div>
                    </form>
                </Form>
            </DialogContent>
        </Dialog>
    );
}