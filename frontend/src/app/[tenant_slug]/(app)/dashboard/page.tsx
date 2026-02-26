// src/app/[tenant_slug]/(app)/dashboard/page.tsx

export default async function TenantDashboard({
  params,
}: {
  params: Promise<{ tenant_slug: string }>;
}) {
  const { tenant_slug } = await params;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold text-slate-900">Dashboard</h1>
        <p className="text-slate-500 mt-1">
          Welcome back to your <span className="font-semibold text-slate-700">{tenant_slug}</span> overview.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Placeholder Stat Cards */}
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <p className="text-sm font-medium text-slate-500">Total Shipments</p>
          <p className="text-3xl font-bold text-slate-900 mt-2">1,248</p>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <p className="text-sm font-medium text-slate-500">In Transit</p>
          <p className="text-3xl font-bold text-primary mt-2">42</p>
        </div>
        <div className="bg-white p-6 rounded-xl border border-slate-200 shadow-sm">
          <p className="text-sm font-medium text-slate-500">Delivered (30d)</p>
          <p className="text-3xl font-bold text-slate-900 mt-2">1,102</p>
        </div>
      </div>
    </div>
  );
}