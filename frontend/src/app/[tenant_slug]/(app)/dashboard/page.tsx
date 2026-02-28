// src/app/[tenant_slug]/(app)/dashboard/page.tsx
"use client";

import { PickupRead, PickupStatus, ShipmentsService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertCircle, ArrowRight, Box, CheckCircle2, Clock, Loader2, MapPin, Package, Plus, Truck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

export default function TenantDashboard() {
  const { tenant, routeTo } = useTenant();
  const { user, isAdmin } = useUser();

  const [shipments, setShipments] = useState<PickupRead[]>([]);
  const [totalShipments, setTotalShipments] = useState(0);
  const [loading, setLoading] = useState(true);

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

  if (loading) {
    return <div className="flex h-[80vh] items-center justify-center"><Loader2 className="h-10 w-10 animate-spin text-primary" /></div>;
  }

  const inTransitCount = shipments.filter(s => s.status === PickupStatus.IN_TRANSIT).length;
  const completedCount = shipments.filter(s => s.status === PickupStatus.COMPLETED).length;
  const exceptionCount = shipments.filter(s => s.status === PickupStatus.CANCELLED || s.status === PickupStatus.RTO_INITIATED).length;
  const recentShipments = shipments.slice(0, 5);

  return (
    <div className="space-y-8 max-w-7xl mx-auto pb-12 animate-in fade-in duration-500">

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight">
            {isAdmin ? "Company Overview" : "My Dashboard"}
          </h1>
          <p className="text-slate-500 text-lg">
            Welcome back, <span className="font-medium text-slate-700">{user?.email}</span>.
          </p>
        </div>
        <Button size="lg" asChild className="rounded-full shadow-lg hover:scale-105 transition-transform h-12 px-6">
          <Link href={routeTo("/shipments/new")}>
            <Plus className="mr-2 h-5 w-5" /> Book New Shipment
          </Link>
        </Button>
      </div>

      {/* BENTO GRID: Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 md:gap-6">

        {/* Master Metric (Spans 2 columns on extra large, dark theme) */}
        <Card className="xl:col-span-2 border-0 shadow-xl bg-slate-900 text-white overflow-hidden relative">
          <div className="absolute right-0 top-0 opacity-10 transform translate-x-4 -translate-y-4">
            <Package className="h-48 w-48" />
          </div>
          <CardContent className="p-8 relative z-10 flex flex-col justify-between h-full">
            <div className="flex items-center gap-2 text-slate-300 font-medium mb-6">
              <Box className="h-5 w-5 text-primary" /> Total Bookings
            </div>
            <div>
              <div className="text-6xl font-extrabold tracking-tighter">{totalShipments}</div>
              <p className="text-slate-400 mt-2">All time shipments processed.</p>
            </div>
          </CardContent>
        </Card>

        {/* Sub Metric 1 */}
        <Card className="border-0 shadow-md bg-blue-50/50 hover:bg-blue-50 transition-colors">
          <CardContent className="p-8 flex flex-col justify-between h-full">
            <div className="flex items-center justify-between">
              <div className="h-12 w-12 rounded-full bg-blue-100 flex items-center justify-center">
                <Truck className="h-6 w-6 text-blue-600" />
              </div>
            </div>
            <div className="mt-6">
              <div className="text-4xl font-extrabold text-slate-900">{inTransitCount}</div>
              <p className="text-slate-600 font-medium mt-1">Active in Transit</p>
            </div>
          </CardContent>
        </Card>

        {/* Sub Metric 2 */}
        <Card className="border-0 shadow-md bg-green-50/50 hover:bg-green-50 transition-colors">
          <CardContent className="p-8 flex flex-col justify-between h-full">
            <div className="flex items-center justify-between">
              <div className="h-12 w-12 rounded-full bg-green-100 flex items-center justify-center">
                <CheckCircle2 className="h-6 w-6 text-green-600" />
              </div>
            </div>
            <div className="mt-6">
              <div className="text-4xl font-extrabold text-slate-900">{completedCount}</div>
              <p className="text-slate-600 font-medium mt-1">Successfully Delivered</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* LOWER BENTO GRID */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">

        {/* ⬅️ Left Area: Recent Activity Feed */}
        <Card className="xl:col-span-2 border-0 shadow-lg rounded-2xl overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between bg-white border-b border-slate-100 px-8 py-6">
            <CardTitle className="text-xl font-bold flex items-center gap-2">
              <Clock className="h-6 w-6 text-primary" /> Recent Activity
            </CardTitle>
            <Button variant="ghost" asChild className="text-primary hover:bg-primary/5 font-semibold">
              <Link href={routeTo("/shipments")}>View All <ArrowRight className="ml-2 h-4 w-4" /></Link>
            </Button>
          </CardHeader>
          <CardContent className="p-0 bg-white">
            {recentShipments.length === 0 ? (
              <div className="p-12 text-center text-slate-500">No shipments found. Create your first booking!</div>
            ) : (
              <div className="divide-y divide-slate-100">
                {recentShipments.map((shipment) => {
                  let badgeVariant: "default" | "secondary" | "destructive" = "secondary";
                  if (shipment.status === PickupStatus.COMPLETED || shipment.status === PickupStatus.IN_TRANSIT) badgeVariant = "default";
                  if (shipment.status === PickupStatus.CANCELLED) badgeVariant = "destructive";

                  return (
                    <Link
                      key={shipment.id}
                      href={routeTo(`/shipments/${shipment.id}`)}
                      className="flex flex-col sm:flex-row sm:items-center justify-between px-8 py-5 hover:bg-slate-50 transition-colors group"
                    >
                      <div className="flex items-center gap-5">
                        <div className="h-12 w-12 rounded-xl bg-slate-100 flex items-center justify-center shrink-0 group-hover:bg-primary group-hover:text-white text-slate-500 transition-colors">
                          <Box className="h-6 w-6" />
                        </div>
                        <div>
                          <p className="text-lg font-bold text-slate-900 group-hover:text-primary transition-colors">
                            {shipment.tracking_id || shipment.order_reference_id}
                          </p>
                          <div className="flex items-center gap-2 text-sm text-slate-500 mt-1 font-medium">
                            <span>{shipment.pickup_address?.city || "Unknown"}</span>
                            <ArrowRight className="h-3 w-3 text-slate-300" />
                            <span>{shipment.delivery_address?.city || "Unknown"}</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-4 sm:mt-0 flex items-center gap-6">
                        <div className="text-sm text-slate-400 font-medium hidden md:block">
                          {new Date(shipment.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                        </div>
                        <Badge variant={badgeVariant} className="px-3 py-1 shadow-sm text-xs rounded-md">
                          {shipment.status.replace("_", " ")}
                        </Badge>
                      </div>
                    </Link>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>

        {/* ➡️ Right Area: Quick Tools */}
        <div className="space-y-6 flex flex-col">
          {/* Quick Tracking Widget */}
          <Card className="border-0 shadow-lg bg-primary text-primary-foreground rounded-2xl relative overflow-hidden flex-1">
            <div className="absolute top-0 right-0 p-6 opacity-20">
              <MapPin className="h-24 w-24" />
            </div>
            <CardHeader className="relative z-10 px-8 pt-8">
              <CardTitle className="text-2xl font-bold">Track Package</CardTitle>
              <p className="text-primary-foreground/80 mt-2 font-medium">
                Jump directly to live tracking details.
              </p>
            </CardHeader>
            <CardContent className="relative z-10 px-8 pb-8">
              <Button asChild variant="secondary" size="lg" className="w-full text-primary font-bold shadow-xl h-14 rounded-xl hover:scale-105 transition-transform">
                <Link href={routeTo("/track")}>Open Tracker Dashboard</Link>
              </Button>
            </CardContent>
          </Card>

          {/* Exceptions / Alerts */}
          {exceptionCount > 0 && (
            <Card className="border-0 shadow-lg bg-red-50 rounded-2xl">
              <CardContent className="p-8 flex items-start gap-4">
                <div className="h-12 w-12 rounded-full bg-red-100 flex items-center justify-center shrink-0">
                  <AlertCircle className="h-6 w-6 text-red-600" />
                </div>
                <div>
                  <h3 className="text-lg font-bold text-red-900">Attention Required</h3>
                  <p className="text-red-700 mt-1 font-medium">
                    You have {exceptionCount} shipment(s) facing exceptions or cancellations.
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