"""
Cross-encoder reranker — scores (query, chunk) pairs jointly for higher precision
than cosine similarity alone.  Model is lazy-loaded on first call (~80 MB download).

Why cross-encoder over bi-encoder for reranking:
  Bi-encoder (cosine): query and passage embedded independently → fast, but misses
  fine-grained term interactions.
  Cross-encoder: query+passage fed together → full attention across both →
  significantly better precision, acceptable latency for top-50 → top-20 filtering.
"""
from __future__ import annotations

import os
from .config import RERANK_MODEL, RERANK_TOP_K, HF_TOKEN

# Set token before sentence-transformers makes any HF hub calls (only if provided)
if HF_TOKEN:
    os.environ.setdefault("HF_TOKEN", HF_TOKEN)
    os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", HF_TOKEN)
from .models import ControlChunk

_encoder = None   # lazy-loaded


def _get_encoder():
    global _encoder
    if _encoder is None:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as e:
            raise ImportError(
                "sentence-transformers is required for reranking. "
                "Install it with:  pip install sentence-transformers"
            ) from e
        print(f"[Reranker] Loading cross-encoder '{RERANK_MODEL}' (first-time download may take a moment)...")
        _encoder = CrossEncoder(RERANK_MODEL)
        print("[Reranker] Cross-encoder ready.")
    return _encoder


def rerank(
    query: str,
    chunks: list[ControlChunk],
    top_k: int = RERANK_TOP_K,
) -> list[ControlChunk]:
    """Returns top_k chunks sorted by descending cross-encoder score."""
    return [c for _, c in rerank_with_scores(query, chunks, top_k)]


def rerank_with_scores(
    query: str,
    chunks: list[ControlChunk],
    top_k: int = RERANK_TOP_K,
) -> list[tuple[float, ControlChunk]]:
    """
    Score each (query, chunk.statement) pair with the cross-encoder.
    Returns list of (score, chunk) tuples sorted by descending score, top_k kept.
    Scores are passed through to ControlBundle.rerank_score in the pipeline.
    """
    if not chunks:
        return []

    encoder = _get_encoder()
    pairs = [(query, c.statement[:512]) for c in chunks]
    scores = encoder.predict(pairs)

    ranked = sorted(zip(scores, chunks), key=lambda x: float(x[0]), reverse=True)
    kept = ranked[:top_k]
    print(f"[Reranker] {len(chunks)} chunks -> top {len(kept)} after reranking "
          f"(scores: {float(kept[0][0]):.3f} .. {float(kept[-1][0]):.3f}).")
    return [(float(s), c) for s, c in kept]
