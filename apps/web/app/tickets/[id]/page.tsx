"use client";

import { use, useState, useEffect, useRef, useCallback } from "react";
import { ArrowLeft, CheckCircle, XCircle, MessageSquare, Loader2 } from "lucide-react";
import Link from "next/link";
import { api, type Ticket, type TicketEvent } from "@/app/lib/api";
import { StatusBadge } from "@/app/components/StatusBadge";
import { SeverityBadge } from "@/app/components/SeverityBadge";

const NODE_LABELS: Record<string, string> = {
  triage:       "Triage",
  knowledge:    "Knowledge retrieval",
  investigator: "Investigator",
  join:         "Joining results",
  resolver:     "Drafting reply",
  verifier:     "Verifying draft",
  send_reply:   "Sending reply",
  approval_interrupt:        "Waiting for approval",
  wait_for_customer_reply:   "Sent — awaiting reply",
  execute_actions:           "Executing actions",
  exit_to_human:             "Escalated to human",
  escalate:                  "Escalated",
};

function EventRow({ event }: { event: TicketEvent }) {
  const isEnd = event.type === "node_end";
  const isStart = event.type === "node_start";
  const isComplete = event.type === "complete";
  const isInterrupt = event.type === "interrupt";
  const isError = event.type === "error";

  if (event.type === "done") return null;

  return (
    <div className={`flex items-start gap-2 py-1.5 text-sm ${isError ? "text-red-600" : "text-gray-700"}`}>
      <div className="mt-0.5 shrink-0">
        {isComplete ? (
          <CheckCircle size={14} className="text-green-500" />
        ) : isError ? (
          <XCircle size={14} className="text-red-500" />
        ) : isEnd ? (
          <CheckCircle size={14} className="text-gray-400" />
        ) : isInterrupt ? (
          <MessageSquare size={14} className="text-orange-500" />
        ) : (
          <Loader2 size={14} className={`text-blue-400 ${isStart ? "animate-spin" : ""}`} />
        )}
      </div>
      <span className="leading-tight">
        {isComplete
          ? "Complete"
          : isInterrupt
          ? `Interrupt: ${event.type}`
          : isError
          ? `Error: ${event.message}`
          : event.node
          ? `${NODE_LABELS[event.node] ?? event.node} ${isEnd ? "✓" : "…"}`
          : event.type}
      </span>
    </div>
  );
}

