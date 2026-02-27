// frontend/src/app/[tenant_slug]/(auth)/login/page.tsx
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { getTenantBySlug } from "@/lib/api";
import { Package2 } from "lucide-react";
import { LoginForm } from "./login-form";

export default async function LoginPage({
    params,
}: {
    params: Promise<{ tenant_slug: string }>;
}) {
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);
    const brand = tenant?.settings?.brand;

    return (
        <Card className="w-full max-w-md shadow-2xl border border-slate-100 rounded-2xl">
            <CardHeader className="space-y-3 text-center pb-6">
                <div className="flex justify-center mb-2">
                    {/* 🔥 SHOW ACTUAL LOGO IF IT EXISTS */}
                    {brand?.logo_url ? (
                        <img src={brand.logo_url} alt={tenant!.name} className="h-12 object-contain" />
                    ) : (
                        <div className="rounded-full bg-primary/10 p-4">
                            <Package2 className="h-8 w-8 text-primary" />
                        </div>
                    )}
                </div>
                <CardTitle className="text-2xl font-bold tracking-tight text-slate-900">
                    Welcome back
                </CardTitle>
                <CardDescription className="text-slate-500">
                    Sign in to your <span className="font-semibold text-slate-700">{tenant?.name || "Naviera"}</span> portal
                </CardDescription>
            </CardHeader>

            <CardContent>
                <LoginForm />
            </CardContent>
        </Card>
    );
}