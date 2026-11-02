// frontend/src/components/blocks/admin-coordination-guide-modal.tsx
"use client";

/**
 * Global Staff "Delhivery ↔ Logismart Side-by-Side Playbook" Modal.
 *
 * Gives Logismart Admin, Operations, and Support staff a single side-by-side
 * reference table comparing:
 *   1. What Customer Does on Logismart
 *   2. What Admin Does on one.delhivery.com / Hub
 *   3. What Admin Does on Logismart
 * across all 6 core shipping and financial workflows.
 */
import { BookOpenCheck, ExternalLink } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

export const ADMIN_GUIDE_MODAL_TESTID = "admin-coordination-guide-modal";

interface CoordinationWorkflowRow {
  id: string;
  title: string;
  customerOnLogismart: string;
  adminOnDelhiveryOrHub: string;
  adminOnLogismart: string;
}

const COORDINATION_WORKFLOWS: readonly CoordinationWorkflowRow[] = [
  {
    id: "b2c-booking-awb",
    title: "1. B2C Parcel Booking & AWB Sync",
    customerOnLogismart:
      "Books a B2C parcel (Delhivery Surface or Delhivery Express) in 3 steps; wallet is debited for the marked-up quote + 18% GST.",
    adminOnDelhiveryOrHub:
      "Opens one.delhivery.com → Orders → Create Order (or via API auto-booking), books the shipment, and copies the Delhivery AWB & billed amount.",
    adminOnLogismart:
      "Opens Shipment Detail → Carrier booking → clicks 'Enter carrier booking' to save the Delhivery AWB, charged weight (kg), and charged amount (₹).",
  },
  {
    id: "b2b-cargo-prime-delhivery",
    title: "2. B2B Cargo: Logismart Prime vs. Delhivery B2B & Door vs. Godown",
    customerOnLogismart:
      "Selects multi-box cargo, chooses Door Delivery or Godown / Hub Self-Pickup (₹0 Door Charge), and books Logismart Prime or Delhivery B2B Cargo.",
    adminOnDelhiveryOrHub:
      "For Delhivery B2B: books PTL order on one.delhivery.com (B2B) to get LRN. For Logismart Prime: prints 3-Copy LR Docket & 4×6 labels and dispatches via partner transporter.",
    adminOnLogismart:
      "Saves Delhivery LRN or Partner Transporter LR/GR number in Carrier booking; manages city-to-city Prime rates & CSV templates under Settings ▸ Prime Lanes.",
  },
  {
    id: "pickup-requests-hub-audit",
    title: "3. Pickup Requests & Hub Dimension/Weight Audit",
    customerOnLogismart:
      "Creates a Pickup Request (PUR) for Ready-to-Ship orders with preferred date & time slot; hands boxes over to the pickup driver.",
    adminOnDelhiveryOrHub:
      "Schedules pickup on one.delhivery.com (or assigns Logismart first-mile rider/truck); weighs & measures boxes on the hub sorter scale.",
    adminOnLogismart:
      "In Ops Control Tower (/ops) or Shipment Detail, assigns pickup driver, marks Picked Up, and clicks 'Record Measurement' to log actual kg & L×B×H.",
  },
  {
    id: "price-override-wallet-gst",
    title: "4. Overpriced / Underpriced Admin Price Override (Wallet Refund / Debit + GST Notes)",
    customerOnLogismart:
      "Views updated shipment price on Shipment Detail and sees automatic Wallet Refund/Spend entry + downloadable GST Credit/Debit Note under Finances.",
    adminOnDelhiveryOrHub:
      "Checks actual carrier invoice/billing on one.delhivery.com or approves a commercial rate discount / weight-audit settlement.",
    adminOnLogismart:
      "Clicks 'Override / Adjust Price' on Shipment Detail (or inside Record Measurement) and enters New Final Price (₹ incl. GST) — Logismart auto-refunds (REFUND + GST Credit Note) if lower, or auto-debits (SPEND + GST Debit Note) if higher.",
  },
  {
    id: "ndr-exceptions-rto",
    title: "5. Delivery Exceptions (NDR) & Return to Origin (RTO)",
    customerOnLogismart:
      "Reviews undelivered orders under Delivery Exceptions and submits 'Reattempt' (with updated phone/address/date) or 'Return to Origin (RTO)'.",
    adminOnDelhiveryOrHub:
      "Mirrors the Reattempt or RTO instruction in one.delhivery.com → Exceptions (NDR) or dispatches last-mile rider with 6-digit delivery OTP.",
    adminOnLogismart:
      "Monitors open exceptions in Delivery Exceptions & Ops Control Tower; records last-mile delivery OTP or triggers RTO when max attempts are exhausted.",
  },
  {
    id: "wallet-recharges-upi-offline",
    title: "6. Wallet Recharges (Maker-Checker UPI & Offline NEFT/Cash Credit)",
    customerOnLogismart:
      "Scans Logismart's UPI QR on /wallet and submits the 12-digit UTR, or transfers funds offline via NEFT / IMPS / Cash / Bank Transfer.",
    adminOnDelhiveryOrHub:
      "Verifies incoming UTR in Logismart's bank statement and maintains sufficient master wallet balance on one.delhivery.com for carrier bookings.",
    adminOnLogismart:
      "On Finances ▸ Wallet (/wallet), clicks 'Approve' on pending UPI UTR requests or clicks 'Record Offline Credit' to credit a customer's wallet directly with a GST Advance Receipt Voucher.",
  },
];

