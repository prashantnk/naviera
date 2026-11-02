// frontend/src/app/[tenant_slug]/(app)/support/page.tsx
"use client";

import {
  SupportTicketCreate,
  SupportTicketDetailRead,
  SupportTicketMessageRead,
  SupportTicketRead,
  SupportTicketsService,
} from "@/api_client";
import { useUser } from "@/components/auth/auth-guard";
import { LearnMore } from "@/components/finance/learn-more";
import {
  CLAIMS_FINANCE_CHIP,
  SUPPORT_HELP_POINTS,
  readTicketPrefill,
  ticketNeedsAwb,
  type CategoryGroupKey,
} from "@/components/support/ticket-rules";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { extractApiErrorMessage, formatIstDateTime } from "@/lib/utils";
import {
  CheckCircle2,
  Clock,
  Info,
  LifeBuoy,
  Loader2,
  MessageSquare,
  Plus,
  RotateCcw,
  Search,
  Send,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

type TicketStatusTab = "OPEN" | "RESOLVED" | "CLOSED";

interface CategoryChipOption {
  group: CategoryGroupKey;
  label: string;
}

const SHIPMENT_ISSUE_CHIPS: readonly string[] = [
  "Reattempt or Delay in delivery / consignee pickup / return",
  "Firstmile / Seller Pickup related issues",
  "Shipment not delivered (need POD) / Fake remark",
  "Self collect / drop",
  "Damage / Missing / Mismatch",
  "Update shipment details",
  "Cancel delivery / pickup",
  CLAIMS_FINANCE_CHIP,
  "Protect VAS",
  "Channel integration",
  "Behaviour complaint against staff",
];

const OTHER_ISSUE_CHIPS: readonly string[] = [
  "Tech Support",
  "Account",
];

const STATUS_TABS: readonly { value: TicketStatusTab; label: string }[] = [
  { value: "OPEN", label: "Open" },
  { value: "RESOLVED", label: "Resolved" },
  { value: "CLOSED", label: "Closed" },
];

export const CLOSED_TICKET_CUSTOMER_NOTICE =
  "This ticket is closed and cannot receive new replies. If you still need help, please reopen by raising a new ticket.";

/**
 * True when a ticket message was sent by tenant staff (`owner`, `admin`,
 * `operations_user`, `support_user`) rather than a merchant (`customer`) (D-19).
 */
export function isSupportStaffSender(
  senderRole: string | null | undefined
): boolean {
  if (!senderRole) return false;
  return senderRole.trim().toLowerCase() !== "customer";
}

function _formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return formatIstDateTime(
    iso,
    {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    },
    iso
  );
}

function _renderStatusBadge(status: string | undefined) {
  const normalized = (status || "OPEN").toUpperCase();
  if (normalized === "RESOLVED") {
    return (
      <Badge
        variant="outline"
        className="bg-emerald-50 text-emerald-700 border-emerald-200 font-semibold text-xs"
      >
        Resolved
      </Badge>
    );
  }
  if (normalized === "CLOSED") {
    return (
      <Badge
        variant="outline"
        className="bg-slate-100 text-slate-600 border-slate-200 font-semibold text-xs"
      >
        Closed
      </Badge>
    );
  }
  return (
    <Badge
      variant="outline"
      className="bg-amber-50 text-amber-700 border-amber-200 font-semibold text-xs"
    >
      Open
    </Badge>
  );
}

