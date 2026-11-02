// frontend/src/components/exceptions/exception-action-dialogs.tsx
"use client";

import { useEffect, useState } from "react";
import { format, addDays } from "date-fns";
import {
  Calendar,
  CheckCircle2,
  FileUp,
  Info,
  Loader2,
  MapPin,
  ShieldAlert,
  Wallet,
} from "lucide-react";
import { toast } from "sonner";

import {
  DocumentType,
  ExceptionPaymentMode,
  ExceptionsService,
  NdrAction,
  PickupTimeSlot,
} from "@/api_client";
import type {
  ExceptionRow,
  NdrActionRequest,
  PickupUpdate,
} from "@/api_client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { InputAdornment, RequiredMark } from "@/components/ui/form-extras";
import { IconSelect } from "@/components/ui/icon-select";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  DOCUMENT_TYPE_OPTIONS,
  OPTION_TONE_CLASSES,
  PICKUP_TIME_SLOT_OPTIONS,
  toOptions,
  type SelectOption,
} from "@/lib/form-options";
import { getSupabaseClient } from "@/lib/supabase";
import { useUser } from "@/components/auth/auth-guard";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import { RepricePreviewPanel } from "@/components/shipments/reprice-preview-panel";
import { useRepricePreview } from "@/components/shipments/use-reprice-preview";
import { formatInr, NDR_ACTION_META } from "./exception-meta";

const DOCUMENT_SELECT_OPTIONS = toOptions(DOCUMENT_TYPE_OPTIONS);
const TIME_SLOT_SELECT_OPTIONS = toOptions(PICKUP_TIME_SLOT_OPTIONS);

const MAX_UPLOAD_BYTES = 5242880;
const EWAY_BILL_REGEX = /^\d{12}$/;
const PHONE_REGEX = /^\+?[0-9 ]{10,15}$/;

const PAYMENT_MODE_SELECT_OPTIONS: readonly SelectOption<ExceptionPaymentMode>[] = [
  {
    value: ExceptionPaymentMode.PREPAID,
    label: "Prepaid (No doorstep collection)",
    description: "Release for delivery without collecting cash from consignee",
    icon: CheckCircle2,
    tone: "emerald",
  },
  {
    value: ExceptionPaymentMode.COD,
    label: "Cash on Delivery (COD)",
    description: "Collect invoice value from consignee upon delivery",
    icon: Wallet,
    tone: "amber",
  },
];

const SIMPLE_CONFIRM_ACTIONS: ReadonlySet<NdrAction> = new Set([
  NdrAction.REATTEMPT,
  NdrAction.RETURN_TO_ORIGIN,
  NdrAction.DELIVER_WITHOUT_APPOINTMENT,
  NdrAction.HOLD,
  NdrAction.REPACK_AND_DELIVER,
  NdrAction.CANCEL_PICKUP,
]);

export type ExtendedExceptionRow = ExceptionRow & {
  applied_weight?: number | null;
  measured_weight_kg?: number | null;
};

export interface ExceptionActionDialogProps {
  open: boolean;
  action: NdrAction | null;
  row: ExtendedExceptionRow | null;
  bulkShipmentIds?: string[];
  tenantSlug: string;
  onOpenChange: (open: boolean) => void;
  onSuccess: () => void;
}

const TEST_ID = "exception-action";

/**
 * Parses an optional numeric text input (empty means "not provided").
 *
 * @param raw - Input text.
 * @returns The number, or null when empty / not a number.
 */
function _optionalNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * The equivalent shipment change whose server preview shows the backend delta for the
 * Payment Dispute and Partial Delivery actions (both run through the RepricingService).
 *
 * @param action - Selected NDR action.
 * @param paymentMode - Payment mode chosen in the Payment Dispute form.
 * @param revisedCod - Revised COD typed in the Partial Delivery form.
 * @returns PickupUpdate to preview, or null when there is nothing to preview.
 */
function _previewChangeFor(
  action: NdrAction | null,
  paymentMode: ExceptionPaymentMode,
  revisedCod: number | null,
): PickupUpdate | null {
  if (action === NdrAction.UPDATE_PAYMENT_MODE) {
    return { payment_details: { is_cod: paymentMode === ExceptionPaymentMode.COD } };
  }
  if (action === NdrAction.PARTIAL_DELIVERY && revisedCod !== null) {
    return { payment_details: { cod_amount: revisedCod } };
  }
  return null;
}

function _todayIso(): string {
  return format(new Date(), "yyyy-MM-dd");
}

function _tomorrowIso(): string {
  return format(addDays(new Date(), 1), "yyyy-MM-dd");
}

