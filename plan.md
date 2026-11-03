# RESOLUTE — Implementation Plan

Multi-agent customer support resolution platform. This file is the single source of truth for building the project.

**How Claude Code uses this file:** read §0 (rules) and ONLY the task you were assigned (e.g. "T3.2"). Do not read other tasks unless the task says so. When done: tick the task's checkbox, append one line to `PROGRESS.md`, commit.

---

## §0 — Rules for every coding agent

- Stack: Python 3.12, uv, FastAPI, LangGraph, MCP Python SDK (`mcp`, FastMCP), LiteLLM, PostgreSQL + pgvector, Redis, OpenTelemetry, Next.js 15 + TypeScript (later phases).
- Zero-budget infra: Postgres = Supabase (free) or local Docker; Redis = Upstash (free) or local; Auth = Clerk (OIDC/JWT); Tracing = Langfuse cloud via OTLP, or local Arize Phoenix; LLMs = Gemini + Groq free tiers through LiteLLM; embeddings + reranker run locally (sentence-transformers).
- Machine: MacBook Air M1, 8 GB RAM. Never start more than Postgres, Redis and the app locally. Never add a local LLM.
- All config via `src/resolute/config.py` (pydantic-settings) reading `.env`. Model names are config values (`MODEL_SMALL`, `MODEL_STRONG`, `MODEL_JUDGE`), never hardcoded.
- Every LLM call goes through `agentcore/llm.py`. Every tool call goes through an MCP server. Every node is wrapped by guardrails middleware. No exceptions.
- Every agent output is a Pydantic model (structured output). No parsing free text.
- `OFFLINE=1` mode: LLM calls return recorded fixtures from `tests/fixtures/llm/`. Unit tests and CI must pass with `OFFLINE=1` and no API keys. A missing fixture raises `OfflineFixtureError` (never silently falls back).
- A run that produced no result must exit non-zero / return an error status. Silent success is a bug.
- Async everywhere in I/O paths. Type hints everywhere. `ruff` + `mypy --strict` on `src/`.
- Tests: pytest. Each task lists its "Done when" command. Do not mark a task done unless it passes.
- Do not modify files outside the task's file list without saying why.
- Never commit secrets. `.env` is gitignored; `.env.example` lists every variable.

---

## §1 — Architecture (reference)

```
Next.js workspace ──SSE──> FastAPI (JWT/RBAC) ──> LangGraph graph (Postgres checkpointer)
                                                   ├─ triage
                                                   ├─ knowledge ─┐ (parallel fan-out)
                                                   ├─ investigator┘
                                                   ├─ resolver
                                                   ├─ verifier ──(revise ≤2)──> resolver
                                                   └─ supervisor (budget, routing, escalation)
                                                          │
                     MCP servers (auth + audit): github · docs · accounts · logs · stripe(test)
                                                          │
                     Postgres (RLS per tenant, audit, memory, checkpoints) · pgvector · Redis cache
All hops emit OpenTelemetry GenAI spans → Langfuse/Phoenix
```

Repo layout (create in T0.1):

```
resolute/
├── AGENTS.md  CLAUDE.md  plan.md  PROGRESS.md  README.md
├── pyproject.toml  Makefile  docker-compose.yml  .env.example
├── .github/workflows/ci.yml
├── .claude/commands/task.md
├── docs/ discovery.md threat-model.md architecture.md decisions/ results/
├── src/agentcore/          # reusable spine
│   ├── llm.py  routing.py  cost.py  telemetry.py  guardrails.py
│   ├── audit.py  auth.py  cache.py  memory.py  offline.py  errors.py
├── src/resolute/
│   ├── config.py  db.py  models.py
│   ├── retrieval/ ingest.py chunking.py embed.py hybrid.py rerank.py acl.py time_travel.py
│   ├── mcp_servers/ github.py docs.py accounts.py logs.py stripe_srv.py client.py
│   ├── graph/ state.py build.py agents/{triage,knowledge,investigator,resolver,verifier,supervisor}.py
│   ├── hitl/ policies.py queue.py
│   └── api/ main.py routes_tickets.py routes_approvals.py sse.py
├── apps/web/               # Next.js (Phase 6)
├── evals/ data/ real_issues/ scenarios/ adversarial/ judge/ baseline/ run.py report.py
├── migrations/             # SQL migrations (incl. RLS)
├── scripts/ collect_issues.py seed_northwind.py
└── tests/ unit/ integration/ fixtures/
```

---

## §2 — Milestones

- **M1 Resume-ready slice** = Phases 0–5 + T7.1 + T7.2: six agents end to end, 3 MCP servers, hybrid RAG with traces, memory, one approval gate, 100 real issues scored vs baseline.
- **M2 Interview-ready** = + Phases 7–8 (full evals, adversarial, fault injection, caching, cost).
- **M3 Complete** = + Phases 6 (full UI) and 9 (deploy, docs, demo).

---

## Phase 0 — Foundation

- [x] **T0.1 Scaffold repo** · Tool: Claude Code · Model: small
  - Do: create the layout in §1; `pyproject.toml` with uv (deps: fastapi, uvicorn, pydantic-settings, langgraph, langgraph-checkpoint-postgres, mcp, litellm, psycopg[binary], sqlalchemy, pgvector, redis, opentelemetry-sdk, opentelemetry-exporter-otlp, sentence-transformers, bm25s, httpx, tenacity, pytest, pytest-asyncio, ruff, mypy); Makefile targets `install, up, down, test, lint, eval-smoke, eval-full`; `.env.example`; `.gitignore`.
  - Done when: `make install && make lint && make test` succeeds (empty test passes).
- [ ] **T0.2 Agent instruction files** · Tool: you (manual)
  - Do: create `AGENTS.md` from Appendix A; `CLAUDE.md` containing the single line `@AGENTS.md`; `.claude/commands/task.md` from Appendix B; empty `PROGRESS.md`.
- [x] **T0.3 Config + compose** · Tool: Claude Code · Model: small
  - Do: `config.py` (pydantic-settings, all env vars); `docker-compose.yml` with `postgres` (pgvector image) and `redis` only, memory limits 512m/128m.
  - Done when: `make up` starts both; `python -c "from resolute.config import settings"` works.
- [x] **T0.4 CI skeleton** · Tool: Claude Code · Model: small
  - Do: GitHub Actions: uv install, ruff, mypy, pytest with `OFFLINE=1`.
  - Done when: CI green on push.
- [ ] **T0.5 Discovery + threat model** · Tool: you, draft with claude.ai
  - Do: `docs/discovery.md` (Northwind Cloud scenario, roles, workflow today, pain, success metrics, out of scope); `docs/threat-model.md` (assets, actors, direct injection, injection via tool output, tool poisoning, confused deputy, cross-tenant access, over-broad actions).

## Phase 1 — Data and baseline (first benchmark)

- [x] **T1.1 Collect real issues** · Tool: Claude Code · Model: default
  - Do: `scripts/collect_issues.py` uses GitHub REST API (token from `.env`) to pull closed issues/answered discussions from 3 well-documented OSS repos (configurable). Keep issues with a maintainer answer or linked merged PR. Save JSONL: `id, repo, title, body, created_at, closed_at, resolution_text, resolution_url, labels`. Target 300; start with 100.
  - Done when: `evals/data/real_issues/issues.jsonl` has ≥100 rows; unit test validates schema.
- [x] **T1.2 Docs + history corpus with timestamps** · Tool: Claude Code · Model: default
  - Do: clone each repo's docs at the default branch; walk git history to record `first_seen_at` per doc file (git log). Index past issues as documents with `created_at`.
  - Done when: `evals/data/corpus/*.jsonl` exists with `doc_id, repo, path, text, created_at`.
- [x] **T1.3 Offline mode + LLM wrapper (minimal)** · Tool: Claude Code · Model: default
  - Do: `agentcore/llm.py` — `async complete(messages, schema=None, model_tier="small", **kw)` via LiteLLM; structured output → Pydantic; records tokens, latency, cost into `agentcore/cost.py`; `agentcore/offline.py` fixture record/replay keyed by hash(model_tier, messages, schema).
  - Done when: tests cover record, replay, missing-fixture error.
- [x] **T1.4 Single-agent baseline** · Tool: Claude Code · Model: default
  - Do: `evals/baseline/single_agent.py` — one strong-model agent with two tools (simple keyword search over corpus filtered by `created_at < issue.created_at`, and GitHub issue search with the same time filter). Produces answer + citations for each issue.
  - Done when: runs on 100 issues, writes `evals/results/baseline_<date>.jsonl`.
- [x] **T1.5 Judge v0 + first report** · Tool: Claude Code · Model: default
  - Do: `evals/judge/judge.py` — judge compares answer to `resolution_text`, outputs `{correct: bool, partial: bool, reason}`; `evals/report.py` prints accuracy, tokens/answer, latency, cost/answer.
  - Done when: `docs/results/baseline.md` committed with real numbers. **This is the first benchmark.**

## Phase 2 — agentcore spine

- [ ] **T2.1 Telemetry** · Tool: Claude Code · Model: default
  - Do: `telemetry.py` — OTel tracer provider, OTLP exporter (Langfuse or Phoenix via env), helpers `span_agent`, `span_llm`, `span_tool`, `span_retrieval_stage` using GenAI semantic-convention attribute names (`gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.tool.name`) + custom `resolute.cost_usd`, `resolute.tenant_id`.
  - Done when: a test run shows nested spans in the tracing UI (screenshot to `docs/results/`).
- [x] **T2.2 Routing + fallback** · Tool: Claude Code · Model: default
  - Do: `routing.py` — tier → ordered list of (provider, model); on rate limit / 5xx fall back to next; retries with tenacity (exponential backoff, jitter); per-run token and cost budget enforcement raising `BudgetExceeded`.
  - Done when: tests simulate 429 → fallback, budget exceed → error.
- [ ] **T2.3 Database + RLS** · Tool: Claude Code · Model: default
  - Do: `migrations/001_core.sql`: tenants, users, accounts, invoices, tickets, messages, audit_events, memories, approvals; `tenant_id` on every tenant table; enable RLS with policy `tenant_id = current_setting('app.tenant_id')`; `db.py` sets `app.tenant_id` per session.
  - Done when: integration test proves tenant A session cannot read tenant B rows.
- [ ] **T2.4 Auth + RBAC** · Tool: Claude Code · Model: default
  - Do: `auth.py` — verify Clerk JWTs via JWKS (cached), extract `user_id, tenant_id, role`; roles: `support_engineer, lead, admin, contractor`; `require_role()` FastAPI dependency; permission matrix in one dict.
  - Done when: tests with locally signed test JWTs cover valid, expired, wrong audience, wrong role.
- [x] **T2.5 Audit log** · Tool: Claude Code · Model: small
  - Do: `audit.py` — append-only insert with `prev_hash` + `hash` (sha256 of row + prev_hash); `verify_chain()`.
  - Done when: tampering test detects a modified row.
- [x] **T2.6 Guardrails middleware** · Tool: Claude Code · Model: strong (design) then default
  - Do: `guardrails.py` — `@guarded(node_name)` decorator for graph nodes: pre-checks (budget, loop count per ticket, wall clock, injection screen on untrusted text fields), post-checks (schema already enforced, PII masking for spans/logs, citation presence where required); policy per check `warn|block`; blocked node returns state with `errors` appended and `degraded=True`, never raises into the graph. Injection screen v1 = curated patterns + heuristics; interface allows a classifier later.
  - Done when: unit tests for each check; a node that throws yields degraded state, not a crash.
- [x] **T2.7 Cache** · Tool: Claude Code · Model: small
  - Do: `cache.py` — Redis helpers: `get_or_set(key, ttl, fn)`; key builder that ALWAYS includes `tenant_id`, `permission_scope`, `docs_version`.
  - Done when: tests prove different scope → different key.
- [x] **T2.8 Memory module** · Tool: Claude Code · Model: default
  - Do: `memory.py` — `ShortTerm` (compaction: summarize thread when > N tokens), `LongTerm` (per-customer facts; `write()` requires `source in {"system_data","verified_outcome"}`), `Episodic` (resolution + outcome, embedding, `expires_at`, `superseded_by`); retrieval by tenant + similarity; nightly `consolidate()` producing known-issue notes.
  - Done when: tests: customer-text source rejected; expired memories not returned; cross-tenant never returned.

## Phase 3 — Retrieval with stage-level observability

- [ ] **T3.1 Chunking + embeddings** · Tool: Claude Code · Model: default
  - Do: chunk docs by heading path (max ~400 tokens, overlap 50); embed locally with `BAAI/bge-small-en-v1.5` on MPS; store in pgvector with `tenant_id, acl_roles, created_at, docs_version`.
- [ ] **T3.2 Hybrid search** · Tool: Claude Code · Model: default
  - Do: BM25 (bm25s, persisted per tenant) + dense (pgvector HNSW) → reciprocal rank fusion; ACL + tenant + `created_at < as_of` filters applied INSIDE both queries.
  - Done when: test proves forbidden doc never returned even if top match.