export default function TicketWorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [events, setEvents] = useState<TicketEvent[]>([]);
  const [replyText, setReplyText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  // Poll ticket state
  const pollTicket = useCallback(async () => {
    try {
      const t = await api.getTicket(id);
      setTicket(t);
    } catch (e) {
      setError(String(e));
    }
  }, [id]);

  useEffect(() => {
    void pollTicket();
    const interval = setInterval(pollTicket, 3000);
    return () => clearInterval(interval);
  }, [pollTicket]);

  // SSE event stream
  useEffect(() => {
    const es = new EventSource(api.streamUrl(id));
    es.onmessage = (e) => {
      try {
        const ev: TicketEvent = JSON.parse(e.data as string) as TicketEvent;
        setEvents((prev) => [...prev, ev]);
        if (ev.type === "done") es.close();
      } catch {
        // ignore parse error
      }
    };
    es.onerror = () => es.close();
    return () => es.close();
  }, [id]);

  // Auto-scroll event feed
  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  async function handleApprove(action: "approve" | "reject") {
    setSending(true);
    try {
      await api.approve(id, action);
      await pollTicket();
    } catch (e) {
      alert(String(e));
    } finally {
      setSending(false);
    }
  }

  async function handleReply(e: React.FormEvent) {
    e.preventDefault();
    if (!replyText.trim()) return;
    setSending(true);
    try {
      await api.reply(id, replyText);
      setReplyText("");
      setEvents([]);    // new run — clear feed
      await pollTicket();
    } catch (e) {
      alert(String(e));
    } finally {
      setSending(false);
    }
  }

  const isApprovalPending =
    ticket?.status === "interrupted" &&
    ticket.interrupt_payload?.type === "approval_required";

  const isReplyPending =
    ticket?.status === "interrupted" &&
    ticket.interrupt_payload?.type === "awaiting_customer_reply";

  return (
    <div>
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Link href="/" className="text-gray-400 hover:text-gray-600">
          <ArrowLeft size={18} />
        </Link>
        <div className="flex-1">
          <h1 className="text-lg font-bold text-gray-900 font-mono">{id}</h1>
          {ticket && (
            <div className="flex items-center gap-2 mt-0.5">
              <StatusBadge status={ticket.status} />
              {ticket.triage?.severity && (
                <SeverityBadge severity={ticket.triage.severity} />
              )}
              {ticket.triage?.category && (
                <span className="text-xs text-gray-500 capitalize">
                  {ticket.triage.category}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      <div className="grid grid-cols-3 gap-6">
        {/* Event feed */}
        <div className="col-span-2 space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-700">Agent activity</h2>
            </div>
            <div className="px-4 py-3 max-h-72 overflow-y-auto">
              {events.length === 0 ? (
                <p className="text-xs text-gray-400">Waiting for events…</p>
              ) : (
                events.map((ev, i) => <EventRow key={i} event={ev} />)
              )}
              <div ref={eventsEndRef} />
            </div>
          </div>

          {/* Draft / reply */}
          {ticket?.draft && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-4 py-3 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">Draft reply</h2>
              </div>
              <div className="px-4 py-4 text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
                {ticket.draft}
              </div>
            </div>
          )}

          {ticket?.final_reply && (
            <div className="bg-green-50 rounded-xl border border-green-200 shadow-sm">
              <div className="px-4 py-3 border-b border-green-100">
                <h2 className="text-sm font-semibold text-green-800">Sent reply</h2>
              </div>
              <div className="px-4 py-4 text-sm text-green-900 whitespace-pre-wrap leading-relaxed">
                {ticket.final_reply}
              </div>
            </div>
          )}

          {/* Approval action */}
          {isApprovalPending && (
            <div className="bg-orange-50 rounded-xl border border-orange-200 shadow-sm p-4">
              <p className="text-sm font-semibold text-orange-800 mb-3">
                Approval required for high-value action
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => handleApprove("approve")}
                  disabled={sending}
                  className="flex items-center gap-1.5 px-4 py-2 bg-green-600 text-white text-sm rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
                >
                  <CheckCircle size={14} /> Approve
                </button>
                <button
                  onClick={() => handleApprove("reject")}
                  disabled={sending}
                  className="flex items-center gap-1.5 px-4 py-2 bg-red-600 text-white text-sm rounded-lg hover:bg-red-700 transition-colors disabled:opacity-50"
                >
                  <XCircle size={14} /> Reject
                </button>
              </div>
            </div>
          )}

          {/* Customer reply */}
          {isReplyPending && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
              <p className="text-sm font-semibold text-gray-700 mb-2">
                Customer replied — send follow-up
              </p>
              <form onSubmit={handleReply}>
                <textarea
                  value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  rows={3}
                  placeholder="Customer's follow-up message…"
                  className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900 resize-none mb-2"
                />
                <button
                  type="submit"
                  disabled={sending}
                  className="px-4 py-1.5 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 transition-colors disabled:opacity-50"
                >
                  {sending ? "Sending…" : "Continue conversation"}
                </button>
              </form>
            </div>
          )}
        </div>

        {/* Evidence + findings sidebar */}
        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-700">Evidence</h2>
            </div>
            <div className="px-4 py-3 text-xs text-gray-500">
              {ticket?.evidence_count
                ? `${ticket.evidence_count} items retrieved`
                : "None yet"}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-sm font-semibold text-gray-700">Findings</h2>
            </div>
            <div className="px-4 py-3 text-xs text-gray-500">
              {ticket?.findings_count
                ? `${ticket.findings_count} findings from tools`
                : "None yet"}
            </div>
          </div>

          {ticket?.triage && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-4 py-3 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">Triage</h2>
              </div>
              <div className="px-4 py-3 space-y-1.5 text-xs text-gray-600">
                <p><span className="font-medium">Summary:</span> {ticket.triage.summary}</p>
                <p><span className="font-medium">Category:</span> {ticket.triage.category}</p>
                <p><span className="font-medium">Tier:</span> {ticket.triage.tier}</p>
              </div>
            </div>
          )}

          {ticket?.errors && ticket.errors.length > 0 && (
            <div className="bg-red-50 rounded-xl border border-red-200 shadow-sm">
              <div className="px-4 py-3 border-b border-red-100">
                <h2 className="text-sm font-semibold text-red-700">Errors</h2>
              </div>
              <div className="px-4 py-3 space-y-1 text-xs text-red-600">
                {ticket.errors.map((e, i) => <p key={i}>{e}</p>)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
