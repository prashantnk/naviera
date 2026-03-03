// frontend/src/app/[tenant_slug]/error.tsx
"use client";

import { Button } from "@/components/ui/button";
import { ServerCrash } from "lucide-react";

export default function TenantError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-4 text-center">
      <div className="max-w-md space-y-6">
        <div className="mx-auto w-24 h-24 bg-red-100 rounded-full flex items-center justify-center mb-6 shadow-inner border border-red-200">
          <ServerCrash className="h-12 w-12 text-red-600" />
        </div>
        <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight">
          Service Unavailable
        </h1>
        <p className="text-lg text-slate-500">
          Our servers are awake, but we encountered a temporary database or system issue.
        </p>
        <div className="pt-6">
          <Button onClick={() => reset()} size="lg" className="h-12 px-8 rounded-xl font-bold bg-slate-900 text-white">
            Try Again
          </Button>
        </div>
      </div>
    </div>
  );
}