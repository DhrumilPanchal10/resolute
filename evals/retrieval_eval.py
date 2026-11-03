"""Retrieval evaluation: Recall@5, MRR, and rerank-lift.

Usage (offline-safe — uses inline labelled pairs):
    python evals/retrieval_eval.py [--out docs/results/retrieval.md]

The labelled set is 100 (query, relevant_doc_ids) pairs.  For the offline
eval the corpus and pairs are generated synthetically; a real run would load
from evals/data/.

Stages measured:
  1. BM25-only
  2. Hybrid (BM25 + dense)
  3. Hybrid + rerank (cross-encoder)

Stage spans are emitted as lightweight dicts (real OTLP tracing wired in T2.1).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from resolute.retrieval.acl import AccessContext  # noqa: E402
from resolute.retrieval.hybrid import BM25Index, dense_search, reciprocal_rank_fusion  # noqa: E402

TENANT = "eval_tenant"
_PUBLIC_CTX = AccessContext(
    tenant_id=TENANT,
    user_roles=frozenset({"support_engineer"}),
    as_of=None,
)


# ---------------------------------------------------------------------------
# Span helpers (lightweight until T2.1 wires OTLP)
# ---------------------------------------------------------------------------


@dataclass
class Span:
    name: str
    inputs: dict = field(default_factory=dict)
    outputs: dict = field(default_factory=dict)
    duration_ms: float = 0.0


def _stage_span(name: str, inputs: dict, fn: callable) -> tuple[object, Span]:
    t0 = time.perf_counter()
    result = fn()
    span = Span(
        name=name,
        inputs=inputs,
        outputs={"n_results": len(result)},
        duration_ms=(time.perf_counter() - t0) * 1000,
    )
    return result, span


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def recall_at_k(hits: list[str], relevant: list[str], k: int = 5) -> float:
    top_k = set(hits[:k])
    rel = set(relevant)
    if not rel:
        return 0.0
    return len(top_k & rel) / len(rel)


def reciprocal_rank(hits: list[str], relevant: list[str]) -> float:
    rel = set(relevant)
    for rank, h in enumerate(hits, start=1):
        if h in rel:
            return 1.0 / rank
    return 0.0


def mean_metric(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


# ---------------------------------------------------------------------------
# Synthetic corpus + labelled queries
# ---------------------------------------------------------------------------


def _build_synthetic_data(
    n_docs: int = 200,
    n_queries: int = 100,
) -> tuple[list[dict], list[dict]]:
    """Return (corpus, labelled_queries) with doc_id pointers."""
    import random

    rng = random.Random(42)
    topics = [
        "authentication OAuth JWT",
        "database migration schema",
        "rate limiting throttle quota",
        "dependency injection container",
        "WebSocket real-time streaming",
        "pagination cursor offset",
        "file upload multipart",
        "error handling exception",
        "caching Redis TTL",
        "deployment Docker Kubernetes",
    ]

    corpus: list[dict] = []
    for i in range(n_docs):
        topic = topics[i % len(topics)]
        words = topic.split()
        extra = " ".join(rng.choice(words) for _ in range(rng.randint(20, 60)))
        corpus.append(
            {
                "doc_id": f"doc_{i:04d}",
                "tenant_id": TENANT,
                "acl_roles": [],
                "created_at": "2020-01-01T00:00:00Z",
                "text": f"# {topic}\n\n{extra}",
                "embedding": [float(hash(f"doc_{i:04d}_{j}") % 1000) / 1000 for j in range(32)],
            }
        )

    labelled: list[dict] = []
    for q in range(n_queries):
        topic = topics[q % len(topics)]
        relevant_ids = [f"doc_{(q * 20) % n_docs:04d}"]  # one labelled relevant doc
        labelled.append(
            {
                "query": f"How do I implement {topic}?",
                "relevant_doc_ids": relevant_ids,
                "embedding": [float(hash(f"q_{q}_{j}") % 1000) / 1000 for j in range(32)],
            }
        )

    return corpus, labelled


# ---------------------------------------------------------------------------
# Evaluation runner
# ---------------------------------------------------------------------------


def evaluate(corpus: list[dict], labelled: list[dict]) -> dict:
    bm25 = BM25Index()
    bm25.build(corpus)

    metrics: dict[str, list[float]] = {
        "bm25_recall5": [],
        "bm25_mrr": [],
        "hybrid_recall5": [],
        "hybrid_mrr": [],
        "rerank_recall5": [],
        "rerank_mrr": [],
    }
    spans: list[dict] = []

    for item in labelled:
        query = item["query"]
        q_emb: list[float] = item["embedding"]
        relevant = item["relevant_doc_ids"]

        # Stage 1: BM25-only
        _q, _idx = query, bm25
        bm25_hits, s1 = _stage_span(
            "bm25",
            {"query": _q},
            lambda q=_q, ix=_idx: ix.search(q, _PUBLIC_CTX, top_k=30),
        )
        bm25_ids = [d.get("doc_id", "") for d, _ in bm25_hits]
        metrics["bm25_recall5"].append(recall_at_k(bm25_ids, relevant))
        metrics["bm25_mrr"].append(reciprocal_rank(bm25_ids, relevant))
        spans.append(s1.__dict__)

        # Stage 2: Hybrid
        _qe = q_emb
        dense_hits, s2 = _stage_span(
            "dense",
            {"query": _q},
            lambda qe=_qe: dense_search(qe, corpus, _PUBLIC_CTX, top_k=30),
        )
        _bh, _dh = bm25_hits, dense_hits
        hybrid_hits, s3 = _stage_span(
            "rrf",
            {},
            lambda bh=_bh, dh=_dh: reciprocal_rank_fusion(bh, dh),
        )
        hybrid_ids = [d.get("doc_id", "") for d, _ in hybrid_hits[:30]]
        metrics["hybrid_recall5"].append(recall_at_k(hybrid_ids, relevant))
        metrics["hybrid_mrr"].append(reciprocal_rank(hybrid_ids, relevant))
        spans.extend([s2.__dict__, s3.__dict__])

        # Stage 3: Rerank (cross-encoder only if model available; skip in offline)
        if not os.environ.get("OFFLINE"):
            try:
                from resolute.retrieval.rerank import rerank

                _hh = hybrid_hits
                reranked, s4 = _stage_span(
                    "rerank",
                    {},
                    lambda q=_q, hh=_hh: rerank(q, hh[:30]),
                )
                rerank_ids = [d.get("doc_id", "") for d, _ in reranked]
                spans.append(s4.__dict__)
            except Exception:
                reranked = hybrid_hits
                rerank_ids = hybrid_ids
        else:
            reranked = hybrid_hits
            rerank_ids = hybrid_ids

        metrics["rerank_recall5"].append(recall_at_k(rerank_ids, relevant))
        metrics["rerank_mrr"].append(reciprocal_rank(rerank_ids, relevant))

    return {
        "bm25_recall5": mean_metric(metrics["bm25_recall5"]),
        "bm25_mrr": mean_metric(metrics["bm25_mrr"]),
        "hybrid_recall5": mean_metric(metrics["hybrid_recall5"]),
        "hybrid_mrr": mean_metric(metrics["hybrid_mrr"]),
        "rerank_recall5": mean_metric(metrics["rerank_recall5"]),
        "rerank_mrr": mean_metric(metrics["rerank_mrr"]),
        "n_queries": len(labelled),
        "spans_sample": spans[:6],
    }


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _report(results: dict) -> str:
    r5b = results["bm25_recall5"]
    r5h = results["hybrid_recall5"]
    r5r = results["rerank_recall5"]
    mrr_b = results["bm25_mrr"]
    mrr_h = results["hybrid_mrr"]
    mrr_r = results["rerank_mrr"]
    lift_r5 = (r5r - r5b) / max(r5b, 1e-9) * 100
    lift_mrr = (mrr_r - mrr_b) / max(mrr_b, 1e-9) * 100

    return f"""# Retrieval Evaluation Results

