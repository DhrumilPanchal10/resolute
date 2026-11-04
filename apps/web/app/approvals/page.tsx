"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { CheckCircle, XCircle, ExternalLink } from "lucide-react";
import { api, type Ticket } from "@/app/lib/api";
import { StatusBadge } from "@/app/components/StatusBadge";
import { SeverityBadge } from "@/app/components/SeverityBadge";
import { DEV_USER } from "@/app/lib/auth";

export default function ApprovalsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const all = await api.listTickets(DEV_USER.tenant_id);
      // Show only tickets interrupted for approval, ordered by severity
      const sevRank: Record<string, number> = {
        critical: 0, high: 1, medium: 2, low: 3,
      };
      const pending = all
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
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  async function decide(ticketId: string, action: "approve" | "reject") {
    setActing(ticketId);
    try {
      await api.approve(ticketId, action);
      await load();
    } catch (e) {
      alert(String(e));
    } finally {
      setActing(null);
    }
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Approval Queue</h1>
        <p className="text-sm text-gray-500">
          Actions requiring lead or admin approval · sorted by severity
        </p>
      </div>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-gray-400">Loading…</div>
        ) : tickets.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-400">
            No pending approvals — queue is clear.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Ticket</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Summary</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Severity</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tickets.map((t) => (
                <tr key={t.ticket_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-xs text-gray-600">
                        {t.ticket_id.slice(0, 8)}…
                      </span>
                      <Link href={`/tickets/${t.ticket_id}`}>
                        <ExternalLink size={12} className="text-gray-400 hover:text-blue-500" />
                      </Link>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-700 max-w-xs truncate">
                    {t.triage?.summary ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    {t.triage?.severity ? (
                      <SeverityBadge severity={t.triage.severity} />
                    ) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={t.status} />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1.5">
                      <button
                        onClick={() => decide(t.ticket_id, "approve")}
                        disabled={acting === t.ticket_id}
                        className="flex items-center gap-1 px-2.5 py-1 bg-green-600 text-white text-xs rounded-md hover:bg-green-700 transition-colors disabled:opacity-50"
                      >
                        <CheckCircle size={12} /> Approve
                      </button>
                      <button
                        onClick={() => decide(t.ticket_id, "reject")}
                        disabled={acting === t.ticket_id}
                        className="flex items-center gap-1 px-2.5 py-1 bg-red-600 text-white text-xs rounded-md hover:bg-red-700 transition-colors disabled:opacity-50"
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
