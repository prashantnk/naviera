// src/app/[tenant_slug]/(app)/dashboard/page.tsx

export default async function TenantDashboard({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;

  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-24 bg-green-50">
      <h1 className="text-4xl font-bold">🏢 Tenant Dashboard</h1>
      <p className="mt-4 text-xl">
        You are viewing:{" "}
        <span className="font-mono text-purple-600">{tenant_slug}</span>
      </p>
      <p className="text-sm text-gray-500">(Zone B: App Dashboard)</p>
    </div>
  );
}
