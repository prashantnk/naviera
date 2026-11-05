// frontend/src/components/blocks/request-b2b-dialog.tsx
"use client";

import { B2BAccessRequestCreate, UsersService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useSingleFlight } from "@/hooks/use-single-flight";
import { extractApiErrorMessage } from "@/lib/utils";
import { Building2, CheckCircle2, Clock, FileText, Loader2, Truck } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

interface RequestB2bAccessDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Modal allowing a B2C customer to request B2B Heavy Cargo (Part Truckload)
 * access from the workspace Admin, optionally providing their Company Name,
 * 15-digit GSTIN, or 10-digit PAN.
 */
export function RequestB2bAccessDialog({
  open,
  onOpenChange,
}: RequestB2bAccessDialogProps) {
  const { user, refreshUser } = useUser();

  const [companyName, setCompanyName] = useState("");
  const [gstin, setGstin] = useState("");
  const [pan, setPan] = useState("");
  const [notes, setNotes] = useState("");
  const { pending: submitting, run } = useSingleFlight();

  const isPending = user?.b2b_request_status === "PENDING";

  useEffect(() => {
    if (open && user) {
      setCompanyName(user.company_name || "");
      setGstin(user.gstin || "");
      setPan(user.pan || "");
    }
  }, [open, user]);

  const handleGstinChange = (rawValue: string) => {
    const cleaned = rawValue.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 15);
    setGstin(cleaned);
    if (cleaned.length >= 12 && !pan) {
      setPan(cleaned.slice(2, 12));
    }
  };

  const handlePanChange = (rawValue: string) => {
    const cleaned = rawValue.toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 10);
    setPan(cleaned);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await run(async () => {
      try {
        const payload: B2BAccessRequestCreate = {
          company_name: companyName.trim() || null,
          gstin: gstin.trim() || null,
          pan: pan.trim() || null,
          notes: notes.trim() || null,
        };
        await UsersService.requestB2BAccessForCurrentUser(payload);
        await refreshUser();
        window.dispatchEvent(new CustomEvent("user-profile-updated"));
        toast.success(
          isPending
            ? "Updated your B2B Cargo access request details."
            : "B2B Cargo access request submitted for Admin approval."
        );
        onOpenChange(false);
      } catch (error) {
        toast.error(
          extractApiErrorMessage(error, "Could not submit B2B access request.")
        );
      }
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg p-0 overflow-hidden">
        <DialogHeader className="px-6 pt-6 pb-4 border-b border-slate-100 bg-slate-50/70">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-amber-100 text-amber-700 border border-amber-200">
              <Truck className="h-5 w-5" />
            </div>
            <div>
              <DialogTitle className="text-lg font-bold text-slate-900">
                Request B2B Heavy Cargo Access
              </DialogTitle>
              <DialogDescription className="text-xs text-slate-500 mt-0.5">
                Unlock Part Truckload (PTL) LR booking, multi-box dockets, and dock appointment scheduling.
              </DialogDescription>
            </div>
          </div>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-4">
          {isPending && (
            <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-3.5 flex items-start gap-3">
              <Clock className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div className="text-xs text-amber-900 space-y-1">
                <div className="font-bold flex items-center gap-2">
                  <span>Request Pending Admin Approval</span>
                  <Badge
                    variant="outline"
                    className="bg-amber-100 text-amber-800 border-amber-300 text-[10px]"
                  >
                    PENDING
                  </Badge>
                </div>
                <p className="text-amber-800/90 leading-relaxed">
                  Your request has been sent to the workspace administrator. You can update your optional GSTIN or PAN details below at any time.
                </p>
              </div>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="b2b-req-company" className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
              <Building2 className="h-3.5 w-3.5 text-slate-400" />
              Company / Business Name <span className="text-slate-400 font-normal">(Optional)</span>
            </Label>
            <Input
              id="b2b-req-company"
              value={companyName}
              onChange={(e) => setCompanyName(e.target.value)}
              placeholder="e.g. Acme Industrial Traders Pvt Ltd"
              className="text-sm"
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
            <div className="space-y-1.5">
              <Label htmlFor="b2b-req-gstin" className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
                <FileText className="h-3.5 w-3.5 text-slate-400" />
                GSTIN <span className="text-slate-400 font-normal">(Optional)</span>
              </Label>
              <Input
                id="b2b-req-gstin"
                value={gstin}
                onChange={(e) => handleGstinChange(e.target.value)}
                placeholder="15-digit GSTIN"
                maxLength={15}
                className="font-mono text-xs uppercase"
              />
              <p className="text-[11px] text-slate-400">
                Printed on B2B LR Label-cum-Invoice
              </p>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="b2b-req-pan" className="text-xs font-semibold text-slate-700 flex items-center gap-1.5">
                <CheckCircle2 className="h-3.5 w-3.5 text-slate-400" />
                PAN Number <span className="text-slate-400 font-normal">(Optional)</span>
              </Label>
              <Input
                id="b2b-req-pan"
                value={pan}
                onChange={(e) => handlePanChange(e.target.value)}
                placeholder="10-digit PAN"
                maxLength={10}
                className="font-mono text-xs uppercase"
              />
              <p className="text-[11px] text-slate-400">
                Business or proprietor PAN
              </p>
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="b2b-req-notes" className="text-xs font-semibold text-slate-700">
              Notes / Expected Cargo Volume <span className="text-slate-400 font-normal">(Optional)</span>
            </Label>
            <Textarea
              id="b2b-req-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="e.g. Shipping 20+ multi-box pallets per month from Gurgaon warehouse"
              rows={2}
              className="text-xs resize-none"
            />
          </div>

          <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-slate-100">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onOpenChange(false)}
              className="h-9 px-4 text-xs font-semibold"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={submitting}
              className="h-9 px-5 text-xs font-semibold bg-primary text-primary-foreground hover:bg-primary/90"
            >
              {submitting ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Submitting
                </>
              ) : isPending ? (
                "Update Request Details"
              ) : (
                "Request B2B Access"
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
