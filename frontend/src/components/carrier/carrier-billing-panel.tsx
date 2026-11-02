// frontend/src/components/carrier/carrier-billing-panel.tsx
"use client";

/**
 * "Carrier booking" card for the ops desk and the shipment detail pages (pricing D7).
 *
 * - Staff who run operations (owner / admin / operations, `capabilities.canOperate`) see
 *   the booked service option, the Delhivery AWB, the charged weight / amount and an
 *   "Enter carrier booking" form.
 * - Other staff (support, read-only) see the same values without the form.
 * - Customers never call the staff-only endpoint; they get the read-only
 *   {@link CarrierInfo} line built from the `PickupRead` values passed in as props.
 *
 * The billing gap badge / alert is driven only by the backend's `has_gap`, `gap_amount`
 * and `gap_message` (Zero Frontend Math).
 *
 * Delhivery One parity: the courier + AWB block on the order detail page; the "gap" is
 * Logismart's own reconciliation of what Delhivery charged vs what the seller was billed.
 */
import { AlertTriangle, CheckCircle2, IndianRupee, Loader2, Pencil, Plus, RefreshCw, Truck } from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { toast } from "sonner";

import { ApiError, ServiceOption } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { formatInr, formatKg } from "@/components/shipments/shipment-money";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn, extractApiErrorMessage } from "@/lib/utils";

import {
  applyAdminShipmentCharge,
  fetchCarrierBilling,
  serviceOptionLabel,
  type CarrierBillingRead,
} from "./carrier-api";
import { CarrierBillingForm } from "./carrier-billing-form";
import { AWB_NOT_ASSIGNED_TEXT, CarrierInfo } from "./carrier-info";
import { DelhiveryCoordinationPlaybook } from "./delhivery-coordination-playbook";

/** Root `data-testid`; children append `.loading`, `.awb`, `.gap-badge`, `.edit`, … */
export const CARRIER_PANEL_TESTID = "carrier-billing";

/**
 * Statuses that mean "no carrier billing view for this user": 403 (role may not read it)
 * and 404 (endpoint not deployed yet). Both fall back to the read-only carrier line.
 */
const FALLBACK_STATUSES: readonly number[] = [403, 404];

export interface CarrierBillingPanelProps {
  shipmentId: string;
  tenantSlug?: string | null;
  /** `PickupRead.carrier_name`, shown to customers / staff without read access. */
  carrierName?: string | null;
  /** `PickupRead.carrier_awb`, shown to customers / staff without read access. */
  carrierAwb?: string | null;
  /** `PickupRead.service_option`, shown to customers / staff without read access. */
  serviceOption?: string | null;
  /** `PickupRead.status`, used to hide price overrides on cancelled shipments. */
  shipmentStatus?: string | null;
  /** Called after ops save a booking (e.g. to refetch the host page's shipment). */
  onSaved?: (billing: CarrierBillingRead) => void;
  className?: string;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; billing: CarrierBillingRead }
  | { kind: "unavailable" }
  | { kind: "error"; message: string };

/**
 * Loads the carrier billing view for staff; skipped entirely for customers.
 *
 * @param shipmentId - Shipment UUID.
 * @param tenantSlug - Tenant slug header.
 * @param enabled - False for customers (staff-only endpoint).
 * @returns The load state, a reload callback and a setter for a freshly saved value.
 */
function useCarrierBilling(shipmentId: string, tenantSlug: string | null | undefined, enabled: boolean) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });

  const reload = useCallback(async () => {
    if (!enabled) return;
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", billing: await fetchCarrierBilling(shipmentId, tenantSlug) });
    } catch (err) {
      if (err instanceof ApiError && FALLBACK_STATUSES.includes(err.status)) {
        setState({ kind: "unavailable" });
        return;
      }
      setState({ kind: "error", message: extractApiErrorMessage(err, "Could not load the carrier booking.") });
    }
  }, [enabled, shipmentId, tenantSlug]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const setSaved = useCallback((billing: CarrierBillingRead) => setState({ kind: "ready", billing }), []);
  return { state, reload, setSaved };
}

/** One label / value row inside the panel. */
function BillingField({ label, testId, children }: { label: string; testId: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-0.5">
      <p className="text-xs font-medium text-muted-foreground break-words">{label}</p>
      <p data-testid={testId} className="text-sm font-medium text-foreground break-words">
        {children}
      </p>
    </div>
  );
}

/**
 * Margin verdict from the backend: an amber alert on under-recovery (`has_gap`), a quiet
 * badge otherwise. Nothing is shown before an AWB exists (no carrier charge to compare yet).
 */
function GapVerdict({
  billing,
  canRecover,
  recovering,
  onRecoverGap,
}: {
  billing: CarrierBillingRead;
  canRecover?: boolean;
  recovering?: boolean;
  onRecoverGap?: () => void;
}) {
  if (billing.has_gap) {
    return (
      <div
        role="alert"
        data-testid={`${CARRIER_PANEL_TESTID}.gap-alert`}
        className="flex flex-col @[420px]:flex-row @[420px]:items-center justify-between gap-3 rounded-md border border-amber-300 bg-amber-50 p-3 text-sm text-amber-950 min-w-0 overflow-hidden"
      >
        <div className="flex items-start gap-2 min-w-0">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-700" aria-hidden="true" />
          <div className="min-w-0 space-y-1 break-words">
            <Badge
              variant="outline"
              data-testid={`${CARRIER_PANEL_TESTID}.gap-badge`}
              className="max-w-full whitespace-normal break-words border-amber-400 bg-amber-100 text-amber-900 h-auto py-0.5"
            >
              Negative margin
              {billing.gap_amount !== null && billing.gap_amount !== undefined && (
                <span data-testid={`${CARRIER_PANEL_TESTID}.gap-amount`}> {formatInr(billing.gap_amount)}</span>
              )}
            </Badge>
            {billing.gap_message && (
              <p data-testid={`${CARRIER_PANEL_TESTID}.gap-message`} className="break-words">{billing.gap_message}</p>
            )}
          </div>
        </div>
        {canRecover && onRecoverGap && (
          <Button
            type="button"
            size="sm"
            disabled={recovering}
            onClick={onRecoverGap}
            data-testid={`${CARRIER_PANEL_TESTID}.recover-gap`}
            className="h-auto min-h-8 max-w-full whitespace-normal bg-amber-800 py-1.5 text-center text-xs font-semibold text-white hover:bg-amber-900 @[420px]:w-auto"
          >
            {recovering ? (
              <Loader2 className="mr-1.5 h-3.5 w-3.5 shrink-0 animate-spin" />
            ) : (
              <IndianRupee className="mr-1 h-3.5 w-3.5 shrink-0" />
            )}
            <span className="break-words">
              Recover Difference from Customer
              {billing.gap_gross_amount ? ` (${formatInr(billing.gap_gross_amount)} incl. GST)` : ""}
            </span>
          </Button>
        )}
      </div>
    );
  }
  if (!billing.carrier_awb) return null;
  return (
    <Badge variant="outline" data-testid={`${CARRIER_PANEL_TESTID}.no-gap-badge`}>
      <CheckCircle2 aria-hidden="true" />
      No billing gap
    </Badge>
  );
}

/**
 * Who charges us for the parcel, for field labels: Logismart Prime runs on partner
 * transporters, every other option is booked on Delhivery.
 *
 * @param option - Booked service option.
 * @returns "Carrier" for Prime, otherwise "Delhivery".
 */
function carrierChargeLabel(option: ServiceOption): string {
  return option === ServiceOption.PRIME_SURFACE ? "Carrier" : "Delhivery";
}

/**
 * Formats the backend margin with its pre-GST basis, e.g. "₹20.00 (₹120.00 − ₹100.00)".
 *
 * @param billing - Carrier billing view.
 * @returns Display text, or an em dash before a carrier charge is entered.
 */
function marginText(billing: CarrierBillingRead): string {
  if (billing.margin_amount === null || billing.margin_amount === undefined) return "—";
  return `${formatInr(billing.margin_amount)} (${formatInr(billing.seller_billed_taxable)} − ${formatInr(
    billing.carrier_charged_taxable
  )})`;
}

