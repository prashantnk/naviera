// src/app/[tenant_slug]/(app)/dashboard/page.tsx
"use client";

import { PickupRead, PickupStatus, ShipmentsService } from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { useTenant } from "@/components/providers/tenant-provider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertCircle, ArrowRight, Box, CheckCircle2, Clock, Loader2, MapPin, Package, PlusCircle, Truck } from "lucide-react";
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
        // Fetch the 50 most recent shipments.
        // The backend automatically filters this list based on user role!
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

  // --- Dynamic Stat Calculations ---
  // (In a massive production app, we would calculate this on the DB layer, 
  // but for the MVP, calculating from the first 50 recent items is perfectly fine).
  const inTransitCount = shipments.filter(s => s.status === PickupStatus.IN_TRANSIT).length;
  const completedCount = shipments.filter(s => s.status === PickupStatus.COMPLETED).length;
  const pendingCount = shipments.filter(s => s.status === PickupStatus.DRAFT || s.status === PickupStatus.OPEN || s.status === PickupStatus.ASSIGNED).length;
  const exceptionCount = shipments.filter(s => s.status === PickupStatus.CANCELLED || s.status === PickupStatus.RTO_INITIATED).length;

  const recentShipments = shipments.slice(0, 5); // Take top 5 for the feed

  return (
    <div className="space-y-8 max-w-6xl mx-auto pb-12">

      {/* Header Section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-slate-900 tracking-tight">
            {isAdmin ? "Company Overview" : "My Dashboard"}
          </h1>
          <p className="text-slate-500 mt-1 text-sm md:text-base">
            Welcome back, <span className="font-semibold text-slate-700">{user?.email}</span>.
            Here is what's happening {isAdmin ? `across ${tenant?.name}` : "with your shipments"}.
          </p>
        </div>
        <div className="flex gap-3">
          <Button asChild className="shadow-sm">
            <Link href={routeTo("/shipments/new")}>
              <PlusCircle className="mr-2 h-4 w-4" /> Book Shipment
            </Link>
          </Button>
        </div>
      </div>

      {/* Top Metrics Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 md:gap-6">
        <Card className="border-slate-200 shadow-sm">
          <CardContent className="p-6">
            <div className="flex items-center justify-between space-y-0 pb-2">
              <p className="text-sm font-medium text-slate-500">Total Bookings</p>
              <Package className="h-4 w-4 text-slate-400" />
            </div>
            <div className="text-3xl font-bold text-slate-900">{totalShipments}</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 shadow-sm">
          <CardContent className="p-6">
            <div className="flex items-center justify-between space-y-0 pb-2">
              <p className="text-sm font-medium text-slate-500">In Transit</p>
              <Truck className="h-4 w-4 text-blue-500" />
            </div>
            <div className="text-3xl font-bold text-slate-900">{inTransitCount}</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 shadow-sm">
          <CardContent className="p-6">
            <div className="flex items-center justify-between space-y-0 pb-2">
              <p className="text-sm font-medium text-slate-500">Completed</p>
              <CheckCircle2 className="h-4 w-4 text-green-500" />
            </div>
            <div className="text-3xl font-bold text-slate-900">{completedCount}</div>
          </CardContent>
        </Card>
        <Card className="border-slate-200 shadow-sm bg-slate-50/50">
          <CardContent className="p-6">
            <div className="flex items-center justify-between space-y-0 pb-2">
              <p className="text-sm font-medium text-slate-500">Needs Attention</p>
              <AlertCircle className="h-4 w-4 text-red-500" />
            </div>
            <div className="text-3xl font-bold text-slate-900">{exceptionCount}</div>
          </CardContent>
        </Card>
      </div>

      {/* Bottom Layout Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* ⬅️ Left Column: Recent Activity (Takes 2/3 width) */}
        <Card className="lg:col-span-2 border-slate-200 shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between bg-slate-50/50 border-b border-slate-100 pb-4">
            <CardTitle className="text-lg font-semibold flex items-center gap-2">
              <Clock className="h-5 w-5 text-primary" /> Recent Shipments
            </CardTitle>
            <Button variant="ghost" size="sm" asChild className="text-slate-500 hover:text-primary">
              <Link href={routeTo("/shipments")}>View All <ArrowRight className="ml-1 h-4 w-4" /></Link>
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {recentShipments.length === 0 ? (
              <div className="p-8 text-center text-slate-500 italic">
                No shipments found. Create your first booking!
              </div>
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
                      className="flex flex-col sm:flex-row sm:items-center justify-between p-4 md:p-6 hover:bg-slate-50 transition-colors group"
                    >
                      <div className="flex items-start gap-4">
                        <div className="h-10 w-10 rounded-full bg-slate-100 flex items-center justify-center shrink-0 group-hover:bg-primary/10 group-hover:text-primary transition-colors">
                          <Box className="h-5 w-5" />
                        </div>
                        <div>
                          <p className="font-semibold text-slate-900 group-hover:text-primary transition-colors">
                            {shipment.tracking_id || shipment.order_reference_id}
                          </p>
                          <div className="flex items-center gap-2 text-sm text-slate-500 mt-1">
                            {/* Added ?. and fallback text */}
                            <span>{shipment.pickup_address?.city || "Unknown Origin"}</span>
                            <ArrowRight className="h-3 w-3" />
                            <span>{shipment.delivery_address?.city || "Unknown Destination"}</span>
                          </div>
                        </div>
                      </div>
                      <div className="mt-4 sm:mt-0 flex items-center justify-between sm:justify-end gap-4 sm:w-1/3">
                        <div className="text-xs text-slate-400 font-medium">
                          {new Date(shipment.created_at).toLocaleDateString()}
                        </div>
                        <Badge variant={badgeVariant} className="shadow-sm">
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

        {/* ➡️ Right Column: Quick Actions & Help (Takes 1/3 width) */}
        <div className="space-y-6">
          {/* Quick Tracking Widget */}
          <Card className="border-slate-200 shadow-sm bg-primary/5 border-primary/10">
            <CardHeader className="pb-3">
              <CardTitle className="text-lg font-semibold text-slate-900 flex items-center gap-2">
                <MapPin className="h-5 w-5 text-primary" /> Track a Package
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-slate-600 mb-4">
                Enter a tracking ID below to jump directly to the live tracking timeline.
              </p>
              <Button asChild variant="default" className="w-full shadow-sm">
                <Link href={routeTo("/track")}>Open Tracker</Link>
              </Button>
            </CardContent>
          </Card>

          {/* Support Widget */}
          <Card className="border-slate-200 shadow-sm">
            <CardContent className="p-6 text-center space-y-4">
              <div className="mx-auto w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center mb-2">
                <AlertCircle className="h-6 w-6 text-slate-600" />
              </div>
              <div>
                <h3 className="font-semibold text-slate-900">Need Help?</h3>
                <p className="text-sm text-slate-500 mt-1">
                  Contact our logistics support team for assistance with exceptions or delayed packages.
                </p>
              </div>
              <Button variant="outline" className="w-full">Contact Support</Button>
            </CardContent>
          </Card>
        </div>

      </div>
    </div>
  );
}