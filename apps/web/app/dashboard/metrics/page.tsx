"use client";

import { useState, useEffect, useCallback } from "react";
import { Ticket as TicketIcon, CheckCircle, Clock, AlertTriangle, TrendingUp } from "lucide-react";
import { demoStore } from "@/app/lib/demo-data";
import type { Ticket } from "@/app/lib/api";

function StatCard({
  label,
  value,
  icon,
  color,
  bgColor,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  color: string;
  bgColor: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <div className="flex items-center justify-between mb-3">
        <div className={`p-2.5 rounded-lg ${bgColor}`}>{icon}</div>
        <TrendingUp size={14} className="text-gray-300" />
      </div>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      <p className="text-xs text-gray-500 mt-1">{label}</p>
    </div>
  );
}

function BarRow({ label, count, total, color }: { label: string; count: number; total: number; color: string }) {
  const pct = total > 0 ? (count / total) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-gray-600 w-24 capitalize truncate">{label}</span>
      <div className="flex-1 bg-gray-100 rounded-full h-2.5 overflow-hidden">
        <div className={`h-2.5 rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-500 w-8 text-right font-medium">{count}</span>
    </div>
  );
}

export default function MetricsPage() {
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setTickets(demoStore.listTickets());
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 5000);
    return () => clearInterval(id);
  }, [load]);

  const total = tickets.length;
  const complete = tickets.filter((t) => t.status === "complete").length;
  const running = tickets.filter((t) => t.status === "running").length;
  const interrupted = tickets.filter((t) => t.status === "interrupted").length;
  const failed = tickets.filter((t) => t.status === "failed").length;
  const rate = total > 0 ? Math.round((complete / total) * 100) : 0;

  const cats = tickets.reduce<Record<string, number>>((acc, t) => {
    const cat = t.triage?.category ?? "unknown";
    acc[cat] = (acc[cat] ?? 0) + 1;
    return acc;
  }, {});

  const sevs = tickets.reduce<Record<string, number>>((acc, t) => {
    const sev = t.triage?.severity ?? "unknown";
    acc[sev] = (acc[sev] ?? 0) + 1;
    return acc;
  }, {});

  const sevColors: Record<string, string> = {
    critical: "bg-red-500",
    high: "bg-orange-500",
    medium: "bg-amber-500",
    low: "bg-blue-500",
    unknown: "bg-gray-400",
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Metrics</h1>
        <p className="text-sm text-gray-500">
          Overview for <span className="font-mono text-xs">tenant-demo</span>
        </p>
      </div>

      {loading ? (
        <div className="text-sm text-gray-400">Loading...</div>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
            <StatCard
              label="Total tickets"
              value={total}
              icon={<TicketIcon size={18} className="text-blue-600" />}
              color="text-blue-600"
              bgColor="bg-blue-50"
            />
            <StatCard
              label="Resolution rate"
              value={`${rate}%`}
              icon={<CheckCircle size={18} className="text-emerald-600" />}
              color="text-emerald-600"
              bgColor="bg-emerald-50"
            />
            <StatCard
              label="Pending approval"
              value={interrupted}
              icon={<Clock size={18} className="text-orange-600" />}
              color="text-orange-600"
              bgColor="bg-orange-50"
            />
            <StatCard
              label="Failed"
              value={failed}
              icon={<AlertTriangle size={18} className="text-red-600" />}
              color="text-red-600"
              bgColor="bg-red-50"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-5 py-3.5 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">By Category</h2>
              </div>
              <div className="px-5 py-4 space-y-3">
                {Object.entries(cats)
                  .sort(([, a], [, b]) => b - a)
                  .map(([cat, count]) => (
                    <BarRow key={cat} label={cat} count={count} total={total} color="bg-blue-500" />
                  ))}
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-5 py-3.5 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">By Severity</h2>
              </div>
              <div className="px-5 py-4 space-y-3">
                {["critical", "high", "medium", "low"].map((sev) => (
                  <BarRow
                    key={sev}
                    label={sev}
                    count={sevs[sev] ?? 0}
                    total={total}
                    color={sevColors[sev] ?? "bg-gray-400"}
                  />
                ))}
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-5 py-3.5 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">By Status</h2>
              </div>
              <div className="px-5 py-4 space-y-3">
                {[
                  { label: "Complete", count: complete, color: "text-emerald-600" },
                  { label: "Running", count: running, color: "text-blue-600" },
                  { label: "Interrupted", count: interrupted, color: "text-orange-600" },
                  { label: "Failed", count: failed, color: "text-red-600" },
                ].map(({ label, count, color }) => (
                  <div key={label} className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">{label}</span>
                    <span className={`text-lg font-bold ${color}`}>{count}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
              <div className="px-5 py-3.5 border-b border-gray-100">
                <h2 className="text-sm font-semibold text-gray-700">System Health</h2>
              </div>
              <div className="px-5 py-4 space-y-3">
                {[
                  { label: "Triage rate", value: "100%", status: "healthy" },
                  { label: "Reply rate", value: "100%", status: "healthy" },
                  { label: "ASR (attack success)", value: "0.0%", status: "healthy" },
                  { label: "Judge agreement", value: "86%", status: "healthy" },
                ].map(({ label, value, status }) => (
                  <div key={label} className="flex justify-between items-center">
                    <span className="text-sm text-gray-600">{label}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-900">{value}</span>
                      <div className={`w-2 h-2 rounded-full ${status === "healthy" ? "bg-emerald-500" : "bg-red-500"}`} />
                    </div>
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
