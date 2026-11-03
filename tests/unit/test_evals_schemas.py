"""Offline schema + logic tests for the eval pipeline (T1.1, T1.2, T1.4, T1.5).

No API calls, no JSONL files from production — all data is inline fixtures.
"""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# T1.1 — IssueRow schema validation
# ---------------------------------------------------------------------------


class TestIssueRowSchema:
    def _valid(self) -> dict:
        return {
            "id": "tiangolo/fastapi#1234",
            "repo": "tiangolo/fastapi",
            "title": "Dependency injection broken",
            "body": "When I do X, Y happens.",
            "created_at": "2023-01-15T10:00:00Z",
            "closed_at": "2023-01-16T12:00:00Z",
            "resolution_text": "This is fixed in v0.95.0 — upgrade.",
            "resolution_url": "https://github.com/tiangolo/fastapi/issues/1234#issuecomment-999",
            "labels": ["bug", "dependencies"],
        }

    def test_valid_row_accepted(self) -> None:
        from scripts.collect_issues import IssueRow

        row = IssueRow(**self._valid())
        assert row.repo == "tiangolo/fastapi"
        assert row.labels == ["bug", "dependencies"]

    @pytest.mark.parametrize("empty_field", ["id", "repo", "title", "created_at", "closed_at"])
    def test_empty_required_field_rejected(self, empty_field: str) -> None:
        from scripts.collect_issues import IssueRow

        data = self._valid()
        data[empty_field] = ""
        with pytest.raises(ValidationError):
            IssueRow(**data)

    def test_missing_field_rejected(self) -> None:
        from scripts.collect_issues import IssueRow

        data = self._valid()
        del data["resolution_text"]
        with pytest.raises(ValidationError):
            IssueRow(**data)

    def test_serialises_to_json(self) -> None:
        from scripts.collect_issues import IssueRow
        import json

        row = IssueRow(**self._valid())
        parsed = json.loads(row.model_dump_json())
        assert parsed["id"] == row.id


# ---------------------------------------------------------------------------
# T1.2 — CorpusRow schema validation
# ---------------------------------------------------------------------------


class TestCorpusRowSchema:
    def _valid(self) -> dict:
        return {
            "doc_id": "tiangolo/fastapi::docs/tutorial/dependencies.md",
            "repo": "tiangolo/fastapi",
            "path": "docs/tutorial/dependencies.md",
            "text": "# Dependencies\n\nFastAPI provides a simple dependency injection system.",
            "created_at": "2021-03-10T08:00:00+00:00",
        }

    def test_valid_row_accepted(self) -> None:
        from scripts.collect_corpus import CorpusRow

        row = CorpusRow(**self._valid())
        assert row.doc_id.startswith("tiangolo/fastapi")

    def test_has_all_required_fields(self) -> None:
        from scripts.collect_corpus import CorpusRow

        row = CorpusRow(**self._valid())
        assert all(
            getattr(row, f) for f in ("doc_id", "repo", "path", "text", "created_at")
        )


# ---------------------------------------------------------------------------
# T1.4 — CorpusIndex keyword search (time-travel filter)
# ---------------------------------------------------------------------------


class TestCorpusIndex:
    def _build_index(self) -> "object":
        from evals.baseline.single_agent import CorpusIndex

        idx = CorpusIndex()
        # Inject docs directly (bypass file I/O)
        idx._docs = [
            {
                "doc_id": "repo::old_doc.md",
                "text": "FastAPI dependency injection tutorial",
                "created_at": "2021-01-01T00:00:00Z",
            },
            {
                "doc_id": "repo::new_doc.md",
                "text": "FastAPI dependency injection new feature",
                "created_at": "2024-01-01T00:00:00Z",
            },
        ]
        return idx

    def test_time_travel_excludes_future_docs(self) -> None:
        from evals.baseline.single_agent import CorpusIndex

        idx = self._build_index()
        # issue created 2022 — only old_doc.md should be visible
        results = idx.keyword_search("FastAPI dependency injection", as_of="2022-06-01T00:00:00Z")
        ids = [r["doc_id"] for r in results]
        assert "repo::old_doc.md" in ids
        assert "repo::new_doc.md" not in ids

    def test_returns_empty_when_all_future(self) -> None:
        from evals.baseline.single_agent import CorpusIndex

        idx = self._build_index()
        results = idx.keyword_search("FastAPI", as_of="2020-01-01T00:00:00Z")
        assert results == []

    def test_top_k_respected(self) -> None:
        from evals.baseline.single_agent import CorpusIndex

        idx = CorpusIndex()
        idx._docs = [
            {"doc_id": f"d{i}", "text": "keyword match", "created_at": "2020-01-01T00:00:00Z"}
            for i in range(10)
        ]
        results = idx.keyword_search("keyword", as_of="2023-01-01T00:00:00Z", k=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# T1.5 — Verdict schema + report generation
# ---------------------------------------------------------------------------


class TestVerdictSchema:
    def test_valid_verdict(self) -> None:
        from evals.judge.judge import Verdict

        v = Verdict(correct=True, partial=False, reason="Answer matches the fix exactly.")
        assert v.correct is True

    def test_partial_without_correct(self) -> None:
        from evals.judge.judge import Verdict

        v = Verdict(correct=False, partial=True, reason="Partially correct but misses key step.")
        assert v.partial is True


class TestReportGeneration:
    def _make_files(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        results_path = tmp_path / "baseline_20260101.jsonl"
        judged_path = tmp_path / "judged_20260101.jsonl"
        issues_path = tmp_path / "issues.jsonl"

        import json

        # 3 baseline rows
        for i in range(3):
            row = {
                "issue_id": f"repo#10{i}",
                "answer": f"answer {i}",
                "citations": [],
                "input_tokens": 100,
                "output_tokens": 50,
                "cost_usd": 0.001,
                "latency_ms": 500.0,
            }
            with results_path.open("a") as f:
                f.write(json.dumps(row) + "\n")

        for i, (correct, partial) in enumerate([(True, False), (False, True), (False, False)]):
            row = {
                "issue_id": f"repo#10{i}",
                "correct": correct,
                "partial": partial,
                "reason": f"reason {i}",
            }
            with judged_path.open("a") as f:
                f.write(json.dumps(row) + "\n")

        for i in range(3):
            row = {
                "id": f"repo#10{i}",
                "repo": "repo",
                "title": f"Issue {i}",
                "body": "body",
                "created_at": "2026-01-01T00:00:00Z",
                "closed_at": "2026-01-02T00:00:00Z",
                "resolution_text": f"fix {i}",
                "resolution_url": "https://example.com",
                "labels": [],
            }
            with issues_path.open("a") as f:
                f.write(json.dumps(row) + "\n")

        return results_path, judged_path, issues_path

    def test_report_contains_accuracy(self, tmp_path: Path) -> None:
        from evals.report import generate

        rp, jp, ip = self._make_files(tmp_path)
        md = generate(rp, jp, ip)
        assert "Accuracy" in md
        assert "1/3" in md  # 1 correct out of 3

    def test_report_contains_efficiency(self, tmp_path: Path) -> None:
        from evals.report import generate

        rp, jp, ip = self._make_files(tmp_path)
        md = generate(rp, jp, ip)
        assert "tokens" in md.lower()
        assert "latency" in md.lower()
