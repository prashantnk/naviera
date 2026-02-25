// src/app/[tenant_slug]/(auth)/login/page.tsx
import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import { getTenantBySlug } from "@/lib/api";
import { Package2 } from "lucide-react";
import { LoginForm } from "./login-form"; // <--- Import our new form

export default async function LoginPage({
    params,
}: {
    params: Promise<{ tenant_slug: string }>;
}) {
    const { tenant_slug } = await params;
    const tenant = await getTenantBySlug(tenant_slug);

    return (
        <Card className="w-full max-w-md shadow-lg border-0">
            <CardHeader className="space-y-3 text-center pb-6">
                <div className="flex justify-center mb-2">
                    <div className="rounded-full bg-primary/10 p-4">
                        <Package2 className="h-8 w-8 text-primary" />
                    </div>
                </div>
                <CardTitle className="text-2xl font-bold tracking-tight text-slate-900">
                    Welcome back
                </CardTitle>
                <CardDescription className="text-slate-500">
                    Sign in to your <span className="font-semibold text-slate-700">{tenant?.name || "Naviera"}</span> account
                </CardDescription>
            </CardHeader>

            <CardContent>
                {/* Pass the dynamic slug down to the client component so it knows where to send the API request */}
                <LoginForm />
            </CardContent>
        </Card>
    );
}