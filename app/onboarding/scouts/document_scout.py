"""
Document scout — LangGraph node for policy docs, strategy docs, handbooks.

Handles: .md, .txt, .pdf, and other narrative text artifacts.
Extracts: Rules (with approval thresholds), Goals, KPIs, Actors, Jurisdictions.
"""

from __future__ import annotations

import logging

from app.config.llm import get_llm
from app.onboarding.prompts import DOCUMENT_PROMPT
from app.onboarding.schemas import ScoutInput, ScoutResult
from app.onboarding.scouts.base import chunk_text, merge_extractions, read_artifact, run_extraction

logger = logging.getLogger(__name__)


async def document_scout(state: ScoutInput) -> dict:
    """
    LangGraph node: extract governance ontology from a document artifact.

    Input state keys: company_id, artifact_path
    Returns: {"scout_results": [ScoutResult], "errors": [...]}
    """
    path = state["artifact_path"]
    seeded_ctx = state.get("seeded_nodes_context") or ""
    logger.info(f"[document_scout] Processing: {path}")

    errors: list[str] = []
    extracted_nodes = []
    extracted_edges = []
    raw_chunks = []

    try:
        text = read_artifact(path)
        if not text:
            return {
                "scout_results": [
                    ScoutResult(
                        scout_type="document",
                        artifact_path=path,
                        errors=[f"Empty or unreadable file: {path}"],
                    )
                ],
                "errors": [],
            }

        chunks = chunk_text(text, chunk_size=800, overlap=120)
        raw_chunks = chunks
        llm = get_llm("capable")

        extractions = []
        for chunk in chunks:
            extraction = await run_extraction(
                llm, DOCUMENT_PROMPT, chunk, path,
                seeded_nodes_context=seeded_ctx,
            )
            extractions.append(extraction)

        extracted_nodes, extracted_edges = merge_extractions(extractions)

    except Exception as exc:
        msg = f"[document_scout] Failed on {path}: {exc}"
        logger.error(msg)
        errors.append(msg)

    result = ScoutResult(
        scout_type="document",
        artifact_path=path,
        extracted_nodes=extracted_nodes,
        extracted_edges=extracted_edges,
        raw_chunks=raw_chunks,
        errors=errors,
    )
    logger.info(
        f"[document_scout] {path}: "
        f"{len(extracted_nodes)} nodes, {len(extracted_edges)} edges"
    )
    return {"scout_results": [result], "errors": []}
