// frontend/src/components/tracking/copy-tracking-id.tsx
"use client";

import React, { useState } from "react";
import { Copy, Check } from "lucide-react";
import { toast } from "sonner";

interface CopyTrackingIdProps {
  /** The tracking ID to copy */
  trackingId: string;
}

/**
 * CopyTrackingId provides a button to copy the tracking ID to clipboard
 * with feedback toast and temporary success icon change.
 */
export function CopyTrackingId({ trackingId }: CopyTrackingIdProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(trackingId);
      setCopied(true);
      toast.success("Tracking ID copied to clipboard!");
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error("Failed to copy text: ", err);
      toast.error("Failed to copy tracking ID.");
    }
  };

  return (
    <button
      onClick={handleCopy}
      className="text-muted-foreground hover:text-primary transition-colors cursor-pointer focus:outline-hidden"
      title="Copy ID"
    >
      {copied ? (
        <Check className="h-5 w-5 text-primary" />
      ) : (
        <Copy className="h-5 w-5" />
      )}
    </button>
  );
}
