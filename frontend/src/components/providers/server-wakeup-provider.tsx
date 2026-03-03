// frontend/src/components/providers/server-wakeup-provider.tsx
"use client";

import React, { useEffect, useState, useRef } from "react";
import { Loader2, Package2 } from "lucide-react";

export function ServerWakeupProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [isWaking, setIsWaking] = useState(false);

  const keepAliveIntervalRef = useRef<NodeJS.Timeout | null>(null);
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    // 1. The Polling Logic
    const startPolling = () => {
      if (pollIntervalRef.current) return;

      // 🔥 FIX 1: Guarantee the UI takes over the moment we enter polling mode
      setIsWaking(true);

      pollIntervalRef.current = setInterval(async () => {
        try {
          const res = await fetch("/health");
          if (res.ok) {
            if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
            window.location.reload();
          }
        } catch (error) {
          // Still sleeping, keep polling...
        }
      }, 5000);
    };

    // 2. The Keep-Alive Heartbeat
    const startKeepAlive = () => {
      if (keepAliveIntervalRef.current) return;

      keepAliveIntervalRef.current = setInterval(async () => {
        try {
          const res = await fetch("/health");
          if (!res.ok) throw new Error("Server dropped connection");
        } catch (error) {
          if (keepAliveIntervalRef.current)
            clearInterval(keepAliveIntervalRef.current);
          startPolling(); // startPolling now handles setIsWaking(true)
        }
      }, 840000);
    };

    // 3. Initial Boot Check
    const initialCheck = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => {
          setIsWaking(true);
          controller.abort();
        }, 3000);

        const res = await fetch("/health", { signal: controller.signal });
        clearTimeout(timeoutId);

        if (!res.ok) {
          // 🔥 FIX 2: If the server returns 400, 500, etc. immediately, take over the screen!
          setIsWaking(true);
          startPolling();
        } else {
          startKeepAlive();
        }
      } catch (error) {
        setIsWaking(true);
        startPolling();
      }
    };

    initialCheck();

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
      if (keepAliveIntervalRef.current)
        clearInterval(keepAliveIntervalRef.current);
    };
  }, []);

  // 4. The Blocking Takeover UI
  if (isWaking) {
    return (
      <div className="fixed inset-0 z-[9999] flex flex-col items-center justify-center bg-slate-50 animate-in fade-in duration-500">
        <div className="flex flex-col items-center space-y-6">
          <Loader2 className="h-12 w-12 animate-spin text-blue-600" />

          <div className="text-center space-y-2">
            <h2 className="text-2xl font-extrabold text-slate-900 tracking-tight">
              The app server is loading...
            </h2>
            <p className="text-slate-500 font-medium">
              This typically takes about 50 seconds on the free tier.
            </p>
          </div>

          <div className="flex items-center gap-3 mt-8 px-5 py-2.5 bg-white rounded-full border border-slate-200 shadow-sm">
            <span className="text-xs font-bold text-slate-400 uppercase tracking-widest">
              Powered By
            </span>
            <div className="flex items-center gap-1.5 font-bold text-slate-900">
              <Package2 className="h-5 w-5 text-blue-600" /> Naviera
            </div>
          </div>
        </div>
      </div>
    );
  }

  // 5. Normal App Render
  return <>{children}</>;
}
