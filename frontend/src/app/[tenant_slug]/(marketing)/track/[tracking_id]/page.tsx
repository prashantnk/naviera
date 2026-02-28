// frontend/src/app/[tenant_slug]/(marketing)/track/[tracking_id]/page.tsx
"use client";

import { PublicTrackingRead, ShipmentsService } from "@/api_client";
import { TrackingTimeline } from "@/components/blocks/tracking-timeline";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Loader2, PackageSearch, Search } from "lucide-react";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function PublicTrackingPage() {
  const params = useParams();
  const router = useRouter();
  const trackingId = params.tracking_id as string;
  const { routeTo, tenantSlug } = useTenant();

  const [data, setData] = useState<PublicTrackingRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [newSearchId, setNewSearchId] = useState(trackingId);

  useEffect(() => {
    if (!trackingId) return;

    const fetchTrackingData = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await ShipmentsService.trackShipment(trackingId);
        setData(response);
      } catch (err: unknown) {
        console.error("Tracking Error:", err);
        setError("We couldn't find a shipment with that Tracking ID.");
      } finally {
        setLoading(false);
      }
    };

    fetchTrackingData();
  }, [trackingId, tenantSlug]);

  const handleNewSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (newSearchId.trim()) {
      router.push(routeTo(`/track/${newSearchId.trim()}`));
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
              placeholder="Enter Tracking ID..."
              value={newSearchId}
              onChange={(e) => setNewSearchId(e.target.value)}
              className="w-full sm:w-64 bg-slate-50 border-slate-200 focus-visible:ring-primary"
            />
            {/* 🔥 FIX: Changed from variant="secondary" to explicitly use the Primary brand colors */}
            <Button
              type="submit"
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

        {error && !loading && (
          <div className="bg-white border border-slate-200 rounded-2xl p-12 text-center space-y-4 shadow-sm">
            <div className="mx-auto w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mb-4">
              <PackageSearch className="h-8 w-8 text-red-500" />
            </div>
            <h3 className="text-xl font-bold text-slate-900">
              Shipment Not Found
            </h3>
            <p className="text-slate-500 max-w-md mx-auto">{error}</p>
          </div>
        )}

        {/* Success State */}
        {data && !loading && !error && <TrackingTimeline data={data} />}
      </div>
    </div>
  );
}
