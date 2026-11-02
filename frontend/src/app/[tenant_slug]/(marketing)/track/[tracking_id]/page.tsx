// frontend/src/app/[tenant_slug]/(marketing)/track/[tracking_id]/page.tsx
"use client";

import { PublicTrackingRead, TrackingService } from "@/api_client";
import {
  TRACKING_INPUT_PLACEHOLDER,
  TrackingLoadError,
  classifyTrackingError,
  normalizeTrackingId,
} from "@/components/blocks/tracking-display";
import { TrackingTimeline } from "@/components/blocks/tracking-timeline";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, PackageSearch, RefreshCw, Search, WifiOff } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

export default function PublicTrackingPage() {
  const params = useParams();
  const router = useRouter();
  const rawTrackingId = decodeURIComponent((params.tracking_id as string) || "");
  const trackingId = normalizeTrackingId(rawTrackingId);
  const { routeTo, tenantSlug } = useTenant();

  const [data, setData] = useState<PublicTrackingRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<TrackingLoadError | null>(null);

  const [newSearchId, setNewSearchId] = useState(trackingId);

  const fetchTrackingData = useCallback(async () => {
    if (!trackingId) return;
    setLoading(true);
    setError(null);
    try {
      const response = await TrackingService.trackShipment(trackingId);
      setData(response);
    } catch (err: unknown) {
      const loadError = classifyTrackingError(err);
      // A wrong AWB is an expected outcome, not an application error.
      if (loadError !== TrackingLoadError.NOT_FOUND) {
        console.error("Tracking Error:", err);
      }
      setData(null);
      setError(loadError);
    } finally {
      setLoading(false);
    }
  }, [trackingId]);

  useEffect(() => {
    fetchTrackingData();
  }, [fetchTrackingData, tenantSlug]);

  const handleNewSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const normalized = normalizeTrackingId(newSearchId);
    if (normalized) {
      router.push(routeTo(`/track/${encodeURIComponent(normalized)}`));
    }
  };

  return (
    // 🔥 FIX: Removed min-h-[100vh] logic. Replaced with clean py-12 padding.
    // The global layout's flex-1 will automatically handle the footer positioning!
    <div className="bg-slate-50/50 py-12 px-4 md:px-6 flex flex-col items-center">
      <div className="w-full max-w-3xl space-y-6">
        {/* Refined Inline Search Bar */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-3 md:p-4 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="text-sm font-bold text-slate-700 flex items-center gap-2 whitespace-nowrap pl-2">
            <PackageSearch className="h-5 w-5 text-primary" />
            Track another shipment
          </div>
          <form
            onSubmit={handleNewSearch}
            className="flex w-full sm:w-auto gap-2"
          >
            <Input
              placeholder={TRACKING_INPUT_PLACEHOLDER}
              aria-label="AWB / tracking number"
              value={newSearchId}
              onChange={(e) => setNewSearchId(e.target.value)}
              autoCapitalize="characters"
              className="w-full sm:w-64 bg-slate-50 border-slate-200 focus-visible:ring-primary uppercase placeholder:normal-case"
            />
            {/* 🔥 FIX: Changed from variant="secondary" to explicitly use the Primary brand colors */}
            <Button
              type="submit"
              aria-label="Search"
              className="font-bold px-6 bg-primary text-primary-foreground hover:opacity-90"
            >
              <Search className="h-4 w-4 md:mr-2" />
              <span className="hidden md:inline">Search</span>
            </Button>
          </form>
        </div>

        {/* State Management */}
        {loading && (
          <div className="flex flex-col items-center justify-center h-64 space-y-4 bg-white rounded-2xl border border-slate-200 shadow-sm">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
            <p className="text-slate-500 font-medium">
              Locating your package...
            </p>
          </div>
        )}

        {error === TrackingLoadError.NOT_FOUND && !loading && (
          <div
            data-testid="tracking.not-found"
            className="bg-white border border-slate-200 rounded-2xl p-8 md:p-12 text-center space-y-4 shadow-sm"
          >
            <div className="mx-auto w-16 h-16 bg-destructive/10 rounded-full flex items-center justify-center mb-4">
              <PackageSearch className="h-8 w-8 text-destructive" />
            </div>
            <h3 className="text-xl font-bold text-slate-900">
              Shipment Not Found
            </h3>
            <p className="text-slate-500 max-w-md mx-auto break-all">
              We couldn&apos;t find a shipment with tracking number{" "}
              <span className="font-semibold text-slate-700">{trackingId}</span>.
            </p>
            <p className="text-slate-500 max-w-md mx-auto text-sm">
              Check the number on your label or order message. New shipments can
              take a few minutes to appear.
            </p>
          </div>
        )}

        {error === TrackingLoadError.UNAVAILABLE && !loading && (
          <div
            data-testid="tracking.unavailable"
            className="bg-white border border-slate-200 rounded-2xl p-8 md:p-12 text-center space-y-4 shadow-sm"
          >
            <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center mb-4">
              <WifiOff className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-xl font-bold text-slate-900">
              Tracking is temporarily unavailable
            </h3>
            <p className="text-slate-500 max-w-md mx-auto">
              We couldn&apos;t load the latest status right now. Your shipment is
              not affected. Please try again in a moment.
            </p>
            <Button
              type="button"
              variant="outline"
              data-testid="tracking.retry"
              onClick={() => fetchTrackingData()}
            >
              <RefreshCw className="h-4 w-4 mr-2" /> Try again
            </Button>
          </div>
        )}

        {/* Success State */}
        {data && !loading && !error && <TrackingTimeline data={data} />}
      </div>
    </div>
  );
}
