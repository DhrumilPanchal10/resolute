"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { ArrowLeft, CheckCircle, XCircle, Loader2, MessageSquare, Clock } from "lucide-react";
import { demoStore } from "@/app/lib/demo-data";
import type { Ticket, TicketEvent } from "@/app/lib/api";
import { StatusBadge } from "@/app/components/StatusBadge";
import { SeverityBadge } from "@/app/components/SeverityBadge";

const NODE_LABELS: Record<string, string> = {
  triage: "Triage",
  knowledge: "Knowledge retrieval",
  investigator: "Account investigation",
  join: "Joining results",
  resolver: "Drafting reply",
  verifier: "Verifying draft",
  send_reply: "Sending reply",
  done: "Complete",
};

function EventRow({ event }: { event: TicketEvent }) {
  const isEnd = event.type === "node_end";
  const isStart = event.type === "node_start";
  const isComplete = event.type === "complete";

  return (
    <div className="flex items-center gap-3 py-2 text-sm">
      <div className="shrink-0">
        {isComplete ? (
          <CheckCircle size={15} className="text-emerald-500" />
        ) : isEnd ? (
          <CheckCircle size={15} className="text-gray-300" />
        ) : (
          <Loader2 size={15} className={`text-blue-400 ${isStart ? "animate-spin" : ""}`} />
        )}
      </div>
      <span className={`leading-tight ${isComplete ? "text-emerald-700 font-medium" : "text-gray-600"}`}>
        {isComplete
          ? "Resolution complete"
          : event.node
            ? `${NODE_LABELS[event.node] ?? event.node} ${isEnd ? "done" : "..."}`
            : event.type}
      </span>
    </div>
  );
}

export function TicketDetail({ id, onBack }: { id: string; onBack: () => void }) {
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [events, setEvents] = useState<TicketEvent[]>([]);
  const [sending, setSending] = useState(false);
  const eventsEndRef = useRef<HTMLDivElement>(null);

  const pollTicket = useCallback(() => {
    const t = demoStore.getTicket(id);
    if (t) setTicket({ ...t });
  }, [id]);

  useEffect(() => {
    pollTicket();
    const existing = demoStore.getEvents(id);
    if (existing.length > 0) {
      setEvents(existing);
    } else {
      const simulated = demoStore.simulateEvents(id);
      let i = 0;
      const interval = setInterval(() => {
        if (i < simulated.length) {
          setEvents((prev) => [...prev, simulated[i]]);
          i++;
        } else {
          clearInterval(interval);
        }
      }, 600);
      return () => clearInterval(interval);
    }
  }, [id, pollTicket]);

  useEffect(() => {
    const interval = setInterval(pollTicket, 1500);
    return () => clearInterval(interval);
  }, [pollTicket]);

  useEffect(() => {
    eventsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  function handleApprove(action: "approve" | "reject") {
    setSending(true);
    demoStore.approve(id, action);
    pollTicket();
    setSending(false);
  }

  const isApprovalPending =
    ticket?.status === "interrupted" &&
    ticket.interrupt_payload?.type === "approval_required";

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <button onClick={onBack} className="text-gray-400 hover:text-gray-600 transition-colors">
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-lg font-bold text-gray-900 font-mono">{id}</h1>
          {ticket && (
            <div className="flex items-center gap-2 mt-1">
              <StatusBadge status={ticket.status} />
              {ticket.triage?.severity && <SeverityBadge severity={ticket.triage.severity} />}
              {ticket.triage?.category && (
                <span className="text-xs text-gray-500 capitalize bg-gray-100 px-2 py-0.5 rounded">
                  {ticket.triage.category}
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-3 gap-6">
        <div className="col-span-2 space-y-5">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-5 py-3.5 border-b border-gray-100 flex items-center gap-2">
              <Clock size={14} className="text-gray-400" />
              <h2 className="text-sm font-semibold text-gray-700">Agent Activity</h2>
            </div>
            <div className="px-5 py-4 max-h-80 overflow-y-auto">
              {events.length === 0 ? (
                <p className="text-xs text-gray-400">Waiting for events...</p>
              ) : (
                events.map((ev, i) => <EventRow key={i} event={ev} />)
              )}
              <div ref={eventsEndRef} />
            </div>
          </div>

          {ticket?.draft && !ticket.final_reply && (
            <div className="bg-amber-50 rounded-xl border border-amber-200 shadow-sm">
              <div className="px-5 py-3.5 border-b border-amber-100">
                <h2 className="text-sm font-semibold text-amber-800">Draft Reply</h2>
              </div>
              <div className="px-5 py-4 text-sm text-amber-900 whitespace-pre-wrap leading-relaxed">
                {ticket.draft}
              </div>
            </div>
          )}

          {ticket?.final_reply && (
            <div className="bg-emerald-50 rounded-xl border border-emerald-200 shadow-sm">
              <div className="px-5 py-3.5 border-b border-emerald-100 flex items-center gap-2">
                <CheckCircle size={14} className="text-emerald-600" />
                <h2 className="text-sm font-semibold text-emerald-800">Sent Reply</h2>
              </div>
              <div className="px-5 py-4 text-sm text-emerald-900 whitespace-pre-wrap leading-relaxed">
                {ticket.final_reply}
              </div>
            </div>
          )}

          {isApprovalPending && (
            <div className="bg-orange-50 rounded-xl border border-orange-200 shadow-sm p-5">
              <div className="flex items-center gap-2 mb-3">
                <MessageSquare size={16} className="text-orange-600" />
                <p className="text-sm font-semibold text-orange-800">Approval Required</p>
              </div>
              <p className="text-xs text-orange-700 mb-4">
                This action requires lead or admin approval before execution.
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => handleApprove("approve")}
                  disabled={sending}
                  className="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 text-white text-sm rounded-lg hover:bg-emerald-700 transition-colors disabled:opacity-50"
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
        </div>

        <div className="space-y-4">
          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Evidence</h2>
            </div>
            <div className="px-4 py-3 text-sm text-gray-600">
              {ticket?.evidence_count
                ? <span className="font-medium">{ticket.evidence_count} items</span>
                : <span className="text-gray-400">None yet</span>}
            </div>
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
            <div className="px-4 py-3 border-b border-gray-100">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Findings</h2>
            </div>
            <div className="px-4 py-3 text-sm text-gray-600">
              {ticket?.findings_count
                ? <span className="font-medium">{ticket.findings_count} from tools</span>
                : <span className="text-gray-400">None yet</span>}
            </div>
          </div>

          {ticket?.triage && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-4 py-3 border-b border-gray-100">
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Triage</h2>
              </div>
              <div className="px-4 py-3 space-y-2 text-sm">
                <p className="text-gray-600">{ticket.triage.summary}</p>
                <div className="flex flex-wrap gap-1.5 mt-2">
                  <span className="text-[10px] bg-gray-100 text-gray-600 px-2 py-0.5 rounded font-medium">
                    tier: {ticket.triage.tier}
                  </span>
                  {ticket.triage.injection_risk && (
                    <span className="text-[10px] bg-red-100 text-red-700 px-2 py-0.5 rounded font-medium">
                      injection risk
                    </span>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
