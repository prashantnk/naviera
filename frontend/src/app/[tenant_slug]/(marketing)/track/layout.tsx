// frontend/src/app/[tenant_slug]/(marketing)/track/layout.tsx
import type { Metadata } from "next";
import type { ReactNode } from "react";

/** The tracking pages are Client Components, so their tab title is set here. */
export const metadata: Metadata = { title: "Track Shipment" };

export default function TrackLayout({ children }: { children: ReactNode }) {
  return children;
}
