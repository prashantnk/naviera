// src/components/forms/update-status-dialog.tsx
"use client";

import {
    NdrExceptionReason,
    PickupStatus,
    ShipmentsService,
} from "@/api_client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import * as z from "zod";

import { Button } from "@/components/ui/button";
import { useUser } from "@/components/auth/auth-guard";
import { useSingleFlight } from "@/hooks/use-single-flight";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogTrigger,
} from "@/components/ui/dialog";
import {
    Form,
    FormControl,
    FormDescription,
    FormField,
    FormItem,
    FormLabel,
    FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { IconSelect } from "@/components/ui/icon-select";
import { InputAdornment, RequiredMark } from "@/components/ui/form-extras";
import { Textarea } from "@/components/ui/textarea";
import { NDR_REASON_OPTIONS, PICKUP_STATUS_OPTIONS, toOptions } from "@/lib/form-options";
import { extractApiErrorMessage } from "@/lib/utils";
import { KeyRound, Loader2, PackageCheck, ShieldAlert, Truck, Undo2 } from "lucide-react";

/** Minimum characters for a receiver name (POD and RTO delivered). */
const MIN_RECEIVER_NAME_LENGTH = 2;

/** Statuses whose form captures who physically received the parcel. */
const RECEIVER_REQUIRED_STATUSES: ReadonlySet<PickupStatus> = new Set([
    PickupStatus.COMPLETED,
    PickupStatus.RTO_DELIVERED,
]);

const updateStatusSchema = z
    .object({
        status: z.nativeEnum(PickupStatus),
        comment: z
            .string()
            .min(5, "Please provide a descriptive reason for this update."),
        is_public: z.boolean(),
        delivery_otp: z.string().optional(),
        pod_received_by: z.string().optional(),
        ndr_reason: z.string().optional(),
        ndr_remark: z.string().optional(),
        charge_amount: z.string().optional(),
        measured_weight_kg: z.string().optional(),
    })
    .superRefine((vals, ctx) => {
        if (vals.status === PickupStatus.COMPLETED) {
            if (!vals.delivery_otp || !/^\d{6}$/.test(vals.delivery_otp.trim())) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    path: ["delivery_otp"],
                    message: "A valid 6-digit Delivery OTP is required for POD.",
                });
            }
            if (!vals.pod_received_by || vals.pod_received_by.trim().length < 2) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    path: ["pod_received_by"],
                    message: "Receiver name is required for Proof of Delivery.",
                });
            }
        }
        if (vals.status === PickupStatus.RTO_DELIVERED) {
            if (!vals.pod_received_by || vals.pod_received_by.trim().length < MIN_RECEIVER_NAME_LENGTH) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    path: ["pod_received_by"],
                    message: "Enter who received the return at the seller's location.",
                });
            }
        }
        if (vals.status === PickupStatus.EXCEPTION) {
            if (!vals.ndr_reason) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    path: ["ndr_reason"],
                    message: "Please select an Exception / NDR Reason.",
                });
            }
            const isFreightReason =
                vals.ndr_reason === NdrExceptionReason.FREIGHT_COLLECTION;
            const isExtraReason =
                vals.ndr_reason === NdrExceptionReason.ADDITIONAL_CHARGES;
            if (isFreightReason || isExtraReason) {
                const parsedCharge = Number(vals.charge_amount);
                if (!vals.charge_amount || Number.isNaN(parsedCharge) || parsedCharge <= 0) {
                    ctx.addIssue({
                        code: z.ZodIssueCode.custom,
                        path: ["charge_amount"],
                        message: "Enter a valid positive charge amount in INR.",
                    });
                }
            }
            const isScaleReason =
                vals.ndr_reason === NdrExceptionReason.WEIGHT_DISCREPANCY;
            if (isScaleReason) {
                const rawScale = vals.measured_weight_kg;
                const parsedScale = Number(rawScale);
                if (!rawScale || Number.isNaN(parsedScale) || parsedScale <= 0) {
                    ctx.addIssue({
                        code: z.ZodIssueCode.custom,
                        path: ["measured_weight_kg"],
                        message: "Enter the hub-measured scale reading in kg.",
                    });
                }
            }
        }
    });

