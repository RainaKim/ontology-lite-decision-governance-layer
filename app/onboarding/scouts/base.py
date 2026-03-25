"""
Shared utilities for all scout nodes.

Provides:
  read_artifact(path)          — read any supported artifact file → str
  classify_artifact(path)      — determine scout type from file extension/name
  chunk_text(text, ...)        — split text into overlapping chunks
  run_extraction(llm, prompt, text, path) — invoke LLM chain and return ArtifactExtraction
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Artifact type classification
# ---------------------------------------------------------------------------

_CONVERSATION_EXTENSIONS = {".eml", ".msg"}
_DATA_EXTENSIONS = {".csv", ".json"}
_DOCUMENT_EXTENSIONS = {".md", ".txt", ".pdf", ".rst"}

_CONVERSATION_DIRS = {"email", "slack"}
_DATA_DIRS = {"spreadsheets", "structure", "decisions", "jira"}
_DOCUMENT_DIRS = {"docs", "meeting_minutes", "context"}


def classify_artifact(path: str) -> str:
    """
    Return the scout type for a given artifact path.

    Returns one of: "document", "conversation", "data"
    Defaults to "document" for unknown types.
    """
    p = Path(path)
    ext = p.suffix.lower()
    parent = p.parent.name.lower()

    if ext in _CONVERSATION_EXTENSIONS or parent in _CONVERSATION_DIRS:
        return "conversation"
    if ext in _DATA_EXTENSIONS and parent in _DATA_DIRS:
        return "data"
    if ext in _DATA_EXTENSIONS:
        # JSON outside data dirs might be structured config — treat as data
        return "data"
    return "document"


# ---------------------------------------------------------------------------
# File reading
# ---------------------------------------------------------------------------


def read_artifact(path: str) -> str:
    """
    Read any supported artifact file and return its text content.

    Handles: .md, .txt, .eml, .csv, .json
    Returns empty string on error (scout will log and continue).
    """
    p = Path(path)
    if not p.exists():
        logger.warning(f"Artifact not found: {path}")
        return ""

    ext = p.suffix.lower()
    try:
        if ext in (".md", ".txt", ".eml", ".rst"):
            return p.read_text(encoding="utf-8", errors="replace")

        if ext == ".csv":
            return _read_csv(p)

        if ext == ".json":
            return _read_json(p)

        # Fallback: try reading as text
        return p.read_text(encoding="utf-8", errors="replace")

    except Exception as exc:
        logger.error(f"Failed to read {path}: {exc}")
        return ""


def _read_csv(path: Path) -> str:
    """Convert CSV to readable text table."""
    content = path.read_text(encoding="utf-8", errors="replace")
    try:
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)
        if not rows:
            return content
        headers = list(rows[0].keys())
        lines = [" | ".join(headers)]
        lines.append("-" * len(lines[0]))
        for row in rows:
            lines.append(" | ".join(str(row.get(h, "")) for h in headers))
        return "\n".join(lines)
    except Exception:
        return content


def _read_json(path: Path) -> str:
    """Pretty-print JSON as readable text."""
    content = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(content)
        return json.dumps(data, indent=2, ensure_ascii=False)
    except Exception:
        return content


# ---------------------------------------------------------------------------
# Text chunking
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    chunk_size: int = 600,
    overlap: int = 100,
) -> list[str]:
    """
    Split text into overlapping character-based chunks.

    Args
    ----
    text        Raw text content
    chunk_size  Target chunk size in characters
    overlap     Overlap between consecutive chunks

    Returns
    -------
    List of text chunks; single-item list if text is shorter than chunk_size.
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        # Try to break at a sentence boundary
        if end < len(text):
            last_break = max(
                chunk.rfind(". "),
                chunk.rfind("\n\n"),
                chunk.rfind("\n"),
            )
            if last_break > chunk_size // 2:
                chunk = chunk[: last_break + 1]

        chunks.append(chunk.strip())
        # Guarantee meaningful forward progress: advance at least half the
        # chunk_size even if sentence-boundary trimming produced a short chunk.
        advance = max(chunk_size // 2, len(chunk) - overlap)
        start += advance

        # Snap to word boundary — avoid starting mid-word.
        # Limit scan to 50 chars to avoid skipping large amounts
        # of whitespace-free text (e.g. encoded data).
        snap_limit = min(start + 50, len(text))
        while start < snap_limit and not text[start - 1].isspace():
            start += 1

        if start >= len(text):
            break

    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# LLM extraction runner
# ---------------------------------------------------------------------------


async def run_extraction(
    llm: Any,
    prompt: Any,
    text: str,
    artifact_path: str,
    seeded_nodes_context: str = "",
) -> "ArtifactExtraction":  # noqa: F821
    """
    Run one LLM extraction chain against a text chunk.

    Args
    ----
    llm                   LangChain chat model
    prompt                ChatPromptTemplate with {text}, {artifact_path}, {seeded_nodes_section} vars
    text                  Artifact text chunk
    artifact_path         Path to the artifact (for provenance)
    seeded_nodes_context  Markdown table of seeded nodes (empty string if none)

    Returns ArtifactExtraction (possibly empty on failure).
    Never raises — errors are logged and an empty result is returned.
    """
    from app.onboarding.schemas import ArtifactExtraction
    from app.onboarding.prompts import build_seeded_nodes_section

    try:
        structured_llm = llm.with_structured_output(ArtifactExtraction, method="json_mode")
        chain = prompt | structured_llm
        result = await chain.ainvoke(
            {
                "text": text,
                "artifact_path": artifact_path,
                "seeded_nodes_section": build_seeded_nodes_section(seeded_nodes_context),
            }
        )
        if result is None:
            logger.warning(f"Extraction returned None for {artifact_path} — LLM failed to produce structured output")
            return ArtifactExtraction(nodes=[], edges=[])
        return result
    except Exception as exc:
        logger.warning(f"Extraction failed for {artifact_path}: {exc}")
        return ArtifactExtraction(nodes=[], edges=[])


def merge_extractions(extractions: list) -> tuple[list, list]:
    """
    Merge multiple ArtifactExtraction results, deduplicating by semantic_id.

    Returns (nodes, edges) with duplicates removed (first occurrence wins).
    """
    seen_node_ids: set[str] = set()
    seen_edge_keys: set[tuple] = set()
    nodes = []
    edges = []

    for ext in extractions:
        for node in ext.nodes:
            key = (node.node_type, node.semantic_id)
            if key not in seen_node_ids:
                seen_node_ids.add(key)
                nodes.append(node)
        for edge in ext.edges:
            key = (edge.from_semantic_id, edge.to_semantic_id, edge.predicate)
            if key not in seen_edge_keys:
                seen_edge_keys.add(key)
                edges.append(edge)

    return nodes, edges