export interface AdminCoordinationGuideModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Renders the 6-workflow side-by-side comparison modal for Logismart Staff.
 */
export function AdminCoordinationGuideModal({
  open,
  onOpenChange,
}: AdminCoordinationGuideModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid={ADMIN_GUIDE_MODAL_TESTID}
        className="sm:max-w-5xl max-h-[90vh] overflow-y-auto"
      >
        <DialogHeader>
          <div className="flex flex-wrap items-center justify-between gap-2 pr-6">
            <DialogTitle className="flex items-center gap-2 text-lg font-bold text-slate-900">
              <BookOpenCheck className="h-5 w-5 text-primary" aria-hidden="true" />
              Delhivery One ↔ Logismart Staff Co-ordination Playbook
            </DialogTitle>
            <Badge
              variant="outline"
              className="border-primary/30 bg-primary/5 text-primary text-xs font-semibold"
            >
              Staff Operations Reference
            </Badge>
          </div>
          <DialogDescription className="text-xs sm:text-sm text-slate-600">
            Side-by-side reference showing how every customer action on Logismart maps to{" "}
            <span className="font-mono font-semibold text-slate-800">one.delhivery.com</span>{" "}
            (or Prime Partner Transporters) and your Admin controls in Logismart.
          </DialogDescription>
        </DialogHeader>

        <div className="overflow-x-auto rounded-xl border border-slate-200">
          <table className="w-full text-left border-collapse text-xs sm:text-sm">
            <thead>
              <tr className="bg-slate-100/90 border-b border-slate-200 text-slate-800">
                <th className="p-3 font-bold w-1/3 border-r border-slate-200">
                  What Customer Does on Logismart
                </th>
                <th className="p-3 font-bold w-1/3 border-r border-slate-200">
                  What Admin Does on one.delhivery.com / Hub
                </th>
                <th className="p-3 font-bold w-1/3">
                  What Admin Does on Logismart
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {COORDINATION_WORKFLOWS.map((workflow) => (
                <tr key={workflow.id} className="align-top hover:bg-slate-50/70">
                  <td className="p-3 border-r border-slate-200 space-y-1">
                    <p className="font-bold text-slate-900">{workflow.title}</p>
                    <p className="text-slate-600 leading-relaxed">{workflow.customerOnLogismart}</p>
                  </td>
                  <td className="p-3 border-r border-slate-200 text-slate-600 leading-relaxed">
                    {workflow.adminOnDelhiveryOrHub}
                  </td>
                  <td className="p-3 text-slate-700 leading-relaxed font-medium">
                    {workflow.adminOnLogismart}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 pt-2">
          <Button variant="outline" size="sm" asChild className="text-xs font-semibold">
            <a
              href="https://one.delhivery.com"
              target="_blank"
              rel="noopener noreferrer"
              data-testid="admin-coordination-guide.open-delhivery"
            >
              Open one.delhivery.com ↗
              <ExternalLink className="ml-1.5 h-3.5 w-3.5" aria-hidden="true" />
            </a>
          </Button>
          <Button type="button" size="sm" onClick={() => onOpenChange(false)}>
            Got it
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
