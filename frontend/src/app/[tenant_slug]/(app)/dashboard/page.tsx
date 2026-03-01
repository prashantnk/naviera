// frontend/src/app/[tenant_slug]/(app)/dashboard/page.tsx
"use client";

import { PickupRead, PickupStatus, ShipmentsService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import {
  AlertCircle,
  ArrowRight,
  Box,
  CheckCircle2,
  Clock,
  Loader2,
  MapPin,
  Package,
  PieChart,
  Plus,
  Search,
  Truck,
} from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

export default function TenantDashboard() {
  const { tenant, routeTo } = useTenant();
  const { user, isAdmin } = useUser();
  const router = useRouter();

  const [shipments, setShipments] = useState<PickupRead[]>([]);
  const [totalShipments, setTotalShipments] = useState(0);
  const [loading, setLoading] = useState(true);
  const [trackingId, setTrackingId] = useState("");

  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        const res = await ShipmentsService.listShipments(1, 50);
        setShipments(res.items);
        setTotalShipments(res.total);
      } catch (error) {
        console.error("Failed to load dashboard data", error);
      } finally {
        setLoading(false);
      }
    };
    fetchDashboardData();
  }, []);

  const handleTrack = (e: React.FormEvent) => {
    e.preventDefault();
    if (trackingId.trim()) router.push(routeTo(`/track/${trackingId.trim()}`));
  };

  // 🔥 NEW: Comprehensive Status Color Mapper
  const getStatusColor = (status: PickupStatus) => {
    switch (status) {
      case PickupStatus.DRAFT:
        return "bg-slate-100 text-slate-700 border-slate-200";
      case PickupStatus.OPEN:
        return "bg-sky-100 text-sky-700 border-sky-200";
      case PickupStatus.ASSIGNED:
        return "bg-indigo-100 text-indigo-700 border-indigo-200";
      case PickupStatus.IN_TRANSIT:
        return "bg-blue-100 text-blue-700 border-blue-200";
      case PickupStatus.COMPLETED:
        return "bg-emerald-100 text-emerald-700 border-emerald-200";
      case PickupStatus.CANCELLED:
        return "bg-rose-100 text-rose-700 border-rose-200";
      case PickupStatus.RTO_INITIATED:
        return "bg-amber-100 text-amber-700 border-amber-200";
      default:
        return "bg-slate-100 text-slate-700";
    }
  };

  if (loading) {
    return (
      <div className="flex h-[80vh] items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  const inTransitCount = shipments.filter(
    (s) => s.status === PickupStatus.IN_TRANSIT
  ).length;
  const completedCount = shipments.filter(
    (s) => s.status === PickupStatus.COMPLETED
  ).length;
  const exceptionCount = shipments.filter(
    (s) =>
      s.status === PickupStatus.CANCELLED ||
      s.status === PickupStatus.RTO_INITIATED
  ).length;
  const recentShipments = shipments.slice(0, 5);

  // Quick stats for the new card
  const expressCount = shipments.filter(
    (s) => s.service_type === "EXPRESS"
  ).length;
  const surfaceCount = shipments.filter(
    (s) => s.service_type === "SURFACE"
  ).length;

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl font-extrabold text-slate-900 tracking-tight">
            {isAdmin ? "Company Overview" : "My Dashboard"}
          </h1>
          <p className="text-slate-500">
            Welcome back,{" "}
            <span className="font-medium text-slate-700">{user?.email}</span>.
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

      {/* BENTO GRID: Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 md:gap-6">
        <Card className="xl:col-span-2 border border-slate-200 shadow-sm bg-white overflow-hidden relative rounded-xl">
          <div className="absolute right-0 top-0 opacity-[0.03] pointer-events-none transform translate-x-4 -translate-y-4">
            <Package className="h-48 w-48 text-slate-900" />
          </div>
          <CardContent className="p-6 md:p-8 relative z-10 flex flex-col justify-between h-full">
            <div className="flex items-center gap-2 text-slate-500 font-bold mb-4 text-xs uppercase tracking-wider">
              <Box className="h-4 w-4 text-primary" /> Total Bookings
            </div>
            <div>
              <div className="text-5xl md:text-6xl font-black tracking-tighter text-slate-900">
                {totalShipments}
              </div>
              <p className="text-slate-500 mt-2 text-sm font-medium">
                All time shipments processed.
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-sm border border-slate-200 bg-white rounded-xl">
          <CardContent className="p-6 md:p-8 flex flex-col justify-between h-full">
            <div className="h-10 w-10 rounded-lg bg-blue-50 border border-blue-100 flex items-center justify-center">
              <Truck className="h-5 w-5 text-blue-600" />
            </div>
            <div className="mt-6">
              <div className="text-3xl font-extrabold text-slate-900">
                {inTransitCount}
              </div>
              <p className="text-slate-500 font-medium mt-1 text-sm">
                Active in Transit
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-sm border border-slate-200 bg-white rounded-xl">
          <CardContent className="p-6 md:p-8 flex flex-col justify-between h-full">
            <div className="h-10 w-10 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center">
              <CheckCircle2 className="h-5 w-5 text-emerald-600" />
            </div>
            <div className="mt-6">
              <div className="text-3xl font-extrabold text-slate-900">
                {completedCount}
              </div>
              <p className="text-slate-500 font-medium mt-1 text-sm">
                Successfully Delivered
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* LOWER BENTO GRID */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* ⬅️ Left Area: Recent Activity Feed */}
        <Card className="xl:col-span-2 border border-slate-200 shadow-sm rounded-xl overflow-hidden flex flex-col">
          <CardHeader className="flex flex-row items-center justify-between bg-white border-b border-slate-100 px-6 py-5 shrink-0">
            <div className="space-y-1">
              <CardTitle className="text-lg font-bold flex items-center gap-2">
                <Clock className="h-5 w-5 text-slate-400" /> Recent Shipments
              </CardTitle>
              <p className="text-xs text-slate-500 font-medium">
                Your 5 most recently created orders.
              </p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              asChild
              className="text-slate-500 hover:text-primary font-medium h-8"
            >
              <Link href={routeTo("/shipments")}>
                View All <ArrowRight className="ml-2 h-3.5 w-3.5" />
              </Link>
            </Button>
          </CardHeader>
          <CardContent className="p-0 bg-white flex-1">
            {recentShipments.length === 0 ? (
              <div className="p-12 text-center text-slate-500 text-sm">
                No shipments found. Create your first booking!
              </div>
            ) : (
              <div className="divide-y divide-slate-100">
                {recentShipments.map((shipment) => (
                  <Link
                    key={shipment.id}
                    href={routeTo(`/shipments/${shipment.id}`)}
                    className="flex flex-col sm:flex-row sm:items-center justify-between px-6 py-4 hover:bg-slate-50 transition-colors group"
                  >
                    <div className="flex items-center gap-4">
                      <div className="h-10 w-10 rounded-lg bg-slate-100 border border-slate-200 flex items-center justify-center shrink-0 group-hover:border-primary/30 group-hover:text-primary text-slate-400 transition-colors">
                        <Box className="h-5 w-5" />
                      </div>
                      <div>
                        <p className="text-sm font-bold text-slate-900 group-hover:text-primary transition-colors">
                          {shipment.tracking_id || shipment.order_reference_id}
                        </p>
                        <div className="flex items-center gap-1.5 text-xs text-slate-500 mt-0.5 font-medium">
                          <span>
                            {shipment.pickup_address?.city || "Unknown"}
                          </span>
                          <ArrowRight className="h-3 w-3 text-slate-300" />
                          <span>
                            {shipment.delivery_address?.city || "Unknown"}
                          </span>
                        </div>
                      </div>
                    </div>
                    <div className="mt-4 sm:mt-0 flex items-center gap-4">
                      <div className="text-xs text-slate-400 font-medium hidden md:block">
                        {new Date(shipment.created_at).toLocaleDateString(
                          "en-US",
                          { month: "short", day: "numeric" }
                        )}
                      </div>
                      {/* 🔥 FULLY STYLED BADGE */}
                      <Badge
                        variant="outline"
                        className={cn(
                          "px-2.5 py-0.5 shadow-none text-[10px] uppercase font-bold tracking-wider rounded-md",
                          getStatusColor(shipment.status)
                        )}
                      >
                        {shipment.status.replace("_", " ")}
                      </Badge>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ➡️ Right Area: Quick Tools & Extra Data */}
        <div className="space-y-6 flex flex-col">
          <Card className="border border-slate-200 shadow-sm bg-white rounded-xl relative overflow-hidden shrink-0">
            <div className="absolute top-0 right-0 p-4 opacity-5 pointer-events-none">
              <MapPin className="h-20 w-20 text-primary" />
            </div>
            <CardHeader className="relative z-10 px-6 pt-6 pb-2">
              <CardTitle className="text-lg font-bold text-slate-900 flex items-center gap-2">
                <Search className="h-5 w-5 text-primary" /> Track a Package
              </CardTitle>
            </CardHeader>
            <CardContent className="relative z-10 px-6 pb-6 pt-2">
              <form onSubmit={handleTrack} className="flex flex-col gap-3">
                <Input
                  placeholder="e.g. NAV-12345"
                  className="bg-slate-50 h-10"
                  value={trackingId}
                  onChange={(e) => setTrackingId(e.target.value)}
                />
                <Button
                  type="submit"
                  variant="default"
                  className="w-full font-semibold shadow-sm h-10 rounded-lg"
                >
                  Quick Track
                </Button>
              </form>
            </CardContent>
          </Card>

          {/* 🔥 FIX: Service Utilization Data Grid */}
          <Card className="border border-slate-200 shadow-sm bg-white rounded-xl flex-1">
            <CardHeader className="border-b border-slate-100 px-6 py-4">
              <CardTitle className="text-sm font-bold text-slate-900 flex items-center gap-2">
                <PieChart className="h-4 w-4 text-slate-400" /> Service Usage
              </CardTitle>
              {/* Honest UX Labeling */}
              <p className="text-[10px] text-slate-500 font-medium">
                Based on your latest {shipments.length} shipments.
              </p>
            </CardHeader>
            <CardContent className="p-6 space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-slate-600">
                  Surface Deliveries
                </span>
                <span className="font-bold text-slate-900">{surfaceCount}</span>
              </div>
              <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden">
                {/* Fixed Math: Divide by shipments.length, not totalShipments! */}
                <div
                  className="bg-slate-800 h-full"
                  style={{
                    width: `${
                      shipments.length > 0
                        ? (surfaceCount / shipments.length) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>

              <div className="flex items-center justify-between pt-2">
                <span className="text-sm font-medium text-slate-600">
                  Express Air
                </span>
                <span className="font-bold text-slate-900">{expressCount}</span>
              </div>
              <div className="w-full bg-slate-100 h-2 rounded-full overflow-hidden">
                <div
                  className="bg-primary h-full"
                  style={{
                    width: `${
                      shipments.length > 0
                        ? (expressCount / shipments.length) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
            </CardContent>
          </Card>

          {/* Exceptions / Alerts */}
          {exceptionCount > 0 && (
            <Card className="border border-red-100 shadow-sm bg-red-50/50 rounded-xl shrink-0">
              <CardContent className="p-5 flex items-start gap-4">
                <div className="h-10 w-10 rounded-lg bg-red-100 flex items-center justify-center shrink-0 border border-red-200">
                  <AlertCircle className="h-5 w-5 text-red-600" />
                </div>
                <div>
                  <h3 className="text-sm font-bold text-red-900">
                    Attention Required
                  </h3>
                  <p className="text-red-700 mt-0.5 text-xs font-medium leading-relaxed">
                    {exceptionCount} shipment(s) have exceptions.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
