// src/app/[tenant_slug]/(app)/shipments/new/page.tsx
"use client";

import { AddressesService, AddressRead, AddressType, RateCalculationResponse, ServiceType, ShipmentsService } from "@/api_client";
import { AddressFieldset } from "@/components/forms/address-fieldset";
import { PackageFieldset } from "@/components/forms/package-fieldset";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { shipmentFormSchema, ShipmentFormValues } from "@/lib/validations/shipment";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, ArrowRight, CheckCircle2, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";

// 🔥 Added Step 4
const STEPS = [
    { id: 0, name: "Basic Details" },
    { id: 1, name: "Addresses" },
    { id: 2, name: "Packages" },
    { id: 3, name: "Review & Book" },
];

export default function CreateShipmentWizard() {
    const { routeTo } = useTenant();
    const router = useRouter();

    const [currentStep, setCurrentStep] = useState(0);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isCalculating, setIsCalculating] = useState(false);

    const [warehouses, setWarehouses] = useState<AddressRead[]>([]);
    const [customers, setCustomers] = useState<AddressRead[]>([]);

    // 🔥 State to hold the pricing receipt
    const [rateQuote, setRateQuote] = useState<RateCalculationResponse | null>(null);

    useEffect(() => {
        const fetchAddresses = async () => {
            try {
                const [whData, custData] = await Promise.all([
                    AddressesService.listSavedAddresses(AddressType.WAREHOUSE),
                    AddressesService.listSavedAddresses(AddressType.CUSTOMER)
                ]);
                setWarehouses(whData);
                setCustomers(custData);
            } catch (e) {
                console.error("Failed to load address book", e);
            }
        };
        fetchAddresses();
    }, []);

    const form = useForm<ShipmentFormValues>({
        resolver: zodResolver(shipmentFormSchema),
        defaultValues: {
            order_reference_id: "",
            requested_pickup_date: "",
            service_type: "SURFACE",
            packages: [{ length: 0, breadth: 0, height: 0, weight: 0, description: "" }],
            pickup_address_id: "",
            delivery_address_id: "",
            new_pickup_address: { name: "", phone: "", address_line1: "", city: "", state: "", pincode: "" },
            new_delivery_address: { name: "", phone: "", address_line1: "", city: "", state: "", pincode: "" },
        },
    });

    // --- THE INTELLIGENT STEPPER ---
    const nextStep = async () => {
        let fieldsToValidate: any[] = [];
        if (currentStep === 0) fieldsToValidate = ["order_reference_id", "requested_pickup_date", "service_type"];

        const isStepValid = await form.trigger(fieldsToValidate);
        if (!isStepValid) return;

        // 🔥 If we are on the Packages step, calculate the rate BEFORE moving to Review!
        if (currentStep === 2) {
            setIsCalculating(true);
            try {
                const values = form.getValues();

                // 1. Resolve Pincodes (Check if ID exists, otherwise use manual input)
                let pPincode = values.new_pickup_address?.pincode;
                if (values.pickup_address_id) {
                    pPincode = warehouses.find(w => w.id === values.pickup_address_id)?.pincode;
                }

                let dPincode = values.new_delivery_address?.pincode;
                if (values.delivery_address_id) {
                    dPincode = customers.find(c => c.id === values.delivery_address_id)?.pincode;
                }

                if (!pPincode || !dPincode) throw new Error("Cannot calculate rate: Missing pincodes.");

                // 2. Call the Pricing Engine
                const quote = await ShipmentsService.calculateShippingRate({
                    pickup_pincode: pPincode,
                    delivery_pincode: dPincode,
                    packages: values.packages as any, // Cast to match API spec
                    service_type: values.service_type as ServiceType,
                });

                // 3. Save Quote and move to Step 4
                setRateQuote(quote);
                setCurrentStep((prev) => prev + 1);
            } catch (error: any) {
                toast.error(error.body?.detail || error.message || "Failed to calculate rates.");
                return; // Stop them from moving to the review step!
            } finally {
                setIsCalculating(false);
            }
            return;
        }

        setCurrentStep((prev) => prev + 1);
    };

    const prevStep = () => setCurrentStep((prev) => prev - 1);

    const onSubmit = async (data: ShipmentFormValues) => {
        setIsSubmitting(true);
        try {
            const payload: any = { ...data };

            if (payload.pickup_address_id) {
                delete payload.new_pickup_address;
            }
            if (payload.delivery_address_id) {
                delete payload.new_delivery_address;
            }

            payload.pickup_address_id = payload.pickup_address_id || undefined;
            payload.delivery_address_id = payload.delivery_address_id || undefined;

            await ShipmentsService.createShipment(payload);
            toast.success("Shipment booked successfully!");
            router.push(routeTo("/shipments"));

        } catch (error: any) {
            let msg = error.message || "Failed to create shipment.";
            if (error.body?.detail && Array.isArray(error.body.detail)) {
                msg = error.body.detail.map((err: any) => `${err.loc.at(-1)}: ${err.msg}`).join(" | ");
            } else if (typeof error.body?.detail === "string") {
                msg = error.body.detail;
            }
            toast.error(msg);
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="max-w-4xl mx-auto space-y-6 pb-20">
            {/* Header & Progress Bar */}
            <div className="flex items-center gap-4">
                <Button variant="outline" size="icon" asChild className="h-9 w-9">
                    <Link href={routeTo("/shipments")}><ArrowLeft className="h-4 w-4" /></Link>
                </Button>
                <div>
                    <h1 className="text-3xl font-bold text-slate-900 tracking-tight">Create Booking</h1>
                    <p className="text-slate-500 mt-1">Step {currentStep + 1} of {STEPS.length}: {STEPS[currentStep].name}</p>
                </div>
            </div>

            <div className="w-full bg-slate-200 h-2 rounded-full overflow-hidden">
                <div className="bg-primary h-full transition-all duration-300 ease-in-out" style={{ width: `${((currentStep + 1) / STEPS.length) * 100}%` }} />
            </div>

            <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
                <Form {...form}>
                    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">

                        {/* STEP 1: BASIC DETAILS */}
                        {currentStep === 0 && (
                            <div className="space-y-6 animate-in fade-in slide-in-from-right-4">
                                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                    <FormField control={form.control} name="order_reference_id" render={({ field }) => (
                                        <FormItem><FormLabel>Order Reference</FormLabel><FormControl><Input placeholder="ORD-123" {...field} className="bg-slate-50" /></FormControl><FormMessage /></FormItem>
                                    )} />
                                    <FormField control={form.control} name="requested_pickup_date" render={({ field }) => (
                                        <FormItem><FormLabel>Pickup Date</FormLabel><FormControl><Input type="date" {...field} className="bg-slate-50" /></FormControl><FormMessage /></FormItem>
                                    )} />

                                    {/* 🔥 NEW: Service Type Selector */}
                                    <FormField control={form.control} name="service_type" render={({ field }) => (
                                        <FormItem>
                                            <FormLabel>Service Speed</FormLabel>
                                            <Select onValueChange={field.onChange} defaultValue={field.value}>
                                                <FormControl><SelectTrigger className="bg-slate-50"><SelectValue /></SelectTrigger></FormControl>
                                                <SelectContent>
                                                    <SelectItem value="SURFACE">Standard Surface</SelectItem>
                                                    <SelectItem value="EXPRESS">Air Express</SelectItem>
                                                </SelectContent>
                                            </Select>
                                            <FormMessage />
                                        </FormItem>
                                    )} />
                                </div>
                            </div>
                        )}

                        {/* STEP 2: ADDRESSES */}
                        {currentStep === 1 && (
                            <div className="space-y-6 animate-in fade-in slide-in-from-right-4">
                                <AddressFieldset control={form.control} type="pickup" title="1. Origin (Pickup)" savedAddresses={warehouses} />
                                <AddressFieldset control={form.control} type="delivery" title="2. Destination (Delivery)" savedAddresses={customers} />
                            </div>
                        )}

                        {/* STEP 3: PACKAGES */}
                        {currentStep === 2 && (
                            <div className="animate-in fade-in slide-in-from-right-4">
                                <PackageFieldset control={form.control} />
                            </div>
                        )}

                        {/* 🔥 STEP 4: REVIEW & BOOK (THE RECEIPT) */}
                        {currentStep === 3 && rateQuote && (
                            <div className="max-w-md mx-auto space-y-6 animate-in fade-in zoom-in-95">
                                <div className="text-center space-y-2">
                                    <div className="mx-auto w-12 h-12 bg-green-100 rounded-full flex items-center justify-center mb-4">
                                        <CheckCircle2 className="h-6 w-6 text-green-600" />
                                    </div>
                                    <h3 className="text-2xl font-bold text-slate-900">Review Pricing</h3>
                                    <p className="text-slate-500">Estimated delivery in {rateQuote.estimated_days} days</p>
                                </div>

                                <div className="bg-slate-50 p-6 rounded-xl border border-slate-200 space-y-4">
                                    <div className="flex justify-between text-slate-600">
                                        <span>Chargeable Weight</span>
                                        <span className="font-medium">{rateQuote.chargeable_weight} kg</span>
                                    </div>
                                    <div className="flex justify-between text-slate-600">
                                        <span>Base Charge</span>
                                        <span className="font-medium">₹{rateQuote.base_charge.toFixed(2)}</span>
                                    </div>
                                    {rateQuote.service_surcharge > 0 && (
                                        <div className="flex justify-between text-primary">
                                            <span>Express Surcharge</span>
                                            <span className="font-medium">₹{rateQuote.service_surcharge.toFixed(2)}</span>
                                        </div>
                                    )}
                                    <div className="flex justify-between text-slate-600">
                                        <span>Taxes (18% GST)</span>
                                        <span className="font-medium">₹{rateQuote.tax_amount.toFixed(2)}</span>
                                    </div>

                                    <div className="border-t border-slate-200 pt-4 mt-2 flex justify-between items-center">
                                        <span className="text-lg font-bold text-slate-900">Total Estimated</span>
                                        <span className="text-2xl font-extrabold text-slate-900">₹{rateQuote.total_amount.toFixed(2)}</span>
                                    </div>
                                </div>
                            </div>
                        )}

                        {/* Navigation Footer */}
                        <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                            <Button type="button" variant="outline" onClick={prevStep} disabled={currentStep === 0 || isSubmitting || isCalculating}>
                                Back
                            </Button>

                            {currentStep === STEPS.length - 1 ? (
                                <Button type="submit" disabled={isSubmitting}>
                                    {isSubmitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Booking...</> : <><Save className="mr-2 h-4 w-4" /> Confirm & Book</>}
                                </Button>
                            ) : (
                                <Button type="button" onClick={nextStep} disabled={isCalculating}>
                                    {isCalculating ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Calculating...</> : <>Next Step <ArrowRight className="ml-2 h-4 w-4" /></>}
                                </Button>
                            )}
                        </div>
                    </form>
                </Form>
            </div>
        </div>
    );
}