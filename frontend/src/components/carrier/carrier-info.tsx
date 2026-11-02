// frontend/src/components/carrier/carrier-info.tsx
"use client";

/**
 * Small read-only "Carrier: Delhivery · AWB 1234…" block (pricing redesign WP0).
 *
 * Used on the customer shipment detail pages and the public tracking page, so it takes
 * plain props and never calls an authenticated hook (`useUser`) or the API. Values come
 * from `PickupRead` / `PublicTrackingRead` (`carrier_name`, `carrier_awb`,
 * `service_option`).
 *
 * Delhivery One parity: the order detail and tracking pages show the courier name and
 * its AWB with a copy action.
 */
import { Check, Copy, Truck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { cn } from "@/lib/utils";

import { serviceOptionLabel } from "./carrier-api";

/** Text shown before the carrier AWB exists (ops have not booked on Delhivery yet). */
export const AWB_NOT_ASSIGNED_TEXT = "Carrier AWB not assigned yet";

/** How long the copy icon stays a check mark after a successful copy. */
const COPIED_RESET_MS = 2000;

/** Root `data-testid`; children append `.name`, `.awb`, `.copy`, `.empty`, `.service`. */
export const CARRIER_INFO_TESTID = "carrier-info";

export interface CarrierInfoProps {
  /** Carrier display name from the API ("Delhivery" / "Logismart Prime"). */
  carrierName?: string | null;
  /** Carrier AWB, or null before ops book the parcel. */
  carrierAwb?: string | null;
  /** Optional booked service option code, shown as its label. */
  serviceOption?: string | null;
  className?: string;
}

/**
 * Copies `text` to the clipboard and reports the outcome with a toast.
 *
 * @param text - The AWB to copy.
 * @returns True when the copy succeeded.
 */
async function _copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("Carrier AWB copied to clipboard.");
    return true;
  } catch {
    toast.error("Could not copy the carrier AWB.");
    return false;
  }
}

/**
 * Renders the carrier name and AWB (with a copy button), or the empty state.
 *
 * @param props - See {@link CarrierInfoProps}.
 */
export function CarrierInfo({ carrierName, carrierAwb, serviceOption, className }: CarrierInfoProps) {
  const [copied, setCopied] = useState(false);
  const optionLabel = serviceOptionLabel(serviceOption);

  const handleCopy = async (awb: string) => {
    if (await _copyToClipboard(awb)) {
      setCopied(true);
      setTimeout(() => setCopied(false), COPIED_RESET_MS);
    }
  };

  return (
    <div
      data-testid={CARRIER_INFO_TESTID}
      className={cn("flex flex-wrap items-center gap-x-2 gap-y-1 text-sm", className)}
    >
      <Truck className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
      <span className="text-muted-foreground">Carrier:</span>
      <span data-testid={`${CARRIER_INFO_TESTID}.name`} className="font-medium text-foreground">
        {carrierName || "—"}
      </span>
      {optionLabel && (
        <span data-testid={`${CARRIER_INFO_TESTID}.service`} className="text-muted-foreground">
          ({optionLabel})
        </span>
      )}
      <span aria-hidden="true" className="text-muted-foreground">
        ·
      </span>
      {carrierAwb ? (
        <span className="inline-flex items-center gap-1">
          <span className="text-muted-foreground">AWB</span>
          <span data-testid={`${CARRIER_INFO_TESTID}.awb`} className="font-mono font-medium text-foreground">
            {carrierAwb}
          </span>
          <button
            type="button"
            data-testid={`${CARRIER_INFO_TESTID}.copy`}
            onClick={() => handleCopy(carrierAwb)}
            className="cursor-pointer text-muted-foreground transition-colors hover:text-primary focus:outline-hidden"
            title="Copy carrier AWB"
            aria-label="Copy carrier AWB"
          >
            {copied ? <Check className="h-4 w-4 text-primary" /> : <Copy className="h-4 w-4" />}
          </button>
        </span>
      ) : (
        <span data-testid={`${CARRIER_INFO_TESTID}.empty`} className="italic text-muted-foreground">
          {AWB_NOT_ASSIGNED_TEXT}
        </span>
      )}
    </div>
  );
}