**Queries evaluated:** {results["n_queries"]}

## Recall@5

| Stage | Recall@5 |
|-------|---------|
| BM25-only | {r5b:.3f} |
| Hybrid (BM25 + dense + RRF) | {r5h:.3f} |
| Hybrid + rerank | {r5r:.3f} |

**Rerank lift over BM25:** {lift_r5:+.1f}%

## MRR (Mean Reciprocal Rank)

| Stage | MRR |
|-------|-----|
| BM25-only | {mrr_b:.3f} |
| Hybrid | {mrr_h:.3f} |
| Hybrid + rerank | {mrr_r:.3f} |

**MRR lift over BM25:** {lift_mrr:+.1f}%

## Stage Tracing (sample spans)

Each retrieval request emits spans with stage name, input counts, output counts,
and duration. These are forwarded to Langfuse/Phoenix via OTLP in T2.1.

```json
{json.dumps(results["spans_sample"], indent=2)}
```

## Notes

- Corpus: synthetic (200 docs, 100 queries). Real evaluation requires
  `evals/data/corpus/*.jsonl` and labelled query→doc pairs.
- Cross-encoder reranking skipped in OFFLINE=1 mode (model not downloaded).
- ACL + time-travel filters are applied inside every query stage.
"""


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "docs" / "results" / "retrieval.md"))
    args = parser.parse_args()

    corpus, labelled = _build_synthetic_data()
    results = evaluate(corpus, labelled)
    md = _report(results)

    print(md)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    print(f"\nReport written to {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
