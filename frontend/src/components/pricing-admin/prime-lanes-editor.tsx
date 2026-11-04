// frontend/src/components/pricing-admin/prime-lanes-editor.tsx
"use client";

/**
 * Logismart Prime lanes editor: the transporter rate table behind the B2B
 * "Logismart Prime" option (API_CONTRACT §7). Staff can read it; owner/admin can
 * edit a row inline, switch lanes on/off, and import a CSV (checked first).
 * `transporter_name` is internal and never shown to customers.
 */
import { Download, FileSpreadsheet, Loader2, RotateCcw, Search, Upload } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  buildQueryCacheKey,
  getCachedQuery,
  setCachedQuery,
} from "@/lib/query-cache";
import { extractApiErrorMessage } from "@/lib/utils";

import { NoticeBanner, NoticeTone } from "./notice-banner";
import {
  downloadPrimeLanesCsv,
  downloadPrimeLanesTemplateCsv,
  fetchPrimeLanes,
  type PrimeLaneRead,
} from "./pricing-admin-api";
import { PrimeImportDialog } from "./prime-import-dialog";
import { PrimeLaneRow } from "./prime-lane-row";
import { EDITABLE_LANE_COLUMNS, filterLanes } from "./prime-lanes-logic";

const TEST_ID = "prime-lanes";
const LOAD_ERROR_TEXT = "We couldn't load the Prime lanes.";

interface PrimeLanesEditorProps {
  tenantSlug: string | null | undefined;
  /** Owner/admin may edit; other staff read only. */
  canEdit: boolean;
}

/**
 * Renders the Prime lanes table with its toolbar.
 *
 * @param props - See `PrimeLanesEditorProps`.
 */
