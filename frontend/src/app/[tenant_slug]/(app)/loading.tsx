// frontend/src/app/[tenant_slug]/(app)/loading.tsx
/**
 * Instant route-transition skeleton for authenticated workspace screens.
 *
 * When a user clicks any sidebar link or dashboard tile whose route bundle is
 * still streaming, Next.js App Router swaps this skeleton into `<main>` in <16ms
 * instead of freezing on the previous screen.
 */
export default function WorkspaceLoading() {
  return (
    <div
      data-testid="workspace-route-loading"
      aria-busy="true"
      aria-label="Loading workspace screen"
      className="mx-auto max-w-7xl space-y-5 pb-12 animate-in fade-in duration-150"
    >
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-slate-200/80 pb-4">
        <div className="space-y-2">
          <div className="h-7 w-48 animate-pulse rounded-lg bg-slate-200/80" />
          <div className="h-4 w-72 animate-pulse rounded-md bg-slate-200/60" />
        </div>
        <div className="flex items-center gap-2">
          <div className="h-9 w-28 animate-pulse rounded-lg bg-slate-200/70" />
          <div className="h-9 w-36 animate-pulse rounded-lg bg-slate-200/80" />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <div className="h-28 animate-pulse rounded-xl border border-slate-200/80 bg-white p-4 shadow-2xs" />
        <div className="h-28 animate-pulse rounded-xl border border-slate-200/80 bg-white p-4 shadow-2xs" />
        <div className="h-28 animate-pulse rounded-xl border border-slate-200/80 bg-white p-4 shadow-2xs" />
      </div>

      <div className="rounded-xl border border-slate-200/80 bg-white p-5 shadow-2xs space-y-3">
        <div className="h-10 w-full animate-pulse rounded-lg bg-slate-100" />
        <div className="h-12 w-full animate-pulse rounded-lg bg-slate-50" />
        <div className="h-12 w-full animate-pulse rounded-lg bg-slate-50" />
        <div className="h-12 w-full animate-pulse rounded-lg bg-slate-50" />
      </div>
    </div>
  );
}
