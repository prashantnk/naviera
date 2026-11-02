// frontend/src/components/finance/weight-claim.ts
import type { WeightDisputeRead } from "@/api_client";
import { CLAIMS_FINANCE_CHIP } from "@/components/support/ticket-rules";

/** Backend `WeightDisputeClaimStatus` values (`backend/app/models/delhivery_modules.py`). */
export const CLAIM_STATUS = {
  NONE: "NONE",
  CLAIM_RAISED: "CLAIM_RAISED",
  ACCEPTED: "ACCEPTED",
  REJECTED: "REJECTED",
} as const;

/** Support category a "Need help?" link on a rejected claim pre-selects. */
export const WEIGHT_CLAIM_HELP_CATEGORY = CLAIMS_FINANCE_CHIP;

/** Normalised claim status (missing = NONE). */
export function claimStatusOf(row: Pick<WeightDisputeRead, "claim_status">): string {
  return (row.claim_status || CLAIM_STATUS.NONE).toUpperCase();
}

/**
 * A claim can be raised only while none is open or decided and ops recorded an upward
 * billing difference; this mirrors `_load_claimable_dispute` so the UI never offers a
 * claim the API would refuse.
 */
export function isClaimable(row: Pick<WeightDisputeRead, "claim_status" | "cost_diff_inr">): boolean {
  return claimStatusOf(row) === CLAIM_STATUS.NONE && Number(row.cost_diff_inr ?? 0) > 0;
}

/**
 * Human label for a claim status (Delhivery One splits claims into Open / Closed).
 * Staff see "Awaiting admin review" on an open claim so they know who acts next.
 */
export function claimStatusLabel(status: string, viewerIsStaff: boolean): string {
  switch (status) {
    case CLAIM_STATUS.CLAIM_RAISED:
      return viewerIsStaff ? "Awaiting admin review" : "Claim under review";
    case CLAIM_STATUS.ACCEPTED:
      return "Claim accepted";
    case CLAIM_STATUS.REJECTED:
      return "Claim rejected";
    default:
      return "No claim";
  }
}

/** First row the seller can still raise a claim on, used to pre-fill "New Claim". */
export function firstClaimableRow<T extends Pick<WeightDisputeRead, "claim_status" | "cost_diff_inr">>(
  rows: readonly T[]
): T | undefined {
  return rows.find(isClaimable);
}

/**
 * Why an AWB typed into "New Claim" cannot be claimed, or null when it can.
 *
 * @param row - The matching dispute row, or undefined when the AWB has no audit record.
 * @param awb - The AWB as typed (for the message).
 */
export function claimBlockReason(
  row: Pick<WeightDisputeRead, "claim_status" | "cost_diff_inr"> | undefined,
  awb: string
): string | null {
  if (!row) return `No audited weight discrepancy found for AWB ${awb}.`;
  const status = claimStatusOf(row);
  if (status === CLAIM_STATUS.CLAIM_RAISED) {
    return `A claim for AWB ${awb} is already under review.`;
  }
  if (status === CLAIM_STATUS.ACCEPTED || status === CLAIM_STATUS.REJECTED) {
    return `The claim for AWB ${awb} is already closed (${claimStatusLabel(status, false).toLowerCase()}).`;
  }
  if (!isClaimable(row)) return `No extra weight charge was billed on AWB ${awb}.`;
  return null;
}
