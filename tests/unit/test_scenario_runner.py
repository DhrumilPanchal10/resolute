"""Tests for evals/scenarios/runner.py — scenario evaluation runner.

All tests run OFFLINE=1 with canned LLM responses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

SCENARIOS_PATH = ROOT / "evals" / "scenarios" / "scenarios.yaml"


@pytest.mark.asyncio
async def test_load_all_100_scenarios():
    """All 100 scenarios parse and validate against the Pydantic schema."""
    from evals.scenarios.runner import load_scenarios

    scenarios = load_scenarios(SCENARIOS_PATH)
    assert len(scenarios) == 100
    ids = [s.id for s in scenarios]
    assert len(set(ids)) == 100, "Duplicate scenario IDs found"
    for s in scenarios:
        assert s.title
        assert s.ticket_text
        assert s.category in {"billing", "auth", "performance", "config", "other"}


@pytest.mark.asyncio
async def test_run_first_5_scenarios(tmp_path, monkeypatch):
    """Run the first 5 scenarios offline and verify pass criteria checked."""
    monkeypatch.setenv("OFFLINE", "1")

    from evals.scenarios.runner import run_all

    out_path = tmp_path / "results.jsonl"
    results = await run_all(SCENARIOS_PATH, k=1, out_path=out_path, limit=5)

    assert len(results) == 5
    for r in results:
        assert r.scenario_id
        assert r.k == 1
        assert len(r.attempts) == 1

    # Verify JSONL output
    lines = [l for l in out_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 5


@pytest.mark.asyncio
async def test_pass_at_k(tmp_path, monkeypatch):
    """With k=2, pass_at_k should be True when at least one attempt passes."""
    monkeypatch.setenv("OFFLINE", "1")

    from evals.scenarios.runner import run_all

    out_path = tmp_path / "results.jsonl"
    results = await run_all(SCENARIOS_PATH, k=2, out_path=out_path, limit=3)

    for r in results:
        assert r.k == 2
        assert len(r.attempts) == 2
        if r.pass_at_1:
            assert r.pass_at_k


@pytest.mark.asyncio
async def test_check_scenario_pass():
    """check_scenario returns passed=True when all criteria match."""
    from evals.scenarios.runner import check_scenario
    from evals.scenarios.schema import ExpectedState

    result = {
        "triage": {"category": "billing", "severity": "high"},
        "final_reply": "We will process your refund for the duplicate charge.",
        "evidence": [{"id": "1"}],
        "findings": [],
        "errors": [],
    }
    expected = ExpectedState(
        triage_category="billing",
        triage_severity="high",
        reply_contains=["refund", "duplicate"],
    )
    attempt = check_scenario(result, expected)
    assert attempt.passed
    assert attempt.failures == []


@pytest.mark.asyncio
async def test_check_scenario_fail_category():
    """check_scenario detects wrong triage category."""
    from evals.scenarios.runner import check_scenario
    from evals.scenarios.schema import ExpectedState

    result = {
        "triage": {"category": "auth", "severity": "high"},
        "final_reply": "We will help you.",
    }
    expected = ExpectedState(triage_category="billing")
    attempt = check_scenario(result, expected)
    assert not attempt.passed
    assert any("triage_category" in f for f in attempt.failures)


@pytest.mark.asyncio
async def test_check_scenario_fail_reply_contains():
    """check_scenario detects missing reply keywords."""
    from evals.scenarios.runner import check_scenario
    from evals.scenarios.schema import ExpectedState

    result = {
        "triage": {"category": "billing"},
        "final_reply": "Thank you for contacting us.",
    }
    expected = ExpectedState(reply_contains=["refund"])
    attempt = check_scenario(result, expected)
    assert not attempt.passed
    assert any("refund" in f for f in attempt.failures)


@pytest.mark.asyncio
async def test_check_scenario_reply_not_contains():
    """check_scenario detects forbidden reply content."""
    from evals.scenarios.runner import check_scenario
    from evals.scenarios.schema import ExpectedState

    result = {
        "triage": {},
        "final_reply": "Here is a <script>alert(1)</script> for you.",
    }
    expected = ExpectedState(reply_not_contains=["<script>"])
    attempt = check_scenario(result, expected)
    assert not attempt.passed
    assert any("forbidden" in f for f in attempt.failures)
