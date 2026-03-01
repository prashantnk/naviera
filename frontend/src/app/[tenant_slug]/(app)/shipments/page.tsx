// frontend/src/app/[tenant_slug]/(app)/shipments/page.tsx
"use client";

import { PickupRead, PickupStatus, ShipmentsService } from "@/api_client";
import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { DataTable } from "@/components/ui/data-table";
import { Input } from "@/components/ui/input";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Loader2, Plus, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { columns } from "./columns";

export default function ShipmentsPage() {
  const router = useRouter();
  const { routeTo } = useTenant();

  const [data, setData] = useState<PickupRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 🔥 NEW: Server-Side Pagination State
  const [pageIndex, setPageIndex] = useState(0); // UI uses 0-based indexing
  const [pageSize, setPageSize] = useState(50);
  const [totalCount, setTotalCount] = useState(0);

  // Client-Side Filter States
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState("ALL");

  // 🔥 UPGRADED: The Fetcher now listens to the pageIndex!
  useEffect(() => {
    const fetchShipments = async () => {
      setLoading(true);
      try {
        // API expects 1-based indexing (so pageIndex 0 becomes page 1)
        const response = await ShipmentsService.listShipments(
          pageIndex + 1,
          pageSize
        );
        setData(response.items);
        setTotalCount(response.total);
      } catch (err: any) {
        console.error(err);
        setError(err.message || "Failed to fetch shipments.");
      } finally {
        setLoading(false);
      }
    };

    fetchShipments();
  }, [pageIndex, pageSize]); // Re-runs every time pageIndex changes!

  // The Omni-Search Triage Engine (Filters the *current* page of data)
  const filteredData = useMemo(() => {
    return data.filter((shipment) => {
      let tabMatch = true;
      if (activeTab === "ACTIVE") {
        tabMatch = [
          PickupStatus.OPEN,
          PickupStatus.ASSIGNED,
          PickupStatus.IN_TRANSIT,
        ].includes(shipment.status);
      } else if (activeTab === "COMPLETED") {
        tabMatch = shipment.status === PickupStatus.COMPLETED;
      } else if (activeTab === "EXCEPTIONS") {
        tabMatch = [
          PickupStatus.CANCELLED,
          PickupStatus.RTO_INITIATED,
        ].includes(shipment.status);
      }

      let searchMatch = true;
      if (searchQuery.trim() !== "") {
        const q = searchQuery.toLowerCase().trim();
        const searchableString = `
                    ${shipment.tracking_id || ""} 
                    ${shipment.order_reference_id} 
                    ${shipment.pickup_address?.name || ""} 
                    ${shipment.pickup_address?.phone || ""} 
                    ${shipment.pickup_address?.city || ""} 
                    ${shipment.delivery_address?.city || ""} 
                    ${shipment.status.replace("_", " ")} 
                    ${shipment.service_type} 
                    ${shipment.shipment_type}
                    ${shipment.latest_status_comment || ""}
                `.toLowerCase();
        searchMatch = searchableString.includes(q);
      }

      return tabMatch && searchMatch;
    });
  }, [data, activeTab, searchQuery]);

  // 🔥 NEW: Pagination Math & Callbacks
  const pageCount = Math.ceil(totalCount / pageSize);
  const canNextPage = pageIndex < pageCount - 1;
  const canPreviousPage = pageIndex > 0;

  const handleNextPage = () => {
    if (canNextPage) setPageIndex((prev) => prev + 1);
  };

  const handlePreviousPage = () => {
    if (canPreviousPage) setPageIndex((prev) => prev - 1);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-in fade-in duration-500">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-slate-200 pb-6">
        <div>
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
            Shipments
          </h1>
          <p className="text-slate-500 mt-1">
            Manage and track all your delivery operations.
          </p>
        </div>
        <Button
          asChild
          className="rounded-lg shadow-sm h-10 px-4 font-semibold"
        >
          <Link href={routeTo("/shipments/new")}>
            <Plus className="mr-2 h-4 w-4" /> Book New Shipment
          </Link>
        </Button>
      </div>

      {error && (
        <div className="p-4 text-red-600 bg-red-50 rounded-lg border border-red-200 text-sm font-medium">
          {error}
        </div>
      )}

      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <Tabs
            defaultValue="ALL"
            value={activeTab}
            onValueChange={setActiveTab}
            className="w-full sm:w-auto"
          >
            <TabsList className="bg-slate-100/80 border border-slate-200">
              <TabsTrigger value="ALL" className="text-xs font-semibold px-4">
                All
              </TabsTrigger>
              <TabsTrigger
                value="ACTIVE"
                className="text-xs font-semibold px-4"
              >
                Active
              </TabsTrigger>
              <TabsTrigger
                value="COMPLETED"
                className="text-xs font-semibold px-4"
              >
                Completed
              </TabsTrigger>
              <TabsTrigger
                value="EXCEPTIONS"
                className="text-xs font-semibold px-4 text-red-600 data-[state=active]:text-red-700"
              >
                Exceptions
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {!loading && (
            <span className="hidden md:inline-flex text-xs font-medium text-slate-400 bg-white px-2.5 py-1 rounded-md border border-slate-200 shadow-sm">
              {totalCount} total records
            </span>
          )}
        </div>

        <div className="relative w-full sm:w-[350px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <Input
            placeholder="Search current page..."
            className="pl-9 bg-white border-slate-200 shadow-sm rounded-lg"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
          />
        </div>
      </div>

      {/* Data Grid with Pagination Controls Passed Down */}
      <div className="animate-in fade-in slide-in-from-bottom-2 duration-500 relative min-h-[400px]">
        {loading && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/50 backdrop-blur-[1px] rounded-xl border border-slate-200">
            <Loader2 className="h-8 w-8 animate-spin text-primary" />
          </div>
        )}

        <DataTable
          columns={columns}
          data={filteredData}
          onRowClick={(row) => router.push(routeTo(`/shipments/${row.id}`))}
          // 🔥 Passing the pagination state!
          pageCount={pageCount}
          pageIndex={pageIndex}
          onNextPage={handleNextPage}
          onPreviousPage={handlePreviousPage}
          canNextPage={canNextPage}
          canPreviousPage={canPreviousPage}
        />
      </div>
    </div>
  );
}
