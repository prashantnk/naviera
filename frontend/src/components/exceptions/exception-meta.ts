// frontend/src/components/exceptions/exception-meta.ts
/**
 * Presentation-only metadata for the Delivery Exceptions / NDR screens.
 *
 * Nothing here decides *whether* an action is allowed: permissions come from
 * each row's server-computed `allowed_actions` (single source of truth in
 * `backend/app/services/ndr_rules.py`). This module only maps enum members to
 * labels, icons, tones and help copy, like a Spring `messages.properties`.
 */
import {
  AlarmClockOff,
  AlertOctagon,
  Banknote,
  CalendarCheck,
  CalendarClock,
  CalendarSync,
  CheckCheck,
  CreditCard,
  FileUp,
  FileWarning,
  FileX,
  Hand,
  ListChecks,
  MapPinOff,
  PackageCheck,
  PackageMinus,
  PackageOpen,
  PackageX,
  PauseCircle,
  Receipt,
  RotateCcw,
  Scale,
  ScaleIcon,
  Truck,
  Undo2,
  UserPen,
  XCircle,
} from "lucide-react";

import { ExceptionCategory, NdrAction, ServiceFlow } from "@/api_client";
import type { OptionMeta, SelectOption } from "@/lib/form-options";

/** Bulk endpoint limit (mirrors `MAX_BULK_ACTION_SHIPMENTS`; the server re-validates). */
export const MAX_BULK_SELECTION = 200;

/** Server page size for the exceptions grid. */
export const EXCEPTIONS_PAGE_SIZE = 20;

/** Debounce for the AWB / Order ID search box. */
export const SEARCH_DEBOUNCE_MS = 400;

/**
 * Actions the `/exceptions/bulk-action` endpoint accepts (API capability, not a
 * permission: every row is still validated against the matrix server-side).
 */
export const BULK_ENDPOINT_ACTIONS: ReadonlySet<NdrAction> = new Set([
  NdrAction.REATTEMPT,
  NdrAction.RETURN_TO_ORIGIN,
  NdrAction.RESCHEDULE_PICKUP,
  NdrAction.CANCEL_PICKUP,
]);

/**
 * Actions offered in the multi-select bar. BOOK_APPOINTMENT needs a slot, so it
 * is fanned out as one `/actions` call per shipment with the same payload.
 */
export const BULK_CAPABLE_ACTIONS: readonly NdrAction[] = [
  NdrAction.REATTEMPT,
  NdrAction.RETURN_TO_ORIGIN,
  NdrAction.BOOK_APPOINTMENT,
  NdrAction.RESCHEDULE_PICKUP,
  NdrAction.CANCEL_PICKUP,
];

/** Display metadata for every merchant action (exhaustive: tsc fails on new enum members). */
export const NDR_ACTION_META: Readonly<Record<NdrAction, OptionMeta>> = {
  [NdrAction.REATTEMPT]: {
    label: "Reattempt",
    description: "Ask the courier to try delivery again",
    icon: RotateCcw,
    tone: "sky",
  },
  [NdrAction.RETURN_TO_ORIGIN]: {
    label: "Return to origin",
    description: "Send the shipment back to you (RTO)",
    icon: Undo2,
    tone: "rose",
  },
  [NdrAction.UPDATE_CONSIGNEE]: {
    label: "Update consignee",
    description: "Correct phone or address (same pincode)",
    icon: UserPen,
    tone: "sky",
  },
  [NdrAction.UPDATE_PAYMENT_MODE]: {
    label: "Update payment mode",
    description: "Switch between COD and prepaid",
    icon: CreditCard,
    tone: "amber",
  },
  [NdrAction.UPDATE_EWAY_BILL]: {
    label: "Update e-way bill",
    description: "Add a valid 12-digit e-way bill",
    icon: FileWarning,
    tone: "amber",
  },
  [NdrAction.UPLOAD_DOCUMENT]: {
    label: "Upload document",
    description: "Share the missing paperwork",
    icon: FileUp,
    tone: "sky",
  },
  [NdrAction.BOOK_APPOINTMENT]: {
    label: "Book appointment",
    description: "Pick a delivery date and slot",
    icon: CalendarCheck,
    tone: "sky",
  },
  [NdrAction.DELIVER_WITHOUT_APPOINTMENT]: {
    label: "Deliver without appointment",
    description: "Authorise delivery without a slot",
    icon: Truck,
    tone: "neutral",
  },
  [NdrAction.PARTIAL_DELIVERY]: {
    label: "Partial delivery",
    description: "Deliver the boxes that arrived",
    icon: PackageMinus,
    tone: "amber",
  },
  [NdrAction.HOLD]: {
    label: "Hold for all boxes",
    description: "Wait until every box reaches the hub",
    icon: PauseCircle,
    tone: "neutral",
  },
  [NdrAction.REPACK_AND_DELIVER]: {
    label: "Repack & deliver",
    description: "Repack damaged boxes and deliver",
    icon: PackageOpen,
    tone: "sky",
  },
  [NdrAction.ACKNOWLEDGE_CHARGES]: {
    label: "Acknowledge charges",
    description: "Pay the charge from your wallet",
    icon: Banknote,
    tone: "amber",
  },
  [NdrAction.ACCEPT_WEIGHT]: {
    label: "Accept weight",
    description: "Accept the hub-measured weight",
    icon: CheckCheck,
    tone: "emerald",
  },
  [NdrAction.DISPUTE_WEIGHT]: {
    label: "Dispute weight",
    description: "Ask operations to re-check the weight",
    icon: Hand,
    tone: "rose",
  },
  [NdrAction.RESCHEDULE_PICKUP]: {
    label: "Reschedule pickup",
    description: "Pick a new pickup date",
    icon: CalendarSync,
    tone: "sky",
  },
  [NdrAction.CANCEL_PICKUP]: {
    label: "Cancel pickup",
    description: "Cancel this return pickup",
    icon: XCircle,
    tone: "rose",
  },
};

