// src/components/blocks/hero-section.tsx
"use client";

import { useTenant } from '@/components/providers/tenant-provider';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Anchor, ArrowRight, Box, CheckCircle2, PackageSearch, Plane, Truck } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

interface HeroSectionProps {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string;
}

export function HeroSection({
  title,
  subtitle,
  ctaText,
  ctaLink,
  badge,
}: HeroSectionProps) {
  const { routeTo } = useTenant();
  const router = useRouter();
  const [trackingId, setTrackingId] = useState("");

  const handleTrack = (e: React.FormEvent) => {
    e.preventDefault();
    if (trackingId.trim()) {
      router.push(routeTo(`/track/${trackingId.trim()}`));
    }
  };

  return (
    <div className="flex flex-col">
      <section className="relative overflow-hidden bg-slate-900 py-16 lg:py-28">
        {/* Subtle Background Pattern */}
        <div className="absolute inset-0 opacity-10 bg-[radial-gradient(circle_at_center,_var(--tw-gradient-stops))] from-white via-transparent to-transparent bg-[length:24px_24px]" />

        <div className="container relative mx-auto px-4 md:px-6 z-10">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-12 items-center">

            {/* LEFT COLUMN: Text Content & Inline Tracker */}
            <div className="flex flex-col justify-center space-y-8 text-white">
              <div className="space-y-5">
                {badge && (
                  <div className="inline-flex items-center rounded-full bg-primary/20 px-4 py-1.5 text-sm font-semibold text-primary-foreground ring-1 ring-inset ring-primary/30 shadow-sm">
                    {badge}
                  </div>
                )}
                <h1 className="text-5xl font-extrabold tracking-tighter sm:text-6xl xl:text-7xl text-white leading-[1.1]">
                  {title}
                </h1>
                <p className="max-w-[600px] text-lg md:text-xl leading-relaxed text-slate-300">
                  {subtitle}
                </p>
              </div>

              {/* 🔥 UPGRADED: Massive Inline Tracker Widget */}
              <div className="bg-white/10 backdrop-blur-xl p-3 rounded-2xl border border-white/20 max-w-lg shadow-2xl">
                <form onSubmit={handleTrack} className="flex flex-col sm:flex-row gap-3">
                  <div className="relative flex-1">
                    <PackageSearch className="absolute left-4 top-4 h-6 w-6 text-slate-400" />
                    <Input
                      placeholder="Enter Tracking ID (e.g. NAV-123)..."
                      className="h-14 pl-12 bg-white text-slate-900 placeholder:text-slate-500 border-0 rounded-xl focus-visible:ring-4 focus-visible:ring-primary/50 text-base md:text-lg shadow-inner"
                      value={trackingId}
                      onChange={(e) => setTrackingId(e.target.value)}
                    />
                  </div>
                  <Button type="submit" size="lg" className="h-14 px-8 rounded-xl text-lg font-bold shadow-lg hover:scale-105 transition-transform duration-200 w-full sm:w-auto">
                    Track
                  </Button>
                </form>
              </div>

              {/* 🔥 UPGRADED: Business Action Buttons */}
              <div className="flex flex-col sm:flex-row gap-4 pt-4">
                <Button size="lg" asChild className="h-14 px-8 rounded-xl text-base md:text-lg font-bold shadow-xl hover:scale-105 transition-all duration-200 bg-white text-slate-900 hover:bg-slate-100">
                  <Link href={routeTo(ctaLink)}>
                    {ctaText} <ArrowRight className="ml-2 h-5 w-5" />
                  </Link>
                </Button>
                {/* THE FIX: Explicitly setting bg-transparent so the white text shows up! */}
                <Button size="lg" className="h-14 px-8 rounded-xl text-base md:text-lg font-bold border-2 border-white/30 bg-transparent text-white hover:bg-white/10 hover:text-white transition-all duration-200">
                  Calculate Rates
                </Button>
              </div>
            </div>

            {/* RIGHT COLUMN: Visuals */}
            <div className="relative mx-auto w-full max-w-[600px] lg:max-w-none">
              <div className="relative rounded-3xl overflow-hidden shadow-2xl border border-white/10 ring-1 ring-white/10 transform lg:-rotate-2 transition-transform duration-500 hover:rotate-0">
                <img
                  src="https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?q=80&w=2070&auto=format&fit=crop"
                  alt="Cargo Ship Logistics"
                  className="w-full object-cover h-[450px] lg:h-[550px]"
                />

                {/* Floating Metrics Badge */}
                <div className="absolute bottom-6 left-6 flex flex-col gap-2 rounded-2xl bg-white/95 backdrop-blur-md p-6 shadow-xl border border-white/20">
                  <div className="flex items-center gap-4 mb-2">
                    <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
                      <CheckCircle2 className="h-7 w-7 text-green-600" />
                    </div>
                    <div>
                      <p className="text-lg font-bold text-slate-900 leading-none">99.8% On-Time</p>
                      <p className="text-sm text-slate-500 mt-1">Global Delivery Rate</p>
                    </div>
                  </div>
                  <div className="h-px w-full bg-slate-200 my-2" />
                  <p className="text-sm font-semibold text-slate-700 flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-primary" /> 150+ Countries Served</p>
                  <p className="text-sm font-semibold text-slate-700 flex items-center gap-2"><CheckCircle2 className="h-4 w-4 text-primary" /> 50K+ Shipments Daily</p>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* --- BOTTOM TRUST BAR --- */}
      <div className="border-b border-slate-200 bg-white py-10">
        <div className="container mx-auto px-4 md:px-6">
          <div className="flex flex-col md:flex-row items-center justify-center md:justify-between gap-8 opacity-60 grayscale hover:grayscale-0 transition-all duration-500">
            <span className="text-sm font-bold tracking-widest text-slate-400 uppercase hidden md:block">Trusted Partners:</span>
            <div className="flex items-center gap-2 font-bold text-slate-700 text-xl"><Anchor className="h-6 w-6 text-primary" /> OceanWay</div>
            <div className="flex items-center gap-2 font-bold text-slate-700 text-xl"><Plane className="h-6 w-6 text-primary" /> AeroSwift</div>
            <div className="flex items-center gap-2 font-bold text-slate-700 text-xl"><Truck className="h-6 w-6 text-primary" /> GroundForce</div>
            <div className="flex items-center gap-2 font-bold text-slate-700 text-xl"><Box className="h-6 w-6 text-primary" /> HarborLink</div>
          </div>
        </div>
      </div>
    </div>
  );
}