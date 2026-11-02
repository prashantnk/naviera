// frontend/src/components/pickups/add-to-pickup-bar.tsx
"use client";

/**
 * Delhivery "Add to Pickup" entry point for the Shipments lists.
 *
 * 1. The user ticks Ready to Ship shipments and clicks **Add to Pickup**.
 * 2. `GET /manifests/pickup-candidates` validates the selection on the server
 *    (one flow, one pickup location, all OPEN). A 400 shows the server message.
 * 3. A dialog offers the existing SCHEDULED pickups of that location
 *    (`POST /manifests/{id}/shipments`) or **Create new pickup**, which opens
 *    the create page with the location and shipments pre-ticked.
 */
import { ManifestResponse, ManifestsService, PickupCandidatesResponse } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import { Loader2, Plus, Truck, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import {
  buildCreatePickupHref,
  formatPickupDate,
  getPickupDisplayId,
  getPickupSlotLabel,
  PICKUP_FLOW_CONFIG,
} from "./pickup-constants";

/** Props of the selection toolbar. */
export interface AddToPickupBarProps {
  /** Currently selected shipment ids (only OPEN rows are selectable). */
  selectedIds: readonly string[];
  /** Clears the page selection. */
  onClear: () => void;
  /** Called after shipments were added to an existing pickup (refresh the list). */
  onAdded: () => void;
}

/**
 * One-line candidate label, e.g. "Add to PUR 328874598 · 15 Oct, 2026 · 02:00 PM - 06:00 PM".
 *
 * @param manifest - Candidate pickup.
 * @returns Display label.
 */
function _candidateLabel(manifest: ManifestResponse): string {
  return `PUR ${getPickupDisplayId(manifest)} · ${formatPickupDate(manifest.scheduled_date)} · ${getPickupSlotLabel(manifest.time_slot)}`;
}

export function AddToPickupBar({ selectedIds, onClear, onAdded }: AddToPickupBarProps) {
  const router = useRouter();
  const { tenantSlug, routeTo } = useTenant();
  const [checking, setChecking] = useState(false);
  const [adding, setAdding] = useState(false);
  const [candidates, setCandidates] = useState<PickupCandidatesResponse | null>(null);
  const [chosenId, setChosenId] = useState<string>("");

  if (selectedIds.length === 0) return null;
  const count = selectedIds.length;

  const handleAddToPickup = async () => {
    setChecking(true);
    try {
      const response = await ManifestsService.getPickupCandidates(Array.from(selectedIds), tenantSlug);
      setCandidates(response);
      setChosenId(response.candidates[0]?.id ?? "");
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "These shipments cannot be added to a pickup."));
    } finally {
      setChecking(false);
    }
  };

  const handleAddToExisting = async () => {
    if (!candidates || !chosenId) return;
    const target = candidates.candidates.find((m) => m.id === chosenId);
    setAdding(true);
    try {
      const updated = await ManifestsService.addShipmentsToManifest(
        chosenId,
        { shipment_ids: Array.from(selectedIds) },
        tenantSlug
      );
      toast.success(
        `Added ${count} shipment${count === 1 ? "" : "s"} to pickup ${getPickupDisplayId(updated)}.`,
        { description: target ? _candidateLabel(target) : undefined }
      );
      setCandidates(null);
      onClear();
      onAdded();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to add shipments to the pickup."));
    } finally {
      setAdding(false);
    }
  };

  const handleCreateNew = () => {
    if (!candidates) return;
    const href = buildCreatePickupHref(candidates.service_flow, {
      locationId: candidates.pickup_address_id,
      locationName: candidates.pickup_location_name,
      shipmentIds: Array.from(selectedIds),
    });
    setCandidates(null);
    router.push(routeTo(href));
  };

  const noun = candidates ? PICKUP_FLOW_CONFIG[candidates.service_flow].shipmentNoun : "shipment";

  return (
    <>
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-primary/20 bg-primary/5 px-4 py-2.5 text-sm">
        <span className="font-semibold text-foreground">
          {count} Ready to Ship shipment{count === 1 ? "" : "s"} selected
        </span>
        <Button size="sm" onClick={handleAddToPickup} disabled={checking} className="h-8 text-xs font-semibold">
          {checking ? (
            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
          ) : (
            <Truck className="mr-1.5 h-3.5 w-3.5" />
          )}
          Add to Pickup
        </Button>
        <Button size="sm" variant="ghost" onClick={onClear} className="h-8 text-xs">
          <X className="mr-1 h-3.5 w-3.5" /> Clear
        </Button>
      </div>

      <Dialog
        open={candidates !== null}
        onOpenChange={(open) => {
          if (!open) setCandidates(null);
        }}
      >
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add to Pickup</DialogTitle>
            <DialogDescription>
              {count} {noun}
              {count === 1 ? "" : "s"} from{" "}
              <span className="font-semibold uppercase text-foreground">
                {candidates?.pickup_location_name}
              </span>
              . Add them to a scheduled pickup or create a new one.
            </DialogDescription>
          </DialogHeader>

          {candidates && candidates.candidates.length > 0 ? (
            <div className="max-h-64 space-y-2 overflow-y-auto" role="radiogroup">
              {candidates.candidates.map((manifest) => (
                <label
                  key={manifest.id}
                  className={cn(
                    "flex cursor-pointer items-start gap-3 rounded-lg border p-3 text-sm",
                    chosenId === manifest.id ? "border-primary bg-primary/5" : "border-border"
                  )}
                >
                  <input
                    type="radio"
                    name="pickup-candidate"
                    className="mt-0.5 accent-primary"
                    checked={chosenId === manifest.id}
                    onChange={() => setChosenId(manifest.id)}
                  />
                  <span className="flex flex-col">
                    <span className="font-semibold text-foreground">Add to {_candidateLabel(manifest)}</span>
                    <span className="text-xs text-muted-foreground">
                      {manifest.expected_awbs ?? 0} {noun}s already in this pickup
                    </span>
                  </span>
                </label>
              ))}
            </div>
          ) : (
            <p className="rounded-lg bg-muted/50 p-3 text-sm text-muted-foreground">
              No pickup is scheduled for this location yet. Create a new pickup request.
            </p>
          )}

          <DialogFooter className="gap-2">
            <Button variant="outline" onClick={handleCreateNew} disabled={adding}>
              <Plus className="mr-1.5 h-4 w-4" /> Create new pickup
            </Button>
            {candidates && candidates.candidates.length > 0 && (
              <Button onClick={handleAddToExisting} disabled={adding || !chosenId}>
                {adding && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Add to pickup
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
