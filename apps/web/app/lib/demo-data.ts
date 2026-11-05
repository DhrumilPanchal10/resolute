import type { Ticket, TicketEvent } from "./api";

let nextId = 1;
function uid() {
  return `ticket-${String(nextId++).padStart(4, "0")}-${Date.now().toString(36)}`;
}

const DEMO_TICKETS: Ticket[] = [
  {
    ticket_id: "tkt-a1b2c3d4",
    tenant_id: "tenant-demo",
    status: "complete",
    triage: {
      category: "billing",
      severity: "high",
      tier: "strong",
      summary: "Customer charged twice for invoice #INV-2024-0042, requesting $49.99 refund",
      injection_risk: false,
      out_of_scope: false,
    },
    draft: null,
    final_reply:
      "I've confirmed the duplicate charge on invoice #INV-2024-0042. A refund of $49.99 has been issued to your original payment method. You should see it reflected within 3-5 business days. I've also flagged this to our billing team to prevent recurrence. Is there anything else I can help with?",
    findings_count: 4,
    evidence_count: 2,
    errors: [],
    interrupt_payload: null,
  },
  {
    ticket_id: "tkt-e5f6g7h8",
    tenant_id: "tenant-demo",
    status: "complete",
    triage: {
      category: "auth",
      severity: "critical",
      tier: "strong",
      summary: "SSO login broken after IdP certificate rotation — all users affected",
      injection_risk: false,
      out_of_scope: false,
    },
    draft: null,
    final_reply:
      "This is a known issue caused by the IdP certificate rotation at 14:30 UTC. Our team has updated the SAML certificate fingerprint in your tenant configuration. SSO logins should resume immediately — please try signing in again and let us know if the issue persists.",
    findings_count: 6,
    evidence_count: 3,
    errors: [],
    interrupt_payload: null,
  },
  {
    ticket_id: "tkt-i9j0k1l2",
    tenant_id: "tenant-demo",
    status: "interrupted",
    triage: {
      category: "billing",
      severity: "high",
      tier: "strong",
      summary: "Enterprise customer requesting $2,400 credit for 3 months of degraded SLA",
      injection_risk: false,
      out_of_scope: false,
    },
    draft:
      "After reviewing your account history, I can confirm there were 3 SLA breaches in the last quarter. Based on your Enterprise agreement, you are entitled to a credit of $2,400. I've prepared this credit for approval by our support lead.",
    final_reply: null,
    findings_count: 8,
    evidence_count: 5,
    errors: [],
    interrupt_payload: { type: "approval_required", action: "issue_credit", amount: 2400 },
  },
  {
    ticket_id: "tkt-m3n4o5p6",
    tenant_id: "tenant-demo",
    status: "running",
    triage: {
      category: "performance",
      severity: "medium",
      tier: "small",
      summary: "API response times increased 3x since last deployment",
      injection_risk: false,
      out_of_scope: false,
    },
    draft: null,
    final_reply: null,
    findings_count: 2,
    evidence_count: 1,
    errors: [],
    interrupt_payload: null,
  },
  {
    ticket_id: "tkt-q7r8s9t0",
    tenant_id: "tenant-demo",
    status: "complete",
    triage: {
      category: "config",
      severity: "low",
      tier: "small",
      summary: "Webhook endpoint returning 404 after URL migration",
      injection_risk: false,
      out_of_scope: false,
    },
    draft: null,
    final_reply:
      "I see the webhook URL was updated in your settings but the trailing slash was missing. I've corrected the endpoint to https://hooks.example.com/resolute/ and verified it's now returning 200. Your webhook events should resume flowing within the next minute.",
    findings_count: 3,
    evidence_count: 2,
    errors: [],
    interrupt_payload: null,
  },
  {
    ticket_id: "tkt-u1v2w3x4",
    tenant_id: "tenant-demo",
    status: "complete",
    triage: {
      category: "other",
      severity: "low",
      tier: "small",
      summary: "Request for API rate limit increase from 100 to 500 req/min",
      injection_risk: false,
      out_of_scope: false,
    },
    draft: null,
    final_reply:
      "I've reviewed your usage patterns and your current plan supports up to 500 req/min. I've updated your rate limit configuration — the change is effective immediately. You can verify this in your dashboard under Settings > API > Rate Limits.",
    findings_count: 2,
    evidence_count: 1,
    errors: [],
    interrupt_payload: null,
  },
];

