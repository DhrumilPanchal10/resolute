"use client";

import { useState, useEffect, useCallback } from "react";
import { Ticket as TicketIcon, CheckCircle, Clock, AlertTriangle } from "lucide-react";
import { api, type Ticket } from "@/app/lib/api";
import { DEV_USER } from "@/app/lib/auth";

interface StatCardProps {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
}

function StatCard({ label, value, icon, color }: StatCardProps) {
  return (
    <div className={`bg-white rounded-xl border border-gray-200 shadow-sm p-5 flex items-center gap-4`}>
      <div className={`p-3 rounded-lg ${color}`}>{icon}</div>
      <div>
        <p className="text-xs text-gray-500 font-medium">{label}</p>
        <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
      </div>
    </div>
  );
}

export default function AdminPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [load]);

  const total = tickets.length;
  const complete = tickets.filter((t) => t.status === "complete").length;
  const running = tickets.filter((t) => t.status === "running").length;
  const needsApproval = tickets.filter(
    (t) =>
      t.status === "interrupted" &&
      t.interrupt_payload?.type === "approval_required"
  ).length;
  const failed = tickets.filter((t) => t.status === "failed").length;
  const resolutionRate = total > 0 ? Math.round((complete / total) * 100) : 0;

  const categoryBreakdown = tickets.reduce<Record<string, number>>((acc, t) => {
    const cat = t.triage?.category ?? "unknown";
    acc[cat] = (acc[cat] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Metrics</h1>
        <p className="text-sm text-gray-500">
          Overview for {DEV_USER.tenant_id} · refreshes every 10 s
        </p>
      </div>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          {error} — start the backend with <code className="font-mono">make up</code>.
        </div>
      )}

      {loading ? (
        <div className="text-sm text-gray-400">Loading…</div>
      ) : (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard
              label="Total tickets"
              value={total}
              icon={<TicketIcon size={18} className="text-blue-600" />}
              color="bg-blue-50"
            />
            <StatCard
              label="Resolved"
              value={`${complete} (${resolutionRate}%)`}
              icon={<CheckCircle size={18} className="text-green-600" />}
              color="bg-green-50"
            />
            <StatCard
              label="Pending approval"
              value={needsApproval}
              icon={<Clock size={18} className="text-orange-600" />}
              color="bg-orange-50"
            />
            <StatCard
              label="Failed"
              value={failed}
              icon={<AlertTriangle size={18} className="text-red-600" />}
              color="bg-red-50"
            />
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Category breakdown */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-4 py-3 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">By category</h2>
              </div>
              <div className="px-4 py-3 space-y-2">
                {Object.keys(categoryBreakdown).length === 0 ? (
                  <p className="text-xs text-gray-400">No data yet</p>
                ) : (
                  Object.entries(categoryBreakdown)
                    .sort(([, a], [, b]) => b - a)
                    .map(([cat, count]) => (
                      <div key={cat} className="flex items-center gap-3">
                        <span className="text-xs text-gray-600 w-24 capitalize truncate">
                          {cat}
                        </span>
                        <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                          <div
                            className="bg-blue-500 h-2 rounded-full transition-all"
                            style={{ width: `${(count / total) * 100}%` }}
                          />
                        </div>
                        <span className="text-xs text-gray-500 w-6 text-right">{count}</span>
                      </div>
                    ))
                )}
              </div>
            </div>

            {/* Status breakdown */}
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-4 py-3 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">By status</h2>
              </div>
              <div className="px-4 py-4 space-y-2 text-sm">
                {(
                  [
                    { label: "Complete",    count: complete,      color: "text-green-600" },
                    { label: "Running",     count: running,       color: "text-yellow-600" },
                    { label: "Interrupted", count: tickets.filter((t) => t.status === "interrupted").length, color: "text-orange-600" },
                    { label: "Failed",      count: failed,        color: "text-red-600" },
                  ] as const
                ).map(({ label, count, color }) => (
                  <div key={label} className="flex justify-between">
                    <span className="text-gray-600">{label}</span>
                    <span className={`font-semibold ${color}`}>{count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