type UpdateStatusFormValues = z.infer<typeof updateStatusSchema>;

interface UpdateStatusDialogProps {
    shipmentId: string;
    currentStatus: PickupStatus;
    /** Server-computed next statuses (`PickupRead.allowed_next_statuses`, E-11). */
    allowedNextStatuses: ReadonlyArray<PickupStatus>;
    onSuccess: () => void;
}

/** Lifecycle statuses with semantic tint + helper text, in enum declaration order. */
const STATUS_SELECT_OPTIONS = toOptions(PICKUP_STATUS_OPTIONS);

/**
 * Moves the server refuses (403) for anyone but owner/admin: Lost and a manual RTO start
 * (WP4). Display filter only; the backend stays the gatekeeper.
 */
const ADMIN_ONLY_TARGET_STATUSES: ReadonlySet<PickupStatus> = new Set([
    PickupStatus.LOST,
    PickupStatus.RTO_INITIATED,
]);

/**
 * Status options the dialog may offer: the current status plus the moves the server
 * accepts (`ShipmentLifecycleMachine` via the API), so nothing offered can 400 (E-11).
 *
 * @param currentStatus - The shipment's current status.
 * @param allowedNextStatuses - `PickupRead.allowed_next_statuses`.
 * @param canSetAdminOnlyStatuses - Whether the user is owner/admin (may set Lost / start RTO).
 * @returns The select options in enum declaration order.
 */
export function buildStatusSelectOptions(
    currentStatus: PickupStatus,
    allowedNextStatuses: ReadonlyArray<PickupStatus>,
    canSetAdminOnlyStatuses: boolean,
) {
    const offered = new Set<PickupStatus>(
        allowedNextStatuses.filter(
            (next) => canSetAdminOnlyStatuses || !ADMIN_ONLY_TARGET_STATUSES.has(next)
        )
    );
    offered.add(currentStatus);
    return STATUS_SELECT_OPTIONS.filter((opt) => offered.has(opt.value as PickupStatus));
}

/** NDR reasons ordered by how often operations raise them. */
const NDR_SELECT_OPTIONS = toOptions(NDR_REASON_OPTIONS, [
    NdrExceptionReason.CONSIGNEE_UNAVAILABLE,
    NdrExceptionReason.CONSIGNEE_REFUSED,
    NdrExceptionReason.DELIVERY_RESCHEDULED,
    NdrExceptionReason.CONSIGNEE_DETAILS_REQUIRED,
    NdrExceptionReason.PAYMENT_DISPUTE,
    NdrExceptionReason.EWAY_BILL_MISSING,
    NdrExceptionReason.DOCUMENT_NEEDED,
    NdrExceptionReason.APPOINTMENT_NEEDED,
    NdrExceptionReason.SHORT_SHIPMENT,
    NdrExceptionReason.DAMAGED,
    NdrExceptionReason.FREIGHT_COLLECTION,
    NdrExceptionReason.ADDITIONAL_CHARGES,
    NdrExceptionReason.WEIGHT_DISCREPANCY,
    NdrExceptionReason.PICKUP_FAILED,
]);

