// frontend/src/app/[tenant_slug]/(marketing)/[...slug]/page.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { Button } from "@/components/ui/button";
import { FileQuestion, Home } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

export default function CatchAll404Page() {
  const { routeTo } = useTenant();
  const params = useParams();

  // Safely parse the slug path for debugging, though we don't necessarily need to show it
  const pathArray = params.slug as string[];
  const attemptedPath = pathArray ? `/${pathArray.join("/")}` : "this page";

  return (
    // 🔥 FIX: Replaced min-h-[60vh] with py-24 for natural flexbox flow
    <div className="py-24 flex flex-col items-center justify-center text-center px-4 bg-slate-50/50">
      <div className="max-w-md space-y-8">
        {/* Icon */}
        <div className="mx-auto w-24 h-24 bg-primary/10 rounded-full flex items-center justify-center mb-2">
          <FileQuestion className="h-12 w-12 text-primary" />
        </div>

        {/* Copy */}
        <div className="space-y-3">
          <h1 className="text-4xl md:text-5xl font-extrabold text-slate-900 tracking-tight">
            Page Not Found
          </h1>
          <p className="text-lg text-slate-500">
            We couldn&apos;t find anything at{" "}
            <span className="font-medium text-slate-700">{attemptedPath}</span>.
            It might have been moved, deleted, or never existed in the first
            place.
          </p>
        </div>

        {/* CTA */}
        <div className="pt-4">
          <Button
            asChild
            size="lg"
            className="rounded-xl h-14 px-8 text-base font-bold shadow-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
          >
            <Link href={routeTo("/")}>
              <Home className="mr-2 h-5 w-5" /> Return to Homepage
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
}