function _renderCategoryGroupPill(group: string | undefined) {
  const normalized = (group || "SHIPMENT_ISSUE").toUpperCase();
  if (normalized === "OTHER_ISSUE") {
    return (
      <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-slate-600">
        Other Issue
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-md bg-sky-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-sky-700">
      Shipment Issue
    </span>
  );
}

export default function SupportTicketsPage() {
  const { capabilities, user: currentUser } = useUser();
  const canWrite = capabilities.canWrite;

  const [activeTab, setActiveTab] = useState<TicketStatusTab>("OPEN");
  const [searchQuery, setSearchQuery] = useState("");
  const [tickets, setTickets] = useState<SupportTicketRead[]>([]);
  const [loading, setLoading] = useState(true);

  // Raise Ticket Modal State
  const [isRaiseOpen, setIsRaiseOpen] = useState(false);
  const [selectedChip, setSelectedChip] = useState<CategoryChipOption | null>(null);
  const [trackingIdInput, setTrackingIdInput] = useState("");
  const [subjectInput, setSubjectInput] = useState("");
  const [descriptionInput, setDescriptionInput] = useState("");
  const [submittingTicket, setSubmittingTicket] = useState(false);
  const awbRequired = selectedChip
    ? ticketNeedsAwb(selectedChip.group, selectedChip.label)
    : false;
  const awbMissing = awbRequired && !trackingIdInput.trim();

  // Deep links: the dashboard Support card (`/support?tab=RESOLVED`) and "Need help?"
  // on a rejected weight claim (`/support?awb=...&category=...` opens a pre-filled ticket).
  // Read once on mount from window.location to avoid a useSearchParams Suspense boundary.
  useEffect(() => {
    const search = window.location.search;
    const requestedTab = new URLSearchParams(search).get("tab");
    const match = STATUS_TABS.find((tab) => tab.value === requestedTab);
    if (match) setActiveTab(match.value);
    const prefill = readTicketPrefill(search);
    if (prefill && canWrite) {
      const chipLabel = SHIPMENT_ISSUE_CHIPS.find((label) => label === prefill.category);
      setSelectedChip(chipLabel ? { group: "SHIPMENT_ISSUE", label: chipLabel } : null);
      setSubjectInput(chipLabel || "");
      setTrackingIdInput(prefill.awb);
      setIsRaiseOpen(true);
    }
  }, [canWrite]);

  // Conversation Detail Dialog State
  const [activeTicketId, setActiveTicketId] = useState<string | null>(null);
  const [ticketDetail, setTicketDetail] = useState<SupportTicketDetailRead | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [sendingReply, setSendingReply] = useState(false);
  const [updatingStatus, setUpdatingStatus] = useState(false);

  const fetchTickets = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await SupportTicketsService.listSupportTickets(
        activeTab,
        searchQuery.trim() || null
      );
      setTickets(rows);
    } catch (error: unknown) {
      toast.error(extractApiErrorMessage(error, "Failed to load support tickets"));
    } finally {
      setLoading(false);
    }
  }, [activeTab, searchQuery]);

  useEffect(() => {
    fetchTickets();
  }, [fetchTickets]);

  const openTicketConversation = async (ticketId: string) => {
    setActiveTicketId(ticketId);
    setLoadingDetail(true);
    setReplyText("");
    try {
      const detail = await SupportTicketsService.getSupportTicket(ticketId);
      setTicketDetail(detail);
    } catch (error: unknown) {
      toast.error(
        extractApiErrorMessage(error, "Could not load ticket conversation")
      );
      setActiveTicketId(null);
    } finally {
      setLoadingDetail(false);
    }
  };

  const resetRaiseTicketForm = () => {
    setSelectedChip(null);
    setTrackingIdInput("");
    setSubjectInput("");
    setDescriptionInput("");
  };

  const handleOpenRaiseModal = () => {
    resetRaiseTicketForm();
    setIsRaiseOpen(true);
  };

  const handleSelectChip = (group: CategoryGroupKey, label: string) => {
    setSelectedChip({ group, label });
    if (!subjectInput.trim()) {
      setSubjectInput(label);
    }
  };

  const handleCreateTicket = async () => {
    if (!selectedChip) {
      toast.error("Please select an issue category first");
      return;
    }
    if (awbMissing) {
      toast.error("Please enter the AWB number of the shipment this issue is about");
      return;
    }
    if (!descriptionInput.trim()) {
      toast.error("Please describe your issue");
      return;
    }

    const payload: SupportTicketCreate = {
      category_group: selectedChip.group,
      sub_category: selectedChip.label,
      subject: subjectInput.trim() || selectedChip.label,
      description: descriptionInput.trim(),
      tracking_id: trackingIdInput.trim() || null,
    };

    setSubmittingTicket(true);
    try {
      const created = await SupportTicketsService.createSupportTicket(payload);
      toast.success(`Support ticket ${created.ticket_number} created`);
      setIsRaiseOpen(false);
      resetRaiseTicketForm();
      if (activeTab !== "OPEN") {
        setActiveTab("OPEN");
      } else {
        fetchTickets();
      }
    } catch (error: unknown) {
      toast.error(extractApiErrorMessage(error, "Failed to raise support ticket"));
    } finally {
      setSubmittingTicket(false);
    }
  };

  const handleSendReply = async () => {
    if (!activeTicketId || !replyText.trim()) return;
    setSendingReply(true);
    try {
      const updated = await SupportTicketsService.addSupportTicketMessage(
        activeTicketId,
        { message: replyText.trim() }
      );
      setTicketDetail(updated);
      setReplyText("");
      toast.success("Reply posted to ticket");
      fetchTickets();
    } catch (error: unknown) {
      toast.error(extractApiErrorMessage(error, "Failed to post reply"));
    } finally {
      setSendingReply(false);
    }
  };

  const handleUpdateTicketStatus = async (nextStatus: TicketStatusTab) => {
    if (!activeTicketId) return;
    setUpdatingStatus(true);
    try {
      const updated = await SupportTicketsService.updateSupportTicketStatus(
        activeTicketId,
        { status: nextStatus }
      );
      setTicketDetail(updated);
      toast.success(`Ticket marked as ${nextStatus}`);
      fetchTickets();
    } catch (error: unknown) {
      toast.error(extractApiErrorMessage(error, "Failed to update ticket status"));
    } finally {
      setUpdatingStatus(false);
    }
  };

  const currentTimestampLabel = useMemo(() => {
    return _formatDateTime(new Date().toISOString());
  }, []);

  return (
    <div className="space-y-5 max-w-7xl mx-auto pb-12">
      {/* Top Header matching Delhivery One */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 border-b border-slate-200 pb-4">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold text-slate-900">Support</h1>
          <LearnMore title="Support tickets" points={SUPPORT_HELP_POINTS} />
        </div>

        {canWrite && (
          <Button
            onClick={handleOpenRaiseModal}
            className="bg-slate-900 hover:bg-slate-800 text-white font-semibold shadow-sm gap-2"
            data-testid="support.actions.raise"
          >
            <Plus className="h-4 w-4" />
            Raise a ticket
          </Button>
        )}
      </div>

      {/* Status Tabs: Open / Resolved / Closed */}
      <div className="border-b border-slate-200">
        <div className="flex items-center gap-6">
          {STATUS_TABS.map((tab) => {
            const isSelected = activeTab === tab.value;
            return (
              <button
                key={tab.value}
                type="button"
                onClick={() => setActiveTab(tab.value)}
                className={
                  isSelected
                    ? "pb-3 text-sm font-semibold text-primary border-b-2 border-primary transition-colors"
                    : "pb-3 text-sm font-medium text-slate-500 hover:text-slate-800 border-b-2 border-transparent transition-colors"
                }
              >
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Resolved Tab Info Note */}
      {activeTab === "RESOLVED" && (
        <div className="flex items-center gap-2 rounded-lg bg-slate-50 border border-slate-200 px-3.5 py-2.5 text-xs italic text-slate-600">
          <Info className="h-4 w-4 text-slate-500 shrink-0" />
          <span>
            Below tickets have been resolved by our client support agent; add comments to reopen if needed
          </span>
        </div>
      )}

      {/* Filter Bar */}
      <div className="flex min-w-0 flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex min-w-0 items-center max-w-md w-full rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden">
          <span className="px-3 py-2 text-xs font-semibold text-slate-600 bg-slate-50 border-r border-slate-200 whitespace-nowrap shrink-0">
            Ticket ID / AWB
          </span>
          <div className="relative min-w-0 flex-1">
            <Input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search ticket ID or AWB"
              className="min-w-0 w-full border-0 shadow-none focus-visible:ring-0 text-sm h-9 pr-8"
            />
            <Search className="absolute right-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          </div>
        </div>

        <div className="text-xs text-slate-500">
          Showing <span className="font-semibold text-slate-800">{tickets.length}</span>{" "}
          {activeTab.toLowerCase()} tickets
        </div>
      </div>

      {/* Tickets Table (desktop) / cards (phone) */}
      <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
        <div className="hidden md:block overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-500">
                <th className="py-3.5 px-4">TICKET ID &amp; AWB</th>
                <th className="py-3.5 px-4">RAISED BY</th>
                <th className="py-3.5 px-4">ISSUE CATEGORY</th>
                <th className="py-3.5 px-4">STATUS</th>
                <th className="py-3.5 px-4">CREATED</th>
                <th className="py-3.5 px-4">LAST UPDATE</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm">
              {loading ? (
                <tr>
                  <td colSpan={6} className="py-16 text-center">
                    <div className="inline-flex items-center gap-2 text-slate-500">
                      <Loader2 className="h-5 w-5 animate-spin text-primary" />
                      <span>Loading support tickets</span>
                    </div>
                  </td>
                </tr>
              ) : tickets.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-16 text-center">
                    <div className="flex flex-col items-center justify-center space-y-2">
                      <div className="h-12 w-12 rounded-full bg-slate-100 flex items-center justify-center">
                        <LifeBuoy className="h-6 w-6 text-slate-400" />
                      </div>
                      <p className="text-sm font-semibold text-slate-700">
                        No {activeTab.toLowerCase()} support tickets found
                      </p>
                      <p className="text-xs text-slate-500 max-w-sm">
                        Need help with a shipment pickup, delivery reattempt, POD, or billing query? Click &ldquo;+ Raise a ticket&rdquo; above.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                tickets.map((ticket) => (
                  <tr
                    key={ticket.id}
                    onClick={() => openTicketConversation(ticket.id)}
                    className="hover:bg-slate-50/90 cursor-pointer transition-colors"
                  >
                    <td className="py-3.5 px-4">
                      <div className="flex flex-col gap-1">
                        <span className="font-bold text-primary hover:underline">
                          {ticket.ticket_number}
                        </span>
                        {ticket.tracking_id ? (
                          <span className="inline-flex items-center w-fit rounded bg-slate-100 px-2 py-0.5 text-[11px] font-mono font-medium text-slate-700">
                            AWB: {ticket.tracking_id}
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">No AWB linked</span>
                        )}
                      </div>
                    </td>
                    <td className="py-3.5 px-4 text-slate-700 font-medium">
                      {ticket.raised_by_email || currentUser?.email || "—"}
                    </td>
                    <td className="py-3.5 px-4">
                      <div className="flex flex-col gap-1 max-w-md">
                        <span className="font-medium text-slate-900 line-clamp-1">
                          {ticket.sub_category}
                        </span>
                        <div className="flex items-center gap-2">
                          {_renderCategoryGroupPill(ticket.category_group)}
                          <span className="text-xs text-slate-500 truncate">
                            {ticket.description}
                          </span>
                        </div>
                      </div>
                    </td>
                    <td className="py-3.5 px-4">{_renderStatusBadge(ticket.status)}</td>
                    <td className="py-3.5 px-4 text-xs text-slate-600 whitespace-nowrap">
                      {_formatDateTime(ticket.created_at)}
                    </td>
                    <td className="py-3.5 px-4 text-xs text-slate-600 whitespace-nowrap">
                      {_formatDateTime(ticket.updated_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="md:hidden divide-y divide-slate-100" data-testid="support.tickets.cards">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-slate-500">
              <Loader2 className="h-5 w-5 animate-spin text-primary" />
              Loading support tickets
            </div>
          ) : tickets.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm font-semibold text-slate-700">
              No {activeTab.toLowerCase()} support tickets found
            </div>
          ) : (
            tickets.map((ticket) => (
              <button
                key={ticket.id}
                type="button"
                onClick={() => openTicketConversation(ticket.id)}
                className="block w-full space-y-1.5 p-4 text-left hover:bg-slate-50/90"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-bold text-primary break-all">
                    {ticket.ticket_number}
                  </span>
                  {_renderStatusBadge(ticket.status)}
                </div>
                <p className="text-sm font-medium text-slate-900 line-clamp-2">
                  {ticket.sub_category}
                </p>
                {ticket.tracking_id && (
                  <p className="text-[11px] font-mono text-slate-600 break-all">
                    AWB: {ticket.tracking_id}
                  </p>
                )}
                <p className="text-[11px] text-slate-500">
                  Updated {_formatDateTime(ticket.updated_at)}
                </p>
              </button>
            ))
          )}
        </div>

        {/* Table Footer matching Delhivery One */}
        <div className="flex items-center justify-between border-t border-slate-200 bg-slate-50/60 px-4 py-2.5 text-xs text-slate-500">
          <span>
            Showing{" "}
            <strong className="text-slate-700">
              {tickets.length > 0 ? 1 : 0} - {tickets.length}
            </strong>{" "}
            of <strong className="text-slate-700">{tickets.length}</strong>
          </span>
        </div>
      </div>

      {/* Raise a Ticket Modal matching snipit_0amobi97r06dg.png */}
      <Dialog open={isRaiseOpen} onOpenChange={setIsRaiseOpen}>
        <DialogContent className="sm:max-w-2xl p-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-4 border-b border-slate-200">
            <div className="flex items-center gap-2.5">
              <DialogTitle className="text-xl font-bold text-slate-900">
                Raise a ticket
              </DialogTitle>
            </div>
            <DialogDescription className="sr-only">
              Select a shipment or account category and describe your support issue.
            </DialogDescription>
          </DialogHeader>

          <div className="p-6 max-h-[70vh] overflow-y-auto space-y-5 bg-slate-50/50">
            {/* Chat-style Support Prompt Bubble */}
            <div className="flex items-start gap-3">
              <div className="h-9 w-9 rounded-full bg-slate-900 text-white flex items-center justify-center text-[10px] font-extrabold tracking-tight shrink-0 shadow-sm">
                SUPPORT
              </div>

              <div className="flex-1 rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-4">
                <div>
                  <h3 className="text-sm font-bold text-slate-900">
                    Help us understand your issue
                  </h3>
                </div>

                {/* SHIPMENT ISSUE Chips */}
                <div className="space-y-2">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    SHIPMENT ISSUE
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {SHIPMENT_ISSUE_CHIPS.map((label) => {
                      const isSelected =
                        selectedChip?.group === "SHIPMENT_ISSUE" &&
                        selectedChip.label === label;
                      return (
                        <button
                          key={label}
                          type="button"
                          onClick={() => handleSelectChip("SHIPMENT_ISSUE", label)}
                          className={
                            isSelected
                              ? "rounded-full border border-slate-900 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white transition-all shadow-sm"
                              : "rounded-full border border-slate-300 bg-white hover:border-slate-500 hover:bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-800 transition-all"
                          }
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* OTHER ISSUE Chips */}
                <div className="space-y-2 pt-1">
                  <p className="text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    OTHER ISSUE
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {OTHER_ISSUE_CHIPS.map((label) => {
                      const isSelected =
                        selectedChip?.group === "OTHER_ISSUE" &&
                        selectedChip.label === label;
                      return (
                        <button
                          key={label}
                          type="button"
                          onClick={() => handleSelectChip("OTHER_ISSUE", label)}
                          className={
                            isSelected
                              ? "rounded-full border border-slate-900 bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white transition-all shadow-sm"
                              : "rounded-full border border-slate-300 bg-white hover:border-slate-500 hover:bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-800 transition-all"
                          }
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="text-[11px] text-slate-400 pt-1">
                  {currentTimestampLabel}
                </div>
              </div>
            </div>

            {/* Expanded Form Fields once a category chip is clicked */}
            {selectedChip && (
              <div className="min-w-0 overflow-hidden rounded-xl border border-slate-200 bg-white p-4 shadow-sm space-y-4">
                <div className="flex items-center justify-between gap-2 border-b border-slate-100 pb-3">
                  <div className="flex items-center gap-2 flex-wrap">
                    {_renderCategoryGroupPill(selectedChip.group)}
                    <span className="text-xs font-bold text-slate-900">
                      {selectedChip.label}
                    </span>
                  </div>
                  <span className="text-[11px] text-emerald-700 font-semibold">
                    Category Selected
                  </span>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 min-w-0">
                  <div className="min-w-0 space-y-1.5">
                    <Label htmlFor="ticket-awb" className="text-xs font-semibold text-slate-700">
                      AWB / Tracking ID{" "}
                      {awbRequired ? (
                        <span className="text-rose-600 font-normal">*</span>
                      ) : (
                        <span className="text-slate-400 font-normal">(optional)</span>
                      )}
                    </Label>
                    <Input
                      id="ticket-awb"
                      value={trackingIdInput}
                      onChange={(e) => setTrackingIdInput(e.target.value)}
                      placeholder="AWB number of the shipment"
                      className="min-w-0 w-full text-sm"
                      aria-invalid={awbMissing}
                      data-testid="support.raise.awb"
                    />
                  </div>

                  <div className="min-w-0 space-y-1.5">
                    <Label htmlFor="ticket-subject" className="text-xs font-semibold text-slate-700">
                      Subject
                    </Label>
                    <Input
                      id="ticket-subject"
                      value={subjectInput}
                      onChange={(e) => setSubjectInput(e.target.value)}
                      placeholder="Short summary of the issue"
                      className="min-w-0 w-full text-sm"
                    />
                  </div>
                </div>

                <div className="min-w-0 space-y-1.5">
                  <Label htmlFor="ticket-description" className="text-xs font-semibold text-slate-700">
                    Describe your issue
                  </Label>
                  <Textarea
                    id="ticket-description"
                    rows={3}
                    value={descriptionInput}
                    onChange={(e) => setDescriptionInput(e.target.value)}
                    placeholder="Provide AWB details, consignee contact, or remark details so our support engineer can resolve this quickly"
                    className="min-w-0 w-full text-sm"
                  />
                </div>
              </div>
            )}
          </div>

          {/* Modal Footer */}
          <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white px-6 py-3.5">
            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={resetRaiseTicketForm}
                className="h-8 text-xs font-semibold text-primary border-slate-200 gap-1.5"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                Reset Categories
              </Button>
            </div>

            <div className="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setIsRaiseOpen(false)}
                className="h-8 text-xs"
              >
                Cancel
              </Button>
              <Button
                type="button"
                size="sm"
                disabled={
                  !selectedChip || awbMissing || !descriptionInput.trim() || submittingTicket
                }
                onClick={handleCreateTicket}
                className="h-8 text-xs bg-slate-900 hover:bg-slate-800 text-white font-semibold"
              >
                {submittingTicket ? (
                  <>
                    <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                    Submitting
                  </>
                ) : (
                  "Submit Ticket"
                )}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Ticket Conversation Drawer / Dialog */}
      <Dialog
        open={Boolean(activeTicketId)}
        onOpenChange={(open) => {
          if (!open) {
            setActiveTicketId(null);
            setTicketDetail(null);
          }
        }}
      >
        <DialogContent className="sm:max-w-2xl p-0 overflow-hidden">
          <DialogHeader className="px-6 pt-5 pb-4 border-b border-slate-200 bg-slate-50/70">
            <div className="flex flex-wrap items-center justify-between gap-2 pr-6">
              <div className="flex items-center gap-2.5">
                <DialogTitle className="text-lg font-bold text-slate-900">
                  {ticketDetail?.ticket_number || "Support Ticket"}
                </DialogTitle>
                {ticketDetail && _renderStatusBadge(ticketDetail.status)}
                {ticketDetail && _renderCategoryGroupPill(ticketDetail.category_group)}
              </div>

              {capabilities.canHandleSupport && ticketDetail && (
                <div className="flex items-center gap-2">
                  {ticketDetail.status !== "RESOLVED" && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={updatingStatus}
                      onClick={() => handleUpdateTicketStatus("RESOLVED")}
                      className="h-7 text-xs border-emerald-200 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 gap-1"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      Mark Resolved
                    </Button>
                  )}
                  {ticketDetail.status !== "CLOSED" && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      disabled={updatingStatus}
                      onClick={() => handleUpdateTicketStatus("CLOSED")}
                      className="h-7 text-xs border-slate-200 bg-white text-slate-700 hover:bg-slate-100 gap-1"
                    >
                      <XCircle className="h-3.5 w-3.5" />
                      Close Ticket
                    </Button>
                  )}
                </div>
              )}
            </div>
            <DialogDescription className="text-xs text-slate-600 pt-1">
              {ticketDetail?.sub_category}
              {ticketDetail?.tracking_id ? ` • AWB: ${ticketDetail.tracking_id}` : ""}
            </DialogDescription>
          </DialogHeader>

          {loadingDetail || !ticketDetail ? (
            <div className="py-16 flex items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-primary" />
            </div>
          ) : (
            <div className="divide-y divide-slate-200">
              {/* Ticket Metadata Strip */}
              <div className="px-6 py-3 bg-white grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                <div>
                  <span className="text-slate-400 block">Raised By</span>
                  <span className="font-semibold text-slate-800 truncate block">
                    {ticketDetail.raised_by_email || "Merchant"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block">AWB / Shipment</span>
                  <span className="font-mono font-semibold text-slate-800">
                    {ticketDetail.tracking_id || "General Query"}
                  </span>
                </div>
                <div>
                  <span className="text-slate-400 block">Created On</span>
                  <span className="font-medium text-slate-700">
                    {_formatDateTime(ticketDetail.created_at)}
                  </span>
                </div>
              </div>

              {/* Messages Thread */}
              <div className="p-6 max-h-[45vh] overflow-y-auto space-y-3 bg-slate-50/60">
                {(ticketDetail.messages || []).length === 0 ? (
                  <div className="text-center py-8 text-xs text-slate-500">
                    No conversation messages yet.
                  </div>
                ) : (
                  (ticketDetail.messages || []).map((msg: SupportTicketMessageRead) => {
                    const isSupportAgent = isSupportStaffSender(msg.sender_role);
                    return (
                      <div
                        key={msg.id}
                        className={
                          isSupportAgent
                            ? "rounded-xl border border-sky-200 bg-sky-50/60 p-3.5 space-y-1.5"
                            : "rounded-xl border border-slate-200 bg-white p-3.5 space-y-1.5 shadow-sm"
                        }
                      >
                        <div className="flex items-center justify-between gap-2 text-xs">
                          <div className="flex items-center gap-2">
                            <span className="font-bold text-slate-900">
                              {msg.sender_email}
                            </span>
                            {isSupportAgent ? (
                              <span className="inline-flex items-center gap-1 rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-bold text-sky-800">
                                <ShieldCheck className="h-3 w-3" />
                                Support Agent
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600">
                                <MessageSquare className="h-3 w-3" />
                                Merchant
                              </span>
                            )}
                          </div>
                          <span className="text-[11px] text-slate-400 flex items-center gap-1">
                            <Clock className="h-3 w-3" />
                            {_formatDateTime(msg.created_at)}
                          </span>
                        </div>
                        <p className="text-sm text-slate-800 whitespace-pre-wrap">
                          {msg.message}
                        </p>
                      </div>
                    );
                  })
                )}
              </div>

              {/* Reply Box */}
              <div className="p-4 bg-white space-y-3">
                {ticketDetail.status === "RESOLVED" && (
                  <div className="flex items-center gap-2 rounded-lg bg-amber-50 border border-amber-200 px-3 py-2 text-xs text-amber-800">
                    <Info className="h-4 w-4 shrink-0" />
                    <span>
                      This ticket is marked Resolved. Posting a new comment as a customer will automatically reopen it.
                    </span>
                  </div>
                )}
                {!canWrite ? (
                  <div
                    data-testid="read-only-ticket-notice"
                    className="flex items-center gap-2 rounded-lg bg-slate-100 border border-slate-200 px-3 py-2.5 text-xs text-slate-700"
                  >
                    <Info className="h-4 w-4 shrink-0 text-slate-500" />
                    <span>You have read-only access, so you cannot reply to tickets.</span>
                  </div>
                ) : ticketDetail.status === "CLOSED" && !capabilities.canHandleSupport ? (
                  <div
                    data-testid="closed-ticket-customer-notice"
                    className="flex items-center gap-2 rounded-lg bg-slate-100 border border-slate-200 px-3 py-2.5 text-xs text-slate-700"
                  >
                    <Info className="h-4 w-4 shrink-0 text-slate-500" />
                    <span>{CLOSED_TICKET_CUSTOMER_NOTICE}</span>
                  </div>
                ) : (
                  <div className="flex items-end gap-2">
                    <Textarea
                      rows={2}
                      value={replyText}
                      onChange={(e) => setReplyText(e.target.value)}
                      placeholder="Write a reply or add shipment update details"
                      className="text-sm flex-1"
                    />
                    <Button
                      type="button"
                      disabled={!replyText.trim() || sendingReply}
                      onClick={handleSendReply}
                      className="bg-slate-900 hover:bg-slate-800 text-white font-semibold gap-1.5 h-10"
                    >
                      {sendingReply ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Send className="h-4 w-4" />
                      )}
                      Reply
                    </Button>
                  </div>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
