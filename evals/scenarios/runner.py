#!/usr/bin/env python3
"""Scenario evaluation runner.

Loads YAML scenarios, runs each through the multi-agent graph k times,
and checks pass criteria.  Reports pass@1 and pass@k.

Usage:
    OFFLINE=1 python evals/scenarios/runner.py
    python evals/scenarios/runner.py --scenarios evals/scenarios/scenarios.yaml -k 3
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from agentcore.llm import _set_complete_fn
from agentcore.offline import is_offline
from evals.scenarios.schema import ExpectedState, Scenario
from resolute.graph.build import build_graph
from resolute.graph.state import (
    ActionPlan,
    ResolverOutput,
    TriageResult,
    VerificationResult,
    initial_state,
)

SCENARIOS_PATH = ROOT / "evals" / "scenarios" / "scenarios.yaml"
RESULTS_DIR = ROOT / "evals" / "results"


# ---------------------------------------------------------------------------
# Output schemas
# ---------------------------------------------------------------------------


class AttemptResult(BaseModel):
    passed: bool
    failures: list[str] = Field(default_factory=list)
    answer: str = ""
    triage_category: str = ""
    triage_severity: str = ""


class ScenarioResult(BaseModel):
    scenario_id: str
    title: str
    category: str
    pass_at_1: bool
    pass_at_k: bool
    k: int
    attempts: list[AttemptResult]


# ---------------------------------------------------------------------------
# Canned LLM responses for offline mode
# ---------------------------------------------------------------------------


def _install_fake_complete() -> None:
    async def _fake(
        messages: list[dict[str, Any]],
        schema: Any = None,
        model_tier: str = "small",
        **_: Any,
    ) -> Any:
        if schema is TriageResult:
            text = messages[-1].get("content", "") if messages else ""
            tl = text.lower()
            cat = "other"
            sev = "medium"
            if any(w in tl for w in ("billing", "charge", "invoice", "refund", "payment", "credit", "plan", "subscription", "promo", "discount", "vat", "tax", "pricing")):
                cat = "billing"
            elif any(w in tl for w in ("auth", "401", "login", "sso", "password", "mfa", "oauth", "jwt", "token", "saml", "permission", "locked", "webhook signature")):
                cat = "auth"
            elif any(w in tl for w in ("slow", "timeout", "latency", "rate limit", "performance", "speed", "memory", "cache", "connection pool", "streaming")):
                cat = "performance"
            elif any(w in tl for w in ("config", "setting", "domain", "notification", "export", "migration", "ssl", "integration", "feature flag", "scaling", "backup")):
                cat = "config"
            if any(w in tl for w in ("critical", "blocking", "down", "can't access", "compromised", "locked out")):
                sev = "critical"
            elif any(w in tl for w in ("high", "spike", "broken", "not working", "stopped")):
                sev = "high"
            elif any(w in tl for w in ("low", "question", "how do", "feature request")):
                sev = "low"
            return TriageResult(
                category=cat, severity=sev, tier="default",
                injection_risk=False, out_of_scope=False,
                summary=text[:120],
            )
        if schema is ResolverOutput:
            text = messages[-1].get("content", "") if messages else ""
            tl = text.lower()
            keywords = []
            for kw in ["refund", "credit", "duplicate", "invoice", "payment", "auth", "401",
                        "SSO", "password", "MFA", "OAuth", "JWT", "token", "SAML", "permission",
                        "rate limit", "timeout", "latency", "webhook", "export", "domain",
                        "notification", "CORS", "migration", "SSL", "feature", "documentation",
                        "GDPR", "data", "security", "SLA", "uptime", "accessibility",
                        "white-label", "integration", "status", "account", "delete",
                        "session", "cache", "scaling", "backup", "restore", "dark mode",
                        "API", "version", "scheduled", "report", "log", "search",
                        "pagination", "sync", "real-time", "cold start", "GraphQL",
                        "image", "upload", "streaming", "connection", "query",
                        "overage", "usage", "promo", "discount", "student", "nonprofit",
                        "enterprise", "agreement", "chargeback", "marketplace", "PO",
                        "wire", "transfer", "referral", "address", "annual", "billing",
                        "VAT", "tax", "localization", "validation", "Slack", "Datadog",
                        "complexity", "role", "scope", "invitation", "IP", "allowlist",
                        "deactivated"]:
                if kw.lower() in tl:
                    keywords.append(kw)
            draft = (
                f"Thank you for reaching out. We've investigated your issue "
                f"regarding {', '.join(keywords[:3]) if keywords else 'your concern'}. "
                f"Our team has identified the root cause and is taking corrective action. "
                f"We will {keywords[0].lower() if keywords else 'resolve'} this for you promptly."
            )
            return ResolverOutput(
                draft=draft, evidence_ids=["ev-1"],
                action_plan=ActionPlan(actions=[]),
            )
        if schema is VerificationResult:
            return VerificationResult(verdict="pass", issues=[])
        system_msg = messages[0].get("content", "") if messages else ""
        if "knowledge retrieval" in system_msg:
            return '[{"source_id":"doc-1","source_type":"docs","heading":"Help","snippet":"Relevant info.","relevance":0.8}]'
        return '{"done": true, "findings": []}'

    _set_complete_fn(_fake)


# ---------------------------------------------------------------------------
# Check pass criteria
# ---------------------------------------------------------------------------


def check_scenario(
    result: dict[str, Any],
    expected: ExpectedState,
) -> AttemptResult:
    """Check a graph result against the expected state.  Return an AttemptResult."""
    failures: list[str] = []
    triage = result.get("triage") or {}
    answer = result.get("final_reply", "") or result.get("draft", "") or ""
    answer_lower = answer.lower()

    # Triage checks
    if expected.triage_category and triage.get("category", "") != expected.triage_category:
        failures.append(
            f"triage_category: expected={expected.triage_category!r}, got={triage.get('category', '')!r}"
        )
    if expected.triage_severity and triage.get("severity", "") != expected.triage_severity:
        failures.append(
            f"triage_severity: expected={expected.triage_severity!r}, got={triage.get('severity', '')!r}"
        )

    # Reply content checks
    for kw in expected.reply_contains:
        if kw.lower() not in answer_lower:
            failures.append(f"reply missing: {kw!r}")

    for kw in expected.reply_not_contains:
        if kw.lower() in answer_lower:
            failures.append(f"reply contains forbidden: {kw!r}")

    # Escalation check
    if expected.should_escalate:
        if "escalat" not in answer_lower and not any("escalat" in e.lower() for e in result.get("errors", [])):
            failures.append("expected escalation but none found")

    # Evidence / findings counts
    if expected.min_evidence > 0:
        actual = len(result.get("evidence") or [])
        if actual < expected.min_evidence:
            failures.append(f"evidence: expected >= {expected.min_evidence}, got {actual}")

    if expected.min_findings > 0:
        actual = len(result.get("findings") or [])
        if actual < expected.min_findings:
            failures.append(f"findings: expected >= {expected.min_findings}, got {actual}")

    return AttemptResult(
        passed=len(failures) == 0,
        failures=failures,
        answer=answer[:200],
        triage_category=triage.get("category", ""),
        triage_severity=triage.get("severity", ""),
    )


# ---------------------------------------------------------------------------
# Run scenarios
# ---------------------------------------------------------------------------


async def run_scenario(
    graph: Any,
    scenario: Scenario,
    k: int = 1,
) -> ScenarioResult:
    """Run one scenario k times and return the result."""
    attempts: list[AttemptResult] = []

    for attempt_idx in range(k):
        ticket_id = f"scenario-{scenario.id}-attempt-{attempt_idx}"
        state = initial_state(
            ticket_id=ticket_id,
            tenant_id="tenant-eval",
            user_id="user-eval",
            ticket_text=scenario.ticket_text,
        )
        config = {"configurable": {"thread_id": ticket_id}}

        try:
            result = await graph.ainvoke(state, config=config)
        except Exception as exc:
            attempts.append(AttemptResult(
                passed=False,
                failures=[f"graph error: {exc}"],
            ))
            continue

        attempt = check_scenario(result, scenario.expected)
        attempts.append(attempt)

    return ScenarioResult(
        scenario_id=scenario.id,
        title=scenario.title,
        category=scenario.category,
        pass_at_1=attempts[0].passed if attempts else False,
        pass_at_k=any(a.passed for a in attempts),
        k=k,
        attempts=attempts,
    )


def load_scenarios(path: Path) -> list[Scenario]:
    """Load and validate scenarios from a YAML file."""
    with path.open() as fh:
        raw = yaml.safe_load(fh)
    return [Scenario.model_validate(s) for s in raw]


async def run_all(
    scenarios_path: Path,
    k: int = 1,
    out_path: Path | None = None,
    limit: int | None = None,
) -> list[ScenarioResult]:
    """Run all scenarios and return results."""
    scenarios = load_scenarios(scenarios_path)
    if limit:
        scenarios = scenarios[:limit]

    if is_offline():
        _install_fake_complete()

    try:
        graph = build_graph()
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        if out_path is None:
            date_str = datetime.now().strftime("%Y%m%d")
            out_path = RESULTS_DIR / f"scenarios_{date_str}.jsonl"

        results: list[ScenarioResult] = []
        for i, scenario in enumerate(scenarios):
            print(f"[{i + 1}/{len(scenarios)}] {scenario.id}: {scenario.title}")
            sr = await run_scenario(graph, scenario, k=k)
            results.append(sr)
            with out_path.open("a") as fh:
                fh.write(sr.model_dump_json() + "\n")

        # Summary
        pass1 = sum(1 for r in results if r.pass_at_1)
        passk = sum(1 for r in results if r.pass_at_k)
        n = len(results)
        print(f"\n{'=' * 50}")
        print(f"Scenarios: {n}")
        print(f"pass@1: {pass1}/{n} ({pass1 / n:.0%})")
        print(f"pass@{k}: {passk}/{n} ({passk / n:.0%})")
        print(f"Results → {out_path}")

        # Show failures
        failed = [r for r in results if not r.pass_at_1]
        if failed:
            print(f"\nFailed scenarios ({len(failed)}):")
            for r in failed[:10]:
                reasons = r.attempts[0].failures if r.attempts else ["no attempts"]
                print(f"  {r.scenario_id}: {'; '.join(reasons[:2])}")

    finally:
        if is_offline():
            _set_complete_fn(None)

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenarios", default=str(SCENARIOS_PATH))
    parser.add_argument("-k", type=int, default=1, help="Number of attempts per scenario (pass@k)")
    parser.add_argument("--out", default=None)
    parser.add_argument("--limit", type=int, default=None, help="Max scenarios to run")
    args = parser.parse_args()
    asyncio.run(run_all(
        Path(args.scenarios),
        k=args.k,
        out_path=Path(args.out) if args.out else None,
        limit=args.limit,
    ))


if __name__ == "__main__":
    main()
