/**
 * k6 load test for the Resolute ticket API.
 *
 * Runs against the FastAPI server (OFFLINE=1 for canned responses).
 * Measures: p95 response time, throughput, error rate.
 *
 * Usage:
 *   # Start server first:
 *   OFFLINE=1 uvicorn resolute.api.main:app --host 0.0.0.0 --port 8000
 *
 *   # Run load test:
 *   k6 run tests/load/k6_tickets.js
 *
 *   # With custom options:
 *   k6 run --vus 10 --duration 30s tests/load/k6_tickets.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// Custom metrics
const ticketCreated = new Counter('tickets_created');
const ticketErrors = new Rate('ticket_error_rate');
const firstResponseTime = new Trend('first_response_ms', true);

// Default options — gentle load for offline mode
export const options = {
  scenarios: {
    smoke: {
      executor: 'constant-vus',
      vus: 2,
      duration: '10s',
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<5000'],  // p95 under 5s (offline is fast)
    ticket_error_rate: ['rate<0.1'],     // less than 10% errors
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

const TICKETS = [
  'I was charged twice for my Pro plan. Invoice INV-2024-001 shows $199 but I see two charges.',
  "Can't log in since the last deploy. Getting 401 every time. Blocking our team.",
  'How do I upgrade from Starter to Pro? What features do I get?',
  'Our integration hits the 100 req/min rate limit regularly. Need 500 req/min.',
  'The CSV export button in the dashboard returns a 500 error since yesterday.',
  'SSO with Okta stopped working this morning. Users cannot authenticate.',
  'Webhook delivery is 10-15 minutes delayed. Expected under 30 seconds.',
  'Password reset email not arriving. Already checked spam folder.',
  'CORS errors when loading embedded widget on customer sites.',
  'Feature flag new-dashboard enabled but old dashboard still showing.',
];

export default function () {
  const ticketText = TICKETS[Math.floor(Math.random() * TICKETS.length)];
  const tenantId = `tenant-load-${__VU}`;

  // POST /tickets — create a new ticket
  const createRes = http.post(
    `${BASE_URL}/tickets`,
    JSON.stringify({
      tenant_id: tenantId,
      user_id: `user-load-${__VU}`,
      ticket_text: ticketText,
    }),
    {
      headers: { 'Content-Type': 'application/json' },
      tags: { name: 'POST /tickets' },
    }
  );

  const created = check(createRes, {
    'create status 200': (r) => r.status === 200,
    'has ticket_id': (r) => {
      try {
        return JSON.parse(r.body).ticket_id !== undefined;
      } catch {
        return false;
      }
    },
  });

  if (created) {
    ticketCreated.add(1);
    ticketErrors.add(0);

    const body = JSON.parse(createRes.body);
    const ticketId = body.ticket_id;

    // Record first response time
    firstResponseTime.add(createRes.timings.duration);

    // GET /tickets/{id} — poll for result
    sleep(0.5);
    const getRes = http.get(`${BASE_URL}/tickets/${ticketId}`, {
      tags: { name: 'GET /tickets/{id}' },
    });

    check(getRes, {
      'get status 200': (r) => r.status === 200,
    });

    // GET /tickets — list
    const listRes = http.get(`${BASE_URL}/tickets?tenant_id=${tenantId}`, {
      tags: { name: 'GET /tickets' },
    });

    check(listRes, {
      'list status 200': (r) => r.status === 200,
    });
  } else {
    ticketErrors.add(1);
  }

  sleep(0.5);
}

export function handleSummary(data) {
  const p95 = data.metrics.http_req_duration
    ? data.metrics.http_req_duration.values['p(95)']
    : 0;
  const created = data.metrics.tickets_created
    ? data.metrics.tickets_created.values.count
    : 0;
  const errorRate = data.metrics.ticket_error_rate
    ? data.metrics.ticket_error_rate.values.rate
    : 0;

  console.log('\n=== Load Test Summary ===');
  console.log(`Tickets created: ${created}`);
  console.log(`p95 response time: ${p95.toFixed(0)} ms`);
  console.log(`Error rate: ${(errorRate * 100).toFixed(1)}%`);

  return {
    stdout: JSON.stringify(
      {
        tickets_created: created,
        p95_ms: p95,
        error_rate: errorRate,
      },
      null,
      2
    ),
  };
}
