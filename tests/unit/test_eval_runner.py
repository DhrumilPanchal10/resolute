"""Tests for evals/run.py — multi-agent evaluation runner.

All tests run OFFLINE=1 with canned LLM responses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


@pytest.mark.asyncio
async def test_smoke_issues_run(tmp_path, monkeypatch):
    """Run the multi-agent eval on built-in smoke issues and verify output."""
    monkeypatch.setenv("OFFLINE", "1")

    # Re-import after env set so is_offline() picks it up
    from evals.run import MultiAgentRow, run

    out_path = tmp_path / "results.jsonl"
    rows = await run(
        issues_path=Path("/nonexistent"),  # forces smoke issues
        out_path=out_path,
    )

    assert len(rows) == 5
    for row in rows:
        assert isinstance(row, MultiAgentRow)
        assert row.issue_id.startswith("smoke-")
        assert row.answer, f"Row {row.issue_id} has empty answer"
        assert row.latency_ms > 0

    # Verify JSONL output
    assert out_path.exists()
    lines = [l for l in out_path.read_text().splitlines() if l.strip()]
    assert len(lines) == 5
    for line in lines:
        parsed = json.loads(line)
        assert "issue_id" in parsed
        assert "answer" in parsed


@pytest.mark.asyncio
async def test_triage_category_varies(tmp_path, monkeypatch):
    """Canned triage should produce different categories based on issue text."""
    monkeypatch.setenv("OFFLINE", "1")

    from evals.run import run

    out_path = tmp_path / "results.jsonl"
    rows = await run(
        issues_path=Path("/nonexistent"),
        out_path=out_path,
    )

    categories = {r.triage_category for r in rows}
    assert len(categories) >= 2, f"Expected varied categories, got {categories}"


@pytest.mark.asyncio
async def test_custom_issues_file(tmp_path, monkeypatch):
    """Run on a custom issues JSONL file."""
    monkeypatch.setenv("OFFLINE", "1")

    from evals.run import run

    issues_file = tmp_path / "issues.jsonl"
    issues_file.write_text(
        json.dumps(
            {
                "id": "custom-001",
                "title": "Test issue",
                "body": "Something is broken",
                "created_at": "2024-01-01T00:00:00Z",
                "resolution_text": "Fixed it.",
            }
        )
        + "\n"
    )

    out_path = tmp_path / "results.jsonl"
    rows = await run(issues_path=issues_file, out_path=out_path)

    assert len(rows) == 1
    assert rows[0].issue_id == "custom-001"
    assert rows[0].answer


@pytest.mark.asyncio
async def test_compare_to_baseline(tmp_path, monkeypatch):
    """compare_to_baseline produces Markdown with both columns when baseline exists."""
    monkeypatch.setenv("OFFLINE", "1")

    from evals.run import MultiAgentRow, compare_to_baseline

    rows = [
        MultiAgentRow(
            issue_id="t1", answer="hi", triage_category="billing",
            triage_severity="low", latency_ms=100.0,
        ),
    ]

    baseline = tmp_path / "baseline.jsonl"
    baseline.write_text(
        json.dumps({"issue_id": "t1", "answer": "hello", "latency_ms": 200.0}) + "\n"
    )

    md = compare_to_baseline(rows, baseline)
    assert "Baseline" in md
    assert "Multi-Agent" in md


@pytest.mark.asyncio
async def test_compare_no_baseline():
    """compare_to_baseline works without a baseline file."""
    from evals.run import MultiAgentRow, compare_to_baseline

    rows = [
        MultiAgentRow(issue_id="t1", answer="hi", latency_ms=50.0),
    ]
    md = compare_to_baseline(rows, None)
    assert "No baseline" in md
