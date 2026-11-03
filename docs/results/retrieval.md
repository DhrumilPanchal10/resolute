# Retrieval Evaluation Results

**Queries evaluated:** 100

## Recall@5

| Stage | Recall@5 |
|-------|---------|
| BM25-only | 0.100 |
| Hybrid (BM25 + dense + RRF) | 0.090 |
| Hybrid + rerank | 0.090 |

**Rerank lift over BM25:** -10.0%

## MRR (Mean Reciprocal Rank)

| Stage | MRR |
|-------|-----|
| BM25-only | 0.104 |
| Hybrid | 0.053 |
| Hybrid + rerank | 0.053 |

**MRR lift over BM25:** -49.6%

## Stage Tracing (sample spans)

Each retrieval request emits spans with stage name, input counts, output counts,
and duration. These are forwarded to Langfuse/Phoenix via OTLP in T2.1.

```json
[
  {
    "name": "bm25",
    "inputs": {
      "query": "How do I implement authentication OAuth JWT?"
    },
    "outputs": {
      "n_results": 30
    },
    "duration_ms": 0.5652920008287765
  },
  {
    "name": "dense",
    "inputs": {
      "query": "How do I implement authentication OAuth JWT?"
    },
    "outputs": {
      "n_results": 30
    },
    "duration_ms": 1.1935839938814752
  },
  {
    "name": "rrf",
    "inputs": {},
    "outputs": {
      "n_results": 55
    },
    "duration_ms": 0.03854199894703925
  },
  {
    "name": "bm25",
    "inputs": {
      "query": "How do I implement database migration schema?"
    },
    "outputs": {
      "n_results": 30
    },
    "duration_ms": 0.4448749969014898
  },
  {
    "name": "dense",
    "inputs": {
      "query": "How do I implement database migration schema?"
    },
    "outputs": {
      "n_results": 30
    },
    "duration_ms": 1.1320420017000288
  },
  {
    "name": "rrf",
    "inputs": {},
    "outputs": {
      "n_results": 55
    },
    "duration_ms": 0.033042000723071396
  }
]
```

## Notes

- Corpus: synthetic (200 docs, 100 queries). Real evaluation requires
  `evals/data/corpus/*.jsonl` and labelled query→doc pairs.
- Cross-encoder reranking skipped in OFFLINE=1 mode (model not downloaded).
- ACL + time-travel filters are applied inside every query stage.
