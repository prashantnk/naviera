// src/components/forms/add-address-dialog.tsx
"use client";

import { AddressesService, AddressType, ApiError } from "@/api_client";
import { Button } from "@/components/ui/button";
import {
    Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
    Form, FormControl, FormField, FormItem, FormLabel, FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

// 1. The Upgraded Enterprise Schema
const addressSchema = z.object({
    name: z.string().min(2, "Contact name is required"),
    company_name: z.string().optional(),
    phone: z.string().min(10, "Phone must be at least 10 digits"),
    email: z.string().email("Invalid email").optional().or(z.literal("")),

    address_type: z.nativeEnum(AddressType),

    address_line1: z.string().min(5, "Please enter a complete address"),
    address_line2: z.string().optional(),
    landmark: z.string().optional(),

    city: z.string().min(2, "City is required"),
    state: z.string().min(2, "State is required"),
    pincode: z.string().min(6, "Valid Pincode required"),
});

type AddressFormValues = z.infer<typeof addressSchema>;

interface AddAddressDialogProps {
    onSuccess: () => void;
}

export function AddAddressDialog({ onSuccess }: AddAddressDialogProps) {
    const [open, setOpen] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);

    const form = useForm<AddressFormValues>({
        resolver: zodResolver(addressSchema),
        defaultValues: {
            name: "", company_name: "", phone: "", email: "",
            address_line1: "", address_line2: "", landmark: "",
            city: "", state: "", pincode: "",
            address_type: AddressType.CUSTOMER,
        },
    });

    const onSubmit = async (data: AddressFormValues) => {
        setIsSubmitting(true);
        try {
            // Sanitize empty strings to undefined for strict backend validation
            const payload = {
                ...data,
                email: data.email === "" ? undefined : data.email,
                company_name: data.company_name === "" ? undefined : data.company_name,
                address_line2: data.address_line2 === "" ? undefined : data.address_line2,
                landmark: data.landmark === "" ? undefined : data.landmark,
            };

            await AddressesService.createSavedAddress(payload);
            toast.success("Address saved successfully!");
            setOpen(false);
            form.reset();
            onSuccess();
        } catch (error: unknown) {
            console.error("Failed to save address:", error);

            let errorMessage = "Failed to save address. Please check your inputs.";
            const apiError = error as ApiError;
            if (apiError && typeof apiError === "object" && "body" in apiError) {
                const body = apiError.body as { detail?: unknown } | undefined;
                if (body && body.detail) {
                    if (Array.isArray(body.detail)) {
                        errorMessage = body.detail
                            .map((err: { loc?: unknown[]; msg?: string }) => {
                                const lastLoc = err.loc?.at(-1);
                                return `${lastLoc ? String(lastLoc) : "field"}: ${err.msg || "invalid value"}`;
                            })
                            .join(" | ");
                    } else if (typeof body.detail === "string") {
                        errorMessage = body.detail;
                    }
                }
            }
            toast.error(errorMessage);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button>
                    <Plus className="mr-2 h-4 w-4" /> Add Address
                </Button>
            </DialogTrigger>

            <DialogContent className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle>Add New Address</DialogTitle>
                    <DialogDescription>
                        Save a warehouse or customer address for quicker booking.
                    </DialogDescription>
                </DialogHeader>

                <Form {...form}>
                    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4 pt-4">

                        {/* Section 1: Identity */}
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                            <FormField control={form.control} name="name" render={({ field }) => (
                                <FormItem><FormLabel>Contact Name <span className="text-red-500">*</span></FormLabel><FormControl><Input placeholder="John Doe" {...field} /></FormControl><FormMessage /></FormItem>
                            )} />
                            <FormField control={form.control} name="company_name" render={({ field }) => (
                                <FormItem><FormLabel>Company Name</FormLabel><FormControl><Input placeholder="Optional" {...field} /></FormControl><FormMessage /></FormItem>
                            )} />
                            <FormField control={form.control} name="phone" render={({ field }) => (
                                <FormItem><FormLabel>Phone <span className="text-red-500">*</span></FormLabel><FormControl><Input placeholder="+91 9876543210" {...field} /></FormControl><FormMessage /></FormItem>
                            )} />
                            <FormField control={form.control} name="email" render={({ field }) => (
                                <FormItem><FormLabel>Email</FormLabel><FormControl><Input placeholder="Optional" {...field} /></FormControl><FormMessage /></FormItem>
                            )} />
                        </div>

                        {/* Section 2: Type */}
                        <FormField control={form.control} name="address_type" render={({ field }) => (
                            <FormItem>
                                <FormLabel>Address Type</FormLabel>
                                <Select onValueChange={field.onChange} defaultValue={field.value}>
                                    <FormControl><SelectTrigger><SelectValue placeholder="Select type" /></SelectTrigger></FormControl>
                                    <SelectContent>
                                        <SelectItem value={AddressType.CUSTOMER}>Customer Destination</SelectItem>
                                        <SelectItem value={AddressType.WAREHOUSE}>My Warehouse (Origin)</SelectItem>
                                    </SelectContent>
                                </Select>
                                <FormMessage />
                            </FormItem>
                        )} />

                        {/* Section 3: Location */}
                        <div className="space-y-4 bg-slate-50 p-4 rounded-xl border border-slate-100">
                            <FormField control={form.control} name="address_line1" render={({ field }) => (
                                <FormItem><FormLabel>Address Line 1 <span className="text-red-500">*</span></FormLabel><FormControl><Input placeholder="Flat, Building, Street" className="bg-white" {...field} /></FormControl><FormMessage /></FormItem>
                            )} />

                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <FormField control={form.control} name="address_line2" render={({ field }) => (
                                    <FormItem><FormLabel>Address Line 2</FormLabel><FormControl><Input placeholder="Area, Sector (Optional)" className="bg-white" {...field} /></FormControl><FormMessage /></FormItem>
                                )} />
                                <FormField control={form.control} name="landmark" render={({ field }) => (
                                    <FormItem><FormLabel>Landmark</FormLabel><FormControl><Input placeholder="Near Apollo Hospital (Optional)" className="bg-white" {...field} /></FormControl><FormMessage /></FormItem>
                                )} />
                            </div>

                            <div className="grid grid-cols-3 gap-4">
                                <FormField control={form.control} name="city" render={({ field }) => (
                                    <FormItem><FormLabel>City <span className="text-red-500">*</span></FormLabel><FormControl><Input placeholder="Mumbai" className="bg-white" {...field} /></FormControl><FormMessage /></FormItem>
                                )} />
                                <FormField control={form.control} name="state" render={({ field }) => (
                                    <FormItem><FormLabel>State <span className="text-red-500">*</span></FormLabel><FormControl><Input placeholder="MH" className="bg-white" {...field} /></FormControl><FormMessage /></FormItem>
                                )} />
                                <FormField control={form.control} name="pincode" render={({ field }) => (
                                    <FormItem><FormLabel>Pincode <span className="text-red-500">*</span></FormLabel><FormControl><Input placeholder="400001" className="bg-white" {...field} /></FormControl><FormMessage /></FormItem>
                                )} />
                            </div>
                        </div>

                        <div className="flex justify-end gap-3 pt-4">
                            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
                            <Button type="submit" disabled={isSubmitting}>
                                {isSubmitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving...</> : "Save Address"}
                            </Button>
                        </div>
                    </form>
                </Form>
            </DialogContent>
        </Dialog>
    );
}