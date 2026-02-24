// src/components/blocks/hero-section.tsx
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { ArrowRight } from "lucide-react";

interface HeroSectionProps {
  title: string;
  subtitle: string;
  ctaText: string;
  ctaLink: string;
  badge?: string; // Optional field
}

export function HeroSection({
  title,
  subtitle,
  ctaText,
  ctaLink,
  badge,
}: HeroSectionProps) {
  return (
    <section className="relative overflow-hidden py-24 lg:py-32 bg-white">
      {/* Background Gradient (Subtle generic styling) */}
      <div className="absolute inset-0 -z-10 h-full w-full bg-[linear-gradient(to_right,#f0f0f0_1px,transparent_1px),linear-gradient(to_bottom,#f0f0f0_1px,transparent_1px)] bg-[size:6rem_4rem] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)]" />

      <div className="container mx-auto px-4 md:px-6">
        <div className="flex flex-col items-center space-y-4 text-center">
          {/* Optional Badge */}
          {badge && (
            <div className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80">
              {badge}
            </div>
          )}

          {/* Dynamic Title */}
          <h1 className="text-3xl font-bold tracking-tighter sm:text-4xl md:text-5xl lg:text-6xl/none text-slate-900">
            {title}
          </h1>

          {/* Dynamic Subtitle */}
          <p className="mx-auto max-w-[700px] md:text-xl text-slate-600">
            {subtitle}
          </p>

          {/* Call to Action */}
          <div className="space-x-4">
            <Button asChild size="lg">
              <Link href={ctaLink}>
                {ctaText} <ArrowRight className="ml-2 h-4 w-4" />
              </Link>
            </Button>
          </div>
        </div>
      </div>
    </section>
  );
}