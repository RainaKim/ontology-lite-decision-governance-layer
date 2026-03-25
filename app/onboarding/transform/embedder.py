"""
Embedder — converts text chunks into 1536-dimension vectors.

Uses OpenAI text-embedding-3-small via langchain-openai.
Gracefully degrades to None when OPENAI_API_KEY is not set or the API
call fails — the rest of the pipeline continues without embeddings.

Vector index is on Chunk.embedding and Decision.embedding (see init_schema.py).
Non-Chunk nodes (Goals, Rules, Actors) do not get embeddings.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536

# Lazy singleton — only initialized when first called
_embedder = None


def _get_embedder():
    """Return a cached OpenAIEmbeddings instance, or None if unavailable."""
    global _embedder
    if _embedder is not None:
        return _embedder

    if not os.getenv("OPENAI_API_KEY"):
        logger.debug("OPENAI_API_KEY not set — embedding disabled")
        return None

    try:
        from langchain_openai import OpenAIEmbeddings

        _embedder = OpenAIEmbeddings(model=_EMBEDDING_MODEL)
        return _embedder
    except Exception as exc:
        logger.warning(f"Failed to initialize embedder: {exc}")
        return None


async def embed_chunks(texts: list[str]) -> Optional[list[list[float]]]:
    """
    Embed a list of text strings.

    Returns a list of 1536-dimensional float vectors, one per text.
    Returns None if embeddings are unavailable (no API key, API error).

    Never raises — callers proceed without embeddings on failure.
    """
    if not texts:
        return None

    embedder = _get_embedder()
    if embedder is None:
        return None

    try:
        vectors = await embedder.aembed_documents(texts)
        logger.debug(f"Embedded {len(texts)} chunks")
        return vectors
    except Exception as exc:
        logger.warning(f"Embedding failed: {exc}")
        return None


async def embed_text(text: str) -> Optional[list[float]]:
    """
    Embed a single text string.

    Returns a 1536-dimensional float vector, or None on failure.
    """
    results = await embed_chunks([text])
    if results is None:
        return None
    return results[0] if results else None
