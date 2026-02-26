// src/components/blocks/hero-section.tsx
"use client";

import { useTenant } from '@/components/providers/tenant-provider';
import { Button } from "@/components/ui/button";
import { Anchor, ArrowRight, Box, CheckCircle2, Phone, Plane, Truck } from "lucide-react";
import Link from "next/link";

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
  return (
    <div className="flex flex-col">
      <section className="relative overflow-hidden bg-white py-16 lg:py-24">
        <div className="container mx-auto px-4 md:px-6">
          <div className="grid grid-cols-1 gap-12 lg:grid-cols-2 lg:gap-8 items-center">

            {/* LEFT COLUMN: Text Content */}
            <div className="flex flex-col justify-center space-y-8">
              <div className="space-y-4">
                {badge && (
                  <div className="inline-flex items-center rounded-full bg-primary/10 px-3 py-1 text-sm font-medium text-primary ring-1 ring-inset ring-primary/20">
                    {badge}
                  </div>
                )}
                <h1 className="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl xl:text-6xl">
                  {title}
                </h1>
                <p className="max-w-[600px] text-lg leading-relaxed text-slate-600">
                  {subtitle}
                </p>
              </div>

              {/* Action Buttons */}
              <div className="flex flex-col sm:flex-row gap-4">
                <Button size="lg" asChild>
                  <Link href={routeTo(ctaLink)}>
                    {ctaText} <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
                <Button size="lg" variant="outline" className="text-slate-700">
                  <Phone className="mr-2 h-4 w-4" /> Contact Sales
                </Button>
              </div>

              {/* Hardcoded Stats (We can make these dynamic from the DB later) */}
              <div className="grid grid-cols-3 gap-4 pt-8 border-t border-slate-100">
                <div>
                  <h4 className="text-2xl font-bold text-slate-900">150+</h4>
                  <p className="text-sm text-slate-500">Countries Served</p>
                </div>
                <div>
                  <h4 className="text-2xl font-bold text-slate-900">50K+</h4>
                  <p className="text-sm text-slate-500">Shipments Daily</p>
                </div>
                <div>
                  <h4 className="text-2xl font-bold text-slate-900">99.8%</h4>
                  <p className="text-sm text-slate-500">On-Time Rate</p>
                </div>
              </div>
            </div>

            {/* RIGHT COLUMN: Visuals */}
            <div className="relative mx-auto w-full max-w-[600px] lg:max-w-none">
              <div className="relative rounded-2xl overflow-hidden shadow-2xl">
                <img
                  src="https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?q=80&w=2070&auto=format&fit=crop"
                  alt="Cargo Ship Logistics"
                  className="w-full object-cover h-[400px] lg:h-[500px]"
                />

                {/* The Floating "Live Tracking" Badge */}
                <div className="absolute bottom-6 left-6 flex items-center gap-4 rounded-xl bg-white p-4 shadow-xl">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/20">
                    <CheckCircle2 className="h-6 w-6 text-primary" />
                  </div>
                  <div>
                    <p className="text-sm font-bold text-slate-900">Live Tracking</p>
                    <p className="text-xs text-slate-500">Real-time updates</p>
                  </div>
                </div>
              </div>
            </div>

          </div>
        </div>
      </section>

      {/* --- BOTTOM TRUST BAR --- */}
      <div className="border-y border-slate-200 bg-slate-50 py-8">
        <div className="container mx-auto px-4 md:px-6">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6 opacity-60 grayscale hover:grayscale-0 transition-all duration-500">
            <span className="text-sm font-bold tracking-widest text-slate-500 uppercase">Trusted Delivery Partners:</span>
            <div className="flex items-center gap-2 font-semibold text-slate-700"><Anchor className="h-5 w-5" /> OceanWay</div>
            <div className="flex items-center gap-2 font-semibold text-slate-700"><Plane className="h-5 w-5" /> AeroSwift</div>
            <div className="flex items-center gap-2 font-semibold text-slate-700"><Truck className="h-5 w-5" /> GroundForce</div>
            <div className="flex items-center gap-2 font-semibold text-slate-700"><Box className="h-5 w-5" /> HarborLink</div>
          </div>
        </div>
      </div>
    </div>
  );
}