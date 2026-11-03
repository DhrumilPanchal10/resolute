"""Hybrid BM25 + dense retrieval with reciprocal rank fusion (RRF).

BM25 is kept per-tenant in memory (re-built from corpus on demand).
Dense retrieval runs against a list of pre-embedded documents (pgvector
would replace the in-memory list in production, but the same interface works).

Reciprocal Rank Fusion:
    score(doc, rank) = 1 / (K + rank)   K = 60 (standard)
    final = sum over all ranking lists
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from resolute.retrieval.acl import AccessContext, filter_docs

RRF_K: int = 60
DEFAULT_TOP_K: int = 30  # candidates sent to reranker


@dataclass
class BM25Index:
    """In-memory BM25 index wrapping bm25s.

    build() must be called before search().
    """

    _corpus: list[dict] = field(default_factory=list, repr=False)
    _retriever: object = field(default=None, repr=False)

    def build(self, docs: list[dict], *, text_key: str = "text") -> None:
        import bm25s

        self._corpus = list(docs)
        texts = [d.get(text_key, "") for d in self._corpus]
        tokenized = bm25s.tokenize(texts, stopwords="en")
        retriever = bm25s.BM25()
        retriever.index(tokenized)
        self._retriever = retriever

    def search(
        self,
        query: str,
        ctx: AccessContext,
        *,
        top_k: int = DEFAULT_TOP_K,
        text_key: str = "text",
    ) -> list[tuple[dict, float]]:
        """Return (doc, bm25_score) pairs after ACL/time-travel filter."""
        if self._retriever is None or not self._corpus:
            return []
        import bm25s

        tokenized_query = bm25s.tokenize(query, stopwords="en")
        # Retrieve more than top_k to allow for ACL filtering
        fetch = min(len(self._corpus), top_k * 4)
        results, scores = self._retriever.retrieve(tokenized_query, k=fetch)

        pairs: list[tuple[dict, float]] = []
        for idx, score in zip(results[0], scores[0], strict=False):
            doc = self._corpus[int(idx)]
            pairs.append((doc, float(score)))

        # Apply ACL + time-travel after retrieval
        filtered = [(doc, score) for doc, score in pairs if filter_docs([doc], ctx)]
        return filtered[:top_k]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def dense_search(
    query_embedding: list[float],
    docs: list[dict],
    ctx: AccessContext,
    *,
    top_k: int = DEFAULT_TOP_K,
    embedding_key: str = "embedding",
) -> list[tuple[dict, float]]:
    """Return top-k docs by cosine similarity after ACL/time-travel filter.

    In production this would be a pgvector HNSW query; this pure-Python
    implementation serves unit tests and offline mode.
    """
    visible = filter_docs(docs, ctx)
    scored: list[tuple[dict, float]] = []
    for doc in visible:
        emb = doc.get(embedding_key)
        if emb is None:
            continue
        sim = cosine_similarity(query_embedding, emb)
        scored.append((doc, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def reciprocal_rank_fusion(
    *ranked_lists: list[tuple[dict, float]],
    id_key: str = "doc_id",
    k: int = RRF_K,
) -> list[tuple[dict, float]]:
    """Fuse multiple ranked lists with RRF and return a merged ranking."""
    scores: dict[str, float] = {}
    doc_by_id: dict[str, dict] = {}

    for ranked in ranked_lists:
        for rank, (doc, _) in enumerate(ranked, start=1):
            doc_id = doc.get(id_key, id(doc))
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            doc_by_id[str(doc_id)] = doc

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(doc_by_id[str(doc_id)], score) for doc_id, score in merged]


def hybrid_search(
    query: str,
    query_embedding: list[float],
    docs: list[dict],
    bm25_index: BM25Index,
    ctx: AccessContext,
    *,
    top_k: int = DEFAULT_TOP_K,
) -> list[tuple[dict, float]]:
    """Combined BM25 + dense → RRF."""
    bm25_hits = bm25_index.search(query, ctx, top_k=top_k)
    dense_hits = dense_search(query_embedding, docs, ctx, top_k=top_k)
    return reciprocal_rank_fusion(bm25_hits, dense_hits)[:top_k]
