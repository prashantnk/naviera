// src/app/[tenant_slug]/(app)/shipments/new/page.tsx
"use client";

import { AddressesService, AddressRead, AddressType, ShipmentsService } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { shipmentFormSchema, ShipmentFormValues } from "@/lib/validations/shipment";
import { zodResolver } from "@hookform/resolvers/zod";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";

import { AddressFieldset } from "@/components/forms/address-fieldset";
import { PackageFieldset } from "@/components/forms/package-fieldset"; // <-- Import the new array fieldset
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ArrowLeft, ArrowRight, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { toast } from "sonner";

const STEPS = [
    { id: 0, name: "Basic Details" },
    { id: 1, name: "Addresses" },
    { id: 2, name: "Packages" },
];

export default function CreateShipmentWizard() {
    const { routeTo } = useTenant();
    const router = useRouter();

    const [currentStep, setCurrentStep] = useState(0);
    const [isSubmitting, setIsSubmitting] = useState(false);

    // 🔥 Split into two distinct states!
    const [warehouses, setWarehouses] = useState<AddressRead[]>([]);
    const [customers, setCustomers] = useState<AddressRead[]>([]);

    useEffect(() => {
        const fetchAddresses = async () => {
            try {
                // 🔥 Fire both API requests at the exact same time for maximum speed
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
            new_pickup_address: { name: "", phone: "", address_line1: "", city: "", state: "", pincode: "" },
            new_delivery_address: { name: "", phone: "", address_line1: "", city: "", state: "", pincode: "" },
            packages: [{ length: 0, breadth: 0, height: 0, weight: 0, description: "" }],
        },
        mode: "onChange",
    });

    const nextStep = async () => {
        let fieldsToValidate: any[] = [];

        if (currentStep === 0) fieldsToValidate = ["order_reference_id", "requested_pickup_date"];
        if (currentStep === 1) fieldsToValidate = ["new_pickup_address", "new_delivery_address"];

        const isStepValid = await form.trigger(fieldsToValidate);
        if (isStepValid) setCurrentStep((prev) => prev + 1);
    };

    const prevStep = () => setCurrentStep((prev) => prev - 1);

    // --- THE FINAL SUBMISSION LOGIC ---
    const onSubmit = async (data: ShipmentFormValues) => {
        setIsSubmitting(true);
        try {
            // Call our auto-generated OpenAPI client!
            // Notice how our Zod schema perfectly matches the FastAPI 'PickupCreate' payload requirements.
            const response = await ShipmentsService.createShipment(data);

            toast.success("Shipment booked successfully!");

            // Redirect the user back to the data grid to see their new shipment
            router.push(routeTo("/shipments"));

        } catch (error: any) {
            console.error("Submission error:", error);
            toast.error(error.body?.detail || error.message || "Failed to create shipment. Check your details.");
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="max-w-4xl mx-auto space-y-6 pb-20">
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

                        {currentStep === 0 && (
                            <div className="space-y-6 animate-in fade-in slide-in-from-right-4">
                                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                                    <FormField control={form.control} name="order_reference_id" render={({ field }) => (
                                        <FormItem><FormLabel>Order Reference ID</FormLabel><FormControl><Input placeholder="e.g. ORD-12345" {...field} className="bg-slate-50" /></FormControl><FormMessage /></FormItem>
                                    )} />
                                    <FormField control={form.control} name="requested_pickup_date" render={({ field }) => (
                                        <FormItem><FormLabel>Requested Pickup Date</FormLabel><FormControl><Input type="date" {...field} className="bg-slate-50" /></FormControl><FormMessage /></FormItem>
                                    )} />
                                </div>
                            </div>
                        )}

                        {currentStep === 1 && (
                            <div className="space-y-6 animate-in fade-in slide-in-from-right-4">
                                <AddressFieldset
                                    control={form.control}
                                    type="pickup"
                                    title="1. Origin (Pickup)"
                                    savedAddresses={warehouses}
                                />
                                <AddressFieldset
                                    control={form.control}
                                    type="delivery"
                                    title="2. Destination (Delivery)"
                                    savedAddresses={customers}
                                />
                            </div>
                        )}

                        {/* --- THE NEW STEP 3: PACKAGES --- */}
                        {currentStep === 2 && (
                            <div className="animate-in fade-in slide-in-from-right-4">
                                <PackageFieldset control={form.control} />
                            </div>
                        )}

                        <div className="flex items-center justify-between pt-4 border-t border-slate-100">
                            <Button type="button" variant="outline" onClick={prevStep} disabled={currentStep === 0 || isSubmitting}>
                                Back
                            </Button>

                            {currentStep === STEPS.length - 1 ? (
                                <Button type="submit" disabled={isSubmitting}>
                                    {isSubmitting ? (
                                        <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Submitting...</>
                                    ) : (
                                        <><Save className="mr-2 h-4 w-4" /> Confirm & Book</>
                                    )}
                                </Button>
                            ) : (
                                <Button type="button" onClick={nextStep}>Next Step <ArrowRight className="ml-2 h-4 w-4" /></Button>
                            )}
                        </div>
                    </form>
                </Form>
            </div>
        </div>
    );
}