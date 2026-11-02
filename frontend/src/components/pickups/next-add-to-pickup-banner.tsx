// frontend/src/components/pickups/next-add-to-pickup-banner.tsx
"use client";

/**
 * "Next: Add to pickup" call to action shown on the order page right after a
 * booking (Delhivery flow: book the order first, schedule the pickup later).
 *
 * The booking wizards redirect to `/shipments/<id>?booked=1`
 * (`buildBookedOrderHref`); this banner reads that flag.
 */
import {
  ManifestsService,
  PickupStatus,
  type PickupCandidatesResponse,
  type PickupRead,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import {
  buildCreatePickupHref,
  formatPickupDate,
  getPickupDisplayId,
  getPickupSlotLabel,
  PICKUP_FLOW_CONFIG,
} from "@/components/pickups/pickup-constants";
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
import { extractApiErrorMessage } from "@/lib/utils";
import type { ServiceFlow } from "@/lib/workspace-flow";
import { CheckCircle2, Loader2, Plus, Truck, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { toast } from "sonner";

/** Query flag the booking wizards append after a successful booking. */
export const BOOKED_QUERY_PARAM = "booked";
const BOOKED_QUERY_VALUE = "1";

/**
 * Adds the "just booked" flag to an order page path.
 *
 * @param orderPath - Tenant-relative order path, e.g. `/shipments/<id>`.
 * @returns The path with `?booked=1`.
 */
export function buildBookedOrderHref(orderPath: string): string {
  return `${orderPath}?${BOOKED_QUERY_PARAM}=${BOOKED_QUERY_VALUE}`;
}

interface NextAddToPickupBannerProps {
  shipment: Pick<PickupRead, "id" | "status" | "pickup_address"> & {
    manifest_id?: string | null;
  };
  flow: ServiceFlow;
  /** Called after the order was added to an existing pickup, so the page can reload it. */
  onAdded?: () => void;
}

function NextAddToPickupBannerContent({ shipment, flow, onAdded }: NextAddToPickupBannerProps) {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { routeTo, tenantSlug } = useTenant();
  const { capabilities } = useUser();
  const [dismissed, setDismissed] = useState(false);
  const [checkingCandidates, setCheckingCandidates] = useState(false);
  const [candidatesData, setCandidatesData] = useState<PickupCandidatesResponse | null>(null);
  const [chosenCandidateId, setChosenCandidateId] = useState<string>("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [adding, setAdding] = useState(false);

  const justBooked = searchParams.get(BOOKED_QUERY_PARAM) === BOOKED_QUERY_VALUE;
  const isReadyToShip =
    shipment.status === PickupStatus.OPEN && !shipment.manifest_id;
  if (!justBooked || !isReadyToShip || !capabilities.canBook || dismissed) return null;

  const flowConfig = PICKUP_FLOW_CONFIG[flow];

  const buildCreateHref = (locationId?: string | null, locationName?: string | null) =>
    routeTo(
      buildCreatePickupHref(flow, {
        locationId: locationId ?? shipment.pickup_address?.id,
        locationName: locationName ?? shipment.pickup_address?.name,
        shipmentIds: [shipment.id],
      }),
    );

  const handleAddToPickupClick = async () => {
    setCheckingCandidates(true);
    try {
      const response = await ManifestsService.getPickupCandidates(
        [shipment.id],
        tenantSlug,
      );
      if (response.candidates.length === 0) {
        router.push(
          buildCreateHref(
            response.pickup_address_id,
            response.pickup_location_name,
          ),
        );
        return;
      }
      setCandidatesData(response);
      setChosenCandidateId(response.candidates[0].id);
      setDialogOpen(true);
    } catch {
      router.push(buildCreateHref());
    } finally {
      setCheckingCandidates(false);
    }
  };

  const handleConfirmExisting = async () => {
    if (!chosenCandidateId) return;
    setAdding(true);
    try {
      const updated = await ManifestsService.addShipmentsToManifest(
        chosenCandidateId,
        { shipment_ids: [shipment.id] },
        tenantSlug,
      );
      toast.success(
        `Added ${flowConfig.shipmentNoun} to pickup ${getPickupDisplayId(updated)}`,
      );
      setDialogOpen(false);
      setDismissed(true);
      onAdded?.();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to add to pickup."));
    } finally {
      setAdding(false);
    }
  };

  return (
    <>
      <div
        role="status"
        className="flex flex-col gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
      >
        <div className="flex items-start gap-2.5">
          <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-emerald-600" />
          <div>
            <p className="text-sm font-bold text-emerald-900">Order created. It is Ready to ship.</p>
            <p className="text-xs text-emerald-800">
              Next: add it to a pickup request and choose the pickup date and slot.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            size="sm"
            className="h-9 font-semibold"
            disabled={checkingCandidates}
            onClick={handleAddToPickupClick}
          >
            {checkingCandidates ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : null}
            Next: Add to pickup
            <Truck className="ml-1.5 h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Dismiss"
            className="h-9 w-9 text-emerald-800 hover:bg-emerald-100"
            onClick={() => setDismissed(true)}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Truck className="h-5 w-5 text-primary" />
              Add to Pickup Request
            </DialogTitle>
            <DialogDescription>
              A scheduled pickup already exists for{" "}
              <span className="font-semibold text-foreground">
                {candidatesData?.pickup_location_name}
              </span>
              . Add this {flowConfig.shipmentNoun} to it or create a new pickup request.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2 py-2">
            {candidatesData?.candidates.map((candidate) => {
              const pickupId = getPickupDisplayId(candidate);
              const active = chosenCandidateId === candidate.id;
              return (
                <label
                  key={candidate.id}
                  className={`flex cursor-pointer items-center justify-between rounded-lg border p-3 transition-colors ${
                    active ? "border-primary bg-primary/5" : "hover:bg-muted/40"
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <input
                      type="radio"
                      name="next-pickup-candidate"
                      checked={active}
                      onChange={() => setChosenCandidateId(candidate.id)}
                      className="h-4 w-4 accent-primary"
                    />
                    <div>
                      <div className="font-mono text-sm font-bold text-foreground">
                        Pickup {pickupId}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {formatPickupDate(candidate.scheduled_date)} ·{" "}
                        {getPickupSlotLabel(candidate.time_slot)}
                      </div>
                    </div>
                  </div>
                  <span className="text-xs font-medium text-muted-foreground">
                    {candidate.expected_awbs} {flowConfig.shipmentNoun}
                    {candidate.expected_awbs === 1 ? "" : "s"}
                  </span>
                </label>
              );
            })}
          </div>
          <DialogFooter className="gap-2 sm:justify-between">
            <Button
              type="button"
              variant="outline"
              disabled={adding}
              onClick={() => {
                setDialogOpen(false);
                router.push(
                  buildCreateHref(
                    candidatesData?.pickup_address_id,
                    candidatesData?.pickup_location_name,
                  ),
                );
              }}
            >
              <Plus className="mr-1.5 h-4 w-4" />
              Create new pickup
            </Button>
            <Button
              type="button"
              disabled={adding || !chosenCandidateId}
              onClick={handleConfirmExisting}
            >
              {adding && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              Add to selected pickup
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

/** `useSearchParams` must render inside `<Suspense>`. */
export function NextAddToPickupBanner(props: NextAddToPickupBannerProps) {
  return (
    <Suspense fallback={null}>
      <NextAddToPickupBannerContent {...props} />
    </Suspense>
  );
}
