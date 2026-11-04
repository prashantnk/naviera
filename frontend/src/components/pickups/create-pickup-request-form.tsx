// frontend/src/components/pickups/create-pickup-request-form.tsx
"use client";

/**
 * Flow-aware "Create Pickup Request" form (Delhivery One parity) shared by
 * `/pickup-requests/new` (B2C) and `/b2b/pickup-requests/new` (B2B).
 *
 * Steps: pickup location -> pickup date & slot -> (B2B) pickup type -> shipments.
 * The shipment picker shows exactly what `GET /manifests/eligible-shipments`
 * returns for the flow + location; the browser never filters shipments and
 * never derives box counts (the server owns them for linked shipments).
 *
 * Spring Boot analogy: a form-backing bean whose `@Valid` rules live on the
 * server (`ManifestService`), with the UI only collecting the selection.
 */
import {
  AddressRead,
  EligibleShipmentRead,
  ManifestsService,
  PickupTimeSlot,
  ServiceFlow,
} from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  fetchAddressesCached,
  getCachedAddresses,
  hasCachedAddresses,
} from "@/hooks/use-addresses";
import { PICKUP_TIME_SLOT_OPTIONS } from "@/lib/form-options";
import {
  buildQueryCacheKey,
  getCachedQuery,
  hasCachedQuery,
  invalidateQueryCache,
  setCachedQuery,
} from "@/lib/query-cache";
import { cn, extractApiErrorMessage } from "@/lib/utils";
import { format, parseISO, startOfToday } from "date-fns";
import {
  ArrowLeft,
  CalendarDays,
  Clock,
  Info,
  Loader2,
  MapPin,
  PackageOpen,
  Truck,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import {
  API_DATE_FORMAT,
  CREATE_PICKUP_TITLE,
  firstAvailablePickupSlot,
  formatPickupDate,
  getPickupSlotLabel,
  isPickupSlotPassed,
  nextWorkingApiDate,
  PICKUP_FLOW_CONFIG,
  PICKUP_SLOT_ORDER,
  todayApiDate,
} from "./pickup-constants";

/** Pickup type for B2B (B2C is always manifested). */
enum PickupMode {
  MANIFESTED = "MANIFESTED",
  BLIND = "BLIND",
}

const CHECKBOX_CLASS = "h-4 w-4 rounded border-input bg-background accent-primary cursor-pointer";
const MIN_BLIND_BOXES = 1;
/** D-07: a blind pickup must carry at least one LR so every carton is billed and labelled. */
const BLIND_PICKUP_NEEDS_LR_MESSAGE =
  "A blind pickup needs at least one LR. Book a blind LR (box count only) from this pickup location first, then select it here.";
/** Shown if "Create" is pressed before the pickup locations / Ready to Ship list loaded. */
export const PICKER_STILL_LOADING_MESSAGE =
  "Still loading the Ready to Ship shipments for this location. Please wait a moment.";

/**
 * Builds the canonical SWR cache key for `GET /manifests/eligible-shipments`.
 */
export function buildEligibleShipmentsCacheKey(
  tenantSlug: string,
  serviceFlow: ServiceFlow,
  locationId: string,
): string {
  return buildQueryCacheKey(tenantSlug, "session", "eligible-shipments", {
    serviceFlow,
    locationId,
  });
}

/** A selectable pickup location (saved address, or the prefilled snapshot). */
interface LocationOption {
  id: string;
  label: string;
  detail: string;
}

/** Props of the shared create form. */
export interface CreatePickupRequestFormProps {
  serviceFlow: ServiceFlow;
  /** Prefill: pickup address id (from "Add to Pickup" or "Reschedule"). */
  initialLocationId?: string;
  /** Prefill: location name used when the id is not a saved address. */
  initialLocationName?: string;
  /** Prefill: shipment ids to pre-tick once the eligible list loads. */
  initialShipmentIds?: readonly string[];
  /** Prefill: API date (`yyyy-MM-dd`). Past dates fall back to today. */
  initialDate?: string;
}

/**
 * Maps saved addresses to location options, appending the prefilled location
 * when it is a per-shipment snapshot that is not in the address book.
 *
 * @param addresses - Saved addresses from the address book.
 * @param initialId - Prefilled location id, if any.
 * @param initialName - Prefilled location name, if any.
 * @returns Options for the location select.
 */
function _buildLocationOptions(
  addresses: AddressRead[],
  initialId: string | undefined,
  initialName: string | undefined
): LocationOption[] {
  const options: LocationOption[] = addresses.map((address) => ({
    id: address.id,
    label: address.company_name || address.name,
    detail: [address.address_line1, address.city, address.pincode].filter(Boolean).join(", "),
  }));
  if (initialId && !options.some((option) => option.id === initialId)) {
    options.unshift({
      id: initialId,
      label: initialName || "Selected pickup location",
      detail: "From your selected shipments",
    });
  }
  return options;
}

/**
 * Clamps a prefilled date to today or later.
 *
 * @param initialDate - Optional API date.
 * @returns A valid API date that is not in the past.
 */
function _resolveInitialDate(initialDate: string | undefined): string {
  const today = todayApiDate();
  if (initialDate && initialDate >= today) return initialDate;
  const hasSlotToday = PICKUP_SLOT_ORDER.some((slot) => !isPickupSlotPassed(slot, today));
  return hasSlotToday ? today : nextWorkingApiDate();
}

export function CreatePickupRequestForm({
  serviceFlow,
  initialLocationId,
  initialLocationName,
  initialShipmentIds,
  initialDate,
}: CreatePickupRequestFormProps) {
  const router = useRouter();
  const { tenantSlug, routeTo } = useTenant();
  const flowConfig = PICKUP_FLOW_CONFIG[serviceFlow];

  const [addresses, setAddresses] = useState<AddressRead[]>(
    () => getCachedAddresses(tenantSlug) ?? []
  );
  const [loadingAddresses, setLoadingAddresses] = useState<boolean>(
    () => !hasCachedAddresses(tenantSlug)
  );
  const [locationId, setLocationId] = useState<string>(() => {
    if (initialLocationId) return initialLocationId;
    const warm = getCachedAddresses(tenantSlug);
    return warm && warm.length === 1 ? warm[0].id : "";
  });

  const startDate = _resolveInitialDate(initialDate);
  const [scheduledDate, setScheduledDate] = useState(startDate);
  const [timeSlot, setTimeSlot] = useState<PickupTimeSlot>(() => firstAvailablePickupSlot(startDate));
  const [datePickerOpen, setDatePickerOpen] = useState(false);

  const [mode, setMode] = useState<PickupMode>(PickupMode.MANIFESTED);
  const [blindBoxes, setBlindBoxes] = useState("");
  const [expectedBoxes, setExpectedBoxes] = useState("1");

  const initialEligibleKey = locationId
    ? buildEligibleShipmentsCacheKey(tenantSlug, serviceFlow, locationId)
    : "";
  const [eligible, setEligible] = useState<EligibleShipmentRead[]>(() =>
    initialEligibleKey
      ? (getCachedQuery<EligibleShipmentRead[]>(initialEligibleKey) ?? [])
      : []
  );
  const [eligibleLoadedFor, setEligibleLoadedFor] = useState<string | null>(() =>
    initialEligibleKey && hasCachedQuery(initialEligibleKey) ? locationId : null
  );
  const loadingEligible = Boolean(locationId) && eligibleLoadedFor !== locationId;
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => {
    if (!initialEligibleKey) return new Set();
    const warmRows = getCachedQuery<EligibleShipmentRead[]>(initialEligibleKey);
    if (!warmRows) return new Set();
    const preselect = new Set(initialShipmentIds ?? []);
    if (preselect.size > 0) {
      return new Set(warmRows.map((row) => row.id).filter((id) => preselect.has(id)));
    }
    return new Set(warmRows.map((row) => row.id));
  });
  const pendingPreselect = useRef<Set<string>>(new Set(initialShipmentIds ?? []));

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const isBlind = flowConfig.allowBlindPickup && mode === PickupMode.BLIND;

  useEffect(() => {
    let ignore = false;
    const warm = getCachedAddresses(tenantSlug);
    if (warm !== null) {
      setAddresses(warm);
      setLoadingAddresses(false);
      if (!initialLocationId && warm.length === 1) {
        setLocationId((prev) => prev || warm[0].id);
      }
    }
    fetchAddressesCached(tenantSlug, { force: warm !== null })
      .then((rows) => {
        if (ignore) return;
        setAddresses(rows);
        if (!initialLocationId && rows.length === 1) {
          setLocationId((prev) => prev || rows[0].id);
        }
      })
      .catch((err: unknown) => {
        if (!ignore && warm === null) {
          setError(extractApiErrorMessage(err, "Failed to load pickup locations."));
        }
      })
      .finally(() => {
        if (!ignore) setLoadingAddresses(false);
      });
    return () => {
      ignore = true;
    };
  }, [tenantSlug, initialLocationId]);

  useEffect(() => {
    if (!locationId) return;
    let ignore = false;
    const eligibleKey = buildEligibleShipmentsCacheKey(tenantSlug, serviceFlow, locationId);
    const warmRows = getCachedQuery<EligibleShipmentRead[]>(eligibleKey);
    if (warmRows !== null) {
      setEligible(warmRows);
      setEligibleLoadedFor(locationId);
      const preselect = pendingPreselect.current;
      if (preselect.size > 0) {
        setSelectedIds(new Set(warmRows.map((row) => row.id).filter((id) => preselect.has(id))));
      } else {
        setSelectedIds(new Set(warmRows.map((row) => row.id)));
      }
      pendingPreselect.current = new Set();
    }
    ManifestsService.listEligibleShipments(serviceFlow, locationId, tenantSlug)
      .then((rows) => {
        setCachedQuery(eligibleKey, rows);
        if (ignore) return;
        setEligible(rows);
        if (warmRows === null) {
          const preselect = pendingPreselect.current;
          if (preselect.size > 0) {
            setSelectedIds(new Set(rows.map((row) => row.id).filter((id) => preselect.has(id))));
          } else {
            setSelectedIds(new Set(rows.map((row) => row.id)));
          }
          pendingPreselect.current = new Set();
        }
      })
      .catch((err: unknown) => {
        if (ignore || warmRows !== null) return;
        setEligible([]);
        setSelectedIds(new Set());
        toast.error(extractApiErrorMessage(err, "Failed to load Ready to Ship shipments."));
      })
      .finally(() => {
        if (!ignore) setEligibleLoadedFor(locationId);
      });
    return () => {
      ignore = true;
    };
  }, [serviceFlow, locationId, tenantSlug]);

  const locationOptions = useMemo(
    () => _buildLocationOptions(addresses, initialLocationId, initialLocationName),
    [addresses, initialLocationId, initialLocationName]
  );

  const allSelected = eligible.length > 0 && eligible.every((row) => selectedIds.has(row.id));

  const toggleShipment = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = (checked: boolean) => {
    setSelectedIds(checked ? new Set(eligible.map((row) => row.id)) : new Set());
  };

  const handleDateChange = (date: Date | undefined) => {
    if (!date) return;
    const next = format(date, API_DATE_FORMAT);
    setScheduledDate(next);
    if (isPickupSlotPassed(timeSlot, next)) setTimeSlot(firstAvailablePickupSlot(next));
    setDatePickerOpen(false);
  };

  /**
   * Client-side completeness checks only; business rules are enforced by the API.
   *
   * @returns An error message, or an empty string when the form can be submitted.
   */
  const validate = (): string => {
    if (!locationId) return "Select a pickup location.";
    // Wait for the Ready to Ship list: submitting earlier would drop the pre-selected
    // orders and create an empty pickup request (seen live on a slow network).
    if (loadingAddresses || loadingEligible) return PICKER_STILL_LOADING_MESSAGE;
    if (!scheduledDate) return "Select a pickup date.";
    if (isPickupSlotPassed(timeSlot, scheduledDate)) return "This slot has already started. Pick a later slot or date.";
    if (isBlind) {
      const boxes = Number.parseInt(blindBoxes, 10);
      if (!Number.isInteger(boxes) || boxes < MIN_BLIND_BOXES) return "Enter the number of boxes for the blind pickup.";
      if (selectedIds.size === 0) return BLIND_PICKUP_NEEDS_LR_MESSAGE;
      return "";
    }
    if (serviceFlow === ServiceFlow.B2B && selectedIds.size === 0) {
      return `Select at least one Ready to Ship ${flowConfig.shipmentNoun} for a B2B pickup request.`;
    }
    if (selectedIds.size === 0) {
      const declaredBoxes = Number.parseInt(expectedBoxes, 10);
      if (!Number.isInteger(declaredBoxes) || declaredBoxes < MIN_BLIND_BOXES) {
        return `Select at least one Ready to Ship ${flowConfig.shipmentNoun} or enter an expected package count.`;
      }
    }
    return "";
  };

  const handleSubmit = async () => {
    const validationError = validate();
    setError(validationError);
    if (validationError) return;

    const declaredExpected = Number.parseInt(expectedBoxes, 10);
    const fallbackBoxes = Number.isInteger(declaredExpected) && declaredExpected >= MIN_BLIND_BOXES ? declaredExpected : 1;

    setSubmitting(true);
    try {
      const created = await ManifestsService.createManifest(
        {
          pickup_address_id: locationId,
          scheduled_date: scheduledDate,
          time_slot: timeSlot,
          service_flow: serviceFlow,
          is_blind_pickup: isBlind,
          total_boxes: isBlind ? Number.parseInt(blindBoxes, 10) : selectedIds.size > 0 ? 0 : fallbackBoxes,
          shipment_ids: Array.from(selectedIds),
        },
        tenantSlug
      );
      invalidateQueryCache("manifests-list");
      invalidateQueryCache("eligible-shipments");
      invalidateQueryCache("shipments-list");
      const slotNotice = (created as { notice?: string | null }).notice;
      toast.success(`Pickup request ${created.pickup_request_number ?? ""} created`, {
        description: slotNotice
          ? `${formatPickupDate(created.scheduled_date)} · ${getPickupSlotLabel(created.time_slot)} — ${slotNotice}`
          : `${formatPickupDate(created.scheduled_date)} · ${getPickupSlotLabel(created.time_slot)}`,
      });
      if (slotNotice) {
        toast.info(slotNotice);
      }
      router.push(routeTo(flowConfig.listHref));
    } catch (err: unknown) {
      setError(extractApiErrorMessage(err, "Failed to create the pickup request."));
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 pb-28 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-start gap-3">
        <Button variant="ghost" size="icon" asChild className="mt-1 shrink-0">
          <Link href={routeTo(flowConfig.listHref)} prefetch={true} aria-label="Back to pickup requests">
            <ArrowLeft className="h-4 w-4" />
          </Link>
        </Button>
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Truck className="h-5 w-5" />
        </div>
        <div>
          <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-foreground">
            {CREATE_PICKUP_TITLE}
          </h1>
          <p className="mt-0.5 text-sm text-muted-foreground">
            Choose a pickup location, date and slot, then select the shipments to hand over.
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-destructive/20 bg-destructive/10 p-4 text-sm font-medium text-destructive">
          {error}
        </div>
      )}

      {/* 1. Pickup location */}
      <section className="space-y-3 rounded-xl border border-border bg-card p-4 sm:p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <MapPin className="h-4 w-4 text-primary" /> Pickup location
        </h2>
        {loadingAddresses ? (
          <div
            data-testid="pickup-locations-skeleton"
            className="h-10 w-full animate-pulse rounded-lg bg-muted/60"
          />
        ) : locationOptions.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No saved pickup locations yet.{" "}
            <Link href={routeTo("/address-book")} prefetch={true} className="font-medium text-primary hover:underline">
              Add one in the Address Book
            </Link>
            .
          </p>
        ) : (
          <Select value={locationId} onValueChange={setLocationId}>
            <SelectTrigger className="h-auto min-h-10 w-full min-w-0 overflow-hidden bg-background py-2 text-left">
              <SelectValue placeholder="Select pickup location" />
            </SelectTrigger>
            <SelectContent>
              {locationOptions.map((option) => (
                <SelectItem key={option.id} value={option.id}>
                  <span className="flex min-w-0 flex-col">
                    <span className="font-semibold uppercase truncate">{option.label}</span>
                    <span className="text-xs text-muted-foreground truncate">{option.detail}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </section>

      {/* 2. Pickup date & slot */}
      <section className="space-y-4 rounded-xl border border-border bg-card p-4 sm:p-6 shadow-sm">
        <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
          <CalendarDays className="h-4 w-4 text-primary" /> Pickup date &amp; slot
        </h2>
        <div className="space-y-1.5">
          <Label>Pickup date</Label>
          <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" className="h-10 w-full justify-start bg-background font-normal sm:w-64">
                <CalendarDays className="mr-2 h-4 w-4" />
                {formatPickupDate(scheduledDate)}
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-auto p-0" align="start">
              <Calendar
                mode="single"
                selected={parseISO(scheduledDate)}
                onSelect={handleDateChange}
                disabled={{ before: startOfToday() }}
              />
            </PopoverContent>
          </Popover>
        </div>
        <div className="space-y-1.5">
          <Label>Pickup slot</Label>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {PICKUP_SLOT_ORDER.map((slot) => {
              const passed = isPickupSlotPassed(slot, scheduledDate);
              const selected = slot === timeSlot;
              return (
                <button
                  key={slot}
                  type="button"
                  disabled={passed}
                  onClick={() => setTimeSlot(slot)}
                  aria-pressed={selected}
                  className={cn(
                    "flex flex-col items-start rounded-lg border px-3 py-2.5 text-left transition-colors",
                    selected
                      ? "border-primary bg-primary/5 ring-1 ring-primary"
                      : "border-border bg-background hover:bg-muted/50",
                    passed && "cursor-not-allowed opacity-50"
                  )}
                >
                  <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
                    <Clock className="h-3.5 w-3.5 text-muted-foreground" />
                    {getPickupSlotLabel(slot)}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {passed ? "Slot already started today" : PICKUP_TIME_SLOT_OPTIONS[slot].description}
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        {flowConfig.sameDayCutoffNote && (
          <p className="flex items-start gap-2 rounded-lg bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
            <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {flowConfig.sameDayCutoffNote}
          </p>
        )}
      </section>

      {/* 3. Pickup type (B2B only) */}
      {flowConfig.allowBlindPickup && (
        <section className="space-y-3 rounded-xl border border-border bg-card p-4 sm:p-6 shadow-sm">
          <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
            <PackageOpen className="h-4 w-4 text-primary" /> Pickup type
          </h2>
          <div className="flex flex-col gap-2 sm:flex-row">
            <Button
              type="button"
              variant={mode === PickupMode.MANIFESTED ? "default" : "outline"}
              onClick={() => setMode(PickupMode.MANIFESTED)}
            >
              Manifested LRs
            </Button>
            <Button
              type="button"
              variant={mode === PickupMode.BLIND ? "default" : "outline"}
              onClick={() => setMode(PickupMode.BLIND)}
            >
              Blind pickup (box count)
            </Button>
          </div>
          {isBlind && (
            <div className="max-w-xs space-y-1.5 pt-1">
              <Label htmlFor="blind-boxes">Number of boxes</Label>
              <Input
                id="blind-boxes"
                type="number"
                inputMode="numeric"
                min={MIN_BLIND_BOXES}
                value={blindBoxes}
                onChange={(event) => setBlindBoxes(event.target.value)}
                placeholder="e.g. 12"
                className="bg-background"
              />
              <p className="text-xs text-muted-foreground">
                Select at least one blind LR (booked with a box count only) below, so every carton gets an AWB and a bill.
              </p>
            </div>
          )}
        </section>
      )}

      {/* 4. Shipments (blind pickups still link ≥1 blind LR, D-07) */}
        <section className="space-y-3 rounded-xl border border-border bg-card p-4 sm:p-6 shadow-sm">
          <div className="flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
            <h2 className="text-base font-semibold text-foreground">
              Ready to Ship {flowConfig.shipmentNoun}s
            </h2>
            {eligible.length > 0 && (
              <span className="text-xs font-medium text-muted-foreground">
                {selectedIds.size} of {eligible.length} selected
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">{flowConfig.pickerHint}</p>

          {!locationId ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Select a pickup location to see its Ready to Ship shipments.
            </p>
          ) : loadingEligible ? (
            <div
              data-testid="eligible-shipments-skeleton"
              className="space-y-2 py-2"
            >
              <div className="h-9 w-full animate-pulse rounded-lg bg-muted/60" />
              <div className="h-10 w-full animate-pulse rounded-lg bg-muted/40" />
              <div className="h-10 w-full animate-pulse rounded-lg bg-muted/40" />
            </div>
          ) : eligible.length === 0 && isBlind ? (
            <div
              data-testid="create-pur.blind-needs-lr"
              className="rounded-lg border border-dashed border-border bg-muted/20 p-4 text-sm text-muted-foreground"
            >
              {BLIND_PICKUP_NEEDS_LR_MESSAGE}
            </div>
          ) : eligible.length === 0 ? (
            <div className="space-y-3 rounded-lg border border-dashed border-border bg-muted/20 p-4">
              <p className="text-sm text-muted-foreground">
                No Ready to Ship shipments are currently manifested at this location. You can still schedule a pickup slot by entering your{" "}
                <span className="font-semibold text-foreground">Expected Package Count</span> below, and add Ready to Ship {flowConfig.shipmentNoun}s to this pickup request before the slot begins.
              </p>
              <div className="max-w-xs space-y-1.5">
                <Label htmlFor="expected-boxes">Expected package count</Label>
                <Input
                  id="expected-boxes"
                  type="number"
                  inputMode="numeric"
                  min={MIN_BLIND_BOXES}
                  value={expectedBoxes}
                  onChange={(event) => setExpectedBoxes(event.target.value)}
                  placeholder="e.g. 5"
                  className="bg-background"
                />
              </div>
            </div>
          ) : (
            <>
              {/* Desktop table */}
              <div className="hidden overflow-x-auto rounded-lg border border-border md:block">
                <table className="w-full text-sm">
                  <thead className="bg-muted/50 text-left text-xs font-semibold text-muted-foreground">
                    <tr>
                      <th className="w-10 px-3 py-2.5">
                        <input
                          type="checkbox"
                          aria-label="Select all shipments"
                          className={CHECKBOX_CLASS}
                          checked={allSelected}
                          onChange={(event) => toggleAll(event.target.checked)}
                        />
                      </th>
                      <th className="px-3 py-2.5">{flowConfig.shipmentIdHeader}</th>
                      <th className="px-3 py-2.5">Order ref</th>
                      <th className="px-3 py-2.5">Destination</th>
                      <th className="px-3 py-2.5">Boxes</th>
                      <th className="px-3 py-2.5">
                        Weight (kg)
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {eligible.map((shipment) => (
                      <tr
                        key={shipment.id}
                        onClick={() => toggleShipment(shipment.id)}
                        className={cn(
                          "cursor-pointer hover:bg-muted/40",
                          selectedIds.has(shipment.id) && "bg-primary/5"
                        )}
                      >
                        <td className="px-3 py-2.5">
                          <input
                            type="checkbox"
                            aria-label="Select shipment"
                            className={CHECKBOX_CLASS}
                            checked={selectedIds.has(shipment.id)}
                            onClick={(event) => event.stopPropagation()}
                            onChange={() => toggleShipment(shipment.id)}
                          />
                        </td>
                        <td className="px-3 py-2.5 font-mono text-xs font-semibold text-foreground">
                          {shipment.tracking_id || "Pending"}
                        </td>
                        <td className="px-3 py-2.5 text-muted-foreground">{shipment.order_reference_id || "-"}</td>
                        <td className="px-3 py-2.5 text-foreground">
                          {shipment.delivery_city}
                          <span className="ml-1 text-xs text-muted-foreground">
                            {shipment.delivery_pincode}
                          </span>
                        </td>
                        <td className="px-3 py-2.5 text-foreground">{shipment.package_count}</td>
                        <td className="px-3 py-2.5 text-foreground">
                          {shipment.total_weight_kg}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Mobile cards */}
              <div className="space-y-2 md:hidden">
                <label className="flex items-center gap-2 px-1 text-xs font-medium text-muted-foreground">
                  <input
                    type="checkbox"
                    className={CHECKBOX_CLASS}
                    checked={allSelected}
                    onChange={(event) => toggleAll(event.target.checked)}
                  />
                  Select all
                </label>
                {eligible.map((shipment) => (
                  <label
                    key={shipment.id}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border border-border p-3",
                      selectedIds.has(shipment.id) && "border-primary bg-primary/5"
                    )}
                  >
                    <input
                      type="checkbox"
                      className={cn(CHECKBOX_CLASS, "mt-0.5")}
                      checked={selectedIds.has(shipment.id)}
                      onChange={() => toggleShipment(shipment.id)}
                    />
                    <span className="flex min-w-0 flex-col gap-0.5 text-sm">
                      <span className="font-mono text-xs font-semibold text-foreground">
                        {shipment.tracking_id || "Pending"}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        Ref {shipment.order_reference_id || "-"} · To {shipment.delivery_city}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {shipment.package_count} box(es) ·{" "}
                        {shipment.total_weight_kg} kg
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </>
          )}
        </section>

      {/* Sticky submit bar */}
      <div className="sticky bottom-0 z-10 -mx-4 border-t border-border bg-background/95 px-4 py-3 backdrop-blur sm:mx-0 sm:rounded-xl sm:border">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-sm text-muted-foreground">
            {isBlind
              ? `Blind pickup · ${selectedIds.size} ${flowConfig.shipmentNoun}${selectedIds.size === 1 ? "" : "s"} selected`
              : selectedIds.size > 0
                ? `${selectedIds.size} ${flowConfig.shipmentNoun}${selectedIds.size === 1 ? "" : "s"} selected`
                : `Expected: ${expectedBoxes || 1} package(s)`}
            {" · "}
            {formatPickupDate(scheduledDate)} · {getPickupSlotLabel(timeSlot)}
          </span>
          <Button
            onClick={handleSubmit}
            disabled={submitting || loadingAddresses || loadingEligible}
            className="h-10 px-5 font-semibold"
          >
            {submitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            {CREATE_PICKUP_TITLE}
          </Button>
        </div>
      </div>
    </div>
  );
}