/** Read-only values of a loaded carrier booking. */
function BillingValues({
  billing,
  canRecover,
  recovering,
  onRecoverGap,
}: {
  billing: CarrierBillingRead;
  canRecover?: boolean;
  recovering?: boolean;
  onRecoverGap?: () => void;
}) {
  const carrier = carrierChargeLabel(billing.service_option);
  return (
    <div className="min-w-0 space-y-3">
      <div className="grid grid-cols-1 gap-3 @[420px]:grid-cols-2">
        <BillingField label="Service option" testId={`${CARRIER_PANEL_TESTID}.service-option`}>
          {serviceOptionLabel(billing.service_option) ?? "—"}
        </BillingField>
        {billing.transporter_name && (
          <BillingField label="Transporter" testId={`${CARRIER_PANEL_TESTID}.transporter`}>
            {billing.transporter_name}
          </BillingField>
        )}
        <BillingField label="Carrier AWB" testId={`${CARRIER_PANEL_TESTID}.awb`}>
          {billing.carrier_awb ? (
            <span className="font-mono">{billing.carrier_awb}</span>
          ) : (
            <span className="italic font-normal text-muted-foreground">{AWB_NOT_ASSIGNED_TEXT}</span>
          )}
        </BillingField>
        <BillingField label={`${carrier} charged weight`} testId={`${CARRIER_PANEL_TESTID}.charged-weight`}>
          {formatKg(billing.charged_weight_kg)}
        </BillingField>
        <BillingField
          label={`${carrier} charged amount (incl. GST)`}
          testId={`${CARRIER_PANEL_TESTID}.charged-amount`}
        >
          {formatInr(billing.charged_amount)}
        </BillingField>
        <BillingField label="Billed to seller (incl. GST)" testId={`${CARRIER_PANEL_TESTID}.seller-billed`}>
          {formatInr(billing.seller_billed_amount)}
        </BillingField>
        <BillingField label="Margin (before GST)" testId={`${CARRIER_PANEL_TESTID}.margin`}>
          {marginText(billing)}
        </BillingField>
      </div>
      <GapVerdict
        billing={billing}
        canRecover={canRecover}
        recovering={recovering}
        onRecoverGap={onRecoverGap}
      />
    </div>
  );
}

/**
 * Renders the carrier booking card (see the module docstring for the role matrix).
 *
 * @param props - See {@link CarrierBillingPanelProps}.
 */
