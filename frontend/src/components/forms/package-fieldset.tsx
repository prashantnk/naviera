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
import { Box, Plus, Trash2, ShieldAlert } from "lucide-react";
import { useFieldArray } from "react-hook-form";

// 🔥 NEW: Accept isReverse prop
export function PackageFieldset({
  control,
  isReverse = false,
}: {
  control: any;
  isReverse?: boolean;
}) {
  const { fields, append, remove } = useFieldArray({
    control,
    name: "packages",
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

          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {/* 🔥 DYNAMIC: Hide precise measurements for Reverse Shipments */}
            {!isReverse && (
              <>
                <FormField
                  control={control}
                  name={`packages.${index}.length`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Length (cm)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          step="0.1"
                          className="bg-white"
                          {...field}
                          onChange={(e) =>
                            field.onChange(e.target.valueAsNumber || 0)
                          }
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={control}
                  name={`packages.${index}.breadth`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Breadth (cm)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          step="0.1"
                          className="bg-white"
                          {...field}
                          onChange={(e) =>
                            field.onChange(e.target.valueAsNumber || 0)
                          }
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={control}
                  name={`packages.${index}.height`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Height (cm)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          step="0.1"
                          className="bg-white"
                          {...field}
                          onChange={(e) =>
                            field.onChange(e.target.valueAsNumber || 0)
                          }
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={control}
                  name={`packages.${index}.weight`}
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Weight (kg)</FormLabel>
                      <FormControl>
                        <Input
                          type="number"
                          step="0.1"
                          className="bg-white"
                          {...field}
                          onChange={(e) =>
                            field.onChange(e.target.valueAsNumber || 0)
                          }
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              </>
            )}

            <FormField
              control={control}
              name={`packages.${index}.box_count`}
              render={({ field }) => (
                <FormItem className={isReverse ? "col-span-2" : ""}>
                  <FormLabel>Number of Boxes</FormLabel>
                  <FormControl>
                    <Input
                      type="number"
                      className="bg-white"
                      {...field}
                      onChange={(e) =>
                        field.onChange(e.target.valueAsNumber || 1)
                      }
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name={`packages.${index}.description`}
              render={({ field }) => (
                <FormItem
                  className={
                    isReverse ? "col-span-3" : "col-span-2 md:col-span-3"
                  }
                >
                  <FormLabel>Contents Description</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="e.g. Laptops, T-Shirts..."
                      className="bg-white"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={control}
              name={`packages.${index}.is_fragile`}
              render={({ field }) => (
                <FormItem className="col-span-2 md:col-span-2 flex flex-row items-center space-x-3 space-y-0 p-3 mt-6 rounded-md border border-amber-200 bg-amber-50/50">
                  <FormControl>
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber-600"
                      checked={field.value}
                      onChange={field.onChange}
                    />
                  </FormControl>
                  <FormLabel className="flex items-center gap-1.5 text-amber-900 cursor-pointer font-semibold">
                    <ShieldAlert className="h-4 w-4 text-amber-600" /> Contains
                    Fragile Items
                  </FormLabel>
                </FormItem>
              )}
            />
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
            weight: 0.1,
            box_count: 1,
            is_fragile: false,
            description: "",
          })
        }
      >
        <Plus className="h-4 w-4 mr-2" /> Add Different Box Type
      </Button>
    </div>
  );
}