export function UpdateStatusDialog({
    shipmentId,
    currentStatus,
    allowedNextStatuses,
    onSuccess,
}: UpdateStatusDialogProps) {
    const [open, setOpen] = useState(false);
    const { pending: isSubmitting, run: runSubmit } = useSingleFlight();
    const { capabilities } = useUser();
    const filteredStatusOptions = buildStatusSelectOptions(
        currentStatus,
        allowedNextStatuses,
        capabilities.canManageTeam,
    );


    const form = useForm<UpdateStatusFormValues>({
        resolver: zodResolver(updateStatusSchema),
        defaultValues: {
            status: currentStatus,
            comment: "",
            is_public: currentStatus !== PickupStatus.EXCEPTION,
            delivery_otp: "",
            pod_received_by: "",
            ndr_reason: "",
            ndr_remark: "",
            charge_amount: "",
            measured_weight_kg: "",
        },
    });

    const watchedStatus = form.watch("status");
    const watchedNdrReason = form.watch("ndr_reason");

    useEffect(() => {
        if (watchedStatus === PickupStatus.EXCEPTION) {
            form.setValue("is_public", false);
        }
    }, [watchedStatus, form]);

    const submitStatus = async (data: UpdateStatusFormValues) => {
        try {
            const isException = data.status === PickupStatus.EXCEPTION;
            const isFreightCharge =
                data.ndr_reason === NdrExceptionReason.FREIGHT_COLLECTION;
            const isAdditionalCharge =
                data.ndr_reason === NdrExceptionReason.ADDITIONAL_CHARGES;
            const isScaleDiscrepancy =
                data.ndr_reason === NdrExceptionReason.WEIGHT_DISCREPANCY;
            const rawMeasuredKg = data.measured_weight_kg;

            await ShipmentsService.updateShipment(shipmentId, {
                status: data.status,
                comment: data.comment,
                is_public: data.is_public,
                delivery_otp:
                    data.status === PickupStatus.COMPLETED
                        ? data.delivery_otp?.trim()
                        : undefined,
                pod_received_by: RECEIVER_REQUIRED_STATUSES.has(data.status)
                    ? data.pod_received_by?.trim()
                    : undefined,
                ndr_reason:
                    isException && data.ndr_reason
                        ? (data.ndr_reason as NdrExceptionReason)
                        : undefined,
                ndr_remark:
                    isException && data.ndr_remark?.trim()
                        ? data.ndr_remark.trim()
                        : undefined,
                charge_amount:
                    isException &&
                    (isFreightCharge || isAdditionalCharge) &&
                    data.charge_amount
                        ? Number(data.charge_amount)
                        : undefined,
                measured_weight_kg:
                    isException && isScaleDiscrepancy && rawMeasuredKg
                        ? Number(rawMeasuredKg)
                        : undefined,
            });

            toast.success("Shipment status updated successfully!");
            window.dispatchEvent(new CustomEvent("wallet-updated"));
            setOpen(false);
            form.reset();
            onSuccess();
        } catch (error: unknown) {
            toast.error(
                extractApiErrorMessage(
                    error,
                    "Failed to update status. Check OTP or transition rules."
                )
            );
        }
    };

    // react-hook-form only flips isSubmitting after a re-render; the single-flight
    // ref drops a second Enter / click that lands before it.
    const onSubmit = (data: UpdateStatusFormValues) => runSubmit(() => submitStatus(data));

    return (
        <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
                <Button variant="default" data-testid="shipment-detail.actions.update-status">
                    <Truck className="mr-2 h-4 w-4" /> Update Status
                </Button>
            </DialogTrigger>

            <DialogContent className="sm:max-w-[460px]">
                <DialogHeader>
                    <DialogTitle>Update Shipment Status</DialogTitle>
                    <DialogDescription>
                        Advance the lifecycle of this shipment. This will be recorded in
                        the audit log.
                    </DialogDescription>
                </DialogHeader>

                <Form {...form}>
                    <form
                        onSubmit={form.handleSubmit(onSubmit)}
                        className="space-y-5 pt-3"
                    >
                        <FormField
                            control={form.control}
                            name="status"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>New Status</FormLabel>
                                    <FormControl>
                                        <IconSelect
                                            data-testid="update-status.form.status"
                                            options={filteredStatusOptions}
                                            value={field.value}
                                            onValueChange={field.onChange}
                                            placeholder="Select a status"
                                        />
                                    </FormControl>
                                    <FormDescription className="text-xs">
                                        Only moves the server accepts from the current status are listed.
                                        Delivered requires the consignee OTP; Exception requires an NDR reason.
                                    </FormDescription>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />

                        {watchedStatus === PickupStatus.RTO_INITIATED &&
                            currentStatus !== PickupStatus.RTO_INITIATED && (
                            <div
                                data-testid="update-status.rto-charge-warning"
                                className="flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-xs text-amber-950"
                            >
                                <Undo2 className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" />
                                <span>
                                    Starting a return (RTO) sends the parcel back to the seller and
                                    debits the RTO freight from the seller&apos;s wallet. The exact
                                    amount appears in the wallet ledger and on the order timeline.
                                </span>
                            </div>
                        )}

                        {watchedStatus === PickupStatus.RTO_DELIVERED &&
                            currentStatus !== PickupStatus.RTO_DELIVERED && (
                            <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4 space-y-3">
                                <div className="flex items-center gap-2 text-emerald-800 font-bold text-xs uppercase tracking-wider">
                                    <PackageCheck className="h-4 w-4 text-emerald-600" />
                                    Return handed over to the seller
                                </div>
                                <FormField
                                    control={form.control}
                                    name="pod_received_by"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel className="text-xs font-bold text-slate-700">
                                                Received By (at the seller&apos;s location)
                                                <RequiredMark />
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    {...field}
                                                    placeholder="e.g. Suresh (Warehouse manager)"
                                                    data-testid="update-status.form.rto-received-by"
                                                    className="bg-white"
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />
                            </div>
                        )}

                        {watchedStatus === PickupStatus.COMPLETED && (
                            <div className="rounded-xl border border-emerald-200 bg-emerald-50/70 p-4 space-y-4">
                                <div className="flex items-center gap-2 text-emerald-800 font-bold text-xs uppercase tracking-wider">
                                    <KeyRound className="h-4 w-4 text-emerald-600" />
                                    6-Digit OTP Proof of Delivery (POD)
                                </div>
                                <FormField
                                    control={form.control}
                                    name="delivery_otp"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel className="text-xs font-bold text-slate-700">
                                                6-Digit Delivery OTP
                                                <RequiredMark />
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    {...field}
                                                    maxLength={6}
                                                    placeholder="Enter 6-digit OTP from consignee"
                                                    className="bg-white font-mono tracking-widest text-base" data-testid="update-status.form.delivery-otp"
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />
                                <FormField
                                    control={form.control}
                                    name="pod_received_by"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel className="text-xs font-bold text-slate-700">
                                                Received By (Consignee or Security Name)
                                                <RequiredMark />
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    {...field}
                                                    placeholder="e.g. Rajesh Sharma (Warehouse Dock 2)" data-testid="update-status.form.pod-received-by"
                                                    className="bg-white"
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />
                            </div>
                        )}

                        {watchedStatus === PickupStatus.EXCEPTION && (
                            <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-4 space-y-3">
                                <div className="flex items-center gap-2 text-rose-800 font-bold text-xs uppercase tracking-wider">
                                    <ShieldAlert className="h-4 w-4 text-rose-600" />
                                    Exception / NDR Reason Required
                                </div>
                                <FormField
                                    control={form.control}
                                    name="ndr_reason"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel className="text-xs font-bold text-slate-700">
                                                Exception / NDR Reason
                                                <RequiredMark />
                                            </FormLabel>
                                            <FormControl>
                                                <div data-testid="update-status.form.ndr-reason">
                                                    <IconSelect
                                                        options={NDR_SELECT_OPTIONS}
                                                        value={field.value}
                                                        onValueChange={field.onChange}
                                                        placeholder="Choose NDR reason"
                                                    />
                                                </div>
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />

                                <FormField
                                    control={form.control}
                                    name="ndr_remark"
                                    render={({ field }) => (
                                        <FormItem>
                                            <FormLabel className="text-xs font-bold text-slate-700">
                                                Field / Courier Remark
                                            </FormLabel>
                                            <FormControl>
                                                <Input
                                                    name={field.name}
                                                    value={field.value ?? ""}
                                                    onChange={field.onChange}
                                                    onBlur={field.onBlur}
                                                    placeholder="e.g. Consignee requested delivery tomorrow afternoon"
                                                    className="bg-white text-xs"
                                                />
                                            </FormControl>
                                            <FormMessage />
                                        </FormItem>
                                    )}
                                />

                                {(watchedNdrReason ===
                                    NdrExceptionReason.FREIGHT_COLLECTION ||
                                    watchedNdrReason ===
                                        NdrExceptionReason.ADDITIONAL_CHARGES) && (
                                    <FormField
                                        control={form.control}
                                        name="charge_amount"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel className="text-xs font-bold text-slate-700">
                                                    {watchedNdrReason === NdrExceptionReason.FREIGHT_COLLECTION
                                                        ? "Freight to Collect (incl. GST)"
                                                        : "Additional Charge (excl. GST)"}
                                                    <RequiredMark />
                                                </FormLabel>
                                                <FormControl>
                                                    <InputAdornment prefix="₹">
                                                        <Input
                                                            type="number"
                                                            min="1"
                                                            step="0.01"
                                                            name={field.name}
                                                            value={field.value ?? ""}
                                                            onChange={field.onChange}
                                                            onBlur={field.onBlur}
                                                            placeholder="Enter INR charge amount"
                                                            className="bg-white font-mono text-xs"
                                                        />
                                                    </InputAdornment>
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />
                                )}

                                {watchedNdrReason ===
                                    NdrExceptionReason.WEIGHT_DISCREPANCY && (
                                    <FormField
                                        control={form.control}
                                        name="measured_weight_kg"
                                        render={({ field }) => (
                                            <FormItem>
                                                <FormLabel className="text-xs font-bold text-slate-700">
                                                    Hub Measured Scale Reading
                                                    <RequiredMark />
                                                </FormLabel>
                                                <FormControl>
                                                    <InputAdornment suffix="kg">
                                                        <Input
                                                            type="number"
                                                            min="0.1"
                                                            step="0.1"
                                                            name={field.name}
                                                            value={field.value ?? ""}
                                                            onChange={field.onChange}
                                                            onBlur={field.onBlur}
                                                            placeholder="Enter measured scale value"
                                                            className="bg-white font-mono text-xs"
                                                        />
                                                    </InputAdornment>
                                                </FormControl>
                                                <FormMessage />
                                            </FormItem>
                                        )}
                                    />
                                )}
                            </div>
                        )}

                        <FormField
                            control={form.control}
                            name="comment"
                            render={({ field }) => (
                                <FormItem>
                                    <FormLabel>Update Comment</FormLabel>
                                    <FormControl>
                                        <Textarea
                                            placeholder="e.g., Driver verified 6-digit OTP and completed delivery."
                                            className="resize-none" data-testid="update-status.form.comment"
                                            {...field}
                                        />
                                    </FormControl>
                                    <FormMessage />
                                </FormItem>
                            )}
                        />

                        <FormField
                            control={form.control}
                            name="is_public"
                            render={({ field }) => (
                                <FormItem className="flex flex-row items-start space-x-3 space-y-0 rounded-md border p-4">
                                    <FormControl>
                                        <input
                                            type="checkbox"
                                            className="h-4 w-4 mt-0.5" data-testid="update-status.form.is-public"
                                            checked={field.value}
                                            onChange={field.onChange}
                                        />
                                    </FormControl>
                                    <div className="space-y-1 leading-none">
                                        <FormLabel>Make Public</FormLabel>
                                        <FormDescription>
                                            Allow the customer to see this update on the tracking
                                            page.
                                        </FormDescription>
                                    </div>
                                </FormItem>
                            )}
                        />

                        <div className="flex justify-end gap-3">
                            <Button
                                type="button"
                                variant="outline"
                                onClick={() => setOpen(false)}
                            >
                                Cancel
                            </Button>
                            <Button type="submit" disabled={isSubmitting} data-testid="update-status.actions.submit">
                                {isSubmitting ? (
                                    <>
                                        <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Saving…
                                    </>
                                ) : (
                                    "Save Update"
                                )}
                            </Button>
                        </div>
                    </form>
                </Form>
            </DialogContent>
        </Dialog>
    );
}