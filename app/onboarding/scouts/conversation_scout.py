"""
Conversation scout — LangGraph node for emails, Slack threads, meeting minutes.

Handles: .eml files, Slack JSON exports, meeting_minutes .txt files.
Extracts: informal rules (source='inferred'), authority patterns, role relationships.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.config.llm import get_llm
from app.onboarding.prompts import CONVERSATION_PROMPT
from app.onboarding.schemas import ScoutInput, ScoutResult
from app.onboarding.scouts.base import chunk_text, merge_extractions, run_extraction

logger = logging.getLogger(__name__)


async def conversation_scout(state: ScoutInput) -> dict:
    """
    LangGraph node: extract governance ontology from conversation artifacts.

    Input state keys: company_id, artifact_path
    Returns: {"scout_results": [ScoutResult], "errors": [...]}
    """
    path = state["artifact_path"]
    seeded_ctx = state.get("seeded_nodes_context") or ""
    logger.info(f"[conversation_scout] Processing: {path}")

    errors: list[str] = []
    extracted_nodes = []
    extracted_edges = []
    raw_chunks = []

    try:
        text = _read_conversation(path)
        if not text:
            return {
                "scout_results": [
                    ScoutResult(
                        scout_type="conversation",
                        artifact_path=path,
                        errors=[f"Empty or unreadable conversation file: {path}"],
                    )
                ],
                "errors": [],
            }

        chunks = chunk_text(text, chunk_size=700, overlap=100)
        raw_chunks = chunks
        llm = get_llm("capable")

        extractions = []
        for chunk in chunks:
            extraction = await run_extraction(
                llm, CONVERSATION_PROMPT, chunk, path,
                seeded_nodes_context=seeded_ctx,
            )
            extractions.append(extraction)

        extracted_nodes, extracted_edges = merge_extractions(extractions)

    except Exception as exc:
        msg = f"[conversation_scout] Failed on {path}: {exc}"
        logger.error(msg)
        errors.append(msg)

    result = ScoutResult(
        scout_type="conversation",
        artifact_path=path,
        extracted_nodes=extracted_nodes,
        extracted_edges=extracted_edges,
        raw_chunks=raw_chunks,
        errors=errors,
    )
    logger.info(
        f"[conversation_scout] {path}: "
        f"{len(extracted_nodes)} nodes, {len(extracted_edges)} edges"
    )
    return {"scout_results": [result], "errors": []}


# ---------------------------------------------------------------------------
# Conversation-specific readers
# ---------------------------------------------------------------------------


def _read_conversation(path: str) -> str:
    """Read a conversation artifact, handling .eml and Slack JSON specially."""
    p = Path(path)
    if not p.exists():
        logger.warning(f"File not found: {path}")
        return ""

    ext = p.suffix.lower()

    if ext == ".eml":
        return _parse_eml(p)

    if ext == ".json":
        return _parse_slack_json(p)

    # Plain text (meeting minutes)
    return p.read_text(encoding="utf-8", errors="replace")


def _parse_eml(path: Path) -> str:
    """Extract readable text from an .eml file (no external parser required)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    # Strip MIME headers, keep From/To/Subject/Date + body
    lines = raw.splitlines()
    header_done = False
    kept_headers: list[str] = []
    body: list[str] = []

    for line in lines:
        if not header_done:
            if line == "":
                header_done = True
                continue
            lower = line.lower()
            if any(lower.startswith(h) for h in ("from:", "to:", "subject:", "date:")):
                kept_headers.append(line)
        else:
            body.append(line)

    return "\n".join(kept_headers) + "\n\n" + "\n".join(body)


def _parse_slack_json(path: Path) -> str:
    """Convert Slack JSON export to readable conversation text."""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        messages = data if isinstance(data, list) else data.get("messages", [])
        lines = []
        for msg in messages:
            user = msg.get("user_profile", {}).get("real_name") or msg.get("user", "unknown")
            text = msg.get("text", "").strip()
            if text:
                lines.append(f"{user}: {text}")
        return "\n".join(lines)
    except Exception as exc:
        logger.warning(f"Failed to parse Slack JSON {path}: {exc}")
        return path.read_text(encoding="utf-8", errors="replace")
