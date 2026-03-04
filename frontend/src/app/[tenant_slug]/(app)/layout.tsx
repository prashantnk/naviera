// frontend/src/app/[tenant_slug]/(app)/layout.tsx
import { AuthGuard } from "@/components/auth/auth-guard";
import { AppHeader } from "@/components/blocks/app-header";
import { AppSidebar } from "@/components/blocks/app-sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
    return (
        <div className="min-h-screen bg-slate-50 flex">
            <AuthGuard>
                <AppSidebar />
                <div className="flex-1 flex flex-col min-w-0">
                    <AppHeader />
                    <main className="flex-1 p-6">
                        {children}
                    </main>
                </div>
            </AuthGuard>
        </div>
    );
}