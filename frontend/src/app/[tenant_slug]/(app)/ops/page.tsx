// frontend/src/app/[tenant_slug]/(app)/ops/page.tsx
"use client";

import {
  CodRemittanceStatus,
  ManifestResponse,
  ManifestsService,
  ManifestStatus,
  NdrExceptionReason,
  PickupRead,
  PickupStatus,
  ShipmentType,
  ShipmentsService,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { CarrierBookingDialog } from "@/components/carrier/carrier-booking-dialog";
import { DispatchPickupDialog } from "@/components/pickups/pickup-action-dialogs";
import {
  getManifestStatusDisplay,
  getShipmentStatusLabel,
} from "@/components/pickups/status-display";
import { useTenant } from "@/components/providers/tenant-provider";
import { MeasurementDialog } from "@/components/shipments/measurement-dialog";
import {
  buildMeasurementForPieceCount,
  type DispatchMeasurement,
} from "@/components/shipments/reprice-api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScreenGuideBanner, type GuideStep } from "@/components/ui/screen-guide-banner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { downloadManifestRunsheetPdf } from "@/lib/api";
import {
  buildQueryCacheKey,
  getCachedQuery,
  hasCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import {
  CashBadgeTone,
  type DeliveryFilter,
  DeliveryFilterKey,
  EMPTY_POD_DRAFT,
  FIELD_NDR_SELECT_OPTIONS,
  FOCUS_REFETCH_MIN_INTERVAL_MS,
  RTO_LEG_STATUSES,
  canMoveTo,
  cashCollectionBadge,
  isDoorCashPending,
  loadPodDraft,
  matchesDeliveryFilter,
  matchesPickupFilter,
  PICKUP_FILTER_ACTIVE,
  PICKUP_FILTER_ALL,
  ndrReasonLabel,
  parseActualPieces,
  pickedBoxesLabel,
  type PodDraft,
  savePodDraft,
  serviceTypeLabel,
  withoutEntry,
} from "./ops-field";
import {
  cn,
  extractApiErrorMessage,
  formatTimeSlot,
  safeFormatDate,
} from "@/lib/utils";
import {
  buildMailtoConsigneeUrl,
  buildWhatsAppConsigneeUrl,
  consigneeStageForStatus,
  hasWhatsAppPhone,
} from "@/lib/whatsapp-notify";
import {
  AlertTriangle,
  Banknote,
  Building2,
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  FileText,
  KeyRound,
  Loader2,
  Mail,
  MapPin,
  MessageCircle,
  Monitor,
  Package,
  PackageCheck,
  Phone,
  RefreshCw,
  Ruler,
  Scale,
  Search,
  ShieldAlert,
  Smartphone,
  Truck,
  Undo2,
  UserCheck,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

type OpsWorkspaceMode = "CONTROL_TOWER" | "FIELD_EXEC";

const MOBILE_VIEWPORT_BREAKPOINT = 768;
const SHIPMENT_FETCH_LIMIT = 100;

const OPS_GUIDE_STEPS: readonly GuideStep[] = [
  {
    title: "First-Mile Pickup Dispatch (PUR)",
    description:
      "Verify actual box counts at the seller warehouse, confirm pickup, and download the Manifest Run-Sheet.",
  },
  {
    title: "Hub Weight Audit & Price Override",
    description:
      "Click Record Measurement to enter hub weight/dimensions (and optional Final ₹ Price Override) with automatic wallet adjustment.",
  },
  {
    title: "Last-Mile 6-Digit OTP & COD",
    description:
      "Mark parcels Out for Delivery, verify the consignee's 6-digit OTP at the doorstep, or log an NDR exception.",
  },
];
/** Statuses that still need pickup / delivery / RTO action in the field queue. */
const OPS_ACTIVE_STATUSES: readonly PickupStatus[] = [
  PickupStatus.OPEN,
  PickupStatus.ASSIGNED,
  PickupStatus.IN_TRANSIT,
  PickupStatus.OUT_FOR_DELIVERY,
  PickupStatus.EXCEPTION,
  PickupStatus.RTO_INITIATED,
  PickupStatus.RTO_IN_TRANSIT,
];

const POD_RECEIVER_PRESETS = [
  "Consignee (Self)",
  "Family Member",
  "Security Guard",
  "Front Desk / Reception",
];

const NOT_PICKED_REASON_PRESETS = [
  "Warehouse closed / Dock unavailable",
  "Shipments not ready / Packing incomplete",
  "Contact person unreachable at pickup address",
  "Vehicle capacity / Dimension mismatch",
];

/** Cash-tab badge tone -> semantic classes (labels come from `cashCollectionBadge`). */
const CASH_BADGE_CLASS: Readonly<Record<CashBadgeTone, string>> = {
  [CashBadgeTone.PENDING]: "bg-amber-600 text-white",
  [CashBadgeTone.WITH_FIELD_TEAM]: "bg-sky-600 text-white",
  [CashBadgeTone.SETTLED]: "bg-emerald-600 text-white",
  [CashBadgeTone.NOT_COLLECTED]: "bg-slate-500 text-white",
};

/** Last-Mile filter chips (D-01: Out for Delivery and RTO have their own chips). */
const DELIVERY_FILTER_CHIPS: ReadonlyArray<{ key: DeliveryFilter; label: string }> = [
  { key: DeliveryFilterKey.ACTIVE, label: "Active Run-Sheet" },
  { key: PickupStatus.IN_TRANSIT, label: "In Transit" },
  { key: PickupStatus.OUT_FOR_DELIVERY, label: "Out for Delivery" },
  { key: PickupStatus.EXCEPTION, label: "NDR Exceptions" },
  { key: DeliveryFilterKey.RTO, label: "RTO (Returns)" },
  { key: PickupStatus.COMPLETED, label: "Delivered (POD)" },
  { key: DeliveryFilterKey.ALL, label: "All" },
];

/** Default receiver of a return at the seller's dock. */
const RTO_RECEIVER_DEFAULT = "Seller warehouse";

function _getManifestBadgeClass(status: ManifestStatus): string {
  switch (status) {
    case ManifestStatus.SCHEDULED:
      return "bg-sky-100 text-sky-800 border-sky-200";
    case ManifestStatus.OUT_FOR_PICKUP:
      return "bg-amber-100 text-amber-900 border-amber-300";
    case ManifestStatus.PICKED:
      return "bg-emerald-100 text-emerald-800 border-emerald-200";
    case ManifestStatus.NOT_PICKED:
      return "bg-rose-100 text-rose-800 border-rose-200";
    case ManifestStatus.CANCELED:
      return "bg-slate-100 text-slate-600 border-slate-200";
    default:
      return "bg-slate-100 text-slate-700 border-slate-200";
  }
}

function _getShipmentBadgeClass(status: PickupStatus): string {
  switch (status) {
    case PickupStatus.IN_TRANSIT:
      return "bg-amber-100 text-amber-900 border-amber-300";
    case PickupStatus.OUT_FOR_DELIVERY:
      return "bg-sky-100 text-sky-900 border-sky-300";
    case PickupStatus.RTO_INITIATED:
    case PickupStatus.RTO_IN_TRANSIT:
      return "bg-orange-100 text-orange-900 border-orange-300";
    case PickupStatus.ASSIGNED:
      return "bg-sky-100 text-sky-800 border-sky-200";
    case PickupStatus.OPEN:
      return "bg-slate-100 text-slate-800 border-slate-200";
    case PickupStatus.COMPLETED:
      return "bg-emerald-100 text-emerald-800 border-emerald-200";
    case PickupStatus.EXCEPTION:
    case PickupStatus.QC_FAILED:
    case PickupStatus.REJECTED_AT_PICKUP:
      return "bg-rose-100 text-rose-800 border-rose-200";
    default:
      return "bg-slate-100 text-slate-700 border-slate-200";
  }
}

function _formatInr(val?: number | null): string {
  if (val === undefined || val === null) {
    return "0.00";
  }
  return Number(val).toLocaleString("en-IN", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export default function OperationsControlTowerPage() {
  const { tenant, tenantSlug, routeTo } = useTenant();
  const { capabilities } = useUser();

  const [workspaceMode, setWorkspaceMode] =
    useState<OpsWorkspaceMode>("CONTROL_TOWER");
  const [activeTab, setActiveTab] = useState<string>("pickups");

  const opsCacheKey = buildQueryCacheKey(
    tenantSlug,
    "session",
    "ops-workspace"
  );
  const cachedOps = getCachedQuery<{
    manifests: ManifestResponse[];
    shipments: PickupRead[];
  }>(opsCacheKey);

  const [manifests, setManifests] = useState<ManifestResponse[]>(
    () => cachedOps?.manifests ?? []
  );
  const [shipments, setShipments] = useState<PickupRead[]>(
    () => cachedOps?.shipments ?? []
  );
  const [loading, setLoading] = useState<boolean>(
    () => !hasCachedQuery(opsCacheKey)
  );
  const [busyActionId, setBusyActionId] = useState<string | null>(null);

  // Tab 1 filters, Dispatch checklist dialog, & Not-Picked dialog state
  const [pickupSearch, setPickupSearch] = useState<string>("");
  const [pickupStatusFilter, setPickupStatusFilter] = useState<string>(PICKUP_FILTER_ACTIVE);
  const [dispatchTarget, setDispatchTarget] =
    useState<ManifestResponse | null>(null);
  const [submittingDispatch, setSubmittingDispatch] = useState<boolean>(false);
  const [notPickedTarget, setNotPickedTarget] =
    useState<ManifestResponse | null>(null);
  const [failureReasonInput, setFailureReasonInput] = useState<string>("");
  const [submittingNotPicked, setSubmittingNotPicked] =
    useState<boolean>(false);

  // Tab 2 filters, inline POD inputs, NDR dialog, & Doorstep QC dialog state
  const [deliverySearch, setDeliverySearch] = useState<string>("");
  const [deliveryStatusFilter, setDeliveryStatusFilter] =
    useState<DeliveryFilter>(DeliveryFilterKey.ACTIVE);
  // E-10: doorstep inputs survive a reload / lost signal (sessionStorage, per tab). The
  // inputs only render after the first load, so the server render never shows them.
  const [initialPodDraft] = useState<PodDraft>(() =>
    typeof window === "undefined"
      ? EMPTY_POD_DRAFT
      : loadPodDraft(window.sessionStorage, tenantSlug)
  );
  const [otpInputs, setOtpInputs] = useState<Record<string, string>>(
    initialPodDraft.otp
  );
  const [receiverInputs, setReceiverInputs] = useState<Record<string, string>>(
    initialPodDraft.receiver
  );
  const [ndrTarget, setNdrTarget] = useState<PickupRead | null>(null);
  const [selectedNdrReason, setSelectedNdrReason] =
    useState<NdrExceptionReason>(NdrExceptionReason.CONSIGNEE_UNAVAILABLE);
  const [ndrRemarkInput, setNdrRemarkInput] = useState<string>("");
  const [submittingNdr, setSubmittingNdr] = useState<boolean>(false);
  const [qcFailTarget, setQcFailTarget] = useState<PickupRead | null>(null);
  const [qcFailRemarkInput, setQcFailRemarkInput] = useState<string>("");
  const [submittingQcFail, setSubmittingQcFail] = useState<boolean>(false);
  // E-01: one-tap "Confirm Picked Up" first asks "Picked N of M from <warehouse>?"
  const [pickupConfirmTarget, setPickupConfirmTarget] =
    useState<ManifestResponse | null>(null);
  const [qcPassedConfirmed, setQcPassedConfirmed] = useState<boolean>(false);
  const lastFetchAtRef = useRef<number>(0);

  // Tab 3 Hub Sorter Audit state
  const [auditSearchQuery, setAuditSearchQuery] = useState<string>("");
  const [selectedAuditShipmentId, setSelectedAuditShipmentId] = useState<
    string | null
  >(null);
  const [measurementTarget, setMeasurementTarget] = useState<PickupRead | null>(
    null
  );
  // Remounts the Record measurement dialog per open (fresh Idempotency-Key each time).
  const [measurementDialogKey, setMeasurementDialogKey] = useState<number>(0);
  // Per-PUR inline "Actual pieces" entered directly on the My Pickups card (purId -> awb -> count).
  const [cardActualPieces, setCardActualPieces] = useState<
    Record<string, Record<string, string>>
  >({});

  // Auto-detect viewport on initial mount (<768px defaults to Field Executive App)
  useEffect(() => {
    if (typeof window !== "undefined") {
      if (window.innerWidth < MOBILE_VIEWPORT_BREAKPOINT) {
        setWorkspaceMode("FIELD_EXEC");
      } else {
        setWorkspaceMode("CONTROL_TOWER");
      }
    }
  }, []);

  /**
   * Loads PURs + the live shipment queue.
   *
   * @param showSpinner - False for background refreshes (focus / retry), so the list and the
   *   rider's typed inputs stay on screen.
   */
  const loadOpsData = useCallback(async (showSpinner: boolean) => {
    const cached = getCachedQuery<{
      manifests: ManifestResponse[];
      shipments: PickupRead[];
    }>(opsCacheKey);
    if (cached !== null) {
      setManifests(cached.manifests);
      setShipments(cached.shipments);
      setLoading(false);
    } else if (showSpinner) {
      setLoading(true);
    }
    lastFetchAtRef.current = Date.now();
    try {
      const [manifestRows, activePage, deliveredPage] = await Promise.all([
        ManifestsService.listManifests(
          undefined,
          undefined,
          undefined,
          tenantSlug
        ),
        // Live queue: only shipments that still need field action, so older
        // in-transit / NDR / COD parcels never drop off behind newer bookings.
        ShipmentsService.listShipments(
          1,
          SHIPMENT_FETCH_LIMIT,
          undefined,
          OPS_ACTIVE_STATUSES.slice(),
          undefined,
          tenantSlug
        ),
        // Recent deliveries feed the COD "cash collected" view.
        ShipmentsService.listShipments(
          1,
          SHIPMENT_FETCH_LIMIT,
          undefined,
          [PickupStatus.COMPLETED, PickupStatus.QC_FAILED],
          undefined,
          tenantSlug
        ),
      ]);
      const nextManifests = manifestRows || [];
      const nextShipments = (activePage?.items || []).concat(
        deliveredPage?.items || []
      );
      setCachedQuery(opsCacheKey, {
        manifests: nextManifests,
        shipments: nextShipments,
      });
      setManifests(nextManifests);
      setShipments(nextShipments);
    } catch (err: unknown) {
      if (cached === null) {
        toast.error(
          extractApiErrorMessage(err, "Failed to load operations data.")
        );
      }
    } finally {
      setLoading(false);
    }
  }, [tenantSlug, opsCacheKey]);

  const fetchOpsData = useCallback(() => loadOpsData(true), [loadOpsData]);

  useEffect(() => {
    fetchOpsData();
  }, [fetchOpsData]);

  // E-10: refresh when the rider comes back to the app (e.g. out of a basement), throttled.
  useEffect(() => {
    const handleVisible = () => {
      if (document.visibilityState !== "visible") return;
      if (Date.now() - lastFetchAtRef.current < FOCUS_REFETCH_MIN_INTERVAL_MS) return;
      void loadOpsData(false);
    };
    document.addEventListener("visibilitychange", handleVisible);
    window.addEventListener("focus", handleVisible);
    return () => {
      document.removeEventListener("visibilitychange", handleVisible);
      window.removeEventListener("focus", handleVisible);
    };
  }, [loadOpsData]);

  // E-10: keep saving the doorstep OTP / receiver inputs for this tab.
  useEffect(() => {
    savePodDraft(window.sessionStorage, tenantSlug, {
      otp: otpInputs,
      receiver: receiverInputs,
    });
  }, [tenantSlug, otpInputs, receiverInputs]);

  // Helper to build full public tracking URL for consignee messages
  const buildPublicTrackingUrl = useCallback(
    (trackingId: string | null | undefined): string => {
      const safeId = trackingId || "";
      const relPath = routeTo(`/track/${safeId}`);
      if (typeof window !== "undefined") {
        return `${window.location.origin}${relPath}`;
      }
      return relPath;
    },
    [routeTo]
  );

  // Filtered First-Mile Pickups
  const filteredManifests = useMemo(() => {
    const query = pickupSearch.trim().toLowerCase();
    return manifests.filter((m) => {
      if (!matchesPickupFilter(m.status, pickupStatusFilter)) {
        return false;
      }
      if (!query) {
        return true;
      }
      const purNum = (m.pickup_request_number || m.id).toLowerCase();
      const locName = (m.pickup_location_name || "").toLowerCase();
      const locAddr = (m.pickup_location_address || "").toLowerCase();
      return (
        purNum.includes(query) ||
        locName.includes(query) ||
        locAddr.includes(query)
      );
    });
  }, [manifests, pickupSearch, pickupStatusFilter]);

  // Last-Mile shipments for Tab 2 (D-01: OFD + RTO legs included, see ops-field.ts)
  const activeDeliveryShipments = useMemo(() => {
    const query = deliverySearch.trim().toLowerCase();

    return shipments.filter((s) => {
      if (!matchesDeliveryFilter(s, deliveryStatusFilter)) {
        return false;
      }

      if (!query) {
        return true;
      }
      const awb = (s.tracking_id || s.id).toLowerCase();
      const consignee = (s.delivery_address?.name || "").toLowerCase();
      const phone = (s.delivery_address?.phone || "").toLowerCase();
      const city = (s.delivery_address?.city || "").toLowerCase();
      return (
        awb.includes(query) ||
        consignee.includes(query) ||
        phone.includes(query) ||
        city.includes(query)
      );
    });
  }, [shipments, deliverySearch, deliveryStatusFilter]);

  // Tab 3 Hub Sorter Weight Audit filtered shipments
  const auditableShipments = useMemo(() => {
    const query = auditSearchQuery.trim().toLowerCase();
    const candidates = shipments.filter(
      (s) => s.status !== PickupStatus.CANCELLED
    );
    if (!query) {
      return candidates;
    }
    return candidates.filter((s) => {
      const awb = (s.tracking_id || s.id).toLowerCase();
      const ref = (s.order_reference_id || "").toLowerCase();
      const consignee = (s.delivery_address?.name || "").toLowerCase();
      return (
        awb.includes(query) || ref.includes(query) || consignee.includes(query)
      );
    });
  }, [shipments, auditSearchQuery]);

  // Tab 4 door-cash shipments: amount comes from the backend `door_collectible` (WP2).
  const doorCollectionShipments = useMemo(() => {
    return shipments.filter(
      (s) =>
        Boolean(s.payment_details?.is_cod) &&
        s.status !== PickupStatus.CANCELLED
    );
  }, [shipments]);

  // KPI counts using neutral counter names
  const scheduledPickupCount = useMemo(
    () =>
      manifests.filter(
        (m) =>
          m.status === ManifestStatus.SCHEDULED ||
          m.status === ManifestStatus.OUT_FOR_PICKUP
      ).length,
    [manifests]
  );

  // E-09: count real Out-for-Delivery parcels, not In Transit.
  const outForDeliveryCount = useMemo(
    () =>
      shipments.filter((s) => s.status === PickupStatus.OUT_FOR_DELIVERY)
        .length,
    [shipments]
  );

  const activeExceptionCount = useMemo(
    () =>
      shipments.filter((s) => s.status === PickupStatus.EXCEPTION).length,
    [shipments]
  );

  const pendingDoorCollectionCount = useMemo(
    () => shipments.filter(isDoorCashPending).length,
    [shipments]
  );

  // Tab 1 Handlers: First-Mile Pickups
  const handleMarkOutForPickup = async (manifest: ManifestResponse) => {
    setBusyActionId(manifest.id);
    try {
      await ManifestsService.markManifestOutForPickup(manifest.id, tenantSlug);
      const label = manifest.pickup_request_number || manifest.id.slice(0, 8);
      toast.success(`PUR ${label} marked Out for Pickup!`);
      await fetchOpsData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to mark Out for Pickup.")
      );
    } finally {
      setBusyActionId(null);
    }
  };

  const handleConfirmPickedUp = (manifest: ManifestResponse) => {
    setDispatchTarget(manifest);
  };

  /**
   * Linked return shipments of a PUR whose doorstep QC the rider must check (E-04).
   *
   * @param manifest - Pickup request card.
   * @returns Reverse shipments with QC required or QC notes, from the loaded queue.
   */
  const getQcReturnShipments = (manifest: ManifestResponse): PickupRead[] =>
    (manifest.shipments ?? [])
      .map((item) => shipments.find((s) => s.id === item.id))
      .filter(
        (s): s is PickupRead =>
          s !== undefined &&
          s.shipment_type === ShipmentType.REVERSE &&
          (s.qc_required || Boolean(s.qc_notes))
      );

  const handleOpenPickupConfirm = (manifest: ManifestResponse) => {
    setQcPassedConfirmed(false);
    setPickupConfirmTarget(manifest);
  };

  const handleSubmitPickupConfirm = async () => {
    if (!pickupConfirmTarget) return;
    const target = pickupConfirmTarget;
    setPickupConfirmTarget(null);
    await handleConfirmCardPickup(target);
  };

  const handleConfirmCardPickup = async (manifest: ManifestResponse) => {
    setBusyActionId(manifest.id);
    try {
      const linked = manifest.shipments ?? [];
      const pickedIds = linked.map((s) => s.id);
      const piecesMap = cardActualPieces[manifest.id] ?? {};
      const measurements: DispatchMeasurement[] = [];

      for (const s of linked) {
        const awb = s.tracking_id || s.id.slice(0, 8).toUpperCase();
        const count = parseActualPieces(piecesMap[awb]);
        if (count !== null) {
          const known = shipments.find((item) => item.id === s.id);
          const m = await buildMeasurementForPieceCount(
            s.id,
            count,
            tenantSlug,
            known
          );
          measurements.push(m);
        }
      }

      await ManifestsService.dispatchManifest(
        manifest.id,
        tenantSlug,
        pickedIds.length > 0
          ? {
              picked_shipment_ids: pickedIds,
              measurements: measurements.length > 0 ? measurements : undefined,
            }
          : undefined
      );
      const label =
        manifest.pickup_request_number || manifest.id.slice(0, 8);
      toast.success(
        measurements.length > 0
          ? `PUR ${label} dispatched with actual pieces for ${measurements.length} AWB(s). Charges updated where the pieces differ.`
          : `PUR ${label} dispatched! Picked shipments are now In Transit and have their delivery OTPs.`
      );
      if (measurements.length > 0) {
        window.dispatchEvent(new CustomEvent("wallet-updated"));
      }
      await fetchOpsData();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to dispatch pickup."));
    } finally {
      setBusyActionId(null);
    }
  };

  const handleSubmitDispatch = async (
    pickedIds: string[],
    measurements: DispatchMeasurement[]
  ) => {
    if (!dispatchTarget) return;
    setSubmittingDispatch(true);
    setBusyActionId(dispatchTarget.id);
    try {
      await ManifestsService.dispatchManifest(
        dispatchTarget.id,
        tenantSlug,
        pickedIds.length > 0
          ? {
              picked_shipment_ids: pickedIds,
              measurements: measurements.length > 0 ? measurements : undefined,
            }
          : undefined
      );
      const label =
        dispatchTarget.pickup_request_number || dispatchTarget.id.slice(0, 8);
      toast.success(
        measurements.length > 0
          ? `PUR ${label} dispatched with actual pieces for ${measurements.length} AWB(s). Charges updated where the pieces differ.`
          : `PUR ${label} dispatched! Picked shipments are now In Transit and have their delivery OTPs.`
      );
      if (measurements.length > 0) {
        window.dispatchEvent(new CustomEvent("wallet-updated"));
      }
      setDispatchTarget(null);
      await fetchOpsData();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to dispatch pickup."));
    } finally {
      setSubmittingDispatch(false);
      setBusyActionId(null);
    }
  };

  const handleOpenNotPickedDialog = (manifest: ManifestResponse) => {
    setNotPickedTarget(manifest);
    setFailureReasonInput(NOT_PICKED_REASON_PRESETS[0]);
  };

  const handleSubmitNotPicked = async () => {
    if (!notPickedTarget) return;
    const trimmedReason = failureReasonInput.trim();
    if (!trimmedReason) {
      toast.error("Please enter or select a pickup failure reason.");
      return;
    }
    setSubmittingNotPicked(true);
    try {
      await ManifestsService.markManifestNotPicked(
        notPickedTarget.id,
        { failure_reason: trimmedReason },
        tenantSlug
      );
      const label =
        notPickedTarget.pickup_request_number ||
        notPickedTarget.id.slice(0, 8);
      toast.success(
        `PUR ${label} marked Not Picked. Linked shipments released back to Ready to Ship.`
      );
      setNotPickedTarget(null);
      setFailureReasonInput("");
      await fetchOpsData();
    } catch (err: unknown) {
      toast.error(extractApiErrorMessage(err, "Failed to mark Not Picked."));
    } finally {
      setSubmittingNotPicked(false);
    }
  };

  const handleDownloadRunsheet = async (manifestId: string) => {
    setBusyActionId(`pdf-${manifestId}`);
    try {
      await downloadManifestRunsheetPdf(manifestId);
      toast.success("Driver Run-Sheet PDF downloaded!");
    } catch {
      toast.error("Failed to download Driver Run-Sheet PDF.");
    } finally {
      setBusyActionId(null);
    }
  };

  // Tab 2 Handlers: Last-Mile Deliveries & 6-Digit OTP POD
  const handleOtpInputChange = (shipmentId: string, val: string) => {
    const cleaned = val.replace(/\D/g, "").slice(0, 6);
    setOtpInputs((prev) => Object.assign({}, prev, { [shipmentId]: cleaned }));
  };

  const handleReceiverInputChange = (shipmentId: string, val: string) => {
    setReceiverInputs((prev) => Object.assign({}, prev, { [shipmentId]: val }));
  };

  /** Drops a shipment's saved doorstep inputs once its move succeeded (E-10). */
  const clearDoorstepInputs = (shipmentId: string) => {
    setOtpInputs((prev) => withoutEntry(prev, shipmentId));
    setReceiverInputs((prev) => withoutEntry(prev, shipmentId));
  };

  /**
   * E-10: after a timeout the Delivered call may have committed anyway. Re-read the
   * shipment; if the server already shows the target status, treat the attempt as done.
   *
   * @param shipmentId - Shipment that was being moved.
   * @param target - Status the rider tried to set.
   * @returns True when the server already has the shipment in `target`.
   */
  const isAlreadyInStatus = async (
    shipmentId: string,
    target: PickupStatus
  ): Promise<boolean> => {
    try {
      const latest = await ShipmentsService.getShipmentDetails(
        shipmentId,
        tenantSlug
      );
      return latest.status === target;
    } catch {
      return false;
    }
  };

  const handleVerifyPodAndDeliver = async (shipment: PickupRead) => {
    const enteredOtp = (otpInputs[shipment.id] || "").trim();
    const enteredReceiver = (
      receiverInputs[shipment.id] || "Consignee (Self)"
    ).trim();

    if (enteredOtp.length !== 6) {
      toast.error(
        "Please enter the 6-digit Delivery Verification OTP from the consignee."
      );
      return;
    }
    if (!enteredReceiver) {
      toast.error("Please specify who received the shipment at the doorstep.");
      return;
    }

    const awbLabel = shipment.tracking_id || shipment.id.slice(0, 8);
    setBusyActionId(shipment.id);
    try {
      await ShipmentsService.updateShipment(
        shipment.id,
        {
          status: PickupStatus.COMPLETED,
          delivery_otp: enteredOtp,
          pod_received_by: enteredReceiver,
          expected_cod_amount: shipment.payment_details?.is_cod
            ? Number(shipment.payment_details?.cod_amount ?? 0)
            : 0,
          is_public: true,
          comment: "Doorstep 6-digit OTP verified by field executive",
        } as unknown as Parameters<typeof ShipmentsService.updateShipment>[1],
        tenantSlug
      );
      toast.success(
        `AWB ${awbLabel} verified via 6-digit OTP and marked Delivered!`
      );
      clearDoorstepInputs(shipment.id);
      await fetchOpsData();
    } catch (err: unknown) {
      if (await isAlreadyInStatus(shipment.id, PickupStatus.COMPLETED)) {
        toast.success(`AWB ${awbLabel} is already marked Delivered.`);
        clearDoorstepInputs(shipment.id);
        await fetchOpsData();
        return;
      }
      toast.error(
        extractApiErrorMessage(
          err,
          "OTP verification failed. Please check the 6-digit OTP."
        )
      );
    } finally {
      setBusyActionId(null);
    }
  };

  /**
   * Moves an RTO parcel one step on its way back to the seller (D-01 RTO card actions).
   *
   * @param shipment - RTO shipment.
   * @param target - RTO_IN_TRANSIT or RTO_DELIVERED (only offered when the server allows it).
   */
  const handleRtoMove = async (shipment: PickupRead, target: PickupStatus) => {
    const awbLabel = shipment.tracking_id || shipment.id.slice(0, 8);
    const isHandover = target === PickupStatus.RTO_DELIVERED;
    const receiver = (receiverInputs[shipment.id] || "").trim();
    if (isHandover && !receiver) {
      toast.error("Enter who received the return at the seller's location.");
      return;
    }
    setBusyActionId(shipment.id);
    try {
      await ShipmentsService.updateShipment(
        shipment.id,
        {
          status: target,
          pod_received_by: isHandover ? receiver : undefined,
          is_public: true,
          comment: isHandover
            ? `Return handed over to the seller (received by ${receiver})`
            : "Return (RTO) on its way back to the seller",
        },
        tenantSlug
      );
      toast.success(
        isHandover
          ? `AWB ${awbLabel} returned to the seller.`
          : `AWB ${awbLabel} marked RTO in transit.`
      );
      clearDoorstepInputs(shipment.id);
      await fetchOpsData();
    } catch (err: unknown) {
      if (await isAlreadyInStatus(shipment.id, target)) {
        toast.success(`AWB ${awbLabel} was already updated.`);
        await fetchOpsData();
        return;
      }
      toast.error(extractApiErrorMessage(err, "Failed to update the return."));
    } finally {
      setBusyActionId(null);
    }
  };

  const handleMarkOutForDelivery = async (shipment: PickupRead) => {
    setBusyActionId(shipment.id);
    try {
      await ShipmentsService.updateShipment(
        shipment.id,
        {
          status: PickupStatus.OUT_FOR_DELIVERY,
          is_public: true,
          comment: "Shipment is out for delivery",
        },
        tenantSlug
      );
      toast.success(
        `AWB ${shipment.tracking_id || shipment.id.slice(0, 8)} marked Out for Delivery!`
      );
      await fetchOpsData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(
          err,
          "Failed to mark out for delivery."
        )
      );
    } finally {
      setBusyActionId(null);
    }
  };

  const handleOpenNdrDialog = (shipment: PickupRead) => {
    setNdrTarget(shipment);
    setSelectedNdrReason(NdrExceptionReason.CONSIGNEE_UNAVAILABLE);
    setNdrRemarkInput("");
  };

  const handleOpenQcFailDialog = (shipment: PickupRead) => {
    setQcFailTarget(shipment);
    setQcFailRemarkInput("");
  };

  const handleSubmitQcFail = async () => {
    if (!qcFailTarget) return;
    const remark = qcFailRemarkInput.trim();
    if (!remark) {
      toast.error("Please enter the doorstep QC failure reason.");
      return;
    }
    setSubmittingQcFail(true);
    try {
      await ShipmentsService.updateShipment(
        qcFailTarget.id,
        {
          status: PickupStatus.QC_FAILED,
          comment: remark,
          is_public: true,
        },
        tenantSlug
      );
      toast.success(
        `Doorstep QC failed for Return AWB ${qcFailTarget.tracking_id || qcFailTarget.id.slice(0, 8)}: return not picked up.`
      );
      setQcFailTarget(null);
      setQcFailRemarkInput("");
      await fetchOpsData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to record Doorstep QC failure.")
      );
    } finally {
      setSubmittingQcFail(false);
    }
  };

  const activeNdrLabel = useMemo(
    () =>
      (
        FIELD_NDR_SELECT_OPTIONS.find((item) => item.value === selectedNdrReason) ||
        FIELD_NDR_SELECT_OPTIONS[0]
      ).label,
    [selectedNdrReason]
  );

  const handleSubmitNdrException = async () => {
    if (!ndrTarget) return;
    const remark = ndrRemarkInput.trim();
    if (!remark) {
      toast.error("Please enter a field executive remark for this NDR.");
      return;
    }

    setSubmittingNdr(true);
    try {
      await ShipmentsService.updateShipment(
        ndrTarget.id,
        {
          status: PickupStatus.EXCEPTION,
          ndr_reason: selectedNdrReason,
          ndr_remark: remark,
          is_public: true,
          comment: `Field NDR (${activeNdrLabel}): ${remark}`,
        },
        tenantSlug
      );
      toast.success(
        `NDR (${activeNdrLabel}) logged on AWB ${ndrTarget.tracking_id || ndrTarget.id.slice(0, 8)}.`
      );
      setNdrTarget(null);
      await fetchOpsData();
    } catch (err: unknown) {
      toast.error(
        extractApiErrorMessage(err, "Failed to raise NDR exception.")
      );
    } finally {
      setSubmittingNdr(false);
    }
  };

  // Tab 3 Handler: open the Record measurement dialog for one AWB
  const handleOpenMeasurement = (shipment: PickupRead) => {
    setSelectedAuditShipmentId(shipment.id);
    setMeasurementDialogKey((key) => key + 1);
    setMeasurementTarget(shipment);
  };

  const isFieldExecMode = workspaceMode === "FIELD_EXEC";

  return (
    <div
      className={cn(
        "mx-auto space-y-6 pb-16 animate-in fade-in duration-300",
        isFieldExecMode ? "max-w-xl" : "max-w-7xl"
      )}
    >
      {/* Top Operations Header + Dual-Mode Switcher Pill */}
      <ScreenGuideBanner
        guideId="ops-control-tower"
        title="How the Operations Control Tower Works (3 Steps)"
        delhiveryEquivalent="Delhivery One: Internal Hub & Field App"
        steps={OPS_GUIDE_STEPS}
        isStaff={true}
      />
      <div className="rounded-2xl border border-border bg-card p-4 sm:p-6 shadow-xs">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex items-start gap-3.5">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-xs">
              {isFieldExecMode ? (
                <Smartphone className="h-6 w-6" />
              ) : (
                <Monitor className="h-6 w-6" />
              )}
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight text-foreground">
                  {isFieldExecMode
                    ? "Field Executive App (Mobile POD & Pickup)"
                    : "Operations Control Tower"}
                </h1>
                <Badge
                  variant="outline"
                  className="bg-emerald-50 text-emerald-800 border-emerald-200 font-bold text-xs"
                >
                  {capabilities.canManageSettings ? "Admin / Hub Ops" : "Field Operations"}
                </Badge>
              </div>
              <p className="mt-1 text-xs sm:text-sm text-muted-foreground">
                {isFieldExecMode
                  ? "Handheld dock pickup scanner, doorstep 6-digit OTP verification, WhatsApp consignee alerts, and NDR logging."
                  : "Unified command center for First-Mile PUR dispatches, Last-Mile 6-Digit OTP POD, Hub Sorter Audits, and Doorstep Cash."}
              </p>
            </div>
          </div>

          {/* Mode Switcher Pill + Refresh */}
          <div className="flex flex-wrap items-center gap-2">
            <div
              role="group"
              aria-label="Operations Workspace Mode Switcher"
              className="inline-flex rounded-xl border border-border bg-muted p-1"
            >
              <button
                type="button"
                onClick={() => setWorkspaceMode("CONTROL_TOWER")}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition-all",
                  workspaceMode === "CONTROL_TOWER"
                    ? "bg-primary text-primary-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Monitor className="h-3.5 w-3.5" />
                <span>Control Tower (Admin Desktop)</span>
              </button>
              <button
                type="button"
                onClick={() => setWorkspaceMode("FIELD_EXEC")}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-bold transition-all",
                  workspaceMode === "FIELD_EXEC"
                    ? "bg-primary text-primary-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                <Smartphone className="h-3.5 w-3.5" />
                <span>Field Executive App (Mobile POD & Pickup)</span>
              </button>
            </div>

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={fetchOpsData}
              disabled={loading}
              className="h-9 font-semibold"
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              Refresh
            </Button>
          </div>
        </div>

        {/* Summary KPI Strip */}
        <div
          className={cn(
            "mt-5 grid gap-3",
            isFieldExecMode
              ? "grid-cols-2"
              : "grid-cols-2 sm:grid-cols-4"
          )}
        >
          <button
            type="button"
            onClick={() => setActiveTab("pickups")}
            className="flex items-center justify-between rounded-xl border border-border bg-background p-3.5 text-left transition hover:border-primary"
          >
            <div>
              <p className="text-xs font-semibold text-muted-foreground">
                Active First-Mile PURs
              </p>
              <p className="mt-1 text-2xl font-extrabold text-foreground">
                {scheduledPickupCount}
              </p>
            </div>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-100 text-sky-800">
              <Truck className="h-5 w-5" />
            </div>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("deliveries")}
            className="flex items-center justify-between rounded-xl border border-border bg-background p-3.5 text-left transition hover:border-primary"
          >
            <div>
              <p className="text-xs font-semibold text-muted-foreground">
                Out for Delivery (OTP)
              </p>
              <p className="mt-1 text-2xl font-extrabold text-amber-800">
                {outForDeliveryCount}
              </p>
            </div>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-100 text-amber-800">
              <KeyRound className="h-5 w-5" />
            </div>
          </button>

          <button
            type="button"
            onClick={() => {
              setActiveTab("deliveries");
              setDeliveryStatusFilter(PickupStatus.EXCEPTION);
            }}
            className="flex items-center justify-between rounded-xl border border-border bg-background p-3.5 text-left transition hover:border-primary"
          >
            <div>
              <p className="text-xs font-semibold text-muted-foreground">
                Active NDR Exceptions
              </p>
              <p className="mt-1 text-2xl font-extrabold text-rose-700">
                {activeExceptionCount}
              </p>
            </div>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-rose-100 text-rose-800">
              <AlertTriangle className="h-5 w-5" />
            </div>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab("cash")}
            className="flex items-center justify-between rounded-xl border border-border bg-background p-3.5 text-left transition hover:border-primary"
          >
            <div>
              <p className="text-xs font-semibold text-muted-foreground">
                Doorstep Cash Queue
              </p>
              <p className="mt-1 text-2xl font-extrabold text-emerald-700">
                {pendingDoorCollectionCount}
              </p>
            </div>
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-100 text-emerald-800">
              <Banknote className="h-5 w-5" />
            </div>
          </button>
        </div>
      </div>

      {/* 4 Operations Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="flex h-auto w-full flex-wrap justify-start gap-1.5 rounded-xl border border-border bg-card p-1.5">
          <TabsTrigger
            value="pickups"
            className="flex-1 sm:flex-initial py-2 px-3 text-xs sm:text-sm font-bold"
          >
            <Truck className="mr-1.5 h-4 w-4" />
            <span>First-Mile Pickups</span>
          </TabsTrigger>
          <TabsTrigger
            value="deliveries"
            className="flex-1 sm:flex-initial py-2 px-3 text-xs sm:text-sm font-bold"
          >
            <KeyRound className="mr-1.5 h-4 w-4" />
            <span>Last-Mile Deliveries &amp; 6-Digit OTP POD</span>
          </TabsTrigger>
          <TabsTrigger
            value="sorter"
            className="flex-1 sm:flex-initial py-2 px-3 text-xs sm:text-sm font-bold"
          >
            <Scale className="mr-1.5 h-4 w-4" />
            <span>Hub Measurements</span>
          </TabsTrigger>
          <TabsTrigger
            value="cash"
            className="flex-1 sm:flex-initial py-2 px-3 text-xs sm:text-sm font-bold"
          >
            <Banknote className="mr-1.5 h-4 w-4" />
            <span>
              Field Cash (COD) Summary
            </span>
          </TabsTrigger>
        </TabsList>

        {/* =================================================================== */}
        {/* TAB 1: FIRST-MILE PICKUPS (TODAY'S PURs)                            */}
        {/* =================================================================== */}
        <TabsContent value="pickups" className="space-y-4">
          <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-border bg-card p-4">
            <div className="relative min-w-0 flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={pickupSearch}
                onChange={(e) => setPickupSearch(e.target.value)}
                placeholder="Search by 9-digit PUR number or warehouse location"
                className="min-w-0 w-full pl-9 h-10 bg-background"
              />
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <Select
                value={pickupStatusFilter}
                onValueChange={setPickupStatusFilter}
              >
                <SelectTrigger className="h-10 w-full sm:w-48 min-w-0 bg-background font-semibold">
                  <SelectValue placeholder="Filter status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={PICKUP_FILTER_ACTIVE}>
                    To pick up
                  </SelectItem>
                  <SelectItem value={PICKUP_FILTER_ALL}>All Pickup Statuses</SelectItem>
                  <SelectItem value={ManifestStatus.SCHEDULED}>
                    Scheduled
                  </SelectItem>
                  <SelectItem value={ManifestStatus.OUT_FOR_PICKUP}>
                    Out for Pickup
                  </SelectItem>
                  <SelectItem value={ManifestStatus.PICKED}>
                    Picked Up
                  </SelectItem>
                  <SelectItem value={ManifestStatus.NOT_PICKED}>
                    Not Picked
                  </SelectItem>
                  <SelectItem value={ManifestStatus.CANCELED}>
                    Cancelled
                  </SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {loading && manifests.length === 0 ? (
            <div
              data-testid="ops-pickups-loading-skeleton"
              className="grid gap-4 grid-cols-1 lg:grid-cols-2"
            >
              {[0, 1].map((idx) => (
                <div
                  key={idx}
                  className="h-48 rounded-xl border border-border bg-card p-5 animate-pulse"
                />
              ))}
            </div>
          ) : filteredManifests.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-10 text-center">
              <Truck className="mx-auto h-10 w-10 text-muted-foreground" />
              <p className="mt-3 text-base font-bold text-foreground">
                No Pickup Requests matching current filter
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Warehouse pickup requests (PURs) will appear here once scheduled
                by merchants.
              </p>
            </div>
          ) : (
            <div
              className={cn(
                "grid gap-4",
                isFieldExecMode ? "grid-cols-1" : "grid-cols-1 lg:grid-cols-2"
              )}
            >
              {filteredManifests.map((m) => {
                const purDisplayId =
                  m.pickup_request_number || m.id.slice(0, 8).toUpperCase();
                const isBusy = busyActionId === m.id;
                const isPdfBusy = busyActionId === `pdf-${m.id}`;
                const expectedCount = m.expected_awbs ?? m.total_boxes ?? 0;
                const pickedCount = m.picked_awbs ?? 0;
                const qcReturns = getQcReturnShipments(m);

                return (
                  <div
                    key={m.id}
                    data-testid={`ops.pickup-card.${purDisplayId}`}
                    className="flex min-w-0 overflow-hidden flex-col justify-between rounded-xl border border-border bg-card p-4 sm:p-5 shadow-xs space-y-4"
                  >
                    <div className="min-w-0 space-y-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-base font-extrabold text-foreground">
                              PUR #{purDisplayId}
                            </span>
                            {m.service_flow && (
                              <Badge
                                variant="secondary"
                                className="text-[11px] font-bold"
                              >
                                {m.service_flow}
                              </Badge>
                            )}
                          </div>
                          <p className="mt-0.5 text-xs text-muted-foreground font-medium">
                            Scheduled: {safeFormatDate(m.scheduled_date)} ·{" "}
                            {formatTimeSlot(m.time_slot)}
                          </p>
                        </div>

                        <Badge
                          variant="outline"
                          className={cn(
                            "font-bold text-xs",
                            _getManifestBadgeClass(m.status)
                          )}
                        >
                          {getManifestStatusDisplay(m.status).label}
                        </Badge>
                      </div>

                      {/* Warehouse Location Details */}
                      <div className="rounded-lg border border-border bg-muted/40 p-3 space-y-1">
                        <div className="flex items-center gap-1.5 text-xs font-bold text-foreground">
                          <Building2 className="h-3.5 w-3.5 text-primary shrink-0" />
                          <span>
                            {m.pickup_location_name || "Merchant Warehouse Dock"}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground pl-5">
                          {m.pickup_location_address ||
                            "Registered pickup location"}
                        </p>
                      </div>

                      {/* Expected vs Picked AWBs */}
                      <div className="grid grid-cols-3 gap-2 text-center">
                        <div className="rounded-lg border border-border bg-background p-2">
                          <p className="text-[11px] font-semibold text-muted-foreground">
                            Expected AWBs
                          </p>
                          <p className="font-mono text-sm font-extrabold text-foreground">
                            {expectedCount}
                          </p>
                        </div>
                        <div className="rounded-lg border border-border bg-background p-2">
                          <p className="text-[11px] font-semibold text-muted-foreground">
                            Picked AWBs
                          </p>
                          <p className="font-mono text-sm font-extrabold text-emerald-700">
                            {pickedCount}
                          </p>
                        </div>
                        <div className="rounded-lg border border-border bg-background p-2">
                          <p className="text-[11px] font-semibold text-muted-foreground">
                            Mode
                          </p>
                          <p className="text-xs font-bold text-foreground">
                            {m.is_blind_pickup ? "Blind Pickup" : "Manifested"}
                          </p>
                        </div>
                      </div>

                      {(m.status === ManifestStatus.SCHEDULED ||
                        m.status === ManifestStatus.OUT_FOR_PICKUP) &&
                        (m.shipments ?? []).length > 0 && (
                          <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-2.5">
                            <p className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                              Actual pieces per AWB (optional)
                            </p>
                            <div className="space-y-1.5">
                              {(m.shipments ?? []).map((s) => {
                                const awb =
                                  s.tracking_id ||
                                  s.id.slice(0, 8).toUpperCase();
                                return (
                                  <div
                                    key={s.id}
                                    className="flex items-center justify-between gap-2 text-xs"
                                  >
                                    <span className="min-w-0 truncate font-mono font-bold text-foreground">
                                      {awb}{" "}
                                      <span className="font-sans font-normal text-muted-foreground">
                                        ({s.package_count ?? 1} booked)
                                      </span>
                                    </span>
                                    <Input
                                      type="number"
                                      inputMode="numeric"
                                      min="1"
                                      step="1"
                                      disabled={isBusy}
                                      data-testid={`ops.pickup-card.${purDisplayId}.actual-pieces-${awb}`}
                                      placeholder={String(s.package_count ?? 1)}
                                      value={
                                        cardActualPieces[m.id]?.[awb] ?? ""
                                      }
                                      onChange={(event) =>
                                        setCardActualPieces((prev) => ({
                                          ...prev,
                                          [m.id]: {
                                            ...(prev[m.id] ?? {}),
                                            [awb]: event.target.value,
                                          },
                                        }))
                                      }
                                      className="h-9 w-24 shrink-0 bg-background font-mono text-xs"
                                    />
                                  </div>
                                );
                              })}
                            </div>
                          </div>
                        )}

                      {(m.status === ManifestStatus.SCHEDULED ||
                        m.status === ManifestStatus.OUT_FOR_PICKUP) &&
                        qcReturns.length > 0 && (
                          <div
                            data-testid={`ops.pickup-card.${purDisplayId}.qc`}
                            className="space-y-1.5 rounded-lg border border-amber-300 bg-amber-50/70 p-2.5 text-xs text-amber-950"
                          >
                            <p className="flex items-center gap-1.5 font-extrabold uppercase tracking-wider text-amber-900">
                              <ClipboardCheck className="h-3.5 w-3.5" />
                              Return QC before you pick up
                            </p>
                            {qcReturns.map((r) => (
                              <div key={r.id} className="space-y-0.5">
                                <p className="font-mono font-bold">
                                  {r.tracking_id || r.id.slice(0, 8).toUpperCase()}
                                </p>
                                <p className="font-semibold">
                                  {r.qc_notes ||
                                    "Check item condition, tags/seals and serial number."}
                                </p>
                                {r.reason_for_return && (
                                  <p className="text-[11px] text-amber-800">
                                    Return reason: {r.reason_for_return}
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        )}

                      {m.failure_reason && (
                        <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-xs text-rose-900">
                          <span className="font-bold">Not Picked Reason: </span>
                          <span>{m.failure_reason}</span>
                        </div>
                      )}
                    </div>

                    {/* Action Buttons */}
                    <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-border">
                      {m.status === ManifestStatus.SCHEDULED && (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={isBusy}
                          data-testid={`ops.pickup-card.${purDisplayId}.out-for-pickup`}
                          onClick={() => handleMarkOutForPickup(m)}
                          className="border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100 font-bold"
                        >
                          {isBusy ? (
                            <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <Truck className="mr-1.5 h-3.5 w-3.5" />
                          )}
                          Mark Out for Pickup
                        </Button>
                      )}

                      {(m.status === ManifestStatus.SCHEDULED ||
                        m.status === ManifestStatus.OUT_FOR_PICKUP) && (
                        <>
                          <Button
                            type="button"
                            size="sm"
                            disabled={isBusy}
                            data-testid={`ops.pickup-card.${purDisplayId}.confirm`}
                            onClick={() => handleOpenPickupConfirm(m)}
                            className="bg-emerald-600 hover:bg-emerald-700 text-white font-bold"
                          >
                            {isBusy ? (
                              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                            ) : (
                              <CheckCircle2 className="mr-1.5 h-3.5 w-3.5" />
                            )}
                            Confirm Picked Up (Dispatch)
                          </Button>

                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={isBusy}
                            data-testid={`ops.pickup-card.${purDisplayId}.checklist`}
                            onClick={() => handleConfirmPickedUp(m)}
                            className="font-bold"
                          >
                            <ClipboardCheck className="mr-1.5 h-3.5 w-3.5" />
                            Checklist &amp; box sizes
                          </Button>

                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={isBusy}
                            data-testid={`ops.pickup-card.${purDisplayId}.not-picked`}
                            onClick={() => handleOpenNotPickedDialog(m)}
                            className="border-rose-300 text-rose-700 hover:bg-rose-50 font-bold"
                          >
                            <XCircle className="mr-1.5 h-3.5 w-3.5" />
                            Mark Not Picked
                          </Button>
                        </>
                      )}

                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={isPdfBusy}
                        onClick={() => handleDownloadRunsheet(m.id)}
                        className="ml-auto font-semibold"
                      >
                        {isPdfBusy ? (
                          <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                        ) : (
                          <FileText className="mr-1.5 h-3.5 w-3.5 text-primary" />
                        )}
                        Run-Sheet PDF
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>

        {/* =================================================================== */}
        {/* TAB 2: LAST-MILE DELIVERIES & 6-DIGIT OTP POD                       */}
        {/* =================================================================== */}
        <TabsContent value="deliveries" className="space-y-4">
          <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl border border-border bg-card p-4">
            <div className="relative min-w-0 flex-1">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={deliverySearch}
                onChange={(e) => setDeliverySearch(e.target.value)}
                placeholder="Search by AWB, consignee name, mobile number, or city"
                className="min-w-0 w-full pl-9 h-10 bg-background"
              />
            </div>

            <div className="flex min-w-0 flex-wrap items-center gap-1.5">
              {DELIVERY_FILTER_CHIPS.map((tabItem) => (
                <Button
                  key={tabItem.key}
                  type="button"
                  size="sm"
                  variant={
                    deliveryStatusFilter === tabItem.key ? "default" : "outline"
                  }
                  onClick={() => setDeliveryStatusFilter(tabItem.key)}
                  className="h-9 text-xs font-bold"
                >
                  {tabItem.label}
                </Button>
              ))}
            </div>
          </div>

          {loading && shipments.length === 0 ? (
            <div className="space-y-3">
              {[0, 1].map((idx) => (
                <div
                  key={idx}
                  className="h-44 rounded-xl border border-border bg-card p-5 animate-pulse"
                />
              ))}
            </div>
          ) : activeDeliveryShipments.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-10 text-center">
              <Package className="mx-auto h-10 w-10 text-muted-foreground" />
              <p className="mt-3 text-base font-bold text-foreground">
                No shipments in this delivery filter
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Dispatch a First-Mile PUR or switch the status filter above to
                inspect other shipments.
              </p>
            </div>
          ) : (
            <div className="space-y-4">
              {activeDeliveryShipments.map((s) => {
                const awb = s.tracking_id || s.id.slice(0, 8).toUpperCase();
                const isBusy = busyActionId === s.id;
                // WP2: the door amount is the backend `door_collectible`, never recomputed here.
                const isCollectOnDelivery = s.door_collectible > 0;
                const collectAmountFormatted = _formatInr(s.door_collectible);
                const consigneeZip = s.delivery_address?.pincode || "";
                const trackingUrl = buildPublicTrackingUrl(awb);
                const tenantBrandName = tenant?.name || "Logismart";

                // E-08: message stage follows the real status; OTP text only once OFD.
                const notifyStage = consigneeStageForStatus(s.status);
                const canWhatsApp =
                  notifyStage !== null &&
                  hasWhatsAppPhone(s.delivery_address?.phone);
                const notifyParams = notifyStage
                  ? {
                      consigneeName: s.delivery_address?.name,
                      trackingId: awb,
                      tenantName: tenantBrandName,
                      trackingUrl,
                      stage: notifyStage,
                      deliveryOtp:
                        s.status === PickupStatus.OUT_FOR_DELIVERY
                          ? s.delivery_otp
                          : null,
                      exceptionReason: s.ndr_reason,
                    }
                  : null;
                const whatsappHref =
                  notifyParams && canWhatsApp
                    ? buildWhatsAppConsigneeUrl(
                        Object.assign({}, notifyParams, {
                          phone: s.delivery_address?.phone,
                        })
                      )
                    : null;
                const mailtoHref = notifyParams
                  ? buildMailtoConsigneeUrl(
                      Object.assign({}, notifyParams, {
                        email: s.delivery_address?.email,
                      })
                    )
                  : null;

                // Every action is offered only when the server would accept it (E-11).
                const canVerifyPod = canMoveTo(s, PickupStatus.COMPLETED);
                const canRaiseNdr = canMoveTo(s, PickupStatus.EXCEPTION);
                const canMarkOfd = canMoveTo(s, PickupStatus.OUT_FOR_DELIVERY);
                const canFailQc = canMoveTo(s, PickupStatus.QC_FAILED);
                const isRtoLeg = RTO_LEG_STATUSES.has(s.status);
                const canRtoInTransit = canMoveTo(s, PickupStatus.RTO_IN_TRANSIT);
                const canRtoDeliver = canMoveTo(s, PickupStatus.RTO_DELIVERED);

                return (
                  <div
                    key={s.id}
                    data-testid={`ops.delivery-card.${awb}`}
                    className="min-w-0 overflow-hidden rounded-2xl border border-border bg-card p-4 sm:p-5 shadow-xs space-y-4"
                  >
                    {canMarkOfd && !isRtoLeg && (
                      <div className="flex flex-wrap items-center justify-between gap-2 pb-2 border-b border-border">
                        <span className="text-xs text-muted-foreground">
                          Shipment out for delivery today?
                        </span>
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          disabled={isBusy}
                          onClick={() => handleMarkOutForDelivery(s)}
                          className="font-bold text-primary border-primary/20 bg-primary/5 hover:bg-primary/10"
                        >
                          <MapPin className="mr-1.5 h-3.5 w-3.5" />
                          Mark out for delivery
                        </Button>
                      </div>
                    )}
                    
                    {/* Top Row: AWB, Payment Mode Badge, Status Badge */}
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div className="space-y-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <Link
                            href={routeTo(`/shipments/${s.id}`)}
                            className="font-mono text-base sm:text-lg font-extrabold text-primary hover:underline flex items-center gap-1"
                          >
                            <span>AWB: {awb}</span>
                            <ExternalLink className="h-3.5 w-3.5" />
                          </Link>
                          <CarrierBookingDialog
                            shipmentId={s.id}
                            tenantSlug={tenantSlug}
                            trackingId={awb}
                            onSaved={() => void loadOpsData(false)}
                          />

                          <Badge
                            variant="outline"
                            className={cn(
                              "font-bold text-xs",
                              _getShipmentBadgeClass(s.status)
                            )}
                          >
                            {getShipmentStatusLabel(s.status)}
                          </Badge>

                          {s.shipment_type === ShipmentType.REVERSE && (
                            <Badge
                              variant="outline"
                              className="bg-amber-50 text-amber-900 border-amber-300 font-extrabold text-xs"
                            >
                              Reverse Return (DTO)
                            </Badge>
                          )}

                          {isCollectOnDelivery ? (
                            <Badge className="bg-amber-600 text-white font-extrabold text-xs">
                              COD: Collect ₹{collectAmountFormatted}
                            </Badge>
                          ) : (
                            <Badge
                              variant="outline"
                              className="bg-emerald-50 text-emerald-800 border-emerald-200 font-bold text-xs"
                            >
                              PREPAID
                            </Badge>
                          )}
                        </div>
                        <p className="text-xs text-muted-foreground">
                          Service: {serviceTypeLabel(s.service_type)}
                          {s.transporter_name ? ` · Transporter: ${s.transporter_name}` : ""}
                          {" · Order Ref: "}
                          {s.order_reference_id || "N/A"}
                        </p>
                      </div>

                      {/* Reference 6-Digit Delivery OTP Pill for Ops/Testing */}
                      {s.delivery_otp && (
                        <div className="flex items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-1.5">
                          <KeyRound className="h-4 w-4 text-amber-800" />
                          <div className="text-xs">
                            <span className="font-semibold text-amber-900">
                              Consignee OTP:{" "}
                            </span>
                            <span className="font-mono text-sm font-extrabold tracking-widest text-amber-950 bg-white px-2 py-0.5 rounded border border-amber-300">
                              {s.delivery_otp}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* G3: Reverse (DTO) Doorstep QC Checklist Callout */}
                    {s.shipment_type === ShipmentType.REVERSE && (
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-amber-300 bg-amber-50/70 p-3.5 text-xs text-amber-950">
                        <div className="space-y-1">
                          <p className="font-extrabold uppercase tracking-wider text-amber-900 flex items-center gap-1.5">
                            <ClipboardCheck className="h-4 w-4 text-amber-800" />
                            <span>Doorstep QC Checklist:</span>
                          </p>
                          <p className="text-amber-950 font-semibold">
                            {s.qc_notes ||
                              "Verify item condition, intact tags/seals, and serial number before accepting return."}
                          </p>
                          {s.reason_for_return && (
                            <p className="text-[11px] text-amber-800">
                              Return Reason: {s.reason_for_return}
                            </p>
                          )}
                        </div>

                        {/* E-04: Fail QC only before pickup (server: OPEN / ASSIGNED -> QC_FAILED) */}
                        {canFailQc && (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={isBusy}
                            onClick={() => handleOpenQcFailDialog(s)}
                            className="border-rose-300 bg-white text-rose-700 hover:bg-rose-50 font-bold shrink-0"
                          >
                            <XCircle className="mr-1.5 h-3.5 w-3.5" />
                            Fail Doorstep QC
                          </Button>
                        )}
                      </div>
                    )}

                    {/* G3: Doorstep QC Failed Banner */}
                    {s.status === PickupStatus.QC_FAILED && (
                      <div className="flex items-center justify-between rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-950">
                        <div className="flex items-center gap-2 font-bold">
                          <XCircle className="h-4 w-4 text-rose-700" />
                          <span>
                            Doorstep QC Failed — Return Rejected at Pickup
                          </span>
                        </div>
                        <Badge
                          variant="outline"
                          className="bg-rose-100 text-rose-900 border-rose-300 font-bold"
                        >
                          QC failed
                        </Badge>
                      </div>
                    )}

                    {/* Consignee Contact & Address + Instant Notification Triggers */}
                    <div className="grid gap-3 md:grid-cols-2 rounded-xl border border-border bg-muted/30 p-3.5">
                      <div className="space-y-1.5">
                        <p className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                          Consignee &amp; Doorstep Address
                        </p>
                        <p className="text-sm font-extrabold text-foreground">
                          {s.delivery_address?.name}
                          {s.delivery_address?.company_name
                            ? ` (${s.delivery_address.company_name})`
                            : ""}
                        </p>
                        <p className="text-xs text-muted-foreground flex items-start gap-1.5">
                          <MapPin className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
                          <span>
                            {s.delivery_address?.address_line1},{" "}
                            {s.delivery_address?.city},{" "}
                            {s.delivery_address?.state} -{" "}
                            <strong className="font-mono text-foreground">
                              {consigneeZip}
                            </strong>
                          </span>
                        </p>
                      </div>

                      {/* Phone Call + Instant WhatsApp & Email Consignee Buttons */}
                      <div className="flex flex-wrap items-center justify-start md:justify-end gap-2">
                        {s.delivery_address?.phone && (
                          <Button
                            asChild
                            size="sm"
                            variant="outline"
                            className="font-bold border-slate-300"
                          >
                            <a href={`tel:${s.delivery_address.phone}`}>
                              <Phone className="mr-1.5 h-3.5 w-3.5 text-primary" />
                              {s.delivery_address.phone}
                            </a>
                          </Button>
                        )}

                        {s.delivery_address?.alternate_phone && (
                          <Button
                            asChild
                            size="sm"
                            variant="outline"
                            className="font-bold border-slate-300"
                          >
                            <a href={`tel:${s.delivery_address.alternate_phone}`}>
                              <Phone className="mr-1.5 h-3.5 w-3.5 text-primary" />
                              {s.delivery_address.alternate_phone} (Alt)
                            </a>
                          </Button>
                        )}

                        {whatsappHref ? (
                          <Button
                            asChild
                            size="sm"
                            className="bg-emerald-600 hover:bg-emerald-700 text-white font-bold"
                          >
                            <a
                              href={whatsappHref}
                              target="_blank"
                              rel="noopener noreferrer"
                              data-testid={`ops.delivery-card.${awb}.whatsapp`}
                            >
                              <MessageCircle className="mr-1.5 h-3.5 w-3.5" />
                              {notifyStage === "OUT_FOR_DELIVERY"
                                ? "WhatsApp OTP to Consignee"
                                : "WhatsApp Consignee"}
                            </a>
                          </Button>
                        ) : (
                          notifyStage !== null && (
                            // OPSX-25: never open wa.me without a number (contact picker = OTP leak).
                            <Button
                              type="button"
                              size="sm"
                              variant="outline"
                              disabled
                              data-testid={`ops.delivery-card.${awb}.whatsapp-disabled`}
                              className="font-semibold"
                            >
                              <MessageCircle className="mr-1.5 h-3.5 w-3.5" />
                              No mobile number for WhatsApp
                            </Button>
                          )
                        )}

                        {mailtoHref && (
                          <Button
                            asChild
                            size="sm"
                            variant="outline"
                            className="font-semibold"
                          >
                            <a href={mailtoHref}>
                              <Mail className="mr-1.5 h-3.5 w-3.5 text-primary" />
                              Email Consignee
                            </a>
                          </Button>
                        )}
                      </div>
                    </div>

                    {/* Completed POD Banner */}
                    {s.status === PickupStatus.COMPLETED && (
                      <div className="flex items-center justify-between rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2.5 text-xs text-emerald-950">
                        <div className="flex items-center gap-2 font-bold">
                          <CheckCircle2 className="h-4 w-4 text-emerald-700" />
                          <span>
                            Delivered &amp; POD Verified — Received By:{" "}
                            {s.pod_received_by || "Consignee"}
                          </span>
                        </div>
                        <Badge
                          variant="outline"
                          className="bg-emerald-100 text-emerald-900 border-emerald-300 font-bold"
                        >
                          POD Verified
                        </Badge>
                      </div>
                    )}

                    {/* Active Exception Banner */}
                    {s.status === PickupStatus.EXCEPTION && (
                      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-rose-200 bg-rose-50 px-4 py-2.5 text-xs text-rose-950">
                        <div className="space-y-0.5">
                          <p className="font-extrabold flex items-center gap-1.5">
                            <ShieldAlert className="h-4 w-4 text-rose-700" />
                            <span>
                              NDR Hold: {ndrReasonLabel(s.ndr_reason)} (Attempts:{" "}
                              {s.ndr_attempt_count ?? 1})
                            </span>
                          </p>
                          {s.ndr_remark && (
                            <p className="text-rose-800 pl-5">
                              Field Remark: {s.ndr_remark}
                            </p>
                          )}
                        </div>
                        <Button
                          asChild
                          size="sm"
                          variant="outline"
                          className="border-rose-300 bg-white text-rose-800 font-bold"
                        >
                          <Link href={routeTo("/delivery-exceptions")}>
                            Open NDR Resolution Hub
                          </Link>
                        </Button>
                      </div>
                    )}

                    {/* Inline 6-Digit OTP POD Verification + Raise NDR Controls */}
                    {canVerifyPod && (
                      <div className="rounded-xl border border-primary/20 bg-primary/5 p-3.5 space-y-3">
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <p className="text-xs font-extrabold uppercase tracking-wider text-foreground flex items-center gap-1.5">
                            <ClipboardCheck className="h-4 w-4 text-primary" />
                            <span>
                              Doorstep 6-Digit OTP Proof of Delivery (POD)
                            </span>
                          </p>
                          {s.delivery_otp && (
                            <button
                              type="button"
                              onClick={() => {
                                handleOtpInputChange(
                                  s.id,
                                  s.delivery_otp || ""
                                );
                                if (!receiverInputs[s.id]) {
                                  handleReceiverInputChange(
                                    s.id,
                                    "Consignee (Self)"
                                  );
                                }
                              }}
                              className="text-[11px] font-bold text-primary hover:underline"
                            >
                              Auto-fill OTP ({s.delivery_otp})
                            </button>
                          )}
                        </div>

                        <div className="grid gap-3 sm:grid-cols-12 min-w-0">
                          <div className="min-w-0 sm:col-span-4">
                            <label className="mb-1 block text-[11px] font-bold text-muted-foreground">
                              6-Digit Consignee OTP
                            </label>
                            <Input
                              type="text"
                              inputMode="numeric"
                              maxLength={6}
                              value={otpInputs[s.id] || ""}
                              onChange={(e) =>
                                handleOtpInputChange(s.id, e.target.value)
                              }
                              placeholder="Enter 6-digit OTP"
                              className="min-w-0 w-full h-10 bg-background font-mono text-base tracking-widest font-bold"
                            />
                          </div>

                          <div className="min-w-0 sm:col-span-5">
                            <label className="mb-1 block text-[11px] font-bold text-muted-foreground">
                              Received By (Consignee / Family / Guard)
                            </label>
                            <Input
                              type="text"
                              value={receiverInputs[s.id] || ""}
                              onChange={(e) =>
                                handleReceiverInputChange(s.id, e.target.value)
                              }
                              placeholder="e.g. Consignee (Self) or Security Guard"
                              className="min-w-0 w-full h-10 bg-background"
                            />
                            <div className="mt-1.5 flex flex-wrap gap-1">
                              {POD_RECEIVER_PRESETS.map((preset) => (
                                <button
                                  key={preset}
                                  type="button"
                                  onClick={() =>
                                    handleReceiverInputChange(s.id, preset)
                                  }
                                  className="rounded-md border border-border bg-background px-2 py-0.5 text-[10px] font-semibold text-muted-foreground hover:border-primary hover:text-foreground"
                                >
                                  {preset}
                                </button>
                              ))}
                            </div>
                          </div>

                          <div className="min-w-0 sm:col-span-3 flex flex-col justify-end gap-2">
                            <Button
                              type="button"
                              disabled={isBusy}
                              onClick={() => handleVerifyPodAndDeliver(s)}
                              className="h-auto min-h-10 py-2 w-full max-w-full whitespace-normal bg-emerald-600 hover:bg-emerald-700 text-white font-bold"
                            >
                              {isBusy ? (
                                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                              ) : (
                                <UserCheck className="mr-1.5 h-4 w-4" />
                              )}
                              Verify OTP &amp; Mark Delivered
                            </Button>
                          </div>
                        </div>

                        {canRaiseNdr && (
                        <div className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t border-border">
                          <span className="text-xs text-muted-foreground">
                            Doorstep delivery attempt unsuccessful?
                          </span>
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={isBusy}
                            onClick={() => handleOpenNdrDialog(s)}
                            className="border-rose-300 bg-white text-rose-700 hover:bg-rose-50 font-bold"
                          >
                            <AlertTriangle className="mr-1.5 h-3.5 w-3.5" />
                            Undelivered / Raise Exception (NDR)
                          </Button>
                        </div>
                        )}
                      </div>
                    )}

                    {/* D-01: RTO card actions (return leg back to the seller) */}
                    {isRtoLeg && (canRtoInTransit || canRtoDeliver) && (
                      <div
                        data-testid={`ops.delivery-card.${awb}.rto`}
                        className="rounded-xl border border-amber-300 bg-amber-50/60 p-3.5 space-y-3"
                      >
                        <p className="text-xs font-extrabold uppercase tracking-wider text-amber-900 flex items-center gap-1.5">
                          <Undo2 className="h-4 w-4" />
                          <span>Return to seller (RTO)</span>
                        </p>
                        <p className="text-xs text-amber-950">
                          Return to: {s.pickup_address?.name}
                          {s.pickup_address?.city ? `, ${s.pickup_address.city}` : ""}
                        </p>
                        {canRtoInTransit && (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            disabled={isBusy}
                            data-testid={`ops.delivery-card.${awb}.rto-in-transit`}
                            onClick={() =>
                              void handleRtoMove(s, PickupStatus.RTO_IN_TRANSIT)
                            }
                            className="font-bold"
                          >
                            <Truck className="mr-1.5 h-3.5 w-3.5" />
                            Mark RTO in transit
                          </Button>
                        )}
                        {canRtoDeliver && (
                          <div className="flex min-w-0 flex-col gap-2 sm:flex-row sm:items-end">
                            <div className="min-w-0 flex-1">
                              <label className="mb-1 block text-[11px] font-bold text-muted-foreground">
                                Received by (at the seller&apos;s location)
                              </label>
                              <Input
                                type="text"
                                value={receiverInputs[s.id] || ""}
                                onChange={(e) =>
                                  handleReceiverInputChange(s.id, e.target.value)
                                }
                                placeholder={RTO_RECEIVER_DEFAULT}
                                data-testid={`ops.delivery-card.${awb}.rto-receiver`}
                                className="min-w-0 w-full h-10 bg-background"
                              />
                            </div>
                            <Button
                              type="button"
                              disabled={isBusy}
                              data-testid={`ops.delivery-card.${awb}.rto-delivered`}
                              onClick={() =>
                                void handleRtoMove(s, PickupStatus.RTO_DELIVERED)
                              }
                              className="h-10 bg-emerald-600 hover:bg-emerald-700 text-white font-bold"
                            >
                              <PackageCheck className="mr-1.5 h-4 w-4" />
                              Returned to seller
                            </Button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>

        <TabsContent value="sorter" className="space-y-4">
          <div className="min-w-0 overflow-hidden rounded-xl border border-border bg-card p-4 sm:p-5 space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
              <div>
                <h2 className="text-base font-extrabold text-foreground flex items-center gap-2">
                  <Scale className="h-5 w-5 text-primary" />
                  <span>Record Hub Measurements</span>
                </h2>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Search any active shipment by AWB, compare the booked boxes
                  with what the hub measured, and record the measurement. The
                  charges are re-billed automatically, up or down.
                </p>
              </div>
            </div>

            <div className="relative min-w-0">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={auditSearchQuery}
                onChange={(e) => setAuditSearchQuery(e.target.value)}
                placeholder="Scan or type AWB number, order reference, or consignee name"
                className="min-w-0 w-full pl-9 h-10 bg-background font-mono"
              />
            </div>
          </div>

          {loading && shipments.length === 0 ? (
            <div className="space-y-3">
              {[0, 1].map((idx) => (
                <div
                  key={idx}
                  className="h-32 rounded-xl border border-border bg-card p-4 animate-pulse"
                />
              ))}
            </div>
          ) : auditableShipments.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">
              No active shipments match that AWB query.
            </div>
          ) : (
            <div className="space-y-3">
              {auditableShipments.slice(0, 20).map((s) => {
                const awb = s.tracking_id || s.id.slice(0, 8).toUpperCase();
                const billedMeasurement =
                  s.payment_details?.chargeable_weight ?? 0;
                const currentCostInr = _formatInr(
                  s.payment_details?.total_logistics_cost
                );
                const boxItemCount = s.packages?.length || 0;
                const isSelected = selectedAuditShipmentId === s.id;

                return (
                  <div
                    key={s.id}
                    onClick={() => setSelectedAuditShipmentId(s.id)}
                    className={cn(
                      "rounded-xl border bg-card p-4 transition",
                      isSelected
                        ? "border-primary ring-1 ring-primary/30"
                        : "border-border"
                    )}
                  >
                    <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                      <div className="space-y-1.5">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-mono text-base font-extrabold text-foreground">
                            AWB: {awb}
                          </span>
                          <Badge
                            variant="outline"
                            className={cn(
                              "text-xs font-bold",
                              _getShipmentBadgeClass(s.status)
                            )}
                          >
                            {getShipmentStatusLabel(s.status)}
                          </Badge>
                          <Badge variant="secondary" className="text-xs">
                            {serviceTypeLabel(s.service_type)}
                          </Badge>
                          {s.transporter_name && (
                            <Badge
                              variant="outline"
                              data-testid={`ops.hub-measurement.${awb}.transporter`}
                              className="bg-amber-50 text-amber-900 border-amber-300 text-xs font-bold"
                            >
                              Transporter: {s.transporter_name}
                            </Badge>
                          )}
                        </div>

                        <p className="text-xs text-muted-foreground">
                          Consignee: {s.delivery_address?.name} (
                          {s.delivery_address?.city}) · Cartons: {boxItemCount}
                        </p>

                        {/* Declared Package Dimensions List */}
                        {s.packages && s.packages.length > 0 && (
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {s.packages.map((pkg, idx) => {
                              const pkgMass = pkg.weight;
                              const pkgUnit = pkg.weight_unit || "KG";
                              return (
                                <span
                                  key={pkg.id || idx}
                                  className="rounded-md border border-border bg-muted/50 px-2 py-0.5 font-mono text-[11px] text-foreground"
                                >
                                  Box #{idx + 1}: {pkg.length ?? 0}x
                                  {pkg.breadth ?? 0}x{pkg.height ?? 0}{" "}
                                  {pkg.dimension_unit || "CM"} ({pkgMass}{" "}
                                  {pkgUnit})
                                </span>
                              );
                            })}
                          </div>
                        )}
                      </div>

                      {/* Billed now vs Record measurement */}
                      <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3">
                        <div className="rounded-lg border border-border bg-muted/40 px-3 py-2 text-right">
                          <p className="text-[11px] font-semibold text-muted-foreground">
                            Billed now
                          </p>
                          <p className="font-mono text-sm font-extrabold text-foreground">
                            <span>{billedMeasurement}</span>
                            <span>
                              {" "}
                              kg · ₹{currentCostInr}
                            </span>
                          </p>
                        </div>

                        <Button
                          type="button"
                          data-testid={`ops.hub-measurement.${awb}.record`}
                          onClick={(event) => {
                            event.stopPropagation();
                            handleOpenMeasurement(s);
                          }}
                          className="h-10 font-bold bg-primary text-primary-foreground"
                        >
                          <Ruler className="mr-1.5 h-4 w-4" />
                          Record measurement
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>

        <TabsContent value="cash" className="space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-border bg-card p-4 sm:p-5">
            <div>
              <h2 className="text-base font-extrabold text-foreground flex items-center gap-2">
                <Banknote className="h-5 w-5 text-emerald-700" />
                <span>
                  Field Cash Collection (COD) &amp; Remittance Ledger
                </span>
              </h2>
              <p className="text-xs text-muted-foreground mt-0.5">
                Tracks cash to collect at doorstep on active deliveries versus
                collected cash ready for merchant wallet settlement.
              </p>
            </div>
            <Button asChild variant="outline" size="sm" className="font-bold">
              <Link href={routeTo("/wallet")}>
                Open Wallet &amp; Remittance Settlement
              </Link>
            </Button>
          </div>

          {loading && shipments.length === 0 ? (
            <div className="space-y-3">
              {[0, 1].map((idx) => (
                <div
                  key={idx}
                  className="h-24 rounded-xl border border-border bg-card p-4 animate-pulse"
                />
              ))}
            </div>
          ) : doorCollectionShipments.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-10 text-center text-sm text-muted-foreground">
              No Cash-on-Delivery (COD) shipments recorded in the active queue.
            </div>
          ) : (
            <div className="space-y-3">
              {doorCollectionShipments.map((s) => {
                const awb = s.tracking_id || s.id.slice(0, 8).toUpperCase();
                const cashValueFormatted = _formatInr(s.door_collectible);
                const cashBadge = cashCollectionBadge(s);
                const isRemitted =
                  s.payment_details?.cod_remittance_status ===
                  CodRemittanceStatus.REMITTED;

                return (
                  <div
                    key={s.id}
                    className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-border bg-card p-4 shadow-xs"
                  >
                    <div className="space-y-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link
                          href={routeTo(`/shipments/${s.id}`)}
                          className="font-mono text-sm sm:text-base font-extrabold text-primary hover:underline"
                        >
                          AWB: {awb}
                        </Link>
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-xs font-bold",
                            _getShipmentBadgeClass(s.status)
                          )}
                        >
                          {getShipmentStatusLabel(s.status)}
                        </Badge>
                        <Badge
                          data-testid={`ops.cash.${awb}.state`}
                          className={cn(
                            "text-xs font-bold",
                            CASH_BADGE_CLASS[cashBadge.tone]
                          )}
                        >
                          {cashBadge.label}
                        </Badge>
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Consignee: {s.delivery_address?.name} ·{" "}
                        {s.delivery_address?.city} · Phone:{" "}
                        {s.delivery_address?.phone}
                        {s.delivery_address?.alternate_phone ? ` (Alt: ${s.delivery_address.alternate_phone})` : ""}
                      </p>
                    </div>

                    <div className="flex items-center justify-between sm:justify-end gap-4 border-t sm:border-t-0 pt-2 sm:pt-0 border-border">
                      <div className="text-left sm:text-right">
                        <p className="text-[11px] font-semibold text-muted-foreground">
                          Doorstep Cash Value
                        </p>
                        <p className="font-mono text-base font-extrabold text-foreground">
                          ₹{cashValueFormatted}
                        </p>
                      </div>

                      <Badge
                        variant="outline"
                        className={cn(
                          "font-bold text-xs px-3 py-1",
                          isRemitted
                            ? "bg-emerald-100 text-emerald-900 border-emerald-300"
                            : "bg-amber-100 text-amber-900 border-amber-300"
                        )}
                      >
                        {isRemitted ? "REMITTED" : "PENDING"}
                      </Badge>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </TabsContent>
      </Tabs>

      {/* =================================================================== */}
      {/* DIALOG 1: MARK MANIFEST NOT PICKED                                  */}
      {/* =================================================================== */}
      <Dialog
        open={notPickedTarget !== null}
        onOpenChange={(open) => {
          if (!open) setNotPickedTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-md overflow-x-hidden">
          <DialogHeader className="min-w-0">
            <DialogTitle>Mark Pickup Request as Not Picked</DialogTitle>
            <DialogDescription>
              Log the reason why PUR #
              {notPickedTarget?.pickup_request_number ||
                notPickedTarget?.id.slice(0, 8)}{" "}
              could not be picked up. Linked shipments will automatically
              revert to Ready to Ship.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2 min-w-0">
            <label className="block text-xs font-bold uppercase tracking-wider text-muted-foreground">
              Quick Reason Presets
            </label>
            <div className="flex flex-wrap gap-1.5">
              {NOT_PICKED_REASON_PRESETS.map((preset) => (
                <button
                  key={preset}
                  type="button"
                  onClick={() => setFailureReasonInput(preset)}
                  className={cn(
                    "rounded-lg border px-2.5 py-1 text-left text-xs font-semibold transition",
                    failureReasonInput === preset
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border bg-background text-muted-foreground hover:text-foreground"
                  )}
                >
                  {preset}
                </button>
              ))}
            </div>

            <div className="pt-1 min-w-0">
              <label className="mb-1 block text-xs font-bold text-foreground">
                Failure Reason
              </label>
              <Input
                value={failureReasonInput}
                onChange={(e) => setFailureReasonInput(e.target.value)}
                placeholder="Enter pickup failure reason"
                className="min-w-0 w-full"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setNotPickedTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={submittingNotPicked}
              onClick={handleSubmitNotPicked}
              className="bg-rose-600 hover:bg-rose-700 text-white font-bold"
            >
              {submittingNotPicked && (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              )}
              Confirm Not Picked
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* =================================================================== */}
      {/* DIALOG 2: RAISE NDR DELIVERY EXCEPTION                              */}
      {/* =================================================================== */}
      <Dialog
        open={ndrTarget !== null}
        onOpenChange={(open) => {
          if (!open) setNdrTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-lg overflow-x-hidden">
          <DialogHeader className="min-w-0">
            <DialogTitle>
              Raise Delivery Exception (NDR) — AWB{" "}
              {ndrTarget?.tracking_id || ndrTarget?.id.slice(0, 8)}
            </DialogTitle>
            <DialogDescription>
              Select the field exception reason and enter a remark for the
              merchant. Note: 3 failed delivery attempts automatically trigger
              an RTO return.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-2 min-w-0">
            <div className="min-w-0">
              <label className="mb-1.5 block text-xs font-bold uppercase tracking-wider text-muted-foreground">
                NDR Exception Reason
              </label>
              <Select
                value={selectedNdrReason}
                onValueChange={(val) =>
                  setSelectedNdrReason(val as NdrExceptionReason)
                }
              >
                <SelectTrigger className="h-10 w-full min-w-0 bg-background font-semibold">
                  <SelectValue placeholder="Select NDR reason" />
                </SelectTrigger>
                <SelectContent>
                  {FIELD_NDR_SELECT_OPTIONS.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value}>
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              <p className="mt-1.5 text-[11px] text-muted-foreground">
                Extra charges (freight collection, handling) are raised by the
                operations team from the order page, not at the door.
              </p>
            </div>

            <div className="min-w-0">
              <label className="mb-1 block text-xs font-bold text-foreground">
                Field Executive Remark (Visible to Merchant)
              </label>
              <Input
                value={ndrRemarkInput}
                onChange={(e) => setNdrRemarkInput(e.target.value)}
                placeholder="e.g. Called consignee twice at doorstep, premises locked"
                className="min-w-0 w-full"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setNdrTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={submittingNdr}
              onClick={handleSubmitNdrException}
              className="bg-rose-600 hover:bg-rose-700 text-white font-bold"
            >
              {submittingNdr && (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              )}
              Log NDR Exception
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* =================================================================== */}
      {/* DIALOG 2b: CONFIRM ONE-TAP PICKUP (E-01)                            */}
      {/* =================================================================== */}
      <Dialog
        open={pickupConfirmTarget !== null}
        onOpenChange={(open) => {
          if (!open) setPickupConfirmTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-md" data-testid="ops.pickup-confirm">
          {pickupConfirmTarget && (() => {
            const linked = pickupConfirmTarget.shipments ?? [];
            const qcReturns = getQcReturnShipments(pickupConfirmTarget);
            const needsQcConfirm = qcReturns.length > 0;
            const purLabel =
              pickupConfirmTarget.pickup_request_number ||
              pickupConfirmTarget.id.slice(0, 8).toUpperCase();
            return (
              <>
                <DialogHeader>
                  <DialogTitle>
                    Picked {linked.length} of {linked.length} shipment
                    {linked.length === 1 ? "" : "s"}?
                  </DialogTitle>
                  <DialogDescription>
                    PUR #{purLabel} from{" "}
                    <span className="font-semibold text-foreground">
                      {pickupConfirmTarget.pickup_location_name ||
                        "the pickup location"}
                    </span>
                    {pickupConfirmTarget.pickup_location_address
                      ? ` (${pickupConfirmTarget.pickup_location_address})`
                      : ""}
                    . They move to In Transit and the seller can no longer
                    cancel them for free. Picked only some? Use{" "}
                    <span className="font-semibold">Checklist &amp; box sizes</span>{" "}
                    instead.
                  </DialogDescription>
                </DialogHeader>

                <div className="space-y-3 py-1 text-xs">
                  <ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-border bg-muted/30 p-2.5 font-mono">
                    {linked.map((item) => {
                      const awb = item.tracking_id || item.id.slice(0, 8).toUpperCase();
                      return (
                        <li key={item.id} className="flex justify-between gap-2">
                          <span className="font-bold">{awb}</span>
                          <span className="font-sans text-muted-foreground">
                            {pickedBoxesLabel(
                              item.package_count,
                              cardActualPieces[pickupConfirmTarget.id]?.[awb]
                            )}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                  {pickupConfirmTarget.is_blind_pickup && (
                    <p className="text-muted-foreground">
                      Blind pickup · declared boxes:{" "}
                      <span className="font-bold text-foreground">
                        {pickupConfirmTarget.total_boxes}
                      </span>
                    </p>
                  )}
                  {needsQcConfirm && (
                    <label className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50/70 p-2.5 text-amber-950">
                      <input
                        type="checkbox"
                        className="mt-0.5 h-4 w-4"
                        checked={qcPassedConfirmed}
                        data-testid="ops.pickup-confirm.qc-passed"
                        onChange={(e) => setQcPassedConfirmed(e.target.checked)}
                      />
                      <span>
                        QC passed for all {qcReturns.length} return item
                        {qcReturns.length === 1 ? "" : "s"} (checked against the
                        seller&apos;s QC notes). If an item fails, cancel and use
                        Fail Doorstep QC on the Last-Mile tab.
                      </span>
                    </label>
                  )}
                </div>

                <DialogFooter>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setPickupConfirmTarget(null)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    disabled={needsQcConfirm && !qcPassedConfirmed}
                    data-testid="ops.pickup-confirm.submit"
                    onClick={() => void handleSubmitPickupConfirm()}
                    className="bg-emerald-600 hover:bg-emerald-700 text-white font-bold"
                  >
                    <CheckCircle2 className="mr-1.5 h-4 w-4" />
                    Yes, all picked up
                  </Button>
                </DialogFooter>
              </>
            );
          })()}
        </DialogContent>
      </Dialog>

      {/* =================================================================== */}
      {/* DIALOG 3: PARTIAL PICKUP AWB CHECKLIST ON CONFIRM PICKED UP (G1)    */}
      {/* =================================================================== */}
      <DispatchPickupDialog
        key={dispatchTarget?.id ?? "none"}
        open={dispatchTarget !== null}
        pickupLabel={
          dispatchTarget
            ? `PUR #${
                dispatchTarget.pickup_request_number ||
                dispatchTarget.id.slice(0, 8).toUpperCase()
              }`
            : ""
        }
        shipments={dispatchTarget?.shipments ?? []}
        submitting={submittingDispatch}
        onSubmit={handleSubmitDispatch}
        onOpenChange={(open) => {
          if (!open) setDispatchTarget(null);
        }}
      />

      {/* =================================================================== */}
      {/* DIALOG 3b: RECORD HUB MEASUREMENT (B4)                              */}
      {/* =================================================================== */}
      {measurementTarget && (
        <MeasurementDialog
          key={measurementDialogKey}
          shipmentId={measurementTarget.id}
          awbLabel={
            measurementTarget.tracking_id ||
            measurementTarget.id.slice(0, 8).toUpperCase()
          }
          tenantSlug={tenantSlug}
          open={measurementTarget !== null}
          onOpenChange={(open) => {
            if (!open) setMeasurementTarget(null);
          }}
          onRecorded={() => {
            void fetchOpsData();
          }}
        />
      )}

      {/* =================================================================== */}
      {/* DIALOG 4: REVERSE (DTO) DOORSTEP QC FAILURE (G3)                    */}
      {/* =================================================================== */}
      <Dialog
        open={qcFailTarget !== null}
        onOpenChange={(open) => {
          if (!open) setQcFailTarget(null);
        }}
      >
        <DialogContent className="sm:max-w-md overflow-x-hidden">
          <DialogHeader className="min-w-0">
            <DialogTitle>
              Fail Doorstep QC — AWB{" "}
              {qcFailTarget?.tracking_id || qcFailTarget?.id.slice(0, 8)}
            </DialogTitle>
            <DialogDescription>
              Reject this reverse return at the customer doorstep if the item
              fails quality inspection. Any linked pickup run-sheet will
              automatically release this AWB.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-3 py-2 min-w-0">
            {qcFailTarget?.qc_notes && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-950">
                <span className="font-bold">Merchant QC Instructions: </span>
                <span>{qcFailTarget.qc_notes}</span>
              </div>
            )}

            <div className="min-w-0">
              <label className="mb-1 block text-xs font-bold text-foreground">
                Doorstep QC Failure Remark (Visible on Public Tracking)
              </label>
              <Input
                value={qcFailRemarkInput}
                onChange={(e) => setQcFailRemarkInput(e.target.value)}
                placeholder="e.g. Seal broken, serial number mismatch, or item damaged"
                className="min-w-0 w-full"
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setQcFailTarget(null)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={submittingQcFail}
              onClick={handleSubmitQcFail}
              className="bg-rose-600 hover:bg-rose-700 text-white font-bold"
            >
              {submittingQcFail && (
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
              )}
              Confirm QC Failed (QC_FAILED)
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
