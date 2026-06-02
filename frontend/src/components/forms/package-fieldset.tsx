// frontend/src/components/forms/package-fieldset.tsx
"use client";

import { Button } from "@/components/ui/button";
import {
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { DimensionUnit, WeightUnit } from "@/api_client";
import { Box, Plus, Trash2, ShieldAlert } from "lucide-react";
import { useFieldArray, Control, ArrayPath, FieldValues, Path, FieldArray } from "react-hook-form";

export interface HasPackages extends FieldValues {
  packages: {
    id?: string;
    length?: number;
    breadth?: number;
    height?: number;
    dimension_unit?: DimensionUnit;
    weight: number;
    weight_unit?: WeightUnit;
    box_count: number;
    is_fragile: boolean;
    description?: string;
  }[];
}

export function PackageFieldset<TFieldValues extends HasPackages>({
  control,
  isReverse = false,
}: {
  control: Control<TFieldValues>;
  isReverse?: boolean;
}) {
  const { fields, append, remove } = useFieldArray({
    control,
    name: "packages" as ArrayPath<TFieldValues>,
  });

  return (
    <div className="space-y-6">
      {fields.map((field, index) => (
        <div
          key={field.id}
          className="relative bg-slate-50 p-6 rounded-xl border border-slate-200 shadow-sm animate-in fade-in slide-in-from-bottom-2"
        >
          <div className="flex items-center justify-between mb-4 border-b border-slate-200 pb-2">
            <h3 className="text-md font-semibold text-slate-900 flex items-center gap-2">
              <Box className="h-4 w-4 text-primary" /> Box Configuration{" "}
              {index + 1}
            </h3>
            {fields.length > 1 && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="text-red-500 hover:bg-red-50"
                onClick={() => remove(index)}
              >
                <Trash2 className="h-4 w-4 mr-1" /> Remove
              </Button>
            )}
          </div>

          <div className="space-y-4">
            {!isReverse ? (
              <>
                {/* Row 1: Dimensions & Unit (12 Cols) */}
                <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 items-start">
                  <FormField
                    control={control}
                    name={`packages.${index}.length` as Path<TFieldValues>}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-semibold text-slate-700">Length</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            step="0.1"
                            className="bg-white h-9 text-xs"
                            placeholder="0"
                            {...field}
                            value={(field.value as number) || ""}
                            onChange={(e) => {
                              const val = e.target.value;
                              field.onChange(val === "" ? "" : Number(val));
                            }}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={control}
                    name={`packages.${index}.breadth` as Path<TFieldValues>}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-semibold text-slate-700">Breadth</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            step="0.1"
                            className="bg-white h-9 text-xs"
                            placeholder="0"
                            {...field}
                            value={(field.value as number) || ""}
                            onChange={(e) => {
                              const val = e.target.value;
                              field.onChange(val === "" ? "" : Number(val));
                            }}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={control}
                    name={`packages.${index}.height` as Path<TFieldValues>}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-semibold text-slate-700">Height</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            step="0.1"
                            className="bg-white h-9 text-xs"
                            placeholder="0"
                            {...field}
                            value={(field.value as number) || ""}
                            onChange={(e) => {
                              const val = e.target.value;
                              field.onChange(val === "" ? "" : Number(val));
                            }}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={control}
                    name={`packages.${index}.dimension_unit` as Path<TFieldValues>}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-semibold text-slate-700">Unit</FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          value={field.value || DimensionUnit.CM}
                        >
                          <FormControl>
                            <SelectTrigger className="bg-white h-9 text-xs">
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {Object.values(DimensionUnit).map((unit) => (
                              <SelectItem key={unit} value={unit} className="text-xs">
                                {unit}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>

                {/* Row 2: Weight Details & Box Count (12 Cols) */}
                <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 items-start mt-4">
                  <div className="sm:col-span-8">
                    <FormField
                      control={control}
                      name={`packages.${index}.weight` as Path<TFieldValues>}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs font-semibold text-slate-700">Weight</FormLabel>
                          <div className="flex gap-2 items-center">
                            <FormControl>
                              <Input
                                type="number"
                                step="0.1"
                                className="bg-white h-9 text-xs flex-1"
                                placeholder="0.0"
                                {...field}
                                value={(field.value as number) || ""}
                                onChange={(e) => {
                                  const val = e.target.value;
                                  field.onChange(val === "" ? "" : Number(val));
                                }}
                              />
                            </FormControl>
                            <FormField
                              control={control}
                              name={`packages.${index}.weight_unit` as Path<TFieldValues>}
                              render={({ field: unitField }) => (
                                <Select
                                  onValueChange={unitField.onChange}
                                  value={unitField.value || WeightUnit.KG}
                                >
                                  <FormControl>
                                    <SelectTrigger className="w-[76px] bg-white h-9 text-xs shrink-0">
                                      <SelectValue />
                                    </SelectTrigger>
                                  </FormControl>
                                  <SelectContent>
                                    {Object.values(WeightUnit).map((unit) => (
                                      <SelectItem key={unit} value={unit} className="text-xs">
                                        {unit.toLowerCase()}
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              )}
                            />
                          </div>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                  <div className="sm:col-span-4">
                    <FormField
                      control={control}
                      name={`packages.${index}.box_count` as Path<TFieldValues>}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs font-semibold text-slate-700">Number of Boxes</FormLabel>
                          <FormControl>
                            <Input
                              type="number"
                              className="bg-white h-9 text-xs"
                              {...field}
                              value={(field.value as number) || 1}
                              onChange={(e) =>
                                field.onChange(e.target.valueAsNumber || 1)
                              }
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                </div>

                {/* Row 3: Contents Description & Fragile Toggle */}
                <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 items-start mt-4">
                  <div className="sm:col-span-8">
                    <FormField
                      control={control}
                      name={`packages.${index}.description` as Path<TFieldValues>}
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs font-semibold text-slate-700">Contents Description</FormLabel>
                          <FormControl>
                            <Input
                              placeholder="e.g. Laptops, T-Shirts..."
                              className="bg-white h-9 text-xs"
                              {...field}
                              value={(field.value as string) || ""}
                            />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                  <div className="sm:col-span-4">
                    <FormField
                      control={control}
                      name={`packages.${index}.is_fragile` as Path<TFieldValues>}
                      render={({ field }) => (
                        <FormItem className="space-y-0 mt-0 sm:mt-6.5">
                          <FormControl>
                            <div
                              onClick={() => field.onChange(!field.value)}
                              className={`flex flex-row items-center gap-2.5 p-2 px-3 h-9 rounded-lg border transition-all cursor-pointer select-none w-full hover:bg-amber-50/50 ${
                                field.value
                                  ? "bg-amber-50/40 border-amber-300 shadow-3xs"
                                  : "bg-white border-slate-200 hover:border-slate-300"
                              }`}
                            >
                              <input
                                type="checkbox"
                                className="h-4 w-4 rounded border-slate-300 text-amber-600 focus:ring-amber-500 cursor-pointer accent-amber-600 shrink-0"
                                checked={!!field.value}
                                onChange={(e) => {
                                  e.stopPropagation();
                                  field.onChange(e.target.checked);
                                }}
                              />
                              <span className="flex items-center gap-1.5 text-amber-800 font-bold text-xs select-none">
                                <ShieldAlert className="h-3.5 w-3.5 text-amber-600 shrink-0" /> Fragile
                              </span>
                            </div>
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                  </div>
                </div>
              </>
            ) : (
              /* Reverse Shipment Layout */
              <div className="grid grid-cols-1 md:grid-cols-12 gap-4 items-start">
                <div className="col-span-12 md:col-span-3">
                  <FormField
                    control={control}
                    name={`packages.${index}.box_count` as Path<TFieldValues>}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Number of Boxes</FormLabel>
                        <FormControl>
                          <Input
                            type="number"
                            className="bg-white"
                            {...field}
                            value={(field.value as number) || 1}
                            onChange={(e) =>
                              field.onChange(e.target.valueAsNumber || 1)
                            }
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
                <div className="col-span-12 md:col-span-6">
                  <FormField
                    control={control}
                    name={`packages.${index}.description` as Path<TFieldValues>}
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel>Contents Description</FormLabel>
                        <FormControl>
                          <Input
                            placeholder="e.g. Laptops, T-Shirts..."
                            className="bg-white"
                            {...field}
                            value={(field.value as string) || ""}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
                <div className="col-span-12 md:col-span-3">
                  <FormField
                    control={control}
                    name={`packages.${index}.is_fragile` as Path<TFieldValues>}
                    render={({ field }) => (
                      <FormItem className="space-y-0 mt-0 md:mt-6.5">
                        <FormControl>
                          <div
                            onClick={() => field.onChange(!field.value)}
                            className={`flex flex-row items-center gap-2.5 p-2 px-3 h-9 rounded-lg border transition-all cursor-pointer select-none w-full hover:bg-amber-50/50 ${
                              field.value
                                ? "bg-amber-50/40 border-amber-300 shadow-3xs"
                                : "bg-white border-slate-200 hover:border-slate-300"
                            }`}
                          >
                            <input
                              type="checkbox"
                              className="h-4 w-4 rounded border-slate-300 text-amber-600 focus:ring-amber-500 cursor-pointer accent-amber-600 shrink-0"
                              checked={!!field.value}
                              onChange={(e) => {
                                e.stopPropagation();
                                field.onChange(e.target.checked);
                              }}
                            />
                            <span className="flex items-center gap-1.5 text-amber-800 font-bold text-xs select-none">
                              <ShieldAlert className="h-3.5 w-3.5 text-amber-600 shrink-0" /> Fragile
                            </span>
                          </div>
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        className="w-full border-dashed border-2 text-slate-500"
        onClick={() =>
          append({
            length: 0,
            breadth: 0,
            height: 0,
            dimension_unit: DimensionUnit.CM,
            weight: 0.1,
            weight_unit: WeightUnit.KG,
            box_count: 1,
            is_fragile: false,
            description: "",
          } as FieldArray<TFieldValues, ArrayPath<TFieldValues>>)
        }
      >
        <Plus className="h-4 w-4 mr-2" /> Add Different Box Type
      </Button>
    </div>
  );
}
