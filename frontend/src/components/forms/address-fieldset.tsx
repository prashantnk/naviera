// src/components/forms/address-fieldset.tsx
"use client";

import { FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ShipmentFormValues } from "@/lib/validations/shipment";
import { Control } from "react-hook-form";

interface AddressFieldsetProps {
    // We strictly type the control object to our Zod schema!
    control: Control<ShipmentFormValues>;
    type: "new_pickup_address" | "new_delivery_address";
    title: string;
}

export function AddressFieldset({ control, type, title }: AddressFieldsetProps) {
    return (
        <div className="space-y-4 bg-slate-50/50 p-6 rounded-xl border border-slate-100">
            <h3 className="text-lg font-semibold text-slate-900 border-b border-slate-200 pb-2 mb-4">
                {title}
            </h3>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <FormField control={control} name={`${type}.name`} render={({ field }) => (
                    <FormItem><FormLabel>Contact Name</FormLabel><FormControl><Input placeholder="John Doe" {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                )} />
                <FormField control={control} name={`${type}.phone`} render={({ field }) => (
                    <FormItem><FormLabel>Phone Number</FormLabel><FormControl><Input placeholder="+91 9876543210" {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                )} />

                <FormField control={control} name={`${type}.address_line1`} render={({ field }) => (
                    <FormItem className="md:col-span-2"><FormLabel>Address Line 1</FormLabel><FormControl><Input placeholder="Flat, Building, Street" {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                )} />

                <FormField control={control} name={`${type}.city`} render={({ field }) => (
                    <FormItem><FormLabel>City</FormLabel><FormControl><Input placeholder="Mumbai" {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                )} />

                <div className="grid grid-cols-2 gap-4">
                    <FormField control={control} name={`${type}.state`} render={({ field }) => (
                        <FormItem><FormLabel>State</FormLabel><FormControl><Input placeholder="MH" {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                    )} />
                    <FormField control={control} name={`${type}.pincode`} render={({ field }) => (
                        <FormItem><FormLabel>Pincode</FormLabel><FormControl><Input placeholder="400001" {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                    )} />
                </div>
            </div>
        </div>
    );
}