const styles: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  high:     "bg-orange-100 text-orange-800",
  medium:   "bg-yellow-100 text-yellow-800",
  low:      "bg-blue-100 text-blue-800",
};

export function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${styles[severity] ?? "bg-gray-100 text-gray-700"}`}>
      {severity}
    </span>
  );
}
