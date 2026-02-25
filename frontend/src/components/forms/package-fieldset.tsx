// src/components/forms/package-fieldset.tsx
"use client";

import { Button } from "@/components/ui/button";
import { FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ShipmentFormValues } from "@/lib/validations/shipment";
import { Box, Plus, Trash2 } from "lucide-react";
import { Control, useFieldArray } from "react-hook-form";

export function PackageFieldset({ control }: { control: Control<ShipmentFormValues> }) {
    // Initialize the dynamic array hook
    const { fields, append, remove } = useFieldArray({
        control,
        name: "packages",
    });

    return (
        <div className="space-y-6">
            {fields.map((field, index) => (
                <div key={field.id} className="relative bg-slate-50/50 p-6 rounded-xl border border-slate-200 shadow-sm animate-in fade-in slide-in-from-bottom-2">

                    {/* Header & Delete Button */}
                    <div className="flex items-center justify-between mb-4 border-b border-slate-200 pb-2">
                        <h3 className="text-md font-semibold text-slate-900 flex items-center gap-2">
                            <Box className="h-4 w-4 text-primary" /> Box {index + 1}
                        </h3>
                        {fields.length > 1 && (
                            <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="text-red-500 hover:text-red-700 hover:bg-red-50"
                                onClick={() => remove(index)}
                            >
                                <Trash2 className="h-4 w-4 mr-1" /> Remove
                            </Button>
                        )}
                    </div>

                    {/* Form Grid */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <FormField control={control} name={`packages.${index}.length`} render={({ field }) => (
                            <FormItem><FormLabel>Length (cm)</FormLabel><FormControl>
                                <Input type="number" step="0.1" className="bg-white" {...field} onChange={e => field.onChange(e.target.valueAsNumber || 0)} />
                            </FormControl><FormMessage /></FormItem>
                        )} />

                        <FormField control={control} name={`packages.${index}.breadth`} render={({ field }) => (
                            <FormItem><FormLabel>Breadth (cm)</FormLabel><FormControl>
                                <Input type="number" step="0.1" className="bg-white" {...field} onChange={e => field.onChange(e.target.valueAsNumber || 0)} />
                            </FormControl><FormMessage /></FormItem>
                        )} />

                        <FormField control={control} name={`packages.${index}.height`} render={({ field }) => (
                            <FormItem><FormLabel>Height (cm)</FormLabel><FormControl>
                                <Input type="number" step="0.1" className="bg-white" {...field} onChange={e => field.onChange(e.target.valueAsNumber || 0)} />
                            </FormControl><FormMessage /></FormItem>
                        )} />

                        <FormField control={control} name={`packages.${index}.weight`} render={({ field }) => (
                            <FormItem><FormLabel>Weight (kg)</FormLabel><FormControl>
                                <Input type="number" step="0.1" className="bg-white" {...field} onChange={e => field.onChange(e.target.valueAsNumber || 0)} />
                            </FormControl><FormMessage /></FormItem>
                        )} />

                        <FormField control={control} name={`packages.${index}.description`} render={({ field }) => (
                            <FormItem className="col-span-2 md:col-span-4"><FormLabel>Contents Description (Optional)</FormLabel><FormControl>
                                <Input placeholder="e.g. Electronics, Clothing..." className="bg-white" {...field} />
                            </FormControl><FormMessage /></FormItem>
                        )} />
                    </div>
                </div>
            ))}

            {/* Add New Box Button */}
            <Button
                type="button"
                variant="outline"
                className="w-full border-dashed border-2 text-slate-500 hover:text-primary hover:border-primary/50"
                onClick={() => append({ length: 0, breadth: 0, height: 0, weight: 0, description: "" })}
            >
                <Plus className="h-4 w-4 mr-2" /> Add Another Package
            </Button>
        </div>
    );
}