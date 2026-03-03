// frontend/src/app/[tenant_slug]/(marketing)/floating-whatsapp.tsx
"use client";

import { useTenant } from "@/components/providers/tenant-provider";
import { MessageCircle } from "lucide-react";
import Link from "next/link";

export function FloatingWhatsApp() {
  const { tenant } = useTenant();
  const whatsappNumber = tenant?.settings?.contact?.whatsapp;

  if (!whatsappNumber) return null;

  return (
    <Link
      href={`https://wa.me/${whatsappNumber}`}
      target="_blank"
      className="fixed bottom-6 right-6 z-50 bg-[#25D366] text-white p-4 rounded-full shadow-2xl hover:scale-110 transition-transform flex flex-col items-center justify-center group"
    >
      <MessageCircle className="h-8 w-8" />
      <span className="absolute -top-8 right-0 bg-white text-slate-900 text-xs font-bold px-2 py-1 rounded shadow-md opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap pointer-events-none">
        Chat With Us
      </span>
    </Link>
  );
}