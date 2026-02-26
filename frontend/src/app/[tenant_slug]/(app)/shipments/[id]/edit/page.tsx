// src/app/[tenant_slug]/(app)/shipments/[id]/edit/page.tsx
"use client";

import { ShipmentsService } from "@/api_client";
import { PackageFieldset } from "@/components/forms/package-fieldset";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Form, FormControl, FormField, FormItem, FormLabel, FormMessage } from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { zodResolver } from "@hookform/resolvers/zod";
import { ArrowLeft, Loader2, Save } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

// 1. The Edit Schema (Notice it requires a comment for the Audit Log!)
const editShipmentSchema = z.object({
    order_reference_id: z.string().min(3, "Order Reference is required"),
    requested_pickup_date: z.string().min(1, "Pickup date is required"),
    packages: z.array(z.object({
        id: z.string().optional(), // Existing packages have IDs!
        length: z.number().min(0.1),
        breadth: z.number().min(0.1),
        height: z.number().min(0.1),
        weight: z.number().min(0.1),
        description: z.string().optional(),
    })).min(1, "At least one package is required"),
    comment: z.string().min(5, "You must provide a reason for editing this shipment."),
});

type EditShipmentValues = z.infer<typeof editShipmentSchema>;

export default function EditShipmentPage() {
    const params = useParams();
    const router = useRouter();
    const shipmentId = params.id as string;
    const { routeTo } = useTenant();

    const [loading, setLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);

    // 2. Initialize Form
    const form = useForm<EditShipmentValues>({
        resolver: zodResolver(editShipmentSchema),
        defaultValues: {
            order_reference_id: "",
            requested_pickup_date: "",
            packages: [],
            comment: "",
        },
    });

    // 3. Fetch Data & Populate Form
    useEffect(() => {
        const fetchShipment = async () => {
            try {
                const data = await ShipmentsService.getShipmentDetails(shipmentId);
                // Reset the form with the database data!
                form.reset({
                    order_reference_id: data.order_reference_id,
                    requested_pickup_date: data.requested_pickup_date,
                    packages: data.packages.map(p => ({
                        id: p.id,
                        length: p.length,
                        breadth: p.breadth,
                        height: p.height,
                        weight: p.weight,
                        description: p.description || "",
                    })),
                    comment: "", // Leave blank for the admin to fill
                });
            } catch (error) {
                toast.error("Failed to load shipment details.");
            } finally {
                setLoading(false);
            }
        };
        fetchShipment();
    }, [shipmentId, form]);

    // 4. Handle Submission
    const onSubmit = async (data: EditShipmentValues) => {
        setIsSubmitting(true);
        try {
            await ShipmentsService.updateShipment(shipmentId, {
                order_reference_id: data.order_reference_id,
                requested_pickup_date: data.requested_pickup_date,
                packages: data.packages,
                comment: data.comment,
                is_public: false, // Admin edits are usually internal
            });

            toast.success("Shipment updated successfully!");
            router.push(routeTo(`/shipments/${shipmentId}`));
        } catch (error: any) {
            console.error(error);
            toast.error(error.body?.detail || "Failed to update shipment.");
        } finally {
            setIsSubmitting(false);
        }
    };

    if (loading) {
        return <div className="flex h-64 items-center justify-center"><Loader2 className="h-8 w-8 animate-spin text-primary" /></div>;
    }

    return (
        <div className="max-w-4xl mx-auto space-y-6 pb-12">

            {/* Header */}
            <div className="flex items-center gap-4 border-b border-slate-200 pb-4">
                <Button variant="outline" size="icon" asChild className="h-9 w-9">
                    <Link href={routeTo(`/shipments/${shipmentId}`)}><ArrowLeft className="h-4 w-4" /></Link>
                </Button>
                <div>
                    <h1 className="text-2xl font-bold text-slate-900 tracking-tight">Edit Shipment</h1>
                    <p className="text-slate-500 text-sm mt-1">Update details for {shipmentId}</p>
                </div>
            </div>

            {/* The Edit Form */}
            <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-6 md:p-8">
                <Form {...form}>
                    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-8">

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 bg-slate-50 p-6 rounded-xl border border-slate-100">
                            <FormField control={form.control} name="order_reference_id" render={({ field }) => (
                                <FormItem><FormLabel>Order Reference ID</FormLabel><FormControl><Input {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                            )} />
                            <FormField control={form.control} name="requested_pickup_date" render={({ field }) => (
                                <FormItem><FormLabel>Requested Pickup Date</FormLabel><FormControl><Input type="date" {...field} className="bg-white" /></FormControl><FormMessage /></FormItem>
                            )} />
                        </div>

                        <div>
                            <h3 className="text-lg font-semibold text-slate-900 mb-4">Package Dimensions</h3>
                            <PackageFieldset control={form.control} />
                        </div>

                        <div className="border-t border-slate-200 pt-6">
                            <FormField control={form.control} name="comment" render={({ field }) => (
                                <FormItem>
                                    <FormLabel>Reason for Edit (Audit Log) <span className="text-red-500">*</span></FormLabel>
                                    <FormControl>
                                        <Textarea placeholder="e.g. Corrected actual weight after warehouse scan." className="resize-none" {...field} />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )} />
                        </div>

                        <div className="flex justify-end pt-4">
                            <Button type="submit" disabled={isSubmitting}>
                                {isSubmitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving...</> : <><Save className="mr-2 h-4 w-4" /> Save Changes</>}
                            </Button>
                        </div>
                    </form>
                </Form>
            </div>
        </div>
    );
}