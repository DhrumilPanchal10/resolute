# Resolute

**Multi-agent customer support resolution platform** — five specialized AI agents collaborate to triage, investigate, and resolve support tickets with full audit trails, human-in-the-loop approval, and tenant isolation.

<!-- Demo GIF placeholder: record with `make demo` and add here -->
<!-- ![Demo](docs/demo.gif) -->

---

## Problem

Single-agent support bots answer from a flat prompt and a keyword search. They hallucinate details, miss billing context, skip security checks, and can't take actions (credits, refunds) safely. The result: generic replies, no accountability, and zero visibility for support leads.

**Resolute** replaces the single agent with a *graph of specialists* — triage, knowledge retrieval, account investigation, draft resolution, and verification — orchestrated by a supervisor that enforces budget, routing, and escalation policies. Every hop is traced, every tool call is audited, and financial actions require human approval.

---

## Results

Evaluation run: **2026-11-04** (offline, canned LLM responses, n = 5–10 per suite).

| Suite | Metric | Value | Threshold | Status |
|-------|--------|-------|-----------|--------|
| Multi-agent | Triage rate | 100% | ≥ 80% | PASS |
| Multi-agent | Reply rate | 100% | ≥ 60% | PASS |
| Scenarios (100 YAML) | pass@1 | 30% | ≥ 20% | PASS |
| Scenarios | pass@k | 30% | ≥ 20% | PASS |
| Adversarial (150 injected) | ASR | 0.0% | ≤ 5% | PASS |
| Adversarial | Benign success | 100% | ≥ 70% | PASS |
| Judge calibration (50 gold) | Agreement | 86% | ≥ 85% | PASS |
| Judge calibration | Cohen's κ | 0.787 | — | Substantial |

Live end-to-end confirmed with Gemini 3.1 Flash Lite (free tier).

---

## Architecture

```
Next.js UI ──SSE──▶ FastAPI (JWT/RBAC) ──▶ LangGraph
                                            ├─ triage          (small model)
                                            ├─ knowledge ──┐   (parallel fan-out)
                                            ├─ investigator┘   (strong model)
                                            ├─ resolver        (strong model)
                                            ├─ verifier ──(revise ≤2)──▶ resolver
                                            └─ supervisor (budget, routing, escalation)
                                                   │
                    MCP servers (auth + audit per call):
                    github · docs · accounts · logs · stripe(test)
                                                   │
                    Postgres (RLS, audit, memory, checkpoints)
                    pgvector · Redis cache · Semantic cache
                                                   │
                    OpenTelemetry GenAI spans ──▶ Langfuse / Phoenix
```

**Data flow:** ticket → triage classifies & screens for injection → knowledge retrieves docs (BM25 + dense + rerank) while investigator queries accounts/logs/GitHub → resolver drafts reply + action plan → verifier checks claims against evidence → supervisor routes approval if needed → final reply + executed actions.

---

## Production Spine

| Concern | File | Notes |
|---------|------|-------|
| LLM gateway | [`src/agentcore/llm.py`](src/agentcore/llm.py) | LiteLLM, route fallback, budget ceiling, offline replay |
| Guardrails | [`src/agentcore/guardrails.py`](src/agentcore/guardrails.py) | Injection screen, PII mask, budget/loop/wall-clock limits |
| Auth (JWT/RBAC) | [`src/agentcore/auth.py`](src/agentcore/auth.py) | Clerk JWKS, 4 roles, 12-permission matrix |
| Audit log | [`src/agentcore/audit.py`](src/agentcore/audit.py) | SHA-256 hash chain, tamper detection |
| Telemetry | [`src/agentcore/telemetry.py`](src/agentcore/telemetry.py) | OTel + GenAI semantic conventions |
| Tool security | [`src/resolute/mcp_servers/base.py`](src/resolute/mcp_servers/base.py) | Circuit breaker, risk tiers, per-call audit |
| Tenant isolation | [`src/resolute/db.py`](src/resolute/db.py) | Postgres RLS, `SET app.tenant_id` per transaction |
| Memory | [`src/agentcore/memory.py`](src/agentcore/memory.py) | Short-term (compaction), long-term (verified only), episodic (embedding + TTL) |
| Retrieval | [`src/resolute/retrieval/`](src/resolute/retrieval/) | Chunking → BM25 + dense → RRF → cross-encoder rerank |
| Semantic cache | [`src/resolute/retrieval/semantic_cache.py`](src/resolute/retrieval/semantic_cache.py) | Cosine similarity, tenant/scope/version isolation |
| HITL | [`src/resolute/hitl/`](src/resolute/hitl/) | Approval queue (severity-sorted), policies, human override persistence |
| Graph | [`src/resolute/graph/build.py`](src/resolute/graph/build.py) | LangGraph StateGraph, Send-based parallel fan-out, MemorySaver checkpoints |
| API | [`src/resolute/api/`](src/resolute/api/) | FastAPI, SSE streaming, ticket lifecycle |

---

## Evaluation Method

**Time-travel retrieval:** Docs index filters by `created_at ≤ as_of` so agents can only see documents that existed when the issue was filed — preventing information leakage in retrospective evals.

