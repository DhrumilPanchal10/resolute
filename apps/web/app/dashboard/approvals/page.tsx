"use client";

import { useState, useEffect, useCallback } from "react";
import { CheckCircle, XCircle } from "lucide-react";
import { demoStore } from "@/app/lib/demo-data";
import type { Ticket } from "@/app/lib/api";
import { StatusBadge } from "@/app/components/StatusBadge";
import { SeverityBadge } from "@/app/components/SeverityBadge";

export default function ApprovalsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);

  const load = useCallback(() => {
    const sevRank: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3 };
    const pending = demoStore
      .listTickets()
      .filter(
        (t) =>
          t.status === "interrupted" &&
          t.interrupt_payload?.type === "approval_required"
      )
      .sort(
        (a, b) =>
          (sevRank[a.triage?.severity ?? "low"] ?? 3) -
          (sevRank[b.triage?.severity ?? "low"] ?? 3)
      );
    setTickets(pending);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 2000);
    return () => clearInterval(id);
  }, [load]);

  function decide(ticketId: string, action: "approve" | "reject") {
    setActing(ticketId);
    demoStore.approve(ticketId, action);
    load();
    setActing(null);
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Approval Queue</h1>
        <p className="text-sm text-gray-500">
          Actions requiring lead or admin approval &middot; sorted by severity
        </p>
      </div>

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-sm text-gray-400">Loading...</div>
        ) : tickets.length === 0 ? (
          <div className="p-12 text-center">
            <CheckCircle size={32} className="text-emerald-300 mx-auto mb-3" />
            <p className="text-sm text-gray-500">No pending approvals</p>
            <p className="text-xs text-gray-400 mt-1">Queue is clear</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 bg-gray-50/80">
              <tr>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Ticket</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Summary</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Severity</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Status</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tickets.map((t) => (
                <tr key={t.ticket_id} className="hover:bg-blue-50/30 transition-colors">
                  <td className="px-5 py-3.5">
                    <span className="font-mono text-xs text-gray-600">{t.ticket_id.slice(0, 12)}</span>
                  </td>
                  <td className="px-5 py-3.5 text-gray-700 max-w-xs truncate">{t.triage?.summary ?? "—"}</td>
                  <td className="px-5 py-3.5">
                    {t.triage?.severity ? <SeverityBadge severity={t.triage.severity} /> : "—"}
                  </td>
                  <td className="px-5 py-3.5"><StatusBadge status={t.status} /></td>
                  <td className="px-5 py-3.5">
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => decide(t.ticket_id, "approve")}
                        disabled={acting === t.ticket_id}
                        className="flex items-center gap-1 px-3 py-1.5 bg-emerald-600 text-white text-xs rounded-md hover:bg-emerald-700 transition-colors disabled:opacity-50"
                      >
                        <CheckCircle size={12} /> Approve
                      </button>
                      <button
                        onClick={() => decide(t.ticket_id, "reject")}
                        disabled={acting === t.ticket_id}
                        className="flex items-center gap-1 px-3 py-1.5 bg-red-600 text-white text-xs rounded-md hover:bg-red-700 transition-colors disabled:opacity-50"
                      >
                        <XCircle size={12} /> Reject
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
