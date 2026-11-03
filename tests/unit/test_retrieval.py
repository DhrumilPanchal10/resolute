"""Offline unit tests for Phase 3 retrieval (T3.1–T3.4).

No network, no ML models loaded — embed.py and rerank.py are mocked.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT / "src"))


# ---------------------------------------------------------------------------
# T3.1 — Chunking
# ---------------------------------------------------------------------------


class TestChunking:
    def test_empty_returns_no_chunks(self) -> None:
        from resolute.retrieval.chunking import chunk_document

        assert chunk_document(doc_id="x", text="") == []
        assert chunk_document(doc_id="x", text="   \n  ") == []

    def test_short_text_is_single_chunk(self) -> None:
        from resolute.retrieval.chunking import chunk_document

        chunks = chunk_document(doc_id="d1", text="# Hello\n\nShort body.")
        assert len(chunks) == 1
        assert "Short body." in chunks[0].text

    def test_long_text_splits_into_multiple(self) -> None:
        from resolute.retrieval.chunking import MAX_CHARS, chunk_document

        long_body = "word " * (MAX_CHARS // 5 + 50)
        chunks = chunk_document(doc_id="d2", text=long_body)
        assert len(chunks) > 1

    def test_no_chunk_exceeds_max_chars(self) -> None:
        from resolute.retrieval.chunking import MAX_CHARS, chunk_document

        # Allow slight overshoot from overlap prepending (≤ MAX_CHARS + OVERLAP_CHARS)
        from resolute.retrieval.chunking import OVERLAP_CHARS

        long_body = "x " * (MAX_CHARS // 2 + 100)
        chunks = chunk_document(doc_id="d3", text=long_body)
        for c in chunks:
            assert len(c.text) <= MAX_CHARS + OVERLAP_CHARS

    def test_heading_path_captured(self) -> None:
        from resolute.retrieval.chunking import chunk_document

        md = "# Guide\n\n## Installation\n\nRun pip install.\n\n## Usage\n\nImport the module."
        chunks = chunk_document(doc_id="d4", text=md)
        paths = [c.heading_path for c in chunks]
        assert any("Installation" in p for p in paths)
        assert any("Usage" in p for p in paths)

    def test_metadata_propagated(self) -> None:
        from resolute.retrieval.chunking import chunk_document

        chunks = chunk_document(
            doc_id="d5",
            text="Hello world body text.",
            tenant_id="acme",
            acl_roles=["admin"],
            created_at="2024-01-01",
            docs_version="v2",
        )
        assert len(chunks) == 1
        c = chunks[0]
        assert c.tenant_id == "acme"
        assert c.acl_roles == ["admin"]
        assert c.created_at == "2024-01-01"
        assert c.docs_version == "v2"

    def test_chunk_index_sequential(self) -> None:
        from resolute.retrieval.chunking import MAX_CHARS, chunk_document

        long_body = "y " * (MAX_CHARS // 2 + 200)
        chunks = chunk_document(doc_id="d6", text=long_body)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_estimated_tokens(self) -> None:
        from resolute.retrieval.chunking import CHARS_PER_TOKEN, chunk_document

        text = "a" * 400
        chunks = chunk_document(doc_id="d7", text=text)
        assert chunks[0].estimated_tokens() == 400 // CHARS_PER_TOKEN


# ---------------------------------------------------------------------------
# T3.1 — ACL + time-travel (acl.py)
# ---------------------------------------------------------------------------


class TestACL:
    def _doc(self, **kw) -> dict:
        base = {
            "doc_id": "x",
            "tenant_id": "t1",
            "acl_roles": [],
            "created_at": "2020-01-01T00:00:00Z",
        }
        base.update(kw)
        return base

    def _ctx(self, **kw):
        from resolute.retrieval.acl import AccessContext

        base = dict(tenant_id="t1", user_roles=frozenset({"support_engineer"}), as_of=None)
        base.update(kw)
        return AccessContext(**base)

    def test_same_tenant_visible(self) -> None:
        from resolute.retrieval.acl import is_visible

        assert is_visible(
            doc_tenant_id="t1",
            doc_acl_roles=[],
            doc_created_at="2020-01-01T00:00:00Z",
            ctx=self._ctx(),
        )

    def test_different_tenant_hidden(self) -> None:
        from resolute.retrieval.acl import is_visible

        assert not is_visible(
            doc_tenant_id="t2",
            doc_acl_roles=[],
            doc_created_at="2020-01-01T00:00:00Z",
            ctx=self._ctx(),
        )

    def test_acl_role_match_visible(self) -> None:
        from resolute.retrieval.acl import is_visible

        assert is_visible(
            doc_tenant_id="t1",
            doc_acl_roles=["admin", "support_engineer"],
            doc_created_at="2020-01-01T00:00:00Z",
            ctx=self._ctx(user_roles=frozenset({"support_engineer"})),
        )

    def test_acl_role_mismatch_hidden(self) -> None:
        from resolute.retrieval.acl import is_visible

        assert not is_visible(
            doc_tenant_id="t1",
            doc_acl_roles=["admin"],
            doc_created_at="2020-01-01T00:00:00Z",
            ctx=self._ctx(user_roles=frozenset({"support_engineer"})),
        )

    def test_time_travel_excludes_future_doc(self) -> None:
        from resolute.retrieval.acl import is_visible

        as_of = datetime(2021, 1, 1, tzinfo=timezone.utc)
        assert not is_visible(
            doc_tenant_id="t1",
            doc_acl_roles=[],
            doc_created_at="2022-01-01T00:00:00Z",
            ctx=self._ctx(as_of=as_of),
        )

    def test_time_travel_includes_past_doc(self) -> None:
        from resolute.retrieval.acl import is_visible

        as_of = datetime(2023, 1, 1, tzinfo=timezone.utc)
        assert is_visible(
            doc_tenant_id="t1",
            doc_acl_roles=[],
            doc_created_at="2020-01-01T00:00:00Z",
            ctx=self._ctx(as_of=as_of),
        )

    def test_filter_docs_removes_cross_tenant(self) -> None:
        from resolute.retrieval.acl import filter_docs

        docs = [
            self._doc(tenant_id="t1"),
            self._doc(tenant_id="t2"),
        ]
        result = filter_docs(docs, self._ctx())
        assert len(result) == 1
        assert result[0]["tenant_id"] == "t1"

    def test_forbidden_doc_never_returned(self) -> None:
        """T3.2 requirement: forbidden doc never returned even if top match."""
        from resolute.retrieval.acl import filter_docs

        docs = [
            self._doc(doc_id="secret", tenant_id="t1", acl_roles=["admin"]),
            self._doc(doc_id="public", tenant_id="t1", acl_roles=[]),
        ]
        ctx = self._ctx(user_roles=frozenset({"support_engineer"}))
        result = filter_docs(docs, ctx)
        ids = [d["doc_id"] for d in result]
        assert "secret" not in ids
        assert "public" in ids


# ---------------------------------------------------------------------------
# T3.2 — Hybrid search (BM25 + dense + RRF)
# ---------------------------------------------------------------------------


class TestHybridSearch:
    def _corpus(self, n: int = 10) -> list[dict]:
        docs = []
        for i in range(n):
            docs.append({
                "doc_id": f"doc_{i}",
                "tenant_id": "t1",
                "acl_roles": [],
                "created_at": "2020-01-01T00:00:00Z",
                "text": f"document about topic_{i} and content_{i}",
                "embedding": [1.0 if j == i % 8 else 0.0 for j in range(8)],
            })
        return docs

    def _ctx(self):
        from resolute.retrieval.acl import AccessContext
        return AccessContext(tenant_id="t1", user_roles=frozenset({"support_engineer"}))

    def test_bm25_returns_matching_docs(self) -> None:
        from resolute.retrieval.hybrid import BM25Index

        corpus = self._corpus()
        idx = BM25Index()
        idx.build(corpus)
        results = idx.search("topic_3 content_3", self._ctx())
        ids = [d["doc_id"] for d, _ in results]
        assert "doc_3" in ids

    def test_bm25_acl_hides_forbidden(self) -> None:
        from resolute.retrieval.acl import AccessContext
        from resolute.retrieval.hybrid import BM25Index

        corpus = self._corpus()
        corpus[0]["acl_roles"] = ["admin"]
        idx = BM25Index()
        idx.build(corpus)
        ctx = AccessContext(tenant_id="t1", user_roles=frozenset({"support_engineer"}))
        results = idx.search("document topic_0", ctx)
        ids = [d["doc_id"] for d, _ in results]
        assert "doc_0" not in ids

    def test_bm25_cross_tenant_hidden(self) -> None:
        from resolute.retrieval.acl import AccessContext
        from resolute.retrieval.hybrid import BM25Index

        corpus = self._corpus()
        corpus[1]["tenant_id"] = "other_tenant"
        idx = BM25Index()
        idx.build(corpus)
        ctx = AccessContext(tenant_id="t1", user_roles=frozenset())
        results = idx.search("document topic_1", ctx)
        ids = [d["doc_id"] for d, _ in results]
        assert "doc_1" not in ids

    def test_dense_returns_closest(self) -> None:
        from resolute.retrieval.hybrid import dense_search

        corpus = self._corpus()
        # query embedding matches doc_3 exactly (position 3 of 8)
        q_emb = [1.0 if j == 3 else 0.0 for j in range(8)]
        ctx = self._ctx()
        results = dense_search(q_emb, corpus, ctx, top_k=5)
        ids = [d["doc_id"] for d, _ in results]
        assert ids[0] == "doc_3"

    def test_rrf_merges_lists(self) -> None:
        from resolute.retrieval.hybrid import reciprocal_rank_fusion

        list_a = [
            ({"doc_id": "a"}, 1.0),
            ({"doc_id": "b"}, 0.5),
        ]
        list_b = [
            ({"doc_id": "b"}, 0.9),
            ({"doc_id": "c"}, 0.1),
        ]
        merged = reciprocal_rank_fusion(list_a, list_b)
        ids = [d["doc_id"] for d, _ in merged]
        # "b" appears in both lists — should rank high
        assert ids[0] == "b"

    def test_hybrid_search_combines_both(self) -> None:
        from resolute.retrieval.hybrid import BM25Index, hybrid_search

        corpus = self._corpus()
        idx = BM25Index()
        idx.build(corpus)
        q_emb = [1.0 if j == 2 else 0.0 for j in range(8)]
        ctx = self._ctx()
        results = hybrid_search("topic_2", q_emb, corpus, idx, ctx, top_k=5)
        assert len(results) > 0
        ids = [d["doc_id"] for d, _ in results]
        # doc_2 is relevant to both query text and embedding
        assert "doc_2" in ids


# ---------------------------------------------------------------------------
# T3.4 — Retrieval eval metrics
# ---------------------------------------------------------------------------


class TestRetrievalMetrics:
    def test_recall_at_k_perfect(self) -> None:
        from evals.retrieval_eval import recall_at_k

        assert recall_at_k(["a", "b", "c"], ["a", "b"], k=5) == 1.0

    def test_recall_at_k_partial(self) -> None:
        from evals.retrieval_eval import recall_at_k

        assert recall_at_k(["a", "x", "y"], ["a", "b"], k=5) == 0.5

    def test_recall_at_k_cutoff(self) -> None:
        from evals.retrieval_eval import recall_at_k

        # relevant doc is at position 6 — not in top 5
        assert recall_at_k(["x"] * 5 + ["a"], ["a"], k=5) == 0.0

    def test_mrr_first_hit(self) -> None:
        from evals.retrieval_eval import reciprocal_rank

        assert reciprocal_rank(["a", "b", "c"], ["a"]) == pytest.approx(1.0)

    def test_mrr_second_hit(self) -> None:
        from evals.retrieval_eval import reciprocal_rank

        assert reciprocal_rank(["x", "a", "c"], ["a"]) == pytest.approx(0.5)

    def test_mrr_no_hit(self) -> None:
        from evals.retrieval_eval import reciprocal_rank

        assert reciprocal_rank(["x", "y", "z"], ["a"]) == 0.0

    def test_evaluate_runs_offline(self) -> None:
        """Full evaluate() call with synthetic data must work in OFFLINE mode."""
        import os

        os.environ.setdefault("OFFLINE", "1")
        from evals.retrieval_eval import _build_synthetic_data, evaluate

        corpus, labelled = _build_synthetic_data(n_docs=20, n_queries=10)
        results = evaluate(corpus, labelled)
        assert results["n_queries"] == 10
        assert 0.0 <= results["hybrid_recall5"] <= 1.0
        assert 0.0 <= results["bm25_mrr"] <= 1.0

    def test_report_generated(self) -> None:
        import os

        os.environ.setdefault("OFFLINE", "1")
        from evals.retrieval_eval import _build_synthetic_data, _report, evaluate

        corpus, labelled = _build_synthetic_data(n_docs=20, n_queries=5)
        results = evaluate(corpus, labelled)
        md = _report(results)
        assert "Recall@5" in md
        assert "MRR" in md
        assert "rerank" in md.lower()
