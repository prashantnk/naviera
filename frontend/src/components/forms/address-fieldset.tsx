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
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ShipmentFormValues } from "@/lib/validations/shipment";
import { BookUser, MapPinPlus } from "lucide-react";
import { useState } from "react";
import { Control } from "react-hook-form";

interface AddressFieldsetProps {
  control: Control<ShipmentFormValues>;
  type: "pickup" | "delivery"; // Simplified type
  title: string;
  savedAddresses: AddressRead[];
}

export function AddressFieldset({
  control,
  type,
  title,
  savedAddresses = [],
}: AddressFieldsetProps) {
  const [mode, setMode] = useState<"saved" | "manual">("saved");

  const idField =
    type === "pickup" ? "pickup_address_id" : "delivery_address_id";
  const objectField =
    type === "pickup" ? "new_pickup_address" : "new_delivery_address";

  return (
    <div className="space-y-6 bg-slate-50/50 p-6 rounded-xl border border-slate-100">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-slate-200 pb-4">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>

        {/* Mode Toggle */}
        <div className="flex bg-slate-100 p-1 rounded-lg border border-slate-200 w-fit">
          <Button
            type="button"
            variant={mode === "saved" ? "default" : "ghost"}
            size="sm"
            onClick={() => setMode("saved")}
            className="h-8"
          >
            <BookUser className="mr-2 h-4 w-4" /> Address Book
          </Button>
          <Button
            type="button"
            variant={mode === "manual" ? "default" : "ghost"}
            size="sm"
            onClick={() => setMode("manual")}
            className="h-8"
          >
            <MapPinPlus className="mr-2 h-4 w-4" /> Enter Manually
          </Button>
        </div>
      </div>

      {/* MODE: SAVED ADDRESS */}
      {mode === "saved" && (
        <div className="animate-in fade-in slide-in-from-left-4">
          <FormField
            control={control}
            name={idField}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Select a Saved Address</FormLabel>
                <Select
                  onValueChange={field.onChange}
                  defaultValue={field.value}
                >
                  <FormControl>
                    <SelectTrigger className="bg-white">
                      <SelectValue placeholder="Choose from address book..." />
                    </SelectTrigger>
                  </FormControl>
                  <SelectContent>
                    {savedAddresses.length === 0 && (
                      <div className="p-2 text-sm text-slate-500 italic">
                        No addresses saved yet.
                      </div>
                    )}
                    {savedAddresses.map((addr) => (
                      <SelectItem key={addr.id} value={addr.id}>
                        <span className="font-medium text-slate-900">
                          {addr.name}
                        </span>
                        <span className="text-slate-400 ml-2">
                          ({addr.city}, {addr.state})
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <FormMessage />
              </FormItem>
            )}
          />
        </div>
      )}

      {/* MODE: MANUAL ENTRY */}
      {mode === "manual" && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 animate-in fade-in slide-in-from-right-4">
          <FormField
            control={control}
            name={`${objectField}.name`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Contact Name</FormLabel>
                <FormControl>
                  <Input
                    placeholder="John Doe"
                    {...field}
                    className="bg-white"
                    value={field.value || ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={control}
            name={`${objectField}.phone`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Phone Number</FormLabel>
                <FormControl>
                  <Input
                    placeholder="+91 9876543210"
                    {...field}
                    className="bg-white"
                    value={field.value || ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={control}
            name={`${objectField}.address_line1`}
            render={({ field }) => (
              <FormItem className="md:col-span-2">
                <FormLabel>Address Line 1</FormLabel>
                <FormControl>
                  <Input
                    placeholder="Flat, Building, Street"
                    {...field}
                    className="bg-white"
                    value={field.value || ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {/* 🔥 Fix 2: Added Missing Address Fields */}
          <FormField
            control={control}
            name={`${objectField}.address_line2`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Address Line 2 (Optional)</FormLabel>
                <FormControl>
                  <Input
                    placeholder="Area, Sector"
                    {...field}
                    className="bg-white"
                    value={field.value || ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />
          <FormField
            control={control}
            name={`${objectField}.landmark`}
            render={({ field }) => (
              <FormItem>
                <FormLabel>Landmark (Optional)</FormLabel>
                <FormControl>
                  <Input
                    placeholder="Near Apollo Hospital"
                    {...field}
                    className="bg-white"
                    value={field.value || ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={control}
            name={`${objectField}.city`}
            render={({ field }) => (
              <FormItem className="md:col-span-2">
                <FormLabel>City</FormLabel>
                <FormControl>
                  <Input
                    placeholder="Mumbai"
                    {...field}
                    className="bg-white"
                    value={field.value || ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="grid grid-cols-2 gap-4 md:col-span-2">
            <FormField
              control={control}
              name={`${objectField}.state`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>State</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="MH"
                      {...field}
                      className="bg-white"
                      value={field.value || ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={control}
              name={`${objectField}.pincode`}
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Pincode</FormLabel>
                  <FormControl>
                    <Input
                      placeholder="400001"
                      {...field}
                      className="bg-white"
                      value={field.value || ""}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>
        </div>
      )}
    </div>
  );
}
