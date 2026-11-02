// frontend/src/components/pricing-admin/prime-import-dialog.tsx
"use client";

/**
 * "Import lanes from CSV": pick a file → the server checks it (dry run) → the
 * admin reads what will change → confirm to import. The server is all-or-nothing,
 * so a file with any row error cannot be imported.
 */
import { FileUp, Loader2 } from "lucide-react";
import { useState, type ChangeEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { extractApiErrorMessage } from "@/lib/utils";

import { NoticeBanner, NoticeTone } from "./notice-banner";
import { importPrimeLanes, type PrimeImportIssue, type PrimeImportReport } from "./pricing-admin-api";
import { formatImportIssue, summarizeImportReport, validateCsvFile } from "./prime-lanes-logic";

const TEST_ID = "prime-lanes.import";
const MAX_LISTED_ISSUES = 50;

interface PrimeImportDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  tenantSlug: string | null | undefined;
  /** Called after a successful import so the table reloads. */
  onImported: () => void;
}

interface IssueListProps {
  title: string;
  issues: readonly PrimeImportIssue[];
  testId: string;
}

/**
 * Lists importer errors or warnings (first 50, then a count of the rest).
 *
 * @param props - Heading, issues and test id.
 */
function IssueList({ title, issues, testId }: IssueListProps) {
  if (issues.length === 0) return null;
  const hidden = issues.length > MAX_LISTED_ISSUES ? issues.length - MAX_LISTED_ISSUES : 0;
  return (
    <div data-testid={testId} className="space-y-1">
      <p className="text-xs font-bold text-slate-800">{title}</p>
      <ul className="max-h-40 space-y-1 overflow-y-auto rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-700">
        {issues.slice(0, MAX_LISTED_ISSUES).map((issue, index) => (
          <li key={`${issue.row ?? "file"}-${index}`}>{formatImportIssue(issue)}</li>
        ))}
        {hidden > 0 && <li className="font-semibold">…and {hidden} more.</li>}
      </ul>
    </div>
  );
}

/**
 * Renders the CSV import dialog with its dry-run preview.
 *
 * @param props - See `PrimeImportDialogProps`.
 */
export function PrimeImportDialog({ open, onOpenChange, tenantSlug, onImported }: PrimeImportDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [report, setReport] = useState<PrimeImportReport | null>(null);
  const [busy, setBusy] = useState(false);

  const reset = () => {
    setFile(null);
    setFileError(null);
    setReport(null);
  };

  const handleOpenChange = (next: boolean) => {
    if (busy) return;
    if (!next) reset();
    onOpenChange(next);
  };

  const handleFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = event.target.files?.[0] ?? null;
    setReport(null);
    setFile(chosen);
    setFileError(chosen ? validateCsvFile(chosen) : null);
  };

  const runDryRun = async () => {
    if (!file) return;
    setBusy(true);
    try {
      setReport(await importPrimeLanes(file, true, tenantSlug));
    } catch (err) {
      toast.error(extractApiErrorMessage(err, "We couldn't check this file."));
    } finally {
      setBusy(false);
    }
  };

  const confirmImport = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const result = await importPrimeLanes(file, false, tenantSlug);
      const summary = summarizeImportReport(result, false);
      if (summary.blocked) {
        setReport(result);
        toast.error(summary.headline);
        return;
      }
      toast.success(summary.headline);
      reset();
      onOpenChange(false);
      onImported();
    } catch (err) {
      toast.error(extractApiErrorMessage(err, "Lanes were not imported."));
    } finally {
      setBusy(false);
    }
  };

  const summary = report ? summarizeImportReport(report, true) : null;
  const canImport = summary !== null && !summary.blocked && !summary.noChanges;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="overflow-x-hidden sm:max-w-lg" data-testid={`${TEST_ID}.dialog`}>
        <DialogHeader className="min-w-0">
          <DialogTitle>Import lanes from CSV</DialogTitle>
          <DialogDescription>
            Use the same columns as &ldquo;Download CSV&rdquo;. We check the file first and show you
            what will change. Nothing is saved until you confirm.
          </DialogDescription>
        </DialogHeader>

        <div className="min-w-0 space-y-4 py-1">
          <Input
            type="file"
            accept=".csv,text/csv"
            onChange={handleFileChange}
            disabled={busy}
            data-testid={`${TEST_ID}.file`}
            className="min-w-0 w-full bg-white"
          />
          {fileError && (
            <NoticeBanner tone={NoticeTone.WARNING} title={fileError} testId={`${TEST_ID}.file-error`} />
          )}

          {summary && report && (
            <div data-testid={`${TEST_ID}.report`} className="space-y-3">
              <NoticeBanner
                tone={summary.blocked ? NoticeTone.WARNING : summary.noChanges ? NoticeTone.INFO : NoticeTone.SUCCESS}
                title={summary.headline}
                testId={`${TEST_ID}.summary`}
              />
              <div className="grid grid-cols-3 gap-2 text-center text-xs">
                <div className="rounded-lg border border-slate-200 bg-white p-2">
                  <span className="block font-mono text-lg font-bold" data-testid={`${TEST_ID}.created`}>
                    {report.created}
                  </span>
                  <span className="text-slate-500">new</span>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-2">
                  <span className="block font-mono text-lg font-bold" data-testid={`${TEST_ID}.updated`}>
                    {report.updated}
                  </span>
                  <span className="text-slate-500">updated</span>
                </div>
                <div className="rounded-lg border border-slate-200 bg-white p-2">
                  <span className="block font-mono text-lg font-bold" data-testid={`${TEST_ID}.deactivated`}>
                    {report.deactivated}
                  </span>
                  <span className="text-slate-500">switched off</span>
                </div>
              </div>
              <IssueList title="Problems to fix" issues={report.errors} testId={`${TEST_ID}.errors`} />
              <IssueList title="Please check" issues={report.warnings} testId={`${TEST_ID}.warnings`} />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" disabled={busy} onClick={() => handleOpenChange(false)}>
            Cancel
          </Button>
          {canImport ? (
            <Button type="button" disabled={busy} onClick={confirmImport} data-testid={`${TEST_ID}.confirm`}>
              {busy && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Import these changes
            </Button>
          ) : (
            <Button
              type="button"
              disabled={busy || !file || fileError !== null}
              onClick={runDryRun}
              data-testid={`${TEST_ID}.check`}
            >
              {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <FileUp className="mr-2 h-4 w-4" />}
              {report ? "Check again" : "Check file"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
