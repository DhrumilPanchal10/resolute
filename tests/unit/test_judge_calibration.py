"""Tests for evals/judge/calibrate.py and gold_labels.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from evals.judge.gold_labels import GOLD_LABELS, GoldLabel


class TestGoldLabels:
    def test_count(self) -> None:
        assert len(GOLD_LABELS) == 50

    def test_ids_unique(self) -> None:
        ids = [g.id for g in GOLD_LABELS]
        assert len(ids) == len(set(ids))

    def test_distribution(self) -> None:
        correct = sum(1 for g in GOLD_LABELS if g.human_correct)
        partial = sum(1 for g in GOLD_LABELS if g.human_partial and not g.human_correct)
        wrong = sum(1 for g in GOLD_LABELS if not g.human_correct and not g.human_partial)
        assert correct == 20
        assert partial == 15
        assert wrong == 15

    def test_all_have_reasons(self) -> None:
        for g in GOLD_LABELS:
            assert len(g.human_reason) > 10, f"{g.id} missing reason"

    def test_all_have_answers(self) -> None:
        for g in GOLD_LABELS:
            assert len(g.agent_answer) > 10, f"{g.id} missing answer"


class TestMetrics:
    def test_cohens_kappa_perfect(self) -> None:
        from evals.judge.calibrate import _cohens_kappa
        results = [
            {"human": "correct", "judge": "correct"},
            {"human": "partial", "judge": "partial"},
            {"human": "wrong", "judge": "wrong"},
        ]
        assert _cohens_kappa(results) == pytest.approx(1.0)

    def test_cohens_kappa_zero(self) -> None:
        from evals.judge.calibrate import _cohens_kappa
        results = [
            {"human": "correct", "judge": "wrong"},
            {"human": "wrong", "judge": "correct"},
        ]
        k = _cohens_kappa(results)
        assert k <= 0.0

    def test_compute_metrics_structure(self) -> None:
        from evals.judge.calibrate import compute_metrics
        results = [
            {"id": "1", "human": "correct", "judge": "correct", "agree": True,
             "human_reason": "ok", "judge_reason": "ok"},
            {"id": "2", "human": "partial", "judge": "wrong", "agree": False,
             "human_reason": "ok", "judge_reason": "bad"},
        ]
        m = compute_metrics(results)
        assert m["n"] == 2
        assert m["agreement"] == 0.5
        assert "confusion" in m
        assert "per_class" in m
        assert m["confusion"]["correct"]["correct"] == 1
        assert m["confusion"]["partial"]["wrong"] == 1


class TestReport:
    def test_generate_report(self) -> None:
        from evals.judge.calibrate import compute_metrics, generate_report
        results = [
            {"id": f"g-{i}", "human": "correct", "judge": "correct",
             "agree": True, "human_reason": "ok", "judge_reason": "ok"}
            for i in range(10)
        ]
        m = compute_metrics(results)
        md = generate_report(m)
        assert "Judge Calibration Report" in md
        assert "Agreement" in md
        assert "Confusion Matrix" in md


@pytest.mark.asyncio
async def test_calibration_end_to_end() -> None:
    """Run full calibration in offline mode."""
    from evals.judge.calibrate import run_calibration
    metrics = await run_calibration()
    assert metrics["n"] == 50
    assert 0.0 <= metrics["agreement"] <= 1.0
    assert -1.0 <= metrics["kappa"] <= 1.0
    assert metrics["agreement"] >= 0.70  # offline canned should get decent agreement
