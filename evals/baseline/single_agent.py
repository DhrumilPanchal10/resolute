#!/usr/bin/env python3
"""Single-agent baseline evaluation.

Runs one strong-model agent per issue using two read-only tools:
  1. keyword_search  — BM25-style keyword search over the corpus,
                        filtered to docs with created_at < issue.created_at
                        (time-travel: no future docs visible)
  2. github_search   — GitHub Issues REST search with the same time filter

Writes one JSONL row per issue to evals/results/baseline_<date>.jsonl.
Row schema: issue_id, answer, citations, input_tokens, output_tokens,
            cost_usd, latency_ms

Usage:
    OFFLINE=0 python evals/baseline/single_agent.py
    python evals/baseline/single_agent.py --issues evals/data/real_issues/issues.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agentcore.cost import RunCost
from agentcore.llm import complete
from resolute.config import settings

ISSUES_PATH = ROOT / "evals" / "data" / "real_issues" / "issues.jsonl"
CORPUS_DIR = ROOT / "evals" / "data" / "corpus"
RESULTS_DIR = ROOT / "evals" / "results"


# ---------------------------------------------------------------------------
# Output schema
# ---------------------------------------------------------------------------


class BaselineRow(BaseModel):
    issue_id: str
    answer: str
    citations: list[str]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float


class AgentAnswer(BaseModel):
    answer: str
    citations: list[str]


# ---------------------------------------------------------------------------
# In-memory corpus index
# ---------------------------------------------------------------------------


class CorpusIndex:
    def __init__(self) -> None:
        self._docs: list[dict] = []

    def load(self) -> None:
        if not CORPUS_DIR.exists():
            return
        for jl in CORPUS_DIR.glob("*.jsonl"):
            with jl.open() as fh:
                for line in fh:
                    if line.strip():
                        self._docs.append(json.loads(line))

    def keyword_search(self, query: str, as_of: str, k: int = 5) -> list[dict]:
        """Return up to k docs with created_at < as_of that contain query terms."""
        terms = set(query.lower().split())
        scored: list[tuple[int, dict]] = []
        for doc in self._docs:
            if doc.get("created_at", "") >= as_of:
                continue
            text = (doc.get("text", "") + " " + doc.get("path", "")).lower()
            hits = sum(1 for t in terms if t in text)
            if hits:
                scored.append((hits, doc))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored[:k]]


# ---------------------------------------------------------------------------
# GitHub search (via REST API with time filter)
# ---------------------------------------------------------------------------


async def _github_search(query: str, as_of: str, k: int = 5) -> list[dict]:
    """Search GitHub Issues created before as_of."""
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        return []
    import httpx

    created_filter = f"created:<{as_of[:10]}"
    q = f"{query} {created_filter} is:issue is:closed"
    url = "https://api.github.com/search/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, headers=headers, params={"q": q, "per_page": k})
        if resp.status_code != 200:
            return []
        items = resp.json().get("items", [])
    return [
        {
            "doc_id": f"github#{item['number']}",
            "text": f"{item['title']}\n{item.get('body','')[:500]}",
            "url": item.get("html_url", ""),
        }
        for item in items[:k]
    ]


# ---------------------------------------------------------------------------
# Single-issue agent
# ---------------------------------------------------------------------------


async def run_agent(
    issue: dict, corpus: CorpusIndex, run_cost: RunCost
) -> BaselineRow:
    issue_id = issue["id"]
    as_of = issue["created_at"]

    # Tool 1: keyword search over corpus
    corpus_hits = corpus.keyword_search(issue["title"] + " " + issue["body"][:300], as_of)
    corpus_context = "\n\n".join(
        f"[{d['doc_id']}] {d['text'][:600]}" for d in corpus_hits
    )

    # Tool 2: GitHub search with time filter
    gh_hits = await _github_search(issue["title"], as_of)
    gh_context = "\n\n".join(
        f"[{d['doc_id']}] {d['text']}" for d in gh_hits
    )

    all_citations = [d["doc_id"] for d in corpus_hits] + [d["doc_id"] for d in gh_hits]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a support engineer. "
                "Answer the customer issue using ONLY the provided context. "
                "Cite the doc_id of every source you use. "
                "If the context is insufficient, say so."
            ),
        },
        {
            "role": "user",
            "content": (
                f"# Issue\n{issue['title']}\n\n{issue['body'][:1000]}\n\n"
                f"# Corpus context\n{corpus_context or '(none)'}\n\n"
                f"# GitHub context\n{gh_context or '(none)'}"
            ),
        },
    ]

    t0 = time.perf_counter()
    result: AgentAnswer = await complete(
        messages,
        schema=AgentAnswer,
        model_tier="strong",
        run_cost=run_cost,
    )
    latency_ms = (time.perf_counter() - t0) * 1000

    last = run_cost.calls[-1] if run_cost.calls else None
    return BaselineRow(
        issue_id=issue_id,
        answer=result.answer,
        citations=result.citations or all_citations[:5],
        input_tokens=last.input_tokens if last else 0,
        output_tokens=last.output_tokens if last else 0,
        cost_usd=last.cost_usd if last else 0.0,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(issues_path: Path) -> None:
    if not issues_path.exists():
        sys.exit(f"Issues file not found: {issues_path}\nRun scripts/collect_issues.py first.")

    corpus = CorpusIndex()
    corpus.load()

    issues: list[dict] = []
    with issues_path.open() as fh:
        for line in fh:
            if line.strip():
                issues.append(json.loads(line))

    if not issues:
        sys.exit("No issues found in the JSONL file.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y%m%d")
    out_path = RESULTS_DIR / f"baseline_{date_str}.jsonl"

    run_cost = RunCost()
    rows: list[BaselineRow] = []
    for i, issue in enumerate(issues):
        print(f"[{i+1}/{len(issues)}] {issue['id']}")
        row = await run_agent(issue, corpus, run_cost)
        rows.append(row)
        # Stream results as they complete
        with out_path.open("a") as fh:
            fh.write(row.model_dump_json() + "\n")

    print(f"\nDone. {len(rows)} answers → {out_path}")
    print(
        f"Total cost: ${run_cost.total_cost_usd:.4f}  "
        f"tokens: {run_cost.total_input_tokens}in/{run_cost.total_output_tokens}out"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--issues",
        default=str(ISSUES_PATH),
        help="Path to issues.jsonl",
    )
    args = parser.parse_args()
    asyncio.run(run(Path(args.issues)))


if __name__ == "__main__":
    main()
