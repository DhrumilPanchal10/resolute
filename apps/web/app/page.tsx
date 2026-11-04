"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { Plus, RefreshCw } from "lucide-react";
import { api, type Ticket } from "@/app/lib/api";
import { StatusBadge } from "@/app/components/StatusBadge";
import { SeverityBadge } from "@/app/components/SeverityBadge";
import { DEV_USER } from "@/app/lib/auth";

export default function InboxPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const load = useCallback(async () => {
    try {
      const data = await api.listTickets(DEV_USER.tenant_id);
      setTickets(data);
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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    try {
      await api.createTicket({
        tenant_id: DEV_USER.tenant_id,
        user_id: DEV_USER.id,
        ticket_text: text,
      });
      setText("");
      setShowForm(false);
      await load();
    } catch (e) {
      alert(String(e));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Inbox</h1>
          <p className="text-sm text-gray-500">All support tickets · {DEV_USER.tenant_id}</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="p-2 rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={16} className="text-gray-500" />
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 bg-gray-900 text-white px-3 py-2 rounded-lg text-sm font-medium hover:bg-gray-700 transition-colors"
          >
            <Plus size={16} /> New Ticket
          </button>
        </div>
      </div>

      {/* New ticket form */}
      {showForm && (
        <div className="mb-6 bg-white rounded-xl border border-gray-200 p-4 shadow-sm">
          <form onSubmit={submit}>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Ticket description
            </label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder="Describe the customer's issue…"
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-gray-900 resize-none"
            />
            <div className="flex justify-end gap-2 mt-3">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-1.5 bg-gray-900 text-white text-sm rounded-lg hover:bg-gray-700 transition-colors disabled:opacity-50"
              >
                {submitting ? "Submitting…" : "Submit"}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          API unavailable — {error}. Start the backend with <code className="font-mono">make up</code>.
        </div>
      )}

      {/* Table */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-sm text-gray-400">Loading…</div>
        ) : tickets.length === 0 ? (
          <div className="p-8 text-center text-sm text-gray-400">
            No tickets yet — create one above.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left font-medium text-gray-500">ID</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Summary</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Category</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Severity</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tickets.map((t) => (
                <tr key={t.ticket_id} className="hover:bg-gray-50 transition-colors">
                  <td className="px-4 py-3">
                    <Link
                      href={`/tickets/${t.ticket_id}`}
                      className="font-mono text-xs text-blue-600 hover:underline"
                    >
                      {t.ticket_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-gray-700 max-w-xs truncate">
                    {t.triage?.summary ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-gray-600 capitalize">
                    {t.triage?.category ?? "—"}
                  </td>
                  <td className="px-4 py-3">
                    {t.triage?.severity ? (
                      <SeverityBadge severity={t.triage.severity} />
                    ) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={t.status} />
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
