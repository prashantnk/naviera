// frontend/src/components/shipments/reprice-confirm-dialog.tsx
"use client";

/**
 * Confirmation dialog shown by the edit pages when the backend preview says the bill
 * changes or a field was refused. The merchant / admin sees the revised charges and the
 * settlement before saving; refused fields (H-7 / H-8 / H-12) block the save until they
 * are reverted.
 */
import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

import type { RepricePreview } from "./reprice-api";
import { RepricePreviewPanel } from "./reprice-preview-panel";

/** Props of {@link RepriceConfirmDialog}. */
export interface RepriceConfirmDialogProps {
  open: boolean;
  preview: RepricePreview | null;
  submitting: boolean;
  /** `data-testid` page prefix, e.g. `shipment-edit`. */
  testIdPage: string;
  onConfirm: () => void;
  onOpenChange: (open: boolean) => void;
}

/** "Review revised charges" dialog for shipment edits. */
export function RepriceConfirmDialog({
  open,
  preview,
  submitting,
  testIdPage,
  onConfirm,
  onOpenChange,
}: RepriceConfirmDialogProps) {
  const hasRejections = (preview?.rejected_fields.length ?? 0) > 0;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        data-testid={`${testIdPage}.preview-dialog`}
        className="max-h-[90vh] w-[calc(100vw-2rem)] overflow-y-auto sm:max-w-lg"
      >
        <DialogHeader>
          <DialogTitle>Review revised charges</DialogTitle>
          <DialogDescription>
            {hasRejections
              ? "Some changes cannot be saved for this shipment. Undo them to continue."
              : "Your changes affect the shipping charges. Check the revised amount before saving."}
          </DialogDescription>
        </DialogHeader>

        <RepricePreviewPanel preview={preview} loading={false} testIdPrefix={`${testIdPage}.preview`} />

        <DialogFooter className="flex-col-reverse gap-2 sm:flex-row">
          <Button
            type="button"
            variant="outline"
            data-testid={`${testIdPage}.actions.back`}
            disabled={submitting}
            onClick={() => onOpenChange(false)}
            className="w-full sm:w-auto"
          >
            Back to edit
          </Button>
          <Button
            type="button"
            data-testid={`${testIdPage}.actions.confirm`}
            disabled={submitting || hasRejections || !preview}
            onClick={onConfirm}
            className="w-full sm:w-auto"
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Confirm and save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
