#!/usr/bin/env python3
"""Generate a Markdown report from baseline + judge results.

Prints to stdout and writes docs/results/baseline.md.

Usage:
    python evals/report.py \
        --results  evals/results/baseline_<date>.jsonl \
        --judged   evals/results/judged_<date>.jsonl \
        --issues   evals/data/real_issues/issues.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DOCS_RESULTS = ROOT / "docs" / "results"


def _load_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open() as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def generate(
    results_path: Path,
    judged_path: Path,
    issues_path: Path,
    run_name: str = "baseline",
) -> str:
    results = {r["issue_id"]: r for r in _load_jsonl(results_path)}
    judged = {r["issue_id"]: r for r in _load_jsonl(judged_path)}
    n = len(results)
    if n == 0:
        sys.exit("No results to report.")

    correct = sum(1 for r in judged.values() if r.get("correct"))
    partial = sum(1 for r in judged.values() if r.get("partial") and not r.get("correct"))
    wrong = len(judged) - correct - partial

    accuracy = correct / len(judged) if judged else 0.0
    partial_rate = (correct + partial) / len(judged) if judged else 0.0

    avg_tokens_in = sum(r.get("input_tokens", 0) for r in results.values()) / n
    avg_tokens_out = sum(r.get("output_tokens", 0) for r in results.values()) / n
    avg_latency = sum(r.get("latency_ms", 0) for r in results.values()) / n
    avg_cost = sum(r.get("cost_usd", 0.0) for r in results.values()) / n
    total_cost = sum(r.get("cost_usd", 0.0) for r in results.values())

    date_str = results_path.stem.replace("baseline_", "")

    md = f"""# Baseline Evaluation Results

**Run date:** {date_str}
**Agent:** single-agent (one strong-model call + keyword search + GitHub search)
**Issues:** {n}

## Accuracy

| Metric | Value |
|--------|-------|
| Correct | {correct}/{len(judged)} ({accuracy:.1%}) |
| Partial (correct + partial) | {correct + partial}/{len(judged)} ({partial_rate:.1%}) |
| Wrong | {wrong}/{len(judged)} |

## Efficiency (per answer)

| Metric | Value |
|--------|-------|
| Avg input tokens | {avg_tokens_in:.0f} |
| Avg output tokens | {avg_tokens_out:.0f} |
| Avg latency | {avg_latency:.0f} ms |
| Avg cost | ${avg_cost:.4f} |
| Total cost | ${total_cost:.4f} |

## Sample Verdicts

| Issue | Correct | Partial | Reason |
|-------|---------|---------|--------|
"""
    sample = list(judged.values())[:10]
    for row in sample:
        reason = row.get("reason", "")[:80].replace("|", "\\|")
        md += (
            f"| {row['issue_id']} "
            f"| {'✓' if row.get('correct') else '✗'} "
            f"| {'✓' if row.get('partial') else '✗'} "
            f"| {reason} |\n"
        )

    md += f"""
## Notes

- Corpus time-travel filter applied: docs with `created_at >= issue.created_at` excluded.
- Judge model: `{run_name}` (see `.env` → `MODEL_JUDGE`).
- This is the **first benchmark**. Multi-agent system results will be compared here in T7.1.
"""
    return md


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True)
    parser.add_argument("--judged", required=True)
    parser.add_argument("--issues", default=str(ROOT / "evals" / "data" / "real_issues" / "issues.jsonl"))
    parser.add_argument("--name", default="baseline")
    args = parser.parse_args()

    md = generate(Path(args.results), Path(args.judged), Path(args.issues), args.name)
    print(md)

    DOCS_RESULTS.mkdir(parents=True, exist_ok=True)
    out = DOCS_RESULTS / "baseline.md"
    out.write_text(md)
    print(f"\nReport written to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
