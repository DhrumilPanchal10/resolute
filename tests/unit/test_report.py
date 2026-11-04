"""Tests for evals/report.py — unified report + CI gate."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.report import check_gate, generate_summary, load_thresholds


class TestLoadThresholds:
    def test_loads_yaml(self) -> None:
        t = load_thresholds()
        assert "multi_agent" in t
        assert "scenarios" in t
        assert "adversarial" in t

    def test_threshold_values(self) -> None:
        t = load_thresholds()
        assert 0 < t["adversarial"]["max_asr"] < 1
        assert 0 < t["adversarial"]["min_benign_success"] <= 1


class TestCheckGate:
    def _make_inputs(
        self,
        triage_rate: float = 1.0,
        reply_rate: float = 1.0,
        pass_at_1: float = 0.5,
        pass_at_k: float = 0.5,
        asr: float = 0.0,
        benign_success: float = 1.0,
    ) -> tuple[dict, dict, dict]:
        ma = {"triage_rate": triage_rate, "reply_rate": reply_rate}
        sc = {"pass_at_1": pass_at_1, "pass_at_k": pass_at_k}
        adv = {"asr": asr, "benign_success_rate": benign_success}
        return ma, sc, adv

    def test_all_pass(self) -> None:
        t = load_thresholds()
        ma, sc, adv = self._make_inputs()
        results = check_gate(ma, sc, adv, t)
        assert all(ok for _, ok, _ in results)

    def test_asr_too_high(self) -> None:
        t = load_thresholds()
        ma, sc, adv = self._make_inputs(asr=0.5)
        results = check_gate(ma, sc, adv, t)
        asr_check = [r for r in results if "asr" in r[0]]
        assert len(asr_check) == 1
        assert asr_check[0][1] is False

    def test_low_triage_rate(self) -> None:
        t = load_thresholds()
        ma, sc, adv = self._make_inputs(triage_rate=0.1)
        results = check_gate(ma, sc, adv, t)
        triage_check = [r for r in results if "triage" in r[0]]
        assert triage_check[0][1] is False

    def test_low_benign_success(self) -> None:
        t = load_thresholds()
        ma, sc, adv = self._make_inputs(benign_success=0.1)
        results = check_gate(ma, sc, adv, t)
        benign_check = [r for r in results if "benign" in r[0]]
        assert benign_check[0][1] is False


class TestGenerateSummary:
    def test_produces_markdown(self) -> None:
        t = load_thresholds()
        ma = {"n": 5, "triage_rate": 1.0, "reply_rate": 1.0, "avg_latency_ms": 50}
        sc = {"n": 10, "pass_at_1": 0.3, "pass_at_k": 0.3}
        adv = {
            "total_injected": 5, "total_benign": 5,
            "injected_blocked": 5, "injected_leaked": 0,
            "asr": 0.0, "benign_answered": 5, "benign_success_rate": 1.0,
        }
        gate = [("test", True, "ok")]
        md = generate_summary(ma, sc, adv, t, gate)
        assert "# Evaluation Summary" in md
        assert "PASS" in md
        assert "ASR" in md

    def test_fail_gate_in_summary(self) -> None:
        t = load_thresholds()
        ma = {"n": 5, "triage_rate": 1.0, "reply_rate": 1.0, "avg_latency_ms": 50}
        sc = {"n": 10, "pass_at_1": 0.3, "pass_at_k": 0.3}
        adv = {
            "total_injected": 5, "total_benign": 5,
            "injected_blocked": 0, "injected_leaked": 5,
            "asr": 1.0, "benign_answered": 0, "benign_success_rate": 0.0,
        }
        gate = [("asr", False, "1.0 > 0.05")]
        md = generate_summary(ma, sc, adv, t, gate)
        assert "FAIL" in md


@pytest.mark.asyncio
async def test_run_report_end_to_end() -> None:
    """Full report run in offline mode."""
    from evals.report import run_report
    code = await run_report(gate=True)
    assert code == 0
    summary = ROOT / "docs" / "results" / "summary.md"
    assert summary.exists()
    content = summary.read_text()
    assert "Evaluation Summary" in content
