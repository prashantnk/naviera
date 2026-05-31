// src/components/forms/update-status-dialog.tsx
"use client";

import { PickupStatus, ShipmentsService, ApiError } from "@/api_client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import {
    Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger,
} from "@/components/ui/dialog";
import {
    Form, FormControl, FormDescription, FormField, FormItem, FormLabel, FormMessage,
} from "@/components/ui/form";
import {
    Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { Loader2, Truck } from "lucide-react";

const updateStatusSchema = z.object({
    status: z.nativeEnum(PickupStatus),
    comment: z.string().min(5, "Please provide a descriptive reason for this update."),
    is_public: z.boolean(),
});

type UpdateStatusFormValues = z.infer<typeof updateStatusSchema>;

interface UpdateStatusDialogProps {
    shipmentId: string;
    currentStatus: PickupStatus;
    onSuccess: () => void; // Callback to refresh the parent page
}

export function UpdateStatusDialog({ shipmentId, currentStatus, onSuccess }: UpdateStatusDialogProps) {
    const [open, setOpen] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);

    const form = useForm<UpdateStatusFormValues>({
        resolver: zodResolver(updateStatusSchema),
        defaultValues: {
            status: currentStatus,
            comment: "",
            is_public: true,
        },
    });

    const onSubmit = async (data: UpdateStatusFormValues) => {
        setIsSubmitting(true);
        try {
            await ShipmentsService.updateShipment(shipmentId, {
                status: data.status,
                comment: data.comment,
                is_public: data.is_public,
            });

            toast.success("Shipment status updated successfully!");
            setOpen(false);
            form.reset(); // Clear the form
            onSuccess();  // Trigger parent refresh
        } catch (error: unknown) {
            console.error("Update error:", error);
            const apiError = error as ApiError;
            toast.error(apiError.body?.detail || "Failed to update status. Transition may be invalid.");
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="default"><Truck className="mr-2 h-4 w-4" /> Update Status</Button>
            </DialogTrigger>

            <DialogContent className="sm:max-w-[425px]">
                <DialogHeader>
                    <DialogTitle>Update Shipment Status</DialogTitle>
                    <DialogDescription>
                        Advance the lifecycle of this shipment. This will be recorded in the audit log.
                    </DialogDescription>
                </DialogHeader>

                <Form {...form}>
                    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6 pt-4">

                        <FormField control={form.control} name="status" render={({ field }) => (
                            <FormItem>
                                <FormLabel>New Status</FormLabel>
                                <Select onValueChange={field.onChange} defaultValue={field.value}>
                                    <FormControl>
                                        <SelectTrigger>
                                            <SelectValue placeholder="Select a status" />
                                        </SelectTrigger>
                                    </FormControl>
                                    <SelectContent>
                                        {Object.values(PickupStatus).map((status) => (
                                            <SelectItem key={status} value={status}>
                                                {status.replace("_", " ")}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                                <FormMessage />
                            </FormItem>
                        )} />

                        <FormField control={form.control} name="comment" render={({ field }) => (
                            <FormItem>
                                <FormLabel>Update Comment</FormLabel>
                                <FormControl>
                                    <Textarea
                                        placeholder="e.g., Driver has been assigned and is en route to warehouse."
                                        className="resize-none"
                                        {...field}
                                    />
                                </FormControl>
                                <FormMessage />
                            </FormItem>
                        )} />

                        <FormField control={form.control} name="is_public" render={({ field }) => (
                            <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                                <FormControl>
                                    <input
                                        type="checkbox"
                                        className="h-4 w-4 mt-0.5"
                                        checked={field.value}
                                        onChange={field.onChange}
                                    />
                                </FormControl>
                                <div className="space-y-1 leading-none">
                                    <FormLabel>Make Public</FormLabel>
                                    <FormDescription>
                                        Allow the customer to see this update on the tracking page.
                                    </FormDescription>
                                </div>
                            </FormItem>
                        )} />

                        <div className="flex justify-end gap-3">
                            <Button type="button" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
                            <Button type="submit" disabled={isSubmitting}>
                                {isSubmitting ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving...</> : "Save Update"}
                            </Button>
                        </div>
                    </form>
                </Form>
            </DialogContent>
        </Dialog>
    );
}