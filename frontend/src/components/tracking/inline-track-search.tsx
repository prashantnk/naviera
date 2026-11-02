// frontend/src/components/tracking/inline-track-search.tsx
"use client";

import React, { useState } from "react";
import { useRouter } from "next/navigation";
import { PackageSearch, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { useTenant } from "@/components/providers/tenant-provider";

interface InlineTrackSearchProps {
  /** Initial tracking ID to populate the search field */
  initialTrackingId?: string;
}

/**
 * InlineTrackSearch component provides a text input and search button
 * allowing users to lookup tracking information for a shipment ID.
 * It dynamically adapts to the current tenant routing mode.
 */
export function InlineTrackSearch({ initialTrackingId = "" }: InlineTrackSearchProps) {
  const router = useRouter();
  const { routeTo } = useTenant();
  const [searchId, setSearchId] = useState<string>(initialTrackingId);

  const handleSearchSubmit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmedId = searchId.trim();
    if (trimmedId) {
      router.push(routeTo(`/track/${trimmedId}`));
    }
  };

  return (
    <div className="bg-card rounded-2xl shadow-xs border border-border p-3 md:p-4 flex flex-col sm:flex-row items-center justify-between gap-4 text-card-foreground">
      <div className="text-sm font-bold text-muted-foreground flex items-center gap-2 whitespace-nowrap pl-2">
        <PackageSearch className="h-5 w-5 text-primary" />
        Track another shipment
      </div>
      <form
        onSubmit={handleSearchSubmit}
        className="flex w-full sm:w-auto gap-2"
      >
        <Input
          type="text"
          placeholder="Enter Tracking ID..."
          value={searchId}
          onChange={(e) => setSearchId(e.target.value)}
          className="w-full sm:w-64 bg-muted/30 border-input focus-visible:ring-ring"
        />
        <Button
          type="submit"
          className="font-bold px-6 bg-primary text-primary-foreground hover:bg-primary/90"
        >
          <Search className="h-4 w-4 md:mr-2" />
          <span className="hidden md:inline">Search</span>
        </Button>
      </form>
    </div>
  );
}
