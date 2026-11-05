"use client";

import { useState, useEffect, useCallback } from "react";
import { Plus, RefreshCw } from "lucide-react";
import { demoStore } from "@/app/lib/demo-data";
import type { Ticket } from "@/app/lib/api";
import { StatusBadge } from "@/app/components/StatusBadge";
import { SeverityBadge } from "@/app/components/SeverityBadge";
import { TicketDetail } from "@/app/components/TicketDetail";

export default function InboxPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [selectedTicket, setSelectedTicket] = useState<string | null>(null);

  const load = useCallback(() => {
    setTickets(demoStore.listTickets());
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 2000);
    return () => clearInterval(id);
  }, [load]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!text.trim()) return;
    setSubmitting(true);
    demoStore.createTicket(text);
    setText("");
    setShowForm(false);
    setSubmitting(false);
    load();
  }

  if (selectedTicket) {
    return <TicketDetail id={selectedTicket} onBack={() => setSelectedTicket(null)} />;
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Inbox</h1>
          <p className="text-sm text-gray-500">
            All support tickets &middot; <span className="font-mono text-xs">tenant-demo</span>
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={load}
            className="p-2.5 rounded-lg border border-gray-200 hover:bg-gray-100 transition-colors"
            title="Refresh"
          >
            <RefreshCw size={15} className="text-gray-500" />
          </button>
          <button
            onClick={() => setShowForm(true)}
            className="flex items-center gap-1.5 bg-gray-900 text-white px-4 py-2.5 rounded-lg text-sm font-medium hover:bg-gray-700 transition-colors"
          >
            <Plus size={15} /> New Ticket
          </button>
        </div>
      </div>

      {showForm && (
        <div className="mb-6 bg-white rounded-xl border border-gray-200 p-5 shadow-sm">
          <form onSubmit={submit}>
            <label className="block text-sm font-medium text-gray-700 mb-2">
              Describe the customer issue
            </label>
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              rows={4}
              placeholder="e.g. I was charged twice for my last invoice and need a refund..."
              className="w-full border border-gray-200 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
            />
            <div className="flex justify-end gap-2 mt-3">
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-4 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !text.trim()}
                className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-40"
              >
                Submit Ticket
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-sm text-gray-400">Loading...</div>
        ) : tickets.length === 0 ? (
          <div className="p-12 text-center text-sm text-gray-400">
            No tickets yet. Create one above.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-100 bg-gray-50/80">
              <tr>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">ID</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Summary</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Category</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Severity</th>
                <th className="px-5 py-3 text-left font-medium text-gray-500 text-xs uppercase tracking-wider">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {tickets.map((t) => (
                <tr key={t.ticket_id} className="hover:bg-blue-50/30 transition-colors cursor-pointer group">
                  <td className="px-5 py-3.5">
                    <button
                      onClick={() => setSelectedTicket(t.ticket_id)}
                      className="font-mono text-xs text-blue-600 group-hover:text-blue-800 hover:underline"
                    >
                      {t.ticket_id.slice(0, 12)}
                    </button>
                  </td>
                  <td className="px-5 py-3.5 text-gray-700 max-w-sm truncate">
                    {t.triage?.summary ?? <span className="text-gray-300 italic">Processing...</span>}
                  </td>
                  <td className="px-5 py-3.5 text-gray-600 capitalize">
                    {t.triage?.category ?? "—"}
                  </td>
                  <td className="px-5 py-3.5">
                    {t.triage?.severity ? <SeverityBadge severity={t.triage.severity} /> : "—"}
                  </td>
                  <td className="px-5 py-3.5">
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
