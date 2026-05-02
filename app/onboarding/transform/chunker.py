"""
Chunker — converts raw text into Chunk nodes for the graph.

Chunk nodes are domain-layer nodes with MERGE-on-content-hash semantics.
Each chunk gets a content_hash ID and optionally an embedding vector.

Used by the transform pipeline to create provenance links from extracted
ontology nodes back to the source text they were derived from.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from app.ontology.models import Node, make_node_id
from app.ontology.node_types import NodeType

logger = logging.getLogger(__name__)


def make_chunk_nodes(
    chunks: list[str],
    company_id: str,
    artifact_path: str,
    embeddings: Optional[list[list[float]]] = None,
) -> list[Node]:
    """
    Convert raw text chunks into Chunk Node objects.

    Args
    ----
    chunks        List of text strings from chunk_text()
    company_id    Company prefix for node IDs
    artifact_path Source artifact path (stored as metadata)
    embeddings    Optional list of 1536d vectors, one per chunk

    Returns
    -------
    List of Node objects with NodeType.CHUNK, ready for write_node().
    Node IDs use content_hash for MERGE-on-hash deduplication.
    """
    nodes: list[Node] = []
    for i, chunk in enumerate(chunks):
        content_hash = _hash_chunk(chunk)
        props: dict = {
            "content_hash": content_hash,
            "text": chunk,
            "char_offset": i,
            "token_count": len(chunk.split()),
            "source_path": artifact_path,
        }

        node = Node(
            id=make_node_id(company_id, NodeType.CHUNK, content_hash),
            type=NodeType.CHUNK,
            label=chunk[:60].replace("\n", " ") + ("..." if len(chunk) > 60 else ""),
            properties=props,
            embedding=embeddings[i] if embeddings and i < len(embeddings) else None,
        )
        nodes.append(node)

    return nodes


def _hash_chunk(text: str) -> str:
    """Return a 16-character hex hash of the chunk text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
