"""Cross-encoder reranking: top-30 candidates → top-5.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2
Runs locally on MPS/CUDA/CPU.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

_RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_encoder: CrossEncoder | None = None

DEFAULT_TOP_N: int = 5
DEFAULT_CANDIDATES: int = 30


def _get_encoder() -> CrossEncoder:
    global _encoder
    if _encoder is None:
        import torch
        from sentence_transformers import CrossEncoder

        device = (
            "mps"
            if torch.backends.mps.is_available()
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        _encoder = CrossEncoder(_RERANK_MODEL, device=device)
    return _encoder


def rerank(
    query: str,
    candidates: list[tuple[dict, float]],
    *,
    top_n: int = DEFAULT_TOP_N,
    text_key: str = "text",
) -> list[tuple[dict, float]]:
    """Score (query, passage) pairs and return top_n sorted by cross-encoder score.

    Args:
        query: The search query string.
        candidates: List of (doc, retrieval_score) tuples — typically the
                    top-30 from hybrid_search.
        top_n: How many to return (default 5).
        text_key: Key in the doc dict that holds the passage text.

    Returns:
        List of (doc, cross_encoder_score) tuples, sorted descending.
    """
    if not candidates:
        return []

    encoder = _get_encoder()
    pairs = [(query, doc.get(text_key, "")) for doc, _ in candidates]
    scores: list[float] = encoder.predict(pairs).tolist()  # type: ignore[union-attr]

    scored = sorted(
        zip([doc for doc, _ in candidates], scores, strict=False),
        key=lambda x: x[1],
        reverse=True,
    )
    return list(scored[:top_n])
