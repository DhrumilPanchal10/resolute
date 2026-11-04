/**
 * Typed API client for the Resolute FastAPI backend.
 * Base URL is read from NEXT_PUBLIC_API_URL (default: http://localhost:8000).
 */

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---- Types ----------------------------------------------------------------

export type TicketStatus =
  | "pending"
  | "running"
  | "interrupted"
  | "complete"
  | "failed";

export interface Ticket {
  ticket_id: string;
  tenant_id: string;
  status: TicketStatus;
  triage?: {
    category: string;
    severity: string;
    tier: string;
    summary: string;
    injection_risk: boolean;
    out_of_scope: boolean;
  } | null;
  draft?: string | null;
  final_reply?: string | null;
  findings_count: number;
  evidence_count: number;
  errors: string[];
  interrupt_payload?: Record<string, unknown> | null;
}

export interface TicketEvent {
  type: string;
  node?: string;
  ticket_id?: string;
  data?: Record<string, unknown>;
  final_reply?: string;
  message?: string;
  pending_actions?: Action[];
  draft?: string;
}

export interface Action {
  action_type: string;
  args: Record<string, unknown>;
  requires_approval: boolean;
  approval_reason: string;
}

// ---- Requests -------------------------------------------------------------

async function req<T>(
  path: string,
  opts?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

// ---- Endpoints ------------------------------------------------------------

export const api = {
  listTickets: (tenant_id: string) =>
    req<Ticket[]>(`/tickets?tenant_id=${encodeURIComponent(tenant_id)}`),

  createTicket: (body: {
    tenant_id: string;
    user_id: string;
    ticket_text: string;
    token?: string;
  }) =>
    req<Ticket>("/tickets", {
      method: "POST",
      body: JSON.stringify(body),
    }),

  getTicket: (id: string) => req<Ticket>(`/tickets/${id}`),

  reply: (id: string, text: string) =>
    req<Ticket>(`/tickets/${id}/reply`, {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  approve: (id: string, action: "approve" | "reject", edited_draft = "") =>
    req<Ticket>(`/approvals/${id}`, {
      method: "POST",
      body: JSON.stringify({ action, edited_draft }),
    }),

  streamUrl: (id: string) => `${BASE}/tickets/${id}/stream`,
};