export function PrimeLanesEditor({ tenantSlug, canEdit }: PrimeLanesEditorProps) {
  const [activeOnly, setActiveOnly] = useState(true);
  const cacheKey = buildQueryCacheKey(tenantSlug, "session", "prime-lanes", {
    activeOnly,
  });
  const [lanes, setLanes] = useState<PrimeLaneRead[] | null>(() =>
    getCachedQuery<PrimeLaneRead[]>(cacheKey)
  );
  const [loadError, setLoadError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [importOpen, setImportOpen] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!tenantSlug) return;
    let cancelled = false;
    const cached = getCachedQuery<PrimeLaneRead[]>(cacheKey);
    if (cached !== null && reloadKey === 0) {
      setLanes(cached);
      setLoadError(null);
    }
    fetchPrimeLanes(activeOnly, tenantSlug).then(
      (fresh) => {
        setCachedQuery(cacheKey, fresh);
        if (cancelled) return;
        setLanes(fresh);
        setLoadError(null);
      },
      (err: unknown) => {
        if (!cancelled && cached === null) {
          setLoadError(extractApiErrorMessage(err, LOAD_ERROR_TEXT));
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, [tenantSlug, activeOnly, cacheKey, reloadKey]);

  /** Re-fetches the lanes (after an import, an Active switch, or "Try again"). */
  const load = useCallback(() => setReloadKey((key) => key + 1), []);

  const visible = useMemo(() => (lanes ? filterLanes(lanes, query) : []), [lanes, query]);

  const replaceLane = (updated: PrimeLaneRead) => {
    setLanes((current) => {
      if (!current) return current;
      const next = current.map((l) => (l.id === updated.id ? updated : l));
      setCachedQuery(cacheKey, next);
      return next;
    });
  };

  const download = async () => {
    setDownloading(true);
    try {
      await downloadPrimeLanesCsv();
    } catch (err) {
      toast.error(extractApiErrorMessage(err, "The CSV could not be downloaded."));
    } finally {
      setDownloading(false);
    }
  };

  const downloadTemplate = async () => {
    setDownloadingTemplate(true);
    try {
      await downloadPrimeLanesTemplateCsv();
    } catch (err) {
      toast.error(extractApiErrorMessage(err, "The template CSV could not be downloaded."));
    } finally {
      setDownloadingTemplate(false);
    }
  };

  return (
    <Card className="min-w-0 overflow-hidden border-slate-200 shadow-sm" data-testid={`${TEST_ID}.card`}>
      <CardHeader>
        <CardTitle>Prime lanes</CardTitle>
        <CardDescription>
          What each transporter charges you per route. Customers see your price: this cost plus the
          lane&apos;s markup and GST, worked out by the server. Only one transporter per route is
          active at a time. A Logismart Prime markup set in Settings ▸ Pricing replaces every
          lane&apos;s own markup.
        </CardDescription>
      </CardHeader>
      <CardContent className="min-w-0 space-y-4">
        <div className="flex flex-col gap-3 min-w-0 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-1 flex-col gap-3 min-w-0 sm:flex-row sm:items-center">
            <div className="relative w-full min-w-0 sm:max-w-xs">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" aria-hidden />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search zone or transporter"
                aria-label="Search lanes"
                data-testid={`${TEST_ID}.search`}
                className="min-w-0 w-full bg-white pl-8"
              />
            </div>
            <label className="flex cursor-pointer items-center gap-2 text-xs font-semibold text-slate-700">
              <input
                type="checkbox"
                checked={activeOnly}
                onChange={(e) => setActiveOnly(e.target.checked)}
                data-testid={`${TEST_ID}.active-only`}
                className="h-4 w-4 rounded border-slate-300 accent-primary"
              />
              Active lanes only
            </label>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={downloadingTemplate}
              onClick={downloadTemplate}
              data-testid="prime-lanes-template-csv"
              className="bg-white"
            >
              {downloadingTemplate ? (
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <FileSpreadsheet className="mr-2 h-4 w-4" />
              )}
              Download Template CSV
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={downloading}
              onClick={download}
              data-testid={`${TEST_ID}.export`}
              className="bg-white"
            >
              {downloading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
              Download CSV
            </Button>
            {canEdit && (
              <Button
                type="button"
                size="sm"
                onClick={() => setImportOpen(true)}
                data-testid={`${TEST_ID}.import-open`}
              >
                <Upload className="mr-2 h-4 w-4" />
                Import CSV
              </Button>
            )}
          </div>
        </div>

        {!canEdit && (
          <NoticeBanner tone={NoticeTone.INFO} title="View only" testId={`${TEST_ID}.read-only`}>
            Only the owner or an admin can change Prime lanes.
          </NoticeBanner>
        )}

        {loadError ? (
          <div data-testid={`${TEST_ID}.load-error`} className="space-y-3">
            <NoticeBanner tone={NoticeTone.WARNING} title={LOAD_ERROR_TEXT}>
              {loadError}
            </NoticeBanner>
            <Button type="button" variant="outline" size="sm" onClick={load}>
              <RotateCcw className="mr-2 h-4 w-4" />
              Try again
            </Button>
          </div>
        ) : lanes === null ? (
          <div data-testid={`${TEST_ID}.loading`} className="space-y-2.5 py-6 text-sm text-slate-500">
            <span className="sr-only">Loading lanes…</span>
            <div className="h-10 w-full rounded-lg bg-slate-100 animate-pulse" />
            <div className="h-10 w-full rounded-lg bg-slate-100 animate-pulse" />
            <div className="h-10 w-full rounded-lg bg-slate-100 animate-pulse" />
          </div>
        ) : lanes.length === 0 ? (
          <NoticeBanner
            tone={NoticeTone.INFO}
            title={activeOnly ? "No active Prime lanes yet" : "No Prime lanes yet"}
            testId={`${TEST_ID}.empty`}
          >
            {activeOnly
              ? "Untick “Active lanes only” to see switched-off lanes. "
              : ""}
            Until a route has an active lane, B2B customers cannot book Logismart Prime on it.
            {canEdit && " Use “Import CSV” to add lanes."}
          </NoticeBanner>
        ) : visible.length === 0 ? (
          <NoticeBanner tone={NoticeTone.INFO} title="No lanes match your search" testId={`${TEST_ID}.no-match`}>
            Try a different zone or transporter name.
          </NoticeBanner>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-slate-200">
            <Table data-testid={`${TEST_ID}.table`}>
              <TableHeader>
                <TableRow>
                  <TableHead>Route</TableHead>
                  <TableHead>Transporter (internal)</TableHead>
                  {EDITABLE_LANE_COLUMNS.map((column) => (
                    <TableHead key={column.field}>{column.label}</TableHead>
                  ))}
                  <TableHead>Active</TableHead>
                  {canEdit && <TableHead className="text-right">Edit</TableHead>}
                </TableRow>
              </TableHeader>
              <TableBody>
                {visible.map((lane) => (
                  <PrimeLaneRow
                    key={lane.id}
                    lane={lane}
                    tenantSlug={tenantSlug}
                    canEdit={canEdit}
                    onSaved={replaceLane}
                    onActiveChanged={load}
                  />
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>

      {canEdit && (
        <PrimeImportDialog open={importOpen} onOpenChange={setImportOpen} tenantSlug={tenantSlug} onImported={load} />
      )}
    </Card>
  );
}