- [ ] **T3.3 Reranker** · Tool: Claude Code · Model: small
  - Do: cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2`, top-30 → top-5.
- [ ] **T3.4 Stage tracing + retrieval eval** · Tool: Claude Code · Model: default
  - Do: each stage emits a span with inputs/outputs counts and ids; `evals/retrieval_eval.py` computes Recall@5, MRR, rerank lift on a labelled set of 100 query→doc pairs (label with Gemini-assisted proposals you verify by hand).
  - Done when: `docs/results/retrieval.md` with BM25-only vs hybrid vs hybrid+rerank.

## Phase 4 — MCP tool servers

- [ ] **T4.1 MCP server base** · Tool: Claude Code · Model: strong (design) then default
  - Do: shared FastMCP wrapper: verify caller JWT, resolve per-user delegated credentials, check RBAC permission for tool, write audit event, emit `span_tool`, timeout + circuit breaker; tools declare `risk: read|write|destructive`.
- [ ] **T4.2 docs server** · Tool: Claude Code · Model: small — `search_docs(query, k)` using Phase 3.
- [ ] **T4.3 accounts server** · Tool: Claude Code · Model: small — `get_account`, `get_invoices`, `get_usage` over Postgres (RLS); `scripts/seed_northwind.py` seeds 2 tenants × 30 accounts, invoices, synthetic logs.
- [ ] **T4.4 github server** · Tool: Claude Code · Model: default — `search_issues(q, as_of)`, `get_issue`, `search_code`, `create_issue` (write); uses the requesting user's token (no shared admin token).
- [ ] **T4.5 logs server** · Tool: Claude Code · Model: small — `search_logs(account_id, since, level, text)` over Postgres full-text.
- [ ] **T4.6 stripe server** · Tool: Claude Code · Model: default — Stripe TEST mode: `issue_credit`, `refund_invoice` (write); requires `approval_token` for amounts over policy; idempotency key = hash(ticket_id, action, args).
  - Done when (phase): integration tests for each server incl. RBAC denial and audit row written.

## Phase 5 — Agents and orchestration

- [ ] **T5.1 State** · Tool: Claude Code · Model: strong
  - Do: `graph/state.py` TypedDict with `Annotated[list, operator.add]` reducers for `findings`, `evidence`, `errors`, `tool_calls`; fields for ticket, triage, plan, draft, actions, verification, revision_count, budget, route.
- [ ] **T5.2 Triage agent** · Tool: Claude Code · Model: small · small model — category, severity, tier, injection_risk, out_of_scope.
- [ ] **T5.3 Knowledge agent** · Tool: Claude Code · Model: small — calls docs server + episodic memory; returns evidence list with citations.
- [ ] **T5.4 Investigator agent** · Tool: Claude Code · Model: default — bounded ReAct (max 6 tool calls) over accounts, logs, github; returns findings with source ids.
- [ ] **T5.5 Resolver agent** · Tool: Claude Code · Model: default — reply draft + `ActionPlan(list[Action])`, every claim tagged with evidence ids.
- [ ] **T5.6 Verifier agent** · Tool: Claude Code · Model: default — checks claims↔evidence, action args provenance (args must match values seen in tool outputs, not ticket text), policy (`hitl/policies.py`); returns `pass|revise|escalate` + issues.
- [ ] **T5.7 Supervisor + graph build** · Tool: Claude Code · Model: strong
  - Do: `graph/build.py`: triage → conditional (exit to human if abusive/out_of_scope) → `Send()` fan-out to knowledge ∥ investigator → resolver → verifier → conditional (revise ≤2 / approval interrupt / auto-send / escalate). Postgres checkpointer (`AsyncPostgresSaver`). `interrupt()` for approvals and customer replies. All nodes wrapped by `@guarded`.
  - Done when: `make demo` runs 3 sample tickets offline end to end; killing the process mid-run and re-invoking with the same thread id resumes.
- [ ] **T5.8 Wire memory** · Tool: Claude Code · Model: small — short-term compaction in resolver input; episodic write on verified outcome event only.

## Phase 6 — API, HITL and UI

- [ ] **T6.1 API** · Tool: Claude Code · Model: default — `POST /tickets`, `GET /tickets/{id}`, `GET /tickets/{id}/stream` (SSE of node events), `POST /approvals/{id}` (approve/reject/edit → resumes graph), `POST /tickets/{id}/reply` (customer reply → resumes).
- [ ] **T6.2 HITL policies + queue** · Tool: Claude Code · Model: small — policy table (refund > threshold, config change, ownership change → lead approval); queue ordered by severity, tier, age; overrides saved to `evals/data/overrides/`.
- [ ] **T6.3 Next.js app** · Tool: Claude Code · Model: default — Clerk auth; pages: inbox, ticket workspace (streams steps, evidence panel with citations, proposed actions), approval queue, admin metrics. Tailwind + shadcn/ui.
  - Done when: full flow clickable locally.

## Phase 7 — Evaluation suite

- [ ] **T7.1 Multi-agent run on real issues** · Tool: Claude Code — run graph on the same 100 issues (time-travelled), compare to baseline.
- [ ] **T7.2 Judge calibration** · Tool: you + Claude Code · Model: small — hand-label 50 answers; compute judge agreement; adjust rubric until ≥85%; save `docs/results/judge_calibration.md`.
- [ ] **T7.3 Action scenarios + simulated customer** · Tool: Claude Code · Model: default — 100 YAML scenarios with expected final DB/Stripe state; simulated customer LLM answers from hidden facts; runner computes pass^1 and pass^k (k configurable, default 3 for free tier).
- [ ] **T7.4 Adversarial suite** · Tool: Claude Code · Model: default — 150 injected tickets + 100 benign; ASR and benign success with guardrails on vs off.
- [ ] **T7.5 Report + CI gate** · Tool: Claude Code · Model: small — `evals/report.py` → markdown tables; CI runs 40-case offline smoke subset; fails if metrics drop below thresholds in `evals/thresholds.yaml`.
  - Done when: `docs/results/summary.md` has all metrics vs baseline.

## Phase 8 — Reliability, caching and cost

- [ ] **T8.1 Fault injection** · Tool: Claude Code — kill worker mid-run, inject tool 500/429, duplicate approval events; assert exactly-once Stripe actions and correct final state.
- [ ] **T8.2 Semantic cache** · Tool: Claude Code — cache documentation-answerable replies keyed by tenant + permission scope + docs_version + normalized query embedding (threshold); measure hit rate and error rate of cached answers.
- [ ] **T8.3 Prompt caching + routing tuning** · Tool: Claude Code — stable prefixes first in prompts; route triage/knowledge to small model; measure cost per resolved ticket before/after.
- [ ] **T8.4 Load test** · Tool: Claude Code · Model: small — k6 script against API with recorded tickets in OFFLINE latency-simulation mode + one small live run; p95 first-token latency.

## Phase 9 — Deploy and polish

- [ ] **T9.1 Containers** · Tool: Claude Code · Model: small — Dockerfiles (API, worker), multi-stage, non-root.
- [ ] **T9.2 Deploy** · Tool: you + Claude Code · Model: small — API on Render/Koyeb free tier, web on Vercel, Supabase + Upstash; Terraform in `infra/terraform/` for AWS (apply via AWS Academy/free credits or LocalStack); only claim what actually ran.
- [ ] **T9.3 README + diagrams** · Tool: claude.ai/Gemini draft, you edit — structure in Appendix C.
- [ ] **T9.4 Demo** · Tool: you — 2-minute and 5-minute recordings.

---

## Appendix A — AGENTS.md (copy into repo root)

```markdown
# Resolute — agent instructions
Project: multi-agent support resolution platform. Full plan: plan.md (read §0 and only your assigned task).
Commands: make install | make up | make test | make lint | make eval-smoke | make demo
Layout: src/agentcore (spine), src/resolute/{retrieval,mcp_servers,graph,hitl,api}, evals/, apps/web
Rules:
- All LLM calls via agentcore/llm.py; all tools via MCP servers; all nodes wrapped by @guarded.
- Pydantic structured outputs only. Async I/O. Type hints. ruff + mypy clean.
- OFFLINE=1 must keep tests passing with no keys. Missing fixture = error.
- Never hardcode model names or secrets. Never add a local LLM (8 GB machine).
- Do not read: evals/data/**, tests/fixtures/**, apps/web/node_modules/**, *.jsonl
- Finish = tests pass → tick task in plan.md → one line in PROGRESS.md → commit "<type>(Tx.y): summary".
```


## Appendix B — .claude/commands/task.md (custom slash command)

```markdown
Do task $ARGUMENTS in plan.md.
Read AGENTS.md rules, plan.md §0, and ONLY task $ARGUMENTS plus the files it names.
First give a plan in at most 5 bullets and wait for my OK.
Then implement until the task's "Done when" passes (run the tests).
Finish: tick the task checkbox in plan.md, append one line to PROGRESS.md, commit "<type>($ARGUMENTS): summary".
```

Usage in Claude Code: `/task T3.2`

## Appendix C — README structure

1. Pitch + demo GIF · 2. Problem · 3. Results table vs single-agent baseline (dated, with n) · 4. Architecture diagram · 5. Production spine checklist with file links · 6. Evaluation method (time-travel index, judge calibration) · 7. Threat model summary · 8. Quickstart (`make install up demo`) · 9. Design decisions and trade-offs · 10. Roadmap.