function _slotToIsoWindow(dateStr: string, slot: PickupTimeSlot): {
  startIso: string;
  endIso: string;
} {
  const parts = slot.split(" - ");
  const startClock = parts[0] || "10:00";
  const endClock = parts[1] || "14:00";
  const startIso = new Date(`${dateStr}T${startClock}:00`).toISOString();
  const endIso = new Date(`${dateStr}T${endClock}:00`).toISOString();
  return { startIso, endIso };
}

export function ExceptionActionDialog({
  open,
  action,
  row,
  bulkShipmentIds,
  tenantSlug,
  onOpenChange,
  onSuccess,
}: ExceptionActionDialogProps) {
  const [submitting, setSubmitting] = useState(false);
  const [uploadingFile, setUploadingFile] = useState(false);

  // Shared comment field
  const [comment, setComment] = useState("");

  // UPDATE_CONSIGNEE fields
  const [consigneeName, setConsigneeName] = useState("");
  const [consigneePhone, setConsigneePhone] = useState("");
  const [addressLine1, setAddressLine1] = useState("");
  const [addressLine2, setAddressLine2] = useState("");
  const [landmark, setLandmark] = useState("");

  // UPDATE_PAYMENT_MODE fields
  const [paymentMode, setPaymentMode] = useState<ExceptionPaymentMode>(
    ExceptionPaymentMode.PREPAID,
  );

  // UPDATE_EWAY_BILL fields
  const [ewayBillNumber, setEwayBillNumber] = useState("");
  const [invoiceNumber, setInvoiceNumber] = useState("");

  // UPLOAD_DOCUMENT fields
  const [documentType, setDocumentType] = useState<DocumentType>(
    DocumentType.GST_INVOICE,
  );
  const [documentUrl, setDocumentUrl] = useState("");
  const [documentName, setDocumentName] = useState("");

  // BOOK_APPOINTMENT & RESCHEDULE_PICKUP fields
  const [selectedDate, setSelectedDate] = useState(_tomorrowIso());
  const [selectedSlot, setSelectedSlot] = useState<PickupTimeSlot>(
    PickupTimeSlot._10_00_14_00,
  );
  const [appointmentId, setAppointmentId] = useState("");

  // PARTIAL_DELIVERY fields (B6): boxes actually delivered and an optional revised COD
  const [deliveredBoxesInput, setDeliveredBoxesInput] = useState("");
  const [revisedCodInput, setRevisedCodInput] = useState("");

  // RETURN_TO_ORIGIN (A-09): staff-only "Logismart liable" waiver of the RTO charge
  const { capabilities } = useUser();
  const [logismartLiable, setLogismartLiable] = useState(false);
  const canWaiveRto = capabilities.isStaff && Boolean(row?.logismart_liable_allowed);

  // Backend delta for Payment Dispute / Partial Delivery (display only, B14)
  const previewChange = _previewChangeFor(action, paymentMode, _optionalNumber(revisedCodInput));
  const repricePreview = useRepricePreview(row?.shipment_id, previewChange, tenantSlug, {
    enabled: open && row !== null,
  });
  const previewBlocksSubmit =
    previewChange !== null &&
    (repricePreview.loading || (repricePreview.preview?.rejected_fields.length ?? 0) > 0);

  useEffect(() => {
    if (!open) return;
    setComment("");
    setLogismartLiable(false);
    setConsigneeName(row?.consignee.name ?? "");
    setConsigneePhone(row?.consignee.phone ?? "");
    setAddressLine1(row?.consignee.address_line1 ?? "");
    setAddressLine2(row?.consignee.address_line2 ?? "");
    setLandmark(row?.consignee.landmark ?? "");
    setPaymentMode(
      row?.payment_mode === ExceptionPaymentMode.COD
        ? ExceptionPaymentMode.PREPAID
        : ExceptionPaymentMode.COD,
    );
    setEwayBillNumber("");
    setInvoiceNumber("");
    setDocumentType(DocumentType.GST_INVOICE);
    setDocumentUrl("");
    setDocumentName("");
    setSelectedDate(
      action === NdrAction.RESCHEDULE_PICKUP ? _todayIso() : _tomorrowIso(),
    );
    setSelectedSlot(PickupTimeSlot._10_00_14_00);
    setAppointmentId("");
    setDeliveredBoxesInput("");
    setRevisedCodInput("");
  }, [open, action, row]);

  if (!action) return null;

  const meta = NDR_ACTION_META[action];
  const ActionIcon = meta.icon;
  const isBulkAppointment =
    action === NdrAction.BOOK_APPOINTMENT &&
    Array.isArray(bulkShipmentIds) &&
    bulkShipmentIds.length > 0;
  const targetCount = isBulkAppointment ? bulkShipmentIds.length : 1;

  const handleFileSelection = async (
    event: React.ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      toast.error("File size must be under 5 MB.");
      return;
    }
    setUploadingFile(true);
    try {
      const supabase = getSupabaseClient(tenantSlug);
      const safeFileName = file.name.replace(/[^a-zA-Z0-9.-]/g, "_");
      const storagePath = [
        tenantSlug,
        `ndr_${Date.now()}_${safeFileName}`,
      ].join("/");
      const { error: uploadError } = await supabase.storage
        .from("documents")
        .upload(storagePath, file, { upsert: true });
      if (uploadError) throw uploadError;

      const publicData = supabase.storage
        .from("documents")
        .getPublicUrl(storagePath).data;
      const resolvedUrl = publicData?.publicUrl || "";
      setDocumentUrl(resolvedUrl);
      setDocumentName(file.name);
      toast.success(`Uploaded ${file.name}`);
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to upload document to storage."),
      );
    } finally {
      setUploadingFile(false);
    }
  };

  const handleSubmit = async () => {
    if (!isBulkAppointment && !row) return;

    if (action === NdrAction.UPDATE_CONSIGNEE && row) {
      const trimmedPhone = consigneePhone.trim();
      const trimmedLine1 = addressLine1.trim();
      if (!PHONE_REGEX.test(trimmedPhone)) {
        toast.error("Please enter a valid 10-digit consignee phone number.");
        return;
      }
      if (trimmedLine1.length < 3) {
        toast.error("Address line 1 must be at least 3 characters.");
        return;
      }
    }

    if (action === NdrAction.UPDATE_EWAY_BILL) {
      if (!EWAY_BILL_REGEX.test(ewayBillNumber.trim())) {
        toast.error("E-Way Bill number must be exactly 12 digits.");
        return;
      }
    }

    if (action === NdrAction.UPLOAD_DOCUMENT) {
      const trimmedUrl = documentUrl.trim();
      if (!trimmedUrl.startsWith("http://") && !trimmedUrl.startsWith("https://")) {
        toast.error("Please upload a file or provide a valid https:// document URL.");
        return;
      }
    }

    if (
      action === NdrAction.BOOK_APPOINTMENT ||
      action === NdrAction.RESCHEDULE_PICKUP
    ) {
      if (!selectedDate) {
        toast.error("Please choose a date.");
        return;
      }
    }

    if (action === NdrAction.PARTIAL_DELIVERY && row) {
      const delivered = _optionalNumber(deliveredBoxesInput);
      if (
        delivered !== null &&
        (!Number.isInteger(delivered) || delivered < 1 || delivered > row.box_count)
      ) {
        toast.error(`Delivered boxes must be a whole number from 1 to ${row.box_count}.`);
        return;
      }
      const revisedCod = _optionalNumber(revisedCodInput);
      if (revisedCodInput.trim() !== "" && (revisedCod === null || revisedCod < 0)) {
        toast.error("Revised COD amount must be zero or more.");
        return;
      }
    }

    if (action === NdrAction.DISPUTE_WEIGHT) {
      if (comment.trim().length < 5) {
        toast.error(
          "Please enter a remark explaining the dispute (at least 5 characters).",
        );
        return;
      }
    }

    setSubmitting(true);
    try {
      if (isBulkAppointment && bulkShipmentIds) {
        const { startIso, endIso } = _slotToIsoWindow(selectedDate, selectedSlot);
        const noteParts = [
          appointmentId.trim() ? `Appointment ID: ${appointmentId.trim()}` : "",
          comment.trim(),
        ].filter(Boolean);
        const payload: NdrActionRequest = {
          action: NdrAction.BOOK_APPOINTMENT,
          appointment_start: startIso,
          appointment_end: endIso,
          notes: noteParts.length > 0 ? noteParts.join(" | ") : null,
        };
        let successCount = 0;
        let failCount = 0;
        for (const id of bulkShipmentIds) {
          try {
            await ExceptionsService.applyExceptionAction(id, payload, tenantSlug);
            successCount += 1;
          } catch {
            failCount += 1;
          }
        }
        if (successCount > 0) {
          toast.success(
            `Booked appointment for ${successCount} shipment(s).`,
          );
        }
        if (failCount > 0) {
          toast.error(
            `${failCount} shipment(s) could not be updated for appointment booking.`,
          );
        }
        onOpenChange(false);
        onSuccess();
        return;
      }

      if (!row) return;

      let payload: NdrActionRequest = {
        action,
        notes: comment.trim() || null,
      };

      if (action === NdrAction.REATTEMPT && selectedDate) {
        payload = Object.assign({}, payload, {
          preferred_date: selectedDate,
        });
      } else if (action === NdrAction.RETURN_TO_ORIGIN && logismartLiable) {
        payload = Object.assign({}, payload, { logismart_liable: true });
      } else if (action === NdrAction.PARTIAL_DELIVERY) {
        payload = {
          action: NdrAction.PARTIAL_DELIVERY,
          delivered_box_count: _optionalNumber(deliveredBoxesInput),
          revised_cod_amount: _optionalNumber(revisedCodInput),
          notes: comment.trim() || null,
        };
      } else if (action === NdrAction.UPDATE_CONSIGNEE) {
        const newName = consigneeName.trim();
        payload = {
          action: NdrAction.UPDATE_CONSIGNEE,
          consignee_name: newName && newName !== row.consignee.name ? newName : null,
          consignee_phone: consigneePhone.trim(),
          consignee_address_line1: addressLine1.trim(),
          consignee_address_line2: addressLine2.trim() || null,
          landmark: landmark.trim() || null,
          consignee_pincode: row.consignee.pincode,
          notes: comment.trim() || null,
        };
      } else if (action === NdrAction.UPDATE_PAYMENT_MODE) {
        payload = {
          action: NdrAction.UPDATE_PAYMENT_MODE,
          is_cod: paymentMode === ExceptionPaymentMode.COD,
          notes: comment.trim() || null,
        };
      } else if (action === NdrAction.UPDATE_EWAY_BILL) {
        payload = {
          action: NdrAction.UPDATE_EWAY_BILL,
          eway_bill_number: ewayBillNumber.trim(),
          invoice_number: invoiceNumber.trim() || null,
          notes: comment.trim() || null,
        };
      } else if (action === NdrAction.UPLOAD_DOCUMENT) {
        const docNote = [
          documentName ? `File: ${documentName}` : "",
          comment.trim(),
        ]
          .filter(Boolean)
          .join(" · ");
        payload = {
          action: NdrAction.UPLOAD_DOCUMENT,
          document_type: documentType,
          document_url: documentUrl.trim(),
          notes: docNote || null,
        };
      } else if (action === NdrAction.BOOK_APPOINTMENT) {
        const { startIso, endIso } = _slotToIsoWindow(selectedDate, selectedSlot);
        const noteParts = [
          appointmentId.trim() ? `Appointment ID: ${appointmentId.trim()}` : "",
          comment.trim(),
        ].filter(Boolean);
        payload = {
          action: NdrAction.BOOK_APPOINTMENT,
          appointment_start: startIso,
          appointment_end: endIso,
          notes: noteParts.length > 0 ? noteParts.join(" · ") : null,
        };
      } else if (action === NdrAction.RESCHEDULE_PICKUP) {
        const slotMeta = PICKUP_TIME_SLOT_OPTIONS[selectedSlot];
        const noteParts = [
          slotMeta ? `Preferred slot: ${slotMeta.label}` : "",
          comment.trim(),
        ].filter(Boolean);
        payload = {
          action: NdrAction.RESCHEDULE_PICKUP,
          preferred_date: selectedDate,
          notes: noteParts.length > 0 ? noteParts.join(" · ") : null,
        };
      }

      await ExceptionsService.applyExceptionAction(
        row.shipment_id,
        payload,
        tenantSlug,
      );

      if (
        action === NdrAction.ACKNOWLEDGE_CHARGES ||
        action === NdrAction.ACCEPT_WEIGHT ||
        action === NdrAction.CANCEL_PICKUP ||
        action === NdrAction.UPDATE_PAYMENT_MODE ||
        action === NdrAction.PARTIAL_DELIVERY
      ) {
        window.dispatchEvent(new CustomEvent("wallet-updated"));
      }

      toast.success(`${meta.label} submitted for ${row.tracking_id || "shipment"}.`);
      onOpenChange(false);
      onSuccess();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, `Failed to perform ${meta.label.toLowerCase()}.`),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const isDestructive =
    action === NdrAction.RETURN_TO_ORIGIN ||
    action === NdrAction.CANCEL_PICKUP ||
    action === NdrAction.DISPUTE_WEIGHT;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid={`${TEST_ID}.dialog`} className="max-h-[90vh] overflow-y-auto overflow-x-hidden sm:max-w-[500px]">
        <DialogHeader className="min-w-0">
          <div className="flex items-center gap-2.5 min-w-0">
            <span
              className={cn(
                "inline-flex size-8 shrink-0 items-center justify-center rounded-lg",
                OPTION_TONE_CLASSES[meta.tone],
              )}
            >
              <ActionIcon className="size-4" />
            </span>
            <div className="min-w-0">
              <DialogTitle className="text-base font-bold text-slate-900">
                {meta.label}
                {isBulkAppointment ? ` (${targetCount} Shipments)` : ""}
              </DialogTitle>
              <DialogDescription className="text-xs text-slate-500">
                {row && !isBulkAppointment
                  ? `AWB / LRN: ${row.tracking_id || row.shipment_id}`
                  : meta.description}
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <div className="min-w-0 space-y-4 py-2">
          {/* 1. Simple confirmation actions */}
          {SIMPLE_CONFIRM_ACTIONS.has(action) && row && (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700 space-y-1">
                <p className="font-semibold text-slate-900">{meta.description}</p>
                {action === NdrAction.REATTEMPT && (
                  <p className="text-slate-600">
                    Current delivery attempts: {row.attempts} of {row.max_attempts}. After{" "}
                    {row.max_attempts} failed attempts, the shipment automatically returns to
                    origin (RTO).
                  </p>
                )}
                {action === NdrAction.RETURN_TO_ORIGIN && (
                  <p className="text-rose-700 font-medium">
                    This will immediately initiate Return to Origin (RTO) for this shipment.
                    The return freight is charged to the shipper&apos;s wallet.
                  </p>
                )}
                {action === NdrAction.RETURN_TO_ORIGIN && canWaiveRto && (
                  <label
                    className="mt-2 flex cursor-pointer items-start gap-2 text-slate-700"
                    data-testid={`${TEST_ID}.logismart-liable`}
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5 h-4 w-4 accent-primary"
                      checked={logismartLiable}
                      onChange={(event) => setLogismartLiable(event.target.checked)}
                    />
                    <span>
                      Logismart is at fault (damaged / short in our custody): waive the RTO
                      charge for the shipper.
                    </span>
                  </label>
                )}
                {action === NdrAction.CANCEL_PICKUP && (
                  <p className="text-rose-700 font-medium">
                    This cancels the return pickup and refunds any prepaid wallet balance.
                  </p>
                )}
                {action === NdrAction.HOLD && (
                  <p className="text-slate-600">
                    The shipment will remain on hold at the destination hub while operations
                    waits for all boxes to arrive.
                  </p>
                )}
              </div>

              {action === NdrAction.REATTEMPT && (
                <div className="space-y-1.5">
                  <Label htmlFor="reattempt-date" className="text-xs font-semibold">
                    Preferred Reattempt Date (Optional)
                  </Label>
                  <Input
                    id="reattempt-date"
                    type="date"
                    min={_todayIso()}
                    value={selectedDate}
                    onChange={(event) => setSelectedDate(event.target.value)}
                    className="h-9 bg-white text-xs"
                  />
                </div>
              )}

              <div className="space-y-1.5">
                <Label htmlFor="ndr-simple-comment" className="text-xs font-semibold">
                  Instructions / Remark (Optional)
                </Label>
                <Textarea
                  id="ndr-simple-comment"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Add delivery instructions or remarks for the field executive"
                  className="resize-none bg-white text-xs"
                  rows={3}
                />
              </div>
            </div>
          )}

          {/* 2. UPDATE_CONSIGNEE */}
          {action === NdrAction.UPDATE_CONSIGNEE && row && (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-lg border border-sky-200 bg-sky-50/70 p-3 text-xs text-sky-900">
                <MapPin className="mt-0.5 size-4 shrink-0 text-sky-700" />
                <div className="space-y-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">
                      Same-Pincode Rule:
                    </span>
                    <Badge
                      variant="outline"
                      className="border-sky-300 bg-white font-mono text-[11px] font-bold text-sky-900"
                    >
                      <span>
                        {row.consignee.pincode}
                      </span>
                    </Badge>
                    <span className="text-sky-700">
                      ({row.consignee.city}, {row.consignee.state})
                    </span>
                  </div>
                  <p className="text-[11px] text-sky-800 leading-relaxed">
                    Address corrections must stay within the same delivery pincode. For a
                    different pincode, return the shipment to origin and book a new order.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 min-w-0">
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="consignee-name" className="text-xs font-semibold">
                    Consignee Name
                  </Label>
                  <Input
                    id="consignee-name"
                    value={consigneeName}
                    onChange={(event) => setConsigneeName(event.target.value)}
                    className="min-w-0 w-full h-9 bg-white text-xs"
                  />
                </div>
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="consignee-phone" className="text-xs font-semibold">
                    Consignee Phone
                    <RequiredMark />
                  </Label>
                  <Input
                    id="consignee-phone"
                    value={consigneePhone}
                    maxLength={15}
                    onChange={(event) => setConsigneePhone(event.target.value)}
                    placeholder="10-digit mobile number"
                    className="min-w-0 w-full h-9 bg-white font-mono text-xs"
                  />
                </div>
              </div>

              <div className="min-w-0 space-y-1.5">
                <Label htmlFor="consignee-line1" className="text-xs font-semibold">
                  Address Line 1
                  <RequiredMark />
                </Label>
                <Input
                  id="consignee-line1"
                  value={addressLine1}
                  onChange={(event) => setAddressLine1(event.target.value)}
                  placeholder="Building, street, locality"
                  className="min-w-0 w-full h-9 bg-white text-xs"
                />
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 min-w-0">
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="consignee-line2" className="text-xs font-semibold">
                    Address Line 2 (Optional)
                  </Label>
                  <Input
                    id="consignee-line2"
                    value={addressLine2}
                    onChange={(event) => setAddressLine2(event.target.value)}
                    placeholder="Area or sector"
                    className="min-w-0 w-full h-9 bg-white text-xs"
                  />
                </div>
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="consignee-landmark" className="text-xs font-semibold">
                    Landmark (Optional)
                  </Label>
                  <Input
                    id="consignee-landmark"
                    value={landmark}
                    onChange={(event) => setLandmark(event.target.value)}
                    placeholder="Near landmark"
                    className="min-w-0 w-full h-9 bg-white text-xs"
                  />
                </div>
              </div>
            </div>
          )}

          {/* 3. UPDATE_PAYMENT_MODE */}
          {action === NdrAction.UPDATE_PAYMENT_MODE && row && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">
                  Doorstep Payment Mode
                  <RequiredMark />
                </Label>
                <IconSelect
                  aria-label="Doorstep payment mode"
                  options={PAYMENT_MODE_SELECT_OPTIONS}
                  value={paymentMode}
                  onValueChange={setPaymentMode}
                />
              </div>

              {paymentMode === ExceptionPaymentMode.COD && (
                <p data-testid="ndr-collect-note" className="text-[11px] text-slate-500">
                  The amount to collect at the door is set by Logismart from the shipment&apos;s
                  invoice value and shown on the order after you save.
                </p>
              )}

              <div className="space-y-1.5">
                <Label htmlFor="payment-comment" className="text-xs font-semibold">
                  Remark (Optional)
                </Label>
                <Textarea
                  id="payment-comment"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Optional note for the delivery hub"
                  className="resize-none bg-white text-xs"
                  rows={2}
                />
              </div>

              <RepricePreviewPanel
                preview={repricePreview.preview}
                loading={repricePreview.loading}
                error={repricePreview.error}
                testIdPrefix={`${TEST_ID}.preview`}
              />
            </div>
          )}

          {/* 3b. PARTIAL_DELIVERY (short shipment, B6) */}
          {action === NdrAction.PARTIAL_DELIVERY && row && (
            <div className="space-y-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-700">
                <p className="font-semibold text-slate-900">{meta.description}</p>
                <p className="mt-1 text-slate-600">
                  Booked boxes: {row.box_count}. Record how many were delivered. If the
                  consignee pays less for the short delivery, enter the revised COD amount.
                </p>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 min-w-0">
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="partial-delivered-boxes" className="text-xs font-semibold">
                    Boxes delivered (Optional)
                  </Label>
                  <Input
                    id="partial-delivered-boxes"
                    type="number"
                    inputMode="numeric"
                    min="1"
                    max={row.box_count}
                    step="1"
                    data-testid={`${TEST_ID}.form.delivered-boxes`}
                    value={deliveredBoxesInput}
                    onChange={(event) => setDeliveredBoxesInput(event.target.value)}
                    placeholder={`1 to ${row.box_count}`}
                    className="min-w-0 w-full h-9 bg-white font-mono text-xs"
                  />
                </div>
                {row.payment_mode === ExceptionPaymentMode.COD && (
                  <div className="min-w-0 space-y-1.5">
                    <Label htmlFor="partial-revised-cod" className="text-xs font-semibold">
                      Revised COD amount (Optional)
                    </Label>
                    <InputAdornment prefix="₹">
                      <Input
                        id="partial-revised-cod"
                        type="number"
                        inputMode="decimal"
                        min="0"
                        step="0.01"
                        data-testid={`${TEST_ID}.form.revised-cod`}
                        value={revisedCodInput}
                        onChange={(event) => setRevisedCodInput(event.target.value)}
                        placeholder={`Now ${formatInr(row.cod_amount)}`}
                        className="min-w-0 w-full h-9 bg-white font-mono text-xs"
                      />
                    </InputAdornment>
                  </div>
                )}
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="partial-comment" className="text-xs font-semibold">
                  Remark (Optional)
                </Label>
                <Textarea
                  id="partial-comment"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="e.g. 2 of 3 boxes delivered, 1 box held at hub"
                  className="resize-none bg-white text-xs"
                  rows={2}
                />
              </div>
              {previewChange !== null && (
                <RepricePreviewPanel
                  preview={repricePreview.preview}
                  loading={repricePreview.loading}
                  error={repricePreview.error}
                  testIdPrefix={`${TEST_ID}.preview`}
                />
              )}
            </div>
          )}

          {/* 4. UPDATE_EWAY_BILL */}
          {action === NdrAction.UPDATE_EWAY_BILL && row && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label htmlFor="eway-bill-input" className="text-xs font-semibold">
                  12-Digit E-Way Bill Number
                  <RequiredMark />
                </Label>
                <Input
                  id="eway-bill-input"
                  value={ewayBillNumber}
                  maxLength={12}
                  onChange={(event) =>
                    setEwayBillNumber(event.target.value.replace(/\D/g, ""))
                  }
                  placeholder="Enter 12-digit numeric EWB"
                  className="h-9 bg-white font-mono tracking-wider text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="eway-invoice-input" className="text-xs font-semibold">
                  Invoice Number (Optional)
                </Label>
                <Input
                  id="eway-invoice-input"
                  value={invoiceNumber}
                  onChange={(event) => setInvoiceNumber(event.target.value)}
                  placeholder="e.g. INV-2026-0042"
                  className="h-9 bg-white font-mono text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="eway-comment" className="text-xs font-semibold">
                  Remark (Optional)
                </Label>
                <Textarea
                  id="eway-comment"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Optional compliance remark"
                  className="resize-none bg-white text-xs"
                  rows={2}
                />
              </div>
            </div>
          )}

          {/* 5. UPLOAD_DOCUMENT */}
          {action === NdrAction.UPLOAD_DOCUMENT && row && (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">
                  Document Type
                  <RequiredMark />
                </Label>
                <IconSelect
                  aria-label="Document type"
                  options={DOCUMENT_SELECT_OPTIONS}
                  value={documentType}
                  onValueChange={setDocumentType}
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">
                  Upload File (PDF, PNG, JPG · Max 5 MB)
                </Label>
                <label className="flex cursor-pointer flex-col items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-slate-300 bg-slate-50 p-4 text-center transition-colors hover:border-primary hover:bg-primary/5">
                  <input
                    type="file"
                    accept=".pdf,.png,.jpg,.jpeg"
                    className="hidden"
                    disabled={uploadingFile}
                    onChange={handleFileSelection}
                  />
                  {uploadingFile ? (
                    <Loader2 className="size-6 animate-spin text-primary" />
                  ) : (
                    <FileUp className="size-6 text-slate-400" />
                  )}
                  <span className="text-xs font-semibold text-slate-700">
                    {uploadingFile
                      ? "Uploading to secure storage"
                      : documentName || "Click to choose a compliance document"}
                  </span>
                </label>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="doc-url-input" className="text-xs font-semibold">
                  Or Document URL (https://)
                  <RequiredMark />
                </Label>
                <Input
                  id="doc-url-input"
                  value={documentUrl}
                  onChange={(event) => setDocumentUrl(event.target.value)}
                  placeholder="https://storage.example.com/document.pdf"
                  className="h-9 bg-white font-mono text-xs"
                />
              </div>
            </div>
          )}

          {/* 6. BOOK_APPOINTMENT */}
          {action === NdrAction.BOOK_APPOINTMENT && (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/80 p-3 text-xs text-amber-900">
                <Info className="mt-0.5 size-4 shrink-0 text-amber-700" />
                <span>
                  Appointments for tomorrow must be booked before 6:00 PM today.
                </span>
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 min-w-0">
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="appointment-date" className="text-xs font-semibold">
                    Appointment Date
                    <RequiredMark />
                  </Label>
                  <Input
                    id="appointment-date"
                    type="date"
                    min={_tomorrowIso()}
                    value={selectedDate}
                    onChange={(event) => setSelectedDate(event.target.value)}
                    className="min-w-0 w-full h-9 bg-white text-xs"
                  />
                </div>
                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="appointment-id-input" className="text-xs font-semibold">
                    Appointment ID (optional, saved in the remark)
                  </Label>
                  <Input
                    id="appointment-id-input"
                    value={appointmentId}
                    onChange={(event) => setAppointmentId(event.target.value)}
                    placeholder="e.g. APT-90812"
                    className="min-w-0 w-full h-9 bg-white font-mono text-xs"
                  />
                </div>
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">
                  Time Slot
                  <RequiredMark />
                </Label>
                <IconSelect
                  aria-label="Appointment time slot"
                  options={TIME_SLOT_SELECT_OPTIONS}
                  value={selectedSlot}
                  onValueChange={setSelectedSlot}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="appointment-notes" className="text-xs font-semibold">
                  Dock / Gate Instructions (Optional)
                </Label>
                <Textarea
                  id="appointment-notes"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="e.g. Report to Gate 3 with PO copy"
                  className="resize-none bg-white text-xs"
                  rows={2}
                />
              </div>
            </div>
          )}

          {/* 7. ACKNOWLEDGE_CHARGES */}
          {action === NdrAction.ACKNOWLEDGE_CHARGES && row && (
            <div className="space-y-3">
              <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-amber-900">
                    Amount to be debited (incl. GST)
                  </span>
                  <span className="text-lg font-extrabold font-mono text-amber-950">
                    {formatInr(row.charge_amount_payable ?? row.charge_amount)}
                  </span>
                </div>
                <p className="text-xs text-amber-800 leading-relaxed">
                  Confirming will immediately debit{" "}
                  <strong className="font-semibold">
                    {formatInr(row.charge_amount_payable ?? row.charge_amount)}
                  </strong>{" "}
                  from your Unified Wallet, generate a GST ledger receipt, and release this
                  shipment for delivery.
                </p>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="charges-comment" className="text-xs font-semibold">
                  Approval Note (Optional)
                </Label>
                <Textarea
                  id="charges-comment"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Optional reference for your finance ledger"
                  className="resize-none bg-white text-xs"
                  rows={2}
                />
              </div>
            </div>
          )}

          {/* 8. Discrepancy actions */}
          {(action === NdrAction.ACCEPT_WEIGHT ||
            action === NdrAction.DISPUTE_WEIGHT) &&
            row && (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3.5 text-xs">
                  <div className="space-y-0.5">
                    <span className="text-[11px] font-semibold uppercase text-slate-500">
                      Declared
                    </span>
                    <p className="font-mono text-sm font-bold text-slate-900">
                      {row.applied_weight != null
                        ? `${row.applied_weight} kg`
                        : `${row.box_count} box(es)`}
                    </p>
                  </div>
                  <div className="space-y-0.5">
                    <span className="text-[11px] font-semibold uppercase text-slate-500">
                      Hub Measured / Delta
                    </span>
                    <p className="font-mono text-sm font-bold text-amber-800">
                      {row.measured_weight_kg != null
                        ? `${row.measured_weight_kg} kg`
                        : row.charge_amount != null
                          ? `${formatInr(row.charge_amount_payable ?? row.charge_amount)} incl. GST`
                          : "See remark"}
                    </p>
                  </div>
                </div>

                {action === NdrAction.ACCEPT_WEIGHT ? (
                  <div className="flex items-start gap-2 rounded-lg border border-emerald-200 bg-emerald-50/70 p-3 text-xs text-emerald-900">
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-emerald-700" />
                    <span>
                      Accepting the hub scale reading re-bills the difference from your
                      Unified Wallet and releases the shipment immediately.
                    </span>
                  </div>
                ) : (
                  <div className="flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50/70 p-3 text-xs text-rose-900">
                    <ShieldAlert className="mt-0.5 size-4 shrink-0 text-rose-700" />
                    <span>
                      Disputing sends this shipment to{" "}
                      <strong className="font-semibold">Awaiting operations</strong> while the
                      hub re-verifies the scale reading.
                    </span>
                  </div>
                )}

                <div className="space-y-1.5">
                  <Label htmlFor="scale-comment" className="text-xs font-semibold">
                    {action === NdrAction.DISPUTE_WEIGHT ? (
                      <>
                        Dispute Reason / Evidence
                        <RequiredMark />
                      </>
                    ) : (
                      "Remark (Optional)"
                    )}
                  </Label>
                  <Textarea
                    id="scale-comment"
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    placeholder={
                      action === NdrAction.DISPUTE_WEIGHT
                        ? "Share package dimensions or scale photo reference (min 5 chars)"
                        : "Optional note"
                    }
                    className="resize-none bg-white text-xs"
                    rows={3}
                  />
                </div>
              </div>
            )}

          {/* 9. RESCHEDULE_PICKUP */}
          {action === NdrAction.RESCHEDULE_PICKUP && row && (
            <div className="space-y-3">
              <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50/70 p-3 text-xs text-amber-900">
                <Calendar className="mt-0.5 size-4 shrink-0 text-amber-700" />
                <span>
                  Pickup attempts used: {row.attempts} of {row.max_attempts}. Up to{" "}
                  {row.max_attempts} reschedules are permitted before automatic cancellation.
                </span>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="reschedule-date" className="text-xs font-semibold">
                  New Pickup Date
                  <RequiredMark />
                </Label>
                <Input
                  id="reschedule-date"
                  type="date"
                  min={_todayIso()}
                  value={selectedDate}
                  onChange={(event) => setSelectedDate(event.target.value)}
                  className="h-9 bg-white text-xs"
                />
              </div>

              <div className="space-y-1.5">
                <Label className="text-xs font-semibold">
                  Preferred Pickup Slot (Optional)
                </Label>
                <IconSelect
                  aria-label="Preferred pickup time slot"
                  options={TIME_SLOT_SELECT_OPTIONS}
                  value={selectedSlot}
                  onValueChange={setSelectedSlot}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="reschedule-comment" className="text-xs font-semibold">
                  Pickup Instructions (Optional)
                </Label>
                <Textarea
                  id="reschedule-comment"
                  value={comment}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="e.g. Call customer 30 minutes prior to arrival"
                  className="resize-none bg-white text-xs"
                  rows={2}
                />
              </div>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={submitting || uploadingFile}
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            type="button"
            variant={isDestructive ? "destructive" : "default"}
            data-testid={`${TEST_ID}.actions.submit`}
            disabled={submitting || uploadingFile || previewBlocksSubmit}
            onClick={handleSubmit}
          >
            {submitting && <Loader2 className="mr-2 size-4 animate-spin" />}
            {meta.label}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
