// frontend/src/components/blocks/hero-section.tsx
"use client";

import { useTenant } from '@/components/providers/tenant-provider';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { getSupabaseClient } from "@/lib/supabase";
import { ArrowRight, CheckCircle2, LayoutDashboard, MapPin, PackageSearch, PlaneTakeoff, ShieldCheck, UserCircle2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

interface HeroSectionProps {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
  trustPartners?: string[];
}

export function HeroSection({ title, subtitle, ctaText, ctaLink, badge, trustPartners = [] }: HeroSectionProps) {
  const { routeTo, tenantSlug } = useTenant();
  const params = useParams();
  const router = useRouter();
  const [trackingId, setTrackingId] = useState("");
  const [isLoggedIn, setIsLoggedIn] = useState(false);

  useEffect(() => {
    const checkAuth = async () => {
      const supabase = getSupabaseClient(tenantSlug);
      const { data: { session } } = await supabase.auth.getSession();
      if (session) setIsLoggedIn(true);
    };
    checkAuth();
  }, [tenantSlug]);

  const handleTrack = (e: React.FormEvent) => {
    e.preventDefault();
    if (trackingId.trim()) router.push(routeTo(`/track/${trackingId.trim()}`));
  };

  return (
    <div className="flex flex-col relative overflow-hidden bg-white">
      {/* --- CLEAN CORPORATE BACKGROUND --- */}
      <div className="absolute top-0 right-0 w-full md:w-1/2 h-full bg-slate-50 skew-x-12 translate-x-32 border-l border-slate-100/50 pointer-events-none" />
      <div className="absolute left-0 top-0 w-full max-w-3xl h-[600px] bg-blue-600/5 blur-[120px] rounded-full pointer-events-none" />

      <section className="relative pt-16 pb-20 lg:pt-24 lg:pb-32 z-10">
        <div className="container mx-auto px-4 md:px-6">
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-16 items-center">

            {/* ⬅️ LEFT COLUMN: Text Content & Tracker */}
            <div className="lg:col-span-6 flex flex-col justify-center space-y-8 relative z-20">
              <div className="space-y-6">
                {badge && (
                  <div className="inline-flex items-center rounded-full bg-slate-50 border border-slate-200 px-4 py-1.5 text-sm font-bold text-slate-700 shadow-sm animate-in fade-in slide-in-from-bottom-4 duration-700">
                    <ShieldCheck className="h-4 w-4 text-[#dc2626] mr-2" />
                    {badge}
                  </div>
                )}
                <h1 className="text-5xl lg:text-[4.5rem] font-extrabold tracking-tighter text-slate-900 leading-[1.05] animate-in fade-in slide-in-from-bottom-6 duration-700 delay-100">
                  <span className="bg-clip-text text-transparent bg-gradient-to-br from-[#003366] to-slate-800">
                    International & Domestic
                  </span>
                  <br />
                  Courier & Cargo.
                </h1>
                <p className="max-w-[550px] text-lg lg:text-xl text-slate-600 font-medium leading-relaxed animate-in fade-in slide-in-from-bottom-6 duration-700 delay-200">
                  {subtitle}
                </p>
              </div>

              {/* 🔥 SMART BIG CTAS */}
              <div className="flex flex-col sm:flex-row gap-4 pt-2 animate-in fade-in duration-700 delay-300">

                {isLoggedIn ? (
                  <Button size="lg" asChild className="h-16 px-8 rounded-xl text-lg font-bold shadow-[0_0_40px_rgba(220,38,38,0.25)] hover:shadow-[0_0_60px_rgba(220,38,38,0.4)] hover:-translate-y-1 transition-all duration-300 bg-[#dc2626] text-white hover:bg-[#b91c1c] group">
                    <Link href={routeTo("/dashboard")}>
                      <LayoutDashboard className="mr-2 h-6 w-6" />
                      Go to Dashboard
                      <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                    </Link>
                  </Button>
                ) : (
                  <Button size="lg" asChild className="h-16 px-8 rounded-xl text-lg font-bold shadow-[0_0_40px_rgba(220,38,38,0.25)] hover:shadow-[0_0_60px_rgba(220,38,38,0.4)] hover:-translate-y-1 transition-all duration-300 bg-[#dc2626] text-white hover:bg-[#b91c1c] group">
                    <Link href={routeTo("/login")}>
                      <UserCircle2 className="mr-2 h-6 w-6" />
                      Customer Login
                      <ArrowRight className="ml-2 h-5 w-5 group-hover:translate-x-1 transition-transform" />
                    </Link>
                  </Button>
                )}

                <Button size="lg" variant="outline" asChild className="h-16 px-8 rounded-xl text-lg font-bold shadow-sm hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 text-slate-700 bg-white border-2 border-slate-200 hover:bg-slate-50 hover:border-slate-300">
                  <Link href={routeTo(ctaLink)}>
                    {ctaText}
                  </Link>
                </Button>
              </div>

              {/* PREMIUM TRACKING WIDGET */}
              <div className="bg-white p-2.5 rounded-2xl border border-slate-200 w-full max-w-[550px] shadow-lg animate-in fade-in zoom-in-95 duration-700 delay-500 relative z-30 mt-4">
                <form onSubmit={handleTrack} className="flex flex-col sm:flex-row gap-2 relative">
                  <div className="relative flex-1">
                    <div className="absolute left-4 top-0 bottom-0 flex items-center justify-center">
                      <PackageSearch className="h-6 w-6 text-slate-400" />
                    </div>
                    <Input
                      placeholder="Enter Tracking ID (e.g. NAV-123)..."
                      className="h-14 pl-12 bg-slate-50 border-transparent text-slate-900 placeholder:text-slate-500 focus-visible:ring-2 focus-visible:ring-primary text-lg shadow-inner"
                      value={trackingId}
                      onChange={(e) => setTrackingId(e.target.value)}
                    />
                  </div>
                  <Button type="submit" size="lg" className="h-14 px-10 rounded-xl text-lg font-bold shadow-md hover:scale-[1.02] transition-transform duration-200 w-full sm:w-auto bg-[#003366] text-white hover:bg-[#002244]">
                    Track
                  </Button>
                </form>
              </div>

              {/* OFFICIAL PARTNERS */}
              {trustPartners.length > 0 && (
                <div className="pt-6 mt-2 border-t border-slate-200 max-w-xl animate-in fade-in duration-700 delay-700">
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Official Partners</p>
                  <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
                    <div className="bg-[#FFCC00] px-3 py-1 rounded text-[#D40511] font-black italic text-xl tracking-tighter shadow-sm">DHL</div>
                    <div className="text-2xl font-extrabold tracking-tighter"><span className="text-[#4D148C]">Fed</span><span className="text-[#FF6600]">Ex</span></div>
                    <div className="text-2xl font-black italic text-[#003366] tracking-tighter">DTDC</div>
                    <div className="text-xl font-black text-[#0055A5] tracking-tighter uppercase">BLUE DART</div>
                    <div className="text-2xl font-bold text-[#351C15] tracking-tighter">ups</div>
                  </div>
                </div>
              )}
            </div>

            {/* ➡️ RIGHT COLUMN: Multi-Modal Bento Collage */}
            <div className="lg:col-span-6 relative w-full h-[550px] lg:h-[650px] animate-in fade-in slide-in-from-right-12 duration-1000 delay-300 mt-10 lg:mt-0">

              {/* Ambient Glow behind images */}
              <div className="absolute inset-10 bg-[#003366]/10 blur-[80px] rounded-full opacity-80 z-0" />

              {/* IMAGE 1: Air Cargo (Top Right) */}
              <div className="absolute top-0 right-0 w-[65%] h-[55%] bg-white p-2 rounded-[2rem] shadow-xl z-10 border border-slate-100 transform hover:scale-[1.02] hover:-rotate-1 transition-all duration-500">
                <img
                  src="https://images.unsplash.com/photo-1542296332-2e4473faf563?q=80&w=2070&auto=format&fit=crop"
                  alt="Global Air Cargo"
                  className="w-full h-full object-cover rounded-[1.5rem]"
                />
              </div>

              {/* IMAGE 2: Surface/Trucks (Bottom Right) */}
              <div className="absolute bottom-8 right-8 w-[60%] h-[40%] bg-white p-2 rounded-[2rem] shadow-2xl z-20 border border-slate-100 transform hover:scale-[1.02] hover:rotate-1 transition-all duration-500">
                <img
                  src="https://images.unsplash.com/photo-1601584115197-04ecc0da31d7?q=80&w=2070&auto=format&fit=crop"
                  alt="Surface Transport Fleet"
                  className="w-full h-full object-cover rounded-[1.5rem]"
                />
              </div>

              {/* IMAGE 3: Warehousing (Middle Left - Overlapping) */}
              <div className="absolute top-[20%] left-0 w-[45%] h-[45%] bg-white p-2 rounded-[2rem] shadow-[0_20px_60px_rgba(0,0,0,0.15)] z-30 border border-slate-100 transform hover:scale-[1.05] transition-all duration-500">
                <img
                  src="https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?q=80&w=2070&auto=format&fit=crop"
                  alt="Warehousing Operations"
                  className="w-full h-full object-cover rounded-[1.5rem]"
                />
              </div>

              {/* 🚀 FLOAT 1: Delivery Rate (Bottom Left) */}
              <div className="absolute -bottom-2 -left-4 md:left-4 bg-white/95 backdrop-blur-xl p-5 rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.1)] border border-slate-100 z-40 transform hover:-translate-y-2 transition-transform duration-500 flex items-center gap-4">
                <div className="h-12 w-12 rounded-full bg-green-100 border border-green-200 flex items-center justify-center shrink-0">
                  <CheckCircle2 className="h-6 w-6 text-green-600" />
                </div>
                <div>
                  <p className="text-xs font-bold text-slate-400 uppercase tracking-wider">Delivery Rate</p>
                  <p className="text-3xl font-black text-slate-900 tracking-tight">99.8%</p>
                </div>
              </div>

              {/* 🚀 FLOAT 2: Live Route Mockup (Top Right, overlapping Air) */}
              <div className="absolute top-1/2 -translate-y-1/2 -left-8 md:-left-12 bg-white/95 backdrop-blur-xl p-5 rounded-2xl shadow-[0_20px_50px_rgba(0,0,0,0.12)] border border-slate-100 z-40 transform lg:-rotate-2 hover:scale-105 transition-transform duration-500 hidden sm:block w-64">
                <div className="flex items-center justify-between mb-4 border-b border-slate-100 pb-3">
                  <span className="text-[10px] font-bold text-slate-400 uppercase tracking-widest flex items-center gap-1">
                    <PlaneTakeoff className="h-3 w-3 text-[#dc2626]" /> Live Air Cargo
                  </span>
                  <span className="flex h-2 w-2 rounded-full bg-green-500 animate-ping" />
                </div>
                <div className="space-y-4">
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-6 w-6 rounded-full bg-slate-100 border border-slate-200 flex items-center justify-center shrink-0">
                      <MapPin className="h-3 w-3 text-slate-500" />
                    </div>
                    <div><p className="text-sm font-bold text-slate-900 leading-tight">New Delhi</p><p className="text-[10px] text-slate-500 uppercase font-semibold">Origin</p></div>
                  </div>
                  <div className="ml-3 border-l-2 border-dashed border-[#dc2626]/40 h-6" />
                  <div className="flex items-start gap-3">
                    <div className="mt-0.5 h-6 w-6 rounded-full bg-[#003366]/10 border border-[#003366]/20 flex items-center justify-center shrink-0">
                      <CheckCircle2 className="h-3 w-3 text-[#003366]" />
                    </div>
                    <div><p className="text-sm font-bold text-slate-900 leading-tight">New York</p><p className="text-[10px] text-slate-500 uppercase font-semibold">In Transit</p></div>
                  </div>
                </div>
              </div>

            </div>

          </div>
        </div>
      </section>
    </div>
  );
}