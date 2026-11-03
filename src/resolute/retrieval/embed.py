"""Local embedding with BAAI/bge-small-en-v1.5.

Loads the model once per process (lazy singleton). Runs on MPS (Apple Silicon),
CUDA, or CPU depending on what's available.

The public surface is:
    embed_texts(texts)  → list[list[float]]   (sync, batch)
    embed_chunk(chunk)  → list[float]         (sync, single)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_MODEL_NAME = "BAAI/bge-small-en-v1.5"
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        import torch
        from sentence_transformers import SentenceTransformer

        device = (
            "mps"
            if torch.backends.mps.is_available()
            else ("cuda" if torch.cuda.is_available() else "cpu")
        )
        _model = SentenceTransformer(_MODEL_NAME, device=device)
    return _model


def embed_texts(texts: list[str], *, batch_size: int = 64) -> list[list[float]]:
    """Return normalised embeddings for a list of texts."""
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


def embed_chunk(text: str) -> list[float]:
    return embed_texts([text])[0]


# Dimensionality for schema / migration references
EMBEDDING_DIM: int = 384  # bge-small-en-v1.5
