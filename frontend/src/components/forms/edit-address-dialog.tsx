// src/components/forms/edit-address-dialog.tsx
"use client";

import { AddressRead, AddressesService, AddressCategory, AddressScope, AddressUpdate, ApiError } from "@/api_client";
import { Button } from "@/components/ui/button";
import { useUser } from "@/components/auth/auth-guard";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Form,
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
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2, User, Building2, Phone, Mail, MapPin, Tag, Eye } from "lucide-react";
import { useEffect, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { usePincodeLocator } from "@/hooks/use-pincode-locator";
import * as z from "zod";

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

export function EditAddressDialog({
  address,
  open,
  setOpen,
  onSuccess,
}: {
  address: AddressRead | null;
  open: boolean;
  setOpen: (o: boolean) => void;
  onSuccess: () => void;
}) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const { isAdmin } = useUser();

  const form = useForm<z.infer<typeof addressSchema>>({
    resolver: zodResolver(addressSchema),
  });

  const pincodeValue = useWatch({
    control: form.control,
    name: "pincode",
  });

  const { isLocating, geoVerified, geoError } = usePincodeLocator<z.infer<typeof addressSchema>>({
    pincodeValue,
    setValue: form.setValue,
    cityField: "city",
    stateField: "state",
  });

  useEffect(() => {
    if (address && open) {
      form.reset({
        name: address.name,
        company_name: address.company_name || "",
        phone: address.phone,
        alternate_phone: address.alternate_phone || "",
        email: address.email || "",
        address_line1: address.address_line1,
        address_line2: address.address_line2 || "",
        landmark: address.landmark || "",
        city: address.city,
        state: address.state,
        pincode: address.pincode,
        category: address.category || AddressCategory.HOME,
        scope: address.scope || AddressScope.PRIVATE,
        gstin: address.gstin || "",
      });
    }
  }, [address, open, form]);

  const onSubmit = async (data: z.infer<typeof addressSchema>) => {
    if (!address) return;
    setIsSubmitting(true);
    try {
      await AddressesService.updateSavedAddress(address.id, {
        ...data,
        email: data.email === "" ? undefined : data.email,
        company_name: data.company_name === "" ? undefined : data.company_name,
        alternate_phone: data.alternate_phone === "" ? undefined : data.alternate_phone,
        address_line2:
          data.address_line2 === "" ? undefined : data.address_line2,
        landmark: data.landmark === "" ? undefined : data.landmark,
        gstin: data.gstin === "" ? undefined : data.gstin,
        // Force scope to PRIVATE for non-admins
        scope: isAdmin ? data.scope : AddressScope.PRIVATE,
      } as AddressUpdate);
      toast.success("Address updated successfully!");
      setOpen(false);
      onSuccess();
    } catch (error: unknown) {
      const apiError = error as ApiError;
      toast.error(apiError.body?.detail || "Failed to update address");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent 
        className="sm:max-w-[600px] max-h-[90vh] overflow-y-auto rounded-xl shadow-lg border border-slate-200"
        onPointerDownOutside={(e) => e.preventDefault()}
      >
        <DialogHeader className="border-b border-slate-100 pb-4">
          <DialogTitle className="text-xl font-bold text-slate-950 flex items-center gap-2">
            <MapPin className="h-5.5 w-5.5 text-slate-950 shrink-0" /> Edit Address
          </DialogTitle>
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
            <div className="space-y-4">
              <h4 className="text-xs font-bold text-indigo-600 uppercase tracking-wider">Contact details</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-50/50 p-4 rounded-xl border border-slate-100">
                <FormField
                  control={form.control}
                  name="name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <User className="h-3.5 w-3.5 text-slate-400" /> Contact Name <span className="text-red-500">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input className="bg-white" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="phone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <Phone className="h-3.5 w-3.5 text-slate-400" /> Phone <span className="text-red-500">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input className="bg-white font-mono" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="email"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <Mail className="h-3.5 w-3.5 text-slate-400" /> Email Address
                      </FormLabel>
                      <FormControl>
                        <Input className="bg-white" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="alternate_phone"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <Phone className="h-3.5 w-3.5 text-slate-400" /> Alternate Phone
                      </FormLabel>
                      <FormControl>
                        <Input className="bg-white font-mono" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="company_name"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <Building2 className="h-3.5 w-3.5 text-slate-400" /> Company Name
                      </FormLabel>
                      <FormControl>
                        <Input className="bg-white" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={form.control}
                  name="gstin"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <Building2 className="h-3.5 w-3.5 text-slate-400" /> GSTIN
                      </FormLabel>
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
                  )}
                />
              </div>
            </div>

            {/* Section 2: Physical address */}
            <div className="space-y-4">
              <h4 className="text-xs font-bold text-indigo-600 uppercase tracking-wider">Physical address</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4 bg-slate-50/50 p-4 rounded-xl border border-slate-100">
                <FormField
                  control={form.control}
                  name="category"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        <Tag className="h-3.5 w-3.5 text-slate-400" /> Address Category
                      </FormLabel>
                      <Select onValueChange={field.onChange} value={field.value}>
                        <FormControl>
                          <SelectTrigger className="bg-white">
                            <SelectValue placeholder="Select Category" />
                          </SelectTrigger>
                        </FormControl>
                        <SelectContent>
                          {Object.values(AddressCategory).map((cat) => (
                            <SelectItem key={cat} value={cat}>
                              {cat}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="pincode"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="flex items-center gap-1.5">
                        Pincode <span className="text-red-500">*</span>
                        {isLocating && <Loader2 className="h-3.5 w-3.5 animate-spin text-indigo-600" />}
                        {geoVerified && <span className="text-[10px] font-bold text-emerald-600 flex items-center gap-0.5">✓ Verified</span>}
                      </FormLabel>
                      <FormControl>
                        <Input className="bg-white" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="address_line1"
                  render={({ field }) => (
                    <FormItem className="md:col-span-2">
                      <FormLabel>
                        Address Line 1 <span className="text-red-500">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input className="bg-white" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="address_line2"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Address Line 2</FormLabel>
                      <FormControl>
                        <Input className="bg-white" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="landmark"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Landmark</FormLabel>
                      <FormControl>
                        <Input className="bg-white" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="city"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        City <span className="text-red-500">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input 
                          className="bg-white" 
                          {...field} 
                          disabled={geoVerified}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                <FormField
                  control={form.control}
                  name="state"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>
                        State <span className="text-red-500">*</span>
                      </FormLabel>
                      <FormControl>
                        <Input 
                          className="bg-white" 
                          {...field} 
                          disabled={geoVerified}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />

                {isAdmin && (
                  <FormField
                    control={form.control}
                    name="scope"
                    render={({ field }) => (
                      <FormItem className="md:col-span-2 animate-in fade-in duration-150">
                        <FormLabel className="flex items-center gap-1.5">
                          <Eye className="h-3.5 w-3.5 text-slate-400" /> Sharing Scope
                        </FormLabel>
                        <Select onValueChange={field.onChange} value={field.value}>
                          <FormControl>
                            <SelectTrigger className="bg-white">
                              <SelectValue placeholder="Select Scope" />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            <SelectItem value={AddressScope.PRIVATE}>Private (Personal Use)</SelectItem>
                            <SelectItem value={AddressScope.TENANT}>Shared (Team-wide)</SelectItem>
                          </SelectContent>
                        </Select>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

                {geoError && (
                  <div className="md:col-span-2 text-[11px] text-amber-600 font-medium bg-amber-50 border border-amber-100 p-2.5 rounded-lg flex items-center gap-1.5 animate-in fade-in duration-150">
                    <span className="text-xs">⚠</span> {geoError}
                  </div>
                )}
              </div>
            </div>

            <div className="flex justify-end gap-3 pt-4 border-t border-slate-100">
              <Button
                type="button"
                variant="outline"
                className="cursor-pointer"
                onClick={() => setOpen(false)}
              >
                Cancel
              </Button>
              <Button type="submit" className="bg-slate-900 hover:bg-slate-800 text-white font-semibold px-5 cursor-pointer" disabled={isSubmitting}>
                {isSubmitting ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving...
                  </>
                ) : (
                  "Save Changes"
                )}
              </Button>
            </div>
          </form>
        </Form>
      </DialogContent>
    </Dialog>
  );
}
