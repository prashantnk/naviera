// frontend/src/components/forms/eway-bill-banner.tsx

import React, { useState } from "react";
import { ExternalLink, Info, Copy, Check } from "lucide-react";
import { Tenant } from "@/types/tenant";

interface EWayBillBannerProps {
  tenant: Tenant | null;
}

export const EWayBillBanner: React.FC<EWayBillBannerProps> = ({ tenant }) => {
  const [copied, setCopied] = useState(false);
  const tenantName = tenant?.name || "Consignor";
  const tenantGstin = tenant?.settings?.contact?.gstin;

  const handleCopy = () => {
    if (tenantGstin) {
      navigator.clipboard.writeText(tenantGstin);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="bg-amber-50/40 border border-amber-200/60 p-3.5 rounded-xl mt-4 flex items-start space-x-2.5 text-xs text-slate-700 animate-in fade-in slide-in-from-top-1 duration-150 shadow-2xs">
      <Info className="h-4.5 w-4.5 text-amber-600 shrink-0 mt-0.5" />
      
      {tenantGstin ? (
        <div className="leading-relaxed">
          Gross invoice value exceeds <strong className="text-slate-900 font-semibold">₹50,000</strong>. 
          If required, please use Consignor (<span className="font-semibold text-slate-800">{tenantName}</span>) GSTIN:{" "}
          <span className="inline-flex items-center gap-1 bg-white border border-slate-200 px-1.5 py-0.5 rounded font-mono font-bold text-slate-900 select-all mx-1.5 shadow-3xs">
            {tenantGstin}
            <button
              type="button"
              onClick={handleCopy}
              className="text-slate-400 hover:text-indigo-600 transition-all active:scale-90 focus:outline-hidden"
              title="Copy GSTIN"
            >
              {copied ? (
                <Check className="h-3 w-3 text-green-600" />
              ) : (
                <Copy className="h-3 w-3" />
              )}
            </button>
          </span>
          to generate the E-Way Bill on the{" "}
          <a
            href="https://ewaybillgst.gov.in/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center font-bold text-indigo-600 hover:text-indigo-700 hover:underline gap-0.5 transition-colors"
          >
            E-Way Bill Portal
            <ExternalLink className="h-3 w-3" />
          </a>
          .
        </div>
      ) : (
        <div className="leading-relaxed">
          Gross invoice value exceeds <strong className="text-slate-900 font-semibold">₹50,000</strong>. 
          Please visit the official{" "}
          <a
            href="https://ewaybillgst.gov.in/"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center font-bold text-indigo-600 hover:text-indigo-700 hover:underline gap-0.5 transition-colors"
          >
            E-Way Bill Portal
            <ExternalLink className="h-3 w-3" />
          </a>
          {" "}to generate the E-Way Bill.
        </div>
      )}
    </div>
  );
};
