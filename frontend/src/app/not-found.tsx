// frontend/src/app/[tenant_slug]/not-found.tsx
import { Button } from "@/components/ui/button";
import { PackageX } from "lucide-react";
import Link from "next/link";

export default function TenantNotFound() {
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center p-4 text-center">
      <div className="max-w-md space-y-6">
        <div className="mx-auto w-24 h-24 bg-slate-200 rounded-full flex items-center justify-center mb-6 shadow-inner">
          <PackageX className="h-12 w-12 text-slate-500" />
        </div>
        
        <h1 className="text-4xl font-extrabold text-slate-900 tracking-tight">
          Workspace Not Found
        </h1>
        
        <p className="text-lg text-slate-500">
          We couldn&apos;t find a logistics workspace at this address. Please check the URL or contact support if you believe this is an error.
        </p>
        
        <div className="pt-6">
          <Button asChild size="lg" className="h-12 px-8 rounded-xl font-bold bg-blue-600 hover:bg-blue-700 text-white">
            <Link href="/">Return to Naviera Home</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}