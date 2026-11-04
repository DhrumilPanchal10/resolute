import type { TicketStatus } from "@/app/lib/api";

const styles: Record<TicketStatus, string> = {
  pending:     "bg-gray-100 text-gray-700",
  running:     "bg-yellow-100 text-yellow-800 animate-pulse",
  interrupted: "bg-orange-100 text-orange-800",
  complete:    "bg-green-100 text-green-800",
  failed:      "bg-red-100 text-red-800",
};

export function StatusBadge({ status }: { status: TicketStatus }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[status]}`}>
      {status}
    </span>
  );
}
