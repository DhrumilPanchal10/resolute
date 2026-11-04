#!/usr/bin/env python3
"""Multi-agent evaluation runner.

Runs the full Resolute graph on real issues (same set as the baseline) and
writes per-issue results to JSONL for judge comparison.

Each issue is:
  1. Loaded from evals/data/real_issues/issues.jsonl
  2. Fed through the compiled LangGraph (triage → knowledge ∥ investigator →
     resolver → verifier → send_reply)
  3. Recorded: final_reply, triage, evidence_count, findings_count, node_path,
     error_count, latency_ms

The runner works in two modes:
  - OFFLINE=1: canned LLM responses (same _fake_complete as `make demo`)
    for CI and smoke tests.  No API keys needed.
  - OFFLINE=0: real LLM calls through agentcore/llm.py with routing.

Usage:
    # Offline smoke test (uses canned responses)
    OFFLINE=1 python evals/run.py

    # Live run (requires API keys)
    python evals/run.py --issues evals/data/real_issues/issues.jsonl

    # With custom output
    python evals/run.py --out evals/results/multiagent_custom.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcore.llm import _set_complete_fn
from agentcore.offline import is_offline
from resolute.graph.build import build_graph
from resolute.graph.state import (
    ActionPlan,
    ResolverOutput,
    TriageResult,
    VerificationResult,
    initial_state,
)

ISSUES_PATH = ROOT / "evals" / "data" / "real_issues" / "issues.jsonl"
RESULTS_DIR = ROOT / "evals" / "results"

# ---------------------------------------------------------------------------
# Synthetic issues for offline smoke tests (used when no real issues exist)
# ---------------------------------------------------------------------------

SMOKE_ISSUES: list[dict[str, Any]] = [
    {
        "id": "smoke-001",
        "title": "Duplicate charge on Pro plan",
        "body": (
            "I was charged twice for my Pro plan subscription last month. "
            "Invoice INV-2024-001 shows $199 but I see two charges on my card."
        ),
        "created_at": "2024-06-15T10:00:00Z",
        "resolution_text": "Refund duplicate charge and confirm single billing going forward.",
    },
    {
        "id": "smoke-002",
        "title": "401 Unauthorized after deploy",
        "body": (
            "Can't log in since the last deploy. Getting 401 every time. "
            "This is blocking our entire team."
        ),
        "created_at": "2024-06-16T14:00:00Z",
        "resolution_text": "Auth token cache was stale after deploy; cleared cache and reissued tokens.",
    },
    {
        "id": "smoke-003",
        "title": "How to upgrade from Starter to Pro?",
        "body": "What features do I get and how is billing handled for the upgrade?",
        "created_at": "2024-06-17T09:00:00Z",
        "resolution_text": "Directed to upgrade flow in dashboard; pro-rated billing explained.",
    },
    {
        "id": "smoke-004",
        "title": "API rate limit too low",
        "body": (
            "Our integration is hitting the 100 req/min rate limit regularly. "
            "We need at least 500 req/min for our production traffic."
        ),
        "created_at": "2024-06-18T11:00:00Z",
        "resolution_text": "Upgraded to Business plan with 1000 req/min; adjusted rate limit config.",
    },
    {
        "id": "smoke-005",
        "title": "Data export not working",
        "body": "The CSV export button in the dashboard returns a 500 error since yesterday.",
        "created_at": "2024-06-19T16:00:00Z",
        "resolution_text": "Bug in export serializer fixed in hotfix v2.3.1.",
    },
]


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class MultiAgentRow(BaseModel):
    issue_id: str
    answer: str
    triage_category: str = ""
    triage_severity: str = ""
    evidence_count: int = 0
    findings_count: int = 0
    error_count: int = 0
    errors: list[str] = Field(default_factory=list)
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Offline canned responses
# ---------------------------------------------------------------------------


def _install_fake_complete() -> None:
    """Install deterministic canned responses for offline eval runs."""

    async def _fake_complete(
        messages: list[dict[str, Any]],
        schema: Any = None,
        model_tier: str = "small",
        **_: Any,
    ) -> Any:
        if schema is TriageResult:
            text = messages[-1].get("content", "") if messages else ""
            category = "billing"
            severity = "medium"
            if "auth" in text.lower() or "401" in text or "login" in text.lower():
                category = "auth"
                severity = "critical"
            elif "rate limit" in text.lower() or "api" in text.lower():
                category = "performance"
                severity = "high"
            elif "export" in text.lower() or "500" in text:
                category = "config"
                severity = "high"
            elif "upgrade" in text.lower() or "plan" in text.lower():
                severity = "low"
            return TriageResult(
                category=category,
                severity=severity,
                tier="default",
                injection_risk=False,
                out_of_scope=False,
                summary=text[:120] if text else "Issue summary",
            )

        if schema is ResolverOutput:
            return ResolverOutput(
                draft=(
                    "Thank you for reaching out. We've investigated your issue "
                    "and will resolve it promptly. Our team has identified the root cause "
                    "and is taking corrective action."
                ),
                evidence_ids=["evidence-1"],
                action_plan=ActionPlan(actions=[]),
            )

        if schema is VerificationResult:
            return VerificationResult(verdict="pass", issues=[])

        system_msg = messages[0].get("content", "") if messages else ""
        if "knowledge retrieval" in system_msg:
            return (
                '[{"source_id":"doc-eval-1","source_type":"docs",'
                '"heading":"FAQ","snippet":"Relevant documentation excerpt.",'
                '"relevance":0.85}]'
            )
        return '{"done": true, "findings": []}'

    _set_complete_fn(_fake_complete)


# ---------------------------------------------------------------------------
# Run one issue through the graph
# ---------------------------------------------------------------------------


async def run_issue(graph: Any, issue: dict[str, Any]) -> MultiAgentRow:
    """Run a single issue through the compiled graph and return a result row."""
    ticket_id = f"eval-{issue['id']}"
    state = initial_state(
        ticket_id=ticket_id,
        tenant_id="tenant-eval",
        user_id="user-eval",
        ticket_text=f"{issue['title']}\n\n{issue['body']}",
    )
    config = {"configurable": {"thread_id": ticket_id}}

    t0 = time.perf_counter()
    try:
        result = await graph.ainvoke(state, config=config)
    except Exception as exc:
        return MultiAgentRow(
            issue_id=issue["id"],
            answer="",
            error_count=1,
            errors=[f"graph invoke failed: {exc}"],
            latency_ms=(time.perf_counter() - t0) * 1000,
        )
    latency_ms = (time.perf_counter() - t0) * 1000

    triage = result.get("triage") or {}
    errors = list(result.get("errors") or [])

    return MultiAgentRow(
        issue_id=issue["id"],
        answer=result.get("final_reply", "") or result.get("draft", "") or "",
        triage_category=triage.get("category", ""),
        triage_severity=triage.get("severity", ""),
        evidence_count=len(result.get("evidence") or []),
        findings_count=len(result.get("findings") or []),
        error_count=len(errors),
        errors=errors,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------


def compare_to_baseline(
    multi_rows: list[MultiAgentRow],
    baseline_path: Path | None,
) -> str:
    """Return a Markdown comparison table, or a note if no baseline exists."""
    n = len(multi_rows)
    if n == 0:
        return "No results to compare."

    answered = sum(1 for r in multi_rows if r.answer)
    errored = sum(1 for r in multi_rows if r.error_count > 0)
    avg_latency = sum(r.latency_ms for r in multi_rows) / n

    lines = [
        "## Multi-Agent Results",
        "",
        f"| Metric | Multi-Agent ({n} issues) |",
        "|--------|-------------------------|",
        f"| Answered | {answered}/{n} ({answered / n:.0%}) |",
        f"| Errored | {errored}/{n} |",
        f"| Avg latency | {avg_latency:.0f} ms |",
    ]

    if baseline_path and baseline_path.exists():
        bl_rows: list[dict[str, Any]] = []
        with baseline_path.open() as fh:
            for line in fh:
                if line.strip():
                    bl_rows.append(json.loads(line))
        if bl_rows:
            bl_n = len(bl_rows)
            bl_answered = sum(1 for r in bl_rows if r.get("answer"))
            bl_avg_lat = sum(r.get("latency_ms", 0) for r in bl_rows) / bl_n
            lines.append("")
            lines.append(f"| Metric | Baseline ({bl_n}) | Multi-Agent ({n}) |")
            lines.append("|--------|-------------------|----------------------|")
            lines.append(
                f"| Answered | {bl_answered}/{bl_n} "
                f"| {answered}/{n} |"
            )
            lines.append(
                f"| Avg latency | {bl_avg_lat:.0f} ms "
                f"| {avg_latency:.0f} ms |"
            )
    else:
        lines.append("")
        lines.append("*No baseline file found for comparison.*")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(
    issues_path: Path,
    out_path: Path | None = None,
    baseline_path: Path | None = None,
) -> list[MultiAgentRow]:
    """Run the multi-agent eval and return result rows."""
    # Load issues
    issues: list[dict[str, Any]] = []
    if issues_path.exists():
        with issues_path.open() as fh:
            for line in fh:
                if line.strip():
                    issues.append(json.loads(line))

    if not issues:
        if is_offline():
            print("No issues file — using built-in smoke issues for offline eval.")
            issues = SMOKE_ISSUES
        else:
            sys.exit(f"Issues file not found or empty: {issues_path}")

    # Install canned responses for offline mode
    if is_offline():
        _install_fake_complete()

    try:
        graph = build_graph()
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        if out_path is None:
            date_str = datetime.now().strftime("%Y%m%d")
            out_path = RESULTS_DIR / f"multiagent_{date_str}.jsonl"

        rows: list[MultiAgentRow] = []
        for i, issue in enumerate(issues):
            print(f"[{i + 1}/{len(issues)}] {issue['id']}")
            row = await run_issue(graph, issue)
            rows.append(row)
            with out_path.open("a") as fh:
                fh.write(row.model_dump_json() + "\n")

        # Summary
        answered = sum(1 for r in rows if r.answer)
        errored = sum(1 for r in rows if r.error_count > 0)
        print(f"\nDone. {len(rows)} issues → {out_path}")
        print(f"  Answered: {answered}/{len(rows)}  Errored: {errored}/{len(rows)}")

        # Comparison
        comparison = compare_to_baseline(rows, baseline_path)
        print(f"\n{comparison}")

    finally:
        if is_offline():
            _set_complete_fn(None)

    return rows


async def run_eval(limit: int | None = None) -> list[MultiAgentRow]:
    """Thin wrapper for the report runner — runs smoke issues with optional limit."""
    issues = SMOKE_ISSUES[:limit] if limit else SMOKE_ISSUES
    if is_offline():
        _install_fake_complete()
    try:
        graph = build_graph()
        rows: list[MultiAgentRow] = []
        for issue in issues:
            row = await run_issue(graph, issue)
            rows.append(row)
    finally:
        if is_offline():
            _set_complete_fn(None)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--issues", default=str(ISSUES_PATH))
    parser.add_argument("--out", default=None)
    parser.add_argument("--baseline", default=None, help="Path to baseline JSONL for comparison")
    args = parser.parse_args()
    asyncio.run(
        run(
            Path(args.issues),
            Path(args.out) if args.out else None,
            Path(args.baseline) if args.baseline else None,
        )
    )


if __name__ == "__main__":
    main()