const DEMO_EVENTS: Record<string, TicketEvent[]> = {
  "tkt-m3n4o5p6": [
    { type: "node_start", node: "triage" },
    { type: "node_end", node: "triage" },
    { type: "node_start", node: "knowledge" },
    { type: "node_start", node: "investigator" },
    { type: "node_end", node: "knowledge" },
  ],
};

let ticketStore = [...DEMO_TICKETS];

export const demoStore = {
  listTickets(): Ticket[] {
    return [...ticketStore];
  },

  getTicket(id: string): Ticket | undefined {
    return ticketStore.find((t) => t.ticket_id === id);
  },

  createTicket(text: string): Ticket {
    const id = uid();
    const ticket: Ticket = {
      ticket_id: id,
      tenant_id: "tenant-demo",
      status: "running",
      triage: null,
      draft: null,
      final_reply: null,
      findings_count: 0,
      evidence_count: 0,
      errors: [],
      interrupt_payload: null,
    };
    ticketStore = [ticket, ...ticketStore];

    setTimeout(() => {
      const t = ticketStore.find((x) => x.ticket_id === id);
      if (t) {
        t.triage = {
          category: "billing",
          severity: "medium",
          tier: "small",
          summary: text.slice(0, 100),
          injection_risk: false,
          out_of_scope: false,
        };
      }
    }, 1500);

    setTimeout(() => {
      const t = ticketStore.find((x) => x.ticket_id === id);
      if (t) {
        t.findings_count = 2;
        t.evidence_count = 1;
      }
    }, 3000);

    setTimeout(() => {
      const t = ticketStore.find((x) => x.ticket_id === id);
      if (t) {
        t.draft =
          "Thank you for reaching out. I've investigated your issue and here's what I found. Let me prepare a detailed response for you.";
      }
    }, 4500);

    setTimeout(() => {
      const t = ticketStore.find((x) => x.ticket_id === id);
      if (t) {
        t.status = "complete";
        t.final_reply =
          "Thank you for reaching out. After investigating your issue, I've identified the root cause and applied the necessary fix. The change is effective immediately. Please let us know if you need any further assistance.";
        t.findings_count = 3;
        t.evidence_count = 2;
      }
    }, 6000);

    return ticket;
  },

  approve(id: string, action: "approve" | "reject"): Ticket | undefined {
    const t = ticketStore.find((x) => x.ticket_id === id);
    if (!t) return undefined;
    if (action === "approve") {
      t.status = "complete";
      t.final_reply = t.draft ?? "Action approved and executed.";
      t.interrupt_payload = null;
    } else {
      t.status = "complete";
      t.final_reply = "Action rejected by lead. Ticket closed.";
      t.interrupt_payload = null;
    }
    return t;
  },

  getEvents(id: string): TicketEvent[] {
    return DEMO_EVENTS[id] ?? [];
  },

  simulateEvents(id: string): TicketEvent[] {
    const events: TicketEvent[] = [
      { type: "node_start", node: "triage" },
      { type: "node_end", node: "triage" },
      { type: "node_start", node: "knowledge" },
      { type: "node_start", node: "investigator" },
      { type: "node_end", node: "knowledge" },
      { type: "node_end", node: "investigator" },
      { type: "node_start", node: "resolver" },
      { type: "node_end", node: "resolver" },
      { type: "node_start", node: "verifier" },
      { type: "node_end", node: "verifier" },
      { type: "complete", node: "done" },
    ];
    DEMO_EVENTS[id] = events;
    return events;
  },
};