export function CarrierBillingPanel({
  shipmentId,
  tenantSlug,
  carrierName,
  carrierAwb,
  serviceOption,
  shipmentStatus,
  onSaved,
  className,
}: CarrierBillingPanelProps) {
  const { capabilities } = useUser();
  const { state, reload, setSaved } = useCarrierBilling(shipmentId, tenantSlug, capabilities.isStaff);
  const [editing, setEditing] = useState(false);
  const [addingCharge, setAddingCharge] = useState(false);
  const [chargeAmount, setChargeAmount] = useState("");
  const [chargeLabel, setChargeLabel] = useState("Carrier rate difference");
  const [submittingCharge, setSubmittingCharge] = useState(false);
  const fallback = (
    <CarrierInfo carrierName={carrierName} carrierAwb={carrierAwb} serviceOption={serviceOption} />
  );

  const handleSaved = (billing: CarrierBillingRead) => {
    setSaved(billing);
    setEditing(false);
    setAddingCharge(false);
    onSaved?.(billing);
  };

  const handleRecoverGap = async (billing: CarrierBillingRead) => {
    const useGross = billing.gap_gross_amount !== null && billing.gap_gross_amount !== undefined && billing.gap_gross_amount > 0;
    const rawAmount = useGross ? billing.gap_gross_amount : billing.gap_amount;
    if (!rawAmount || rawAmount <= 0) return;
    setSubmittingCharge(true);
    try {
      const updated = await applyAdminShipmentCharge(
        shipmentId,
        {
          amount: rawAmount,
          includes_gst: useGross,
          label: "Carrier rate difference recovery",
        },
        tenantSlug,
      );
      toast.success("Recovered carrier rate difference from customer wallet & issued GST Debit Note.");
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      handleSaved(updated);
    } catch (err) {
      toast.error(extractApiErrorMessage(err, "Failed to recover billing difference."));
    } finally {
      setSubmittingCharge(false);
    }
  };

  const handleSubmitAdminCharge = async (e: React.FormEvent) => {
    e.preventDefault();
    const parsedAmount = Number(chargeAmount);
    if (!Number.isFinite(parsedAmount) || parsedAmount <= 0) {
      toast.error("Enter a valid final price greater than ₹0.");
      return;
    }
    const trimmedLabel = chargeLabel.trim() || "Admin price override";
    setSubmittingCharge(true);
    try {
      const updated = await applyAdminShipmentCharge(
        shipmentId,
        {
          override_total_price: parsedAmount,
          label: trimmedLabel,
        },
        tenantSlug,
      );
      toast.success(
        `Shipment price updated to ${formatInr(parsedAmount)} — wallet settled & GST Credit/Debit Note issued.`,
      );
      window.dispatchEvent(new CustomEvent("wallet-updated"));
      setChargeAmount("");
      handleSaved(updated);
    } catch (err) {
      toast.error(extractApiErrorMessage(err, "Failed to override shipment price."));
    } finally {
      setSubmittingCharge(false);
    }
  };

  const openAddCharge = () => {
    if (state.kind === "ready" && state.billing.has_gap && state.billing.charged_amount) {
      setChargeAmount(String(state.billing.charged_amount));
      setChargeLabel("Carrier rate difference");
    } else if (state.kind === "ready" && state.billing.seller_billed_amount) {
      setChargeAmount(String(state.billing.seller_billed_amount));
      setChargeLabel("Admin price override");
    } else {
      setChargeAmount("");
      setChargeLabel("Admin price override");
    }
    setEditing(false);
    setAddingCharge(true);
  };

  const renderBody = () => {
    if (!capabilities.isStaff || state.kind === "unavailable") return fallback;
    if (state.kind === "loading") {
      return (
        <p data-testid={`${CARRIER_PANEL_TESTID}.loading`} className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading carrier booking…
        </p>
      );
    }
    if (state.kind === "error") {
      return (
        <div className="flex items-center justify-between gap-2">
          <p data-testid={`${CARRIER_PANEL_TESTID}.error`} className="text-sm text-destructive">
            {state.message}
          </p>
          <Button variant="outline" size="sm" onClick={() => void reload()} data-testid={`${CARRIER_PANEL_TESTID}.retry`}>
            <RefreshCw className="h-4 w-4" /> Retry
          </Button>
        </div>
      );
    }
    if (editing && capabilities.canOperate) {
      return (
        <CarrierBillingForm
          shipmentId={shipmentId}
          tenantSlug={tenantSlug}
          initial={state.billing}
          onSaved={handleSaved}
          onCancel={() => setEditing(false)}
        />
      );
    }
    return (
      <div className="min-w-0 space-y-4">
        {capabilities.canOperate && (
          <DelhiveryCoordinationPlaybook
            shipmentId={shipmentId}
            serviceOption={state.billing.service_option ?? serviceOption}
            carrierAwb={state.billing.carrier_awb}
            transporterName={state.billing.transporter_name}
          />
        )}
        <BillingValues
          billing={state.billing}
          canRecover={capabilities.canManageFinance}
          recovering={submittingCharge}
          onRecoverGap={() => void handleRecoverGap(state.billing)}
        />
        {addingCharge && capabilities.canManageFinance && (
          <form
            onSubmit={handleSubmitAdminCharge}
            data-testid={`${CARRIER_PANEL_TESTID}.add-charge.form`}
            className="min-w-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-50/70 p-3.5 space-y-3"
          >
            <div className="min-w-0 space-y-1.5">
              <div className="flex flex-wrap items-center justify-between gap-2 min-w-0">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-700 break-words">
                  Override / Adjust Shipment Price
                </p>
                <Badge
                  variant="outline"
                  data-testid={`${CARRIER_PANEL_TESTID}.add-charge.current-price`}
                  className="h-auto max-w-full whitespace-normal break-words bg-white border-slate-300 text-slate-800 font-mono text-xs py-0.5 text-left"
                >
                  Current Billed (incl. GST): {formatInr(state.billing.seller_billed_amount)}
                </Badge>
              </div>
              <p className="text-xs text-slate-500 break-words">
                If lower than current price, the difference is credited back to the customer&apos;s wallet with a GST Credit Note. If higher, it is debited with a GST Debit Note.
              </p>
            </div>
            <div className="min-w-0 space-y-2.5">
              <div className="min-w-0 space-y-1">
                <label
                  htmlFor={`${shipmentId}-admin-charge-amount`}
                  className="block text-xs font-semibold text-slate-700 break-words"
                >
                  New Final Price (₹ incl. 18% GST)
                </label>
                <Input
                  id={`${shipmentId}-admin-charge-amount`}
                  type="number"
                  step="0.01"
                  min="1"
                  required
                  value={chargeAmount}
                  onChange={(e) => setChargeAmount(e.target.value)}
                  placeholder="e.g. 177.00"
                  className="h-9 min-w-0 w-full bg-white text-sm font-mono"
                  data-testid={`${CARRIER_PANEL_TESTID}.add-charge.amount`}
                />
              </div>
              <div className="min-w-0 space-y-1">
                <label
                  htmlFor={`${shipmentId}-admin-charge-label`}
                  className="block text-xs font-semibold text-slate-700 break-words"
                >
                  Reason / Note
                </label>
                <Input
                  id={`${shipmentId}-admin-charge-label`}
                  type="text"
                  maxLength={120}
                  required
                  value={chargeLabel}
                  onChange={(e) => setChargeLabel(e.target.value)}
                  placeholder="Admin price override / Rate discount / Carrier diff"
                  className="h-9 min-w-0 w-full bg-white text-sm"
                  data-testid={`${CARRIER_PANEL_TESTID}.add-charge.label`}
                />
              </div>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2 min-w-0">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={submittingCharge}
                onClick={() => setAddingCharge(false)}
                data-testid={`${CARRIER_PANEL_TESTID}.add-charge.cancel`}
              >
                Cancel
              </Button>
              <Button
                type="submit"
                size="sm"
                disabled={submittingCharge}
                data-testid={`${CARRIER_PANEL_TESTID}.add-charge.submit`}
                className="h-auto min-h-8 max-w-full whitespace-normal py-1.5 text-center"
              >
                {submittingCharge && <Loader2 className="mr-1.5 h-3.5 w-3.5 shrink-0 animate-spin" />}
                <span>Apply Final Price &amp; Settle Wallet</span>
              </Button>
            </div>
          </form>
        )}
      </div>
    );
  };

  const isCancelled = shipmentStatus === "CANCELLED";
  const showEditButton = capabilities.canOperate && state.kind === "ready" && !editing && !addingCharge && !isCancelled;
  const showAddChargeButton = capabilities.canManageFinance && state.kind === "ready" && !editing && !addingCharge && !isCancelled;

  return (
    <Card data-testid={CARRIER_PANEL_TESTID} className={cn("@container min-w-0 overflow-hidden gap-3", className)}>
      <CardHeader className="flex flex-col gap-2 min-w-0 @[420px]:flex-row @[420px]:items-start @[420px]:justify-between">
        <div className="min-w-0 space-y-1">
          <CardTitle className="flex items-center gap-2 text-base break-words">
            <Truck className="h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
            <span>Carrier booking</span>
          </CardTitle>
          {capabilities.canOperate && (
            <CardDescription className="break-words">Book with the carrier, then enter the AWB and charges here.</CardDescription>
          )}
        </div>
        {(showEditButton || showAddChargeButton) && (
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            {showAddChargeButton && (
              <Button
                size="sm"
                variant="outline"
                onClick={openAddCharge}
                data-testid={`${CARRIER_PANEL_TESTID}.add-charge.open`}
                className="h-auto min-h-8 max-w-full whitespace-normal py-1.5"
              >
                <Plus className="h-4 w-4 shrink-0" />
                <span>Override / Adjust Price</span>
              </Button>
            )}
            {showEditButton && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setEditing(true)}
                data-testid={`${CARRIER_PANEL_TESTID}.edit`}
                className="h-auto min-h-8 max-w-full whitespace-normal py-1.5"
              >
                <Pencil className="h-4 w-4 shrink-0" />
                <span>{state.billing.carrier_awb ? "Edit carrier booking" : "Enter carrier booking"}</span>
              </Button>
            )}
          </div>
        )}
      </CardHeader>
      <CardContent className="min-w-0">{renderBody()}</CardContent>
    </Card>
  );
}
