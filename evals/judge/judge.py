#!/usr/bin/env python3
"""LLM judge for the Resolute baseline evaluation.

Compares each agent answer to the ground-truth resolution_text and
outputs a structured verdict: {correct, partial, reason}.

Usage (called from evals/report.py or directly):
    python evals/judge/judge.py --results evals/results/baseline_<date>.jsonl \
                                 --issues  evals/data/real_issues/issues.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcore.cost import RunCost
from agentcore.llm import complete

ISSUES_PATH = ROOT / "evals" / "data" / "real_issues" / "issues.jsonl"


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class Verdict(BaseModel):
    correct: bool
    partial: bool
    reason: str


class JudgedRow(BaseModel):
    issue_id: str
    correct: bool
    partial: bool
    reason: str


# ---------------------------------------------------------------------------
# Judge prompt
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are an expert evaluator for a customer support AI system.
You will be given:
  - A customer issue (title + body)
  - The ground-truth resolution written by a maintainer
  - The AI agent's answer

Evaluate whether the AI answer correctly resolves the issue.
Output a JSON object with:
  "correct": true if the answer is fully correct and actionable
  "partial": true if the answer is partially correct or on the right track
  "reason": one sentence explaining your verdict (reference specific details)

Be strict: vague answers or answers that miss the key fix are NOT correct.
"""


async def judge_one(
    issue: dict,
    answer: str,
    run_cost: RunCost,
) -> Verdict:
    messages = [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": (
                f"## Issue\n{issue['title']}\n\n{issue['body'][:800]}\n\n"
                f"## Ground-truth resolution\n{issue['resolution_text'][:800]}\n\n"
                f"## AI answer\n{answer[:800]}"
            ),
        },
    ]
    return await complete(messages, schema=Verdict, model_tier="judge", run_cost=run_cost)  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(results_path: Path, issues_path: Path) -> list[JudgedRow]:
    if not results_path.exists():
        sys.exit(f"Results file not found: {results_path}")
    if not issues_path.exists():
        sys.exit(f"Issues file not found: {issues_path}")

    issues: dict[str, dict] = {}
    with issues_path.open() as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                issues[row["id"]] = row

    out_path = results_path.parent / results_path.name.replace("baseline_", "judged_")
    run_cost = RunCost()
    judged: list[JudgedRow] = []

    with results_path.open() as fh:
        result_lines = [json.loads(l) for l in fh if l.strip()]

    for i, result in enumerate(result_lines):
        issue_id = result["issue_id"]
        issue = issues.get(issue_id)
        if not issue:
            print(f"  [WARN] issue {issue_id} not found in issues file — skipping")
            continue
        print(f"[{i+1}/{len(result_lines)}] judging {issue_id}…")
        verdict = await judge_one(issue, result["answer"], run_cost)
        judged.append(JudgedRow(issue_id=issue_id, **verdict.model_dump()))

    with out_path.open("w") as fh:
        for row in judged:
            fh.write(row.model_dump_json() + "\n")

    print(f"\nJudged {len(judged)} answers → {out_path}")
    print(f"Judge cost: ${run_cost.total_cost_usd:.4f}")
    return judged


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, help="Baseline JSONL results file")
    parser.add_argument("--issues", default=str(ISSUES_PATH))
    args = parser.parse_args()
    asyncio.run(run(Path(args.results), Path(args.issues)))


if __name__ == "__main__":
    main()