/** Category metadata plus the Delhivery-style "Learn more" explanation. */
export interface ExceptionCategoryMeta extends OptionMeta {
  /** Inline help shown in the "Learn more" popover. */
  help: string;
}

/** Display metadata for every exception bucket (B2C groups and B2B categories). */
export const EXCEPTION_CATEGORY_META: Readonly<Record<ExceptionCategory, ExceptionCategoryMeta>> = {
  [ExceptionCategory.SHIPMENT_EXCEPTIONS]: {
    label: "Shipment Exceptions",
    description: "Stuck in transit, needs your input",
    icon: AlertOctagon,
    tone: "amber",
    help: "Shipments held in transit because of damage, a missing e-way bill, incomplete consignee details or a payment dispute. Fix the detail or return the shipment.",
  },
  [ExceptionCategory.NDR]: {
    label: "NDR (Undelivered)",
    description: "Delivery attempted but not completed",
    icon: AlarmClockOff,
    tone: "rose",
    help: "The courier attempted delivery but could not complete it (refused, unavailable or rescheduled). Reattempt up to 3 times; after the 3rd failed attempt the shipment is returned to origin automatically.",
  },
  [ExceptionCategory.PICKUP_FAILED]: {
    label: "Pickup Failed (Reverse)",
    description: "Return pickup could not be completed",
    icon: Undo2,
    tone: "rose",
    help: "The return pickup from your customer failed. Reschedule up to 3 times or cancel the pickup; after the 3rd failure it is cancelled automatically.",
  },
  [ExceptionCategory.NON_ACTIONABLE]: {
    label: "Non-actionable",
    description: "Being handled by operations",
    icon: ListChecks,
    tone: "neutral",
    help: "No action is needed from you. Operations is handling these shipments, or you have already responded.",
  },
  [ExceptionCategory.PAYMENT_DISPUTE]: {
    label: "Payment Dispute",
    description: "Consignee disputes COD vs prepaid",
    icon: CreditCard,
    tone: "amber",
    help: "The consignee disputes the payment mode. Update the payment mode, or reattempt with the same details.",
  },
  [ExceptionCategory.DAMAGES]: {
    label: "Damages",
    description: "Boxes damaged in transit",
    icon: PackageX,
    tone: "rose",
    help: "One or more boxes were damaged in transit. Review the photos, then return all boxes or ask the hub to repack and deliver.",
  },
  [ExceptionCategory.EWAY_BILL]: {
    label: "E-Way Bill",
    description: "E-way bill missing or expired",
    icon: FileX,
    tone: "amber",
    help: "The e-way bill is missing or has expired, so the vehicle cannot move. Update the 12-digit e-way bill and invoice number.",
  },
  [ExceptionCategory.CONSIGNEE_DETAILS]: {
    label: "Consignee Details",
    description: "Phone or address incomplete",
    icon: MapPinOff,
    tone: "amber",
    help: "The consignee phone or address is incomplete. Edit the details (same pincode only) or reattempt with the same details.",
  },
  [ExceptionCategory.DOCUMENT_NEEDED]: {
    label: "Document Needed",
    description: "Paperwork required to proceed",
    icon: FileWarning,
    tone: "amber",
    help: "A document is needed before delivery (for example an invoice, PO copy or declaration). Choose the document type and upload the file.",
  },
  [ExceptionCategory.SHORT_SHIPMENTS]: {
    label: "Short Shipments",
    description: "Not all boxes reached the hub",
    icon: PackageMinus,
    tone: "rose",
    help: "Only some boxes reached the destination hub. Attempt a partial delivery now, or hold until all boxes arrive.",
  },
  [ExceptionCategory.APPOINTMENT_NEEDED]: {
    label: "Appointment Needed",
    description: "Consignee requires a delivery slot",
    icon: CalendarClock,
    tone: "amber",
    help: "The consignee accepts deliveries only with an appointment. Book a date and slot (in bulk if needed), or authorise delivery without one. Book tomorrow's appointments before 6:00 PM today.",
  },
  [ExceptionCategory.FREIGHT_COLLECTION]: {
    label: "Freight Collection",
    description: "Pending freight must be cleared",
    icon: Banknote,
    tone: "amber",
    help: "Freight is pending on this shipment. Acknowledging clears it by debiting your wallet for the amount shown.",
  },
  [ExceptionCategory.ADDITIONAL_CHARGES]: {
    label: "Additional Charges",
    description: "Extra charges need acknowledgement",
    icon: Receipt,
    tone: "amber",
    help: "Extra charges were incurred at delivery (for example Mathadi or union charges). Acknowledging debits your wallet for the amount shown.",
  },
  [ExceptionCategory.MEASURED_WEIGHT]: {
    label: "Acknowledge Measured Weight",
    description: "Hub weight differs from declared",
    icon: Scale,
    tone: "amber",
    help: "The hub-measured weight differs from the declared weight. Accept it (you are re-billed for the difference) or dispute it for a re-check.",
  },
};