**Judge calibration:** 50 gold-labeled answers (20 correct / 15 partial / 15 wrong) scored by human and LLM judge. 86% agreement, Cohen's κ = 0.787 (substantial). See [`docs/results/judge_calibration.md`](docs/results/judge_calibration.md).

**Adversarial suite:** 150 injected tickets across 5 attack categories (ignore-instructions, encoding/obfuscation, social engineering, data exfiltration, indirect injection) + 100 benign. ASR = 0.0%.

**Scenario coverage:** 100 YAML scenarios (30 billing, 20 auth, 20 perf, 20 config, 10 other) with expected triage, reply, and action criteria.

---

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Prompt injection | Guardrails pre-screen (pattern + heuristic); triage flags `injection_risk`; escalation on detection |
| Data exfiltration | Tenant RLS; MCP tools enforce `tenant_id` on every query; cross-tenant access blocked |
| Unauthorized actions | RBAC (4 roles × 12 permissions); financial tools require lead/admin + HITL approval |
| Budget abuse | Per-run USD ceiling; pre-check before every LLM call; `BudgetExceeded` halts run |
| Replay / tampering | SHA-256 hash-chain audit log; idempotency keys on Stripe (SHA-256 of ticket+action+args) |
| Stale knowledge | Time-travel index; semantic cache keyed by `docs_version`; TTL expiry |
| Circuit cascade | Per-tool circuit breaker (CLOSED → OPEN → HALF_OPEN); degraded state on node crash |

---

## Quickstart

```bash
# Prerequisites: Python 3.12+, uv, Docker, Node.js 18+

# 1. Install
make install

# 2. Start Postgres + Redis
make up

# 3. Copy and fill environment
cp .env.example .env
# Edit .env: add GEMINI_API_KEY (free from ai.google.dev)

# 4. Run demo (offline — no API keys needed)
make demo

# 5. Run tests
make test          # 421 tests, OFFLINE=1
make eval-smoke    # quick eval gate
make eval-report   # full eval with CI gate
```

### Live mode

Set `OFFLINE=0` in `.env` and provide a `GEMINI_API_KEY`. The system uses `gemini-3.1-flash-lite` (small/judge tier) and `gemini-3.8-flash` (strong tier) via LiteLLM with automatic route fallback.

### Docker

```bash
docker compose up --build
# API at http://localhost:8000
# Swagger docs at http://localhost:8000/docs
```

### Web UI

```bash
cd apps/web && npm install && npm run dev
# http://localhost:3000
```

---

## Design Decisions & Trade-offs

| Decision | Why | Trade-off |
|----------|-----|-----------|
| LangGraph over raw chains | Need parallel fan-out (knowledge ∥ investigator), revision loops, and checkpointed state for HITL interrupts | Heavier dependency; learning curve |
| MCP servers for every tool | Uniform auth + audit + circuit breaking per call; tools are swappable without changing agent code | Extra abstraction layer; slightly more boilerplate |
| LiteLLM routing | Provider-agnostic model names; built-in retry + fallback across routes | Adds a dependency; model name mapping can lag new releases |
| Offline fixture replay | CI runs with zero API keys; deterministic tests; no flaky rate-limit failures | Fixtures can drift from live behavior; must re-record periodically |
| Postgres RLS for multi-tenancy | Row-level security enforced at DB level — bugs in app code can't leak tenant data | Requires `SET app.tenant_id` per transaction; harder to debug |
| Pydantic structured output only | No parsing free text; schema validation catches malformed LLM responses | Constrains model output format; some models struggle with complex schemas |
| Local embeddings (bge-small) | Zero cost; no API dependency; fast enough for support corpus sizes | 8 GB RAM limit means no large models; quality ceiling vs. API embeddings |

---

## Roadmap

- [ ] PostgreSQL-backed retrieval (pgvector) replacing in-memory BM25
- [ ] Streaming token output to SSE for real-time reply preview
- [ ] Multi-turn conversation memory within a ticket thread
- [ ] Webhook integration (Slack, email) for ticket ingestion
- [ ] A/B testing framework for agent configurations
- [ ] Fine-tuned judge model on production override data

---

## Project Structure

```
resolute/
├── src/agentcore/       # LLM gateway, guardrails, auth, audit, memory, telemetry
├── src/resolute/
│   ├── retrieval/       # Chunking, embedding, BM25, rerank, semantic cache
│   ├── mcp_servers/     # docs, accounts, logs, github, stripe (each with auth+audit)
│   ├── graph/           # LangGraph state, agent nodes, supervisor, build
│   ├── hitl/            # Approval queue, policies, human override
│   └── api/             # FastAPI routes, SSE, ticket store
├── evals/               # Multi-agent eval, scenarios, adversarial, judge calibration
├── tests/               # 421 tests (unit, reliability, load)
├── apps/web/            # Next.js 16 frontend
├── infra/terraform/     # AWS ECS Fargate IaC
├── migrations/          # Postgres DDL (RLS, pgvector)
└── scripts/             # Data collection, seeding
```

---

*Built with LangGraph, FastAPI, MCP, LiteLLM, Postgres, and Next.js.*