/** Delhivery Domestic tab order for B2C. */
export const B2C_CATEGORY_ORDER: readonly ExceptionCategory[] = [
  ExceptionCategory.SHIPMENT_EXCEPTIONS,
  ExceptionCategory.NDR,
  ExceptionCategory.PICKUP_FAILED,
  ExceptionCategory.NON_ACTIONABLE,
];

/** Delhivery Cargo left-menu order for B2B (11 "on hold" categories). */
export const B2B_CATEGORY_ORDER: readonly ExceptionCategory[] = [
  ExceptionCategory.PAYMENT_DISPUTE,
  ExceptionCategory.DAMAGES,
  ExceptionCategory.EWAY_BILL,
  ExceptionCategory.CONSIGNEE_DETAILS,
  ExceptionCategory.DOCUMENT_NEEDED,
  ExceptionCategory.SHORT_SHIPMENTS,
  ExceptionCategory.NDR,
  ExceptionCategory.APPOINTMENT_NEEDED,
  ExceptionCategory.FREIGHT_COLLECTION,
  ExceptionCategory.ADDITIONAL_CHARGES,
  ExceptionCategory.MEASURED_WEIGHT,
];

/** Category order per flow. */
export const CATEGORY_ORDER_BY_FLOW: Readonly<Record<ServiceFlow, readonly ExceptionCategory[]>> = {
  [ServiceFlow.B2C]: B2C_CATEGORY_ORDER,
  [ServiceFlow.B2B]: B2B_CATEGORY_ORDER,
};

/** Category options (icon + label) for the mobile category picker. */
export function categoryOptions(
  order: readonly ExceptionCategory[],
): SelectOption<ExceptionCategory>[] {
  return order.map((value) => Object.assign({ value }, EXCEPTION_CATEGORY_META[value]));
}

/** Rupee formatter for server-provided amounts (display only, never arithmetic). */
const INR_FORMATTER = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/**
 * Formats a backend amount for display.
 *
 * @param amount - Amount from the API (may be null).
 * @returns e.g. "₹50.00", or an em dash when absent.
 */
export function formatInr(amount: number | null | undefined): string {
  if (amount === null || amount === undefined || Number.isNaN(amount)) {
    return "—";
  }
  return INR_FORMATTER.format(amount);
}

/** Unused-icon guard: keeps the weight icon alias tree-shakable without lint noise. */
export const WEIGHT_ICON = ScaleIcon;

/** Icon for "received at hub" style confirmations. */
export const RESOLVED_ICON = PackageCheck;

/**
 * Actions that cost the shipper money or change what the rider collects. Decision D30 /
 * A-22 / backend `ndr_rules.CONSENT_ACTIONS`: only the shipper (customer) or Owner / Admin
 * may perform them, so operations / support staff never see them.
 */
export const WALLET_DEBIT_ACTIONS: readonly NdrAction[] = [
  NdrAction.ACKNOWLEDGE_CHARGES,
  NdrAction.ACCEPT_WEIGHT,
  NdrAction.RETURN_TO_ORIGIN,
  NdrAction.UPDATE_PAYMENT_MODE,
];

/** What the viewer may do, from `useUser().capabilities`. */
export interface ExceptionViewerRights {
  /** False for the read-only user: every action is refused by the API (403). */
  canWrite: boolean;
  /** True for customers and Owner / Admin staff (wallet-debit consent). */
  canAcceptCharges: boolean;
}

/**
 * Narrows a row's server `allowed_actions` to the ones this viewer may click.
 *
 * The server list says what the shipment allows; the role rules mirror
 * `assert_not_read_only` and the D30 consent rule, so no button ends in a 403.
 *
 * @param actions - The row's `allowed_actions`.
 * @param rights - The viewer's rights.
 * @returns The actions to render (empty for the read-only user).
 */
export function visibleExceptionActions(
  actions: readonly NdrAction[] | null | undefined,
  rights: ExceptionViewerRights,
): NdrAction[] {
  if (!rights.canWrite) return [];
  const all = (actions ?? []).slice();
  if (rights.canAcceptCharges) return all;
  return all.filter((action) => !WALLET_DEBIT_ACTIONS.includes(action));
}
