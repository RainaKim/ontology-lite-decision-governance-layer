"""
Data scout — LangGraph node for CSVs, spreadsheets, org charts, approval logs.

Handles: .csv files, .json structured data (org_chart, authority_matrix, etc.).
Extracts: Actor nodes, Department nodes, numeric approval thresholds, hierarchy.

Special handling for past_decisions.json and approval_logs.csv: these are parsed
as structured Decision nodes (instance-layer) with edges to Rules and Actors,
rather than generic text chunks.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from pathlib import Path

from app.config.llm import get_llm
from app.onboarding.prompts import DATA_PROMPT
from app.onboarding.schemas import (
    ArtifactExtraction,
    ExtractedEdge,
    ExtractedNode,
    ScoutInput,
    ScoutResult,
)
from app.onboarding.scouts.base import chunk_text, merge_extractions, read_artifact, run_extraction

logger = logging.getLogger(__name__)


def _is_decision_json(path: str, text: str) -> bool:
    """Detect if a JSON file contains structured past decisions."""
    name = Path(path).stem.lower()
    if "decision" in name:
        try:
            data = json.loads(text)
            # Could be {"decisions": [...]} or a top-level list
            records = data if isinstance(data, list) else data.get("decisions", [])
            if records and isinstance(records, list) and isinstance(records[0], dict):
                first = records[0]
                return any(k in first for k in ("id", "decision_id", "date", "amount"))
        except (json.JSONDecodeError, TypeError):
            pass
    return False


def _is_approval_csv(path: str, text: str) -> bool:
    """Detect if a CSV file contains approval log records."""
    name = Path(path).stem.lower()
    if "approval" in name or "log" in name:
        try:
            reader = csv.DictReader(io.StringIO(text))
            headers = set(h.lower() for h in (reader.fieldnames or []))
            return bool(headers & {"approver", "approved_by", "status", "decision_id"})
        except Exception:
            pass
    return False


def _slugify(text: str) -> str:
    """Convert text to a valid semantic_id slug."""
    s = text.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:60]


def _parse_decisions_json(text: str) -> tuple[list[ExtractedNode], list[ExtractedEdge]]:
    """Parse structured decision records into Decision nodes and edges."""
    data = json.loads(text)
    records = data if isinstance(data, list) else data.get("decisions", [])

    nodes: list[ExtractedNode] = []
    edges: list[ExtractedEdge] = []

    for record in records:
        if not isinstance(record, dict):
            continue

        dec_id = record.get("id") or record.get("decision_id") or ""
        if not dec_id:
            continue

        sem_id = _slugify(str(dec_id))
        label = record.get("title") or record.get("description") or str(dec_id)
        description = record.get("description") or label

        props = {
            "decision_id": str(dec_id),
            "description": description,
        }
        for field in ("date", "requester", "amount", "status", "decision_type"):
            if field in record and record[field] is not None:
                props[field] = record[field]

        nodes.append(ExtractedNode(
            node_type="Decision",
            semantic_id=sem_id,
            label=str(label)[:120],
            properties=props,
            confidence=1.0,
            source_excerpt=str(label)[:100],
        ))

        # Create TRIGGERED edges to rules
        triggered_rules = record.get("triggered_rules") or record.get("rules_triggered") or []
        if isinstance(triggered_rules, str):
            triggered_rules = [triggered_rules]
        for rule_id in triggered_rules:
            rule_sem = _slugify(str(rule_id))
            if rule_sem:
                edges.append(ExtractedEdge(
                    from_semantic_id=sem_id,
                    to_semantic_id=rule_sem,
                    predicate="TRIGGERED",
                    evidence=f"Decision {dec_id} triggered rule {rule_id}",
                ))

        # Create APPROVED_BY edges to actors
        approver = record.get("approver") or record.get("approved_by") or ""
        if approver:
            approver_sem = _slugify(str(approver))
            if approver_sem:
                edges.append(ExtractedEdge(
                    from_semantic_id=sem_id,
                    to_semantic_id=approver_sem,
                    predicate="APPROVED_BY",
                    evidence=f"Decision {dec_id} approved by {approver}",
                ))

        # Create GOVERNED_BY edge to related goal
        related_goal = record.get("related_goal") or record.get("goal") or ""
        if related_goal:
            goal_sem = _slugify(str(related_goal))
            if goal_sem:
                edges.append(ExtractedEdge(
                    from_semantic_id=sem_id,
                    to_semantic_id=goal_sem,
                    predicate="GOVERNED_BY",
                    evidence=f"Decision {dec_id} related to goal {related_goal}",
                ))

    return nodes, edges


def _parse_approval_csv(text: str) -> tuple[list[ExtractedNode], list[ExtractedEdge]]:
    """Parse approval log CSV into Decision nodes and edges."""
    reader = csv.DictReader(io.StringIO(text))
    nodes: list[ExtractedNode] = []
    edges: list[ExtractedEdge] = []
    seen_ids: set[str] = set()

    for row in reader:
        # Normalize header keys to lowercase
        row_lower = {k.lower().strip(): v for k, v in row.items()}

        dec_id = (
            row_lower.get("decision_id")
            or row_lower.get("log_id")
            or row_lower.get("id")
            or ""
        )
        if not dec_id or dec_id in seen_ids:
            continue
        seen_ids.add(dec_id)

        sem_id = _slugify(str(dec_id))
        description = row_lower.get("description") or row_lower.get("title") or str(dec_id)

        props = {
            "decision_id": str(dec_id),
            "description": description,
        }
        for field in ("date", "requester", "amount", "status"):
            val = row_lower.get(field)
            if val:
                props[field] = val

        nodes.append(ExtractedNode(
            node_type="Decision",
            semantic_id=sem_id,
            label=str(description)[:120],
            properties=props,
            confidence=1.0,
            source_excerpt=str(description)[:100],
        ))

        # APPROVED_BY edge
        approver = row_lower.get("approver") or row_lower.get("approved_by") or ""
        if approver:
            approver_sem = _slugify(str(approver))
            if approver_sem:
                edges.append(ExtractedEdge(
                    from_semantic_id=sem_id,
                    to_semantic_id=approver_sem,
                    predicate="APPROVED_BY",
                    evidence=f"Decision {dec_id} approved by {approver}",
                ))

        # TRIGGERED edge
        rule_ref = row_lower.get("rule") or row_lower.get("rule_id") or ""
        if rule_ref:
            rule_sem = _slugify(str(rule_ref))
            if rule_sem:
                edges.append(ExtractedEdge(
                    from_semantic_id=sem_id,
                    to_semantic_id=rule_sem,
                    predicate="TRIGGERED",
                    evidence=f"Decision {dec_id} triggered rule {rule_ref}",
                ))

    return nodes, edges


async def data_scout(state: ScoutInput) -> dict:
    """
    LangGraph node: extract governance ontology from structured data artifacts.

    Input state keys: company_id, artifact_path
    Returns: {"scout_results": [ScoutResult], "errors": [...]}
    """
    path = state["artifact_path"]
    seeded_ctx = state.get("seeded_nodes_context") or ""
    logger.info(f"[data_scout] Processing: {path}")

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
                        scout_type="data",
                        artifact_path=path,
                        errors=[f"Empty or unreadable data file: {path}"],
                    )
                ],
                "errors": [],
            }

        # --- Decision-specific parsing (Fix #5) ---
        # Detect structured decision files and parse them directly
        # instead of treating them as generic text chunks.
        raw_text = Path(path).read_text(encoding="utf-8", errors="replace") if Path(path).exists() else text

        if _is_decision_json(path, raw_text):
            logger.info(f"[data_scout] Detected structured decisions JSON: {path}")
            dec_nodes, dec_edges = _parse_decisions_json(raw_text)
            extracted_nodes.extend(dec_nodes)
            extracted_edges.extend(dec_edges)
            raw_chunks = [text]  # Keep full text as a single chunk for provenance
            logger.info(
                f"[data_scout] Parsed {len(dec_nodes)} Decision nodes, "
                f"{len(dec_edges)} edges from {path}"
            )
        elif _is_approval_csv(path, raw_text):
            logger.info(f"[data_scout] Detected approval logs CSV: {path}")
            dec_nodes, dec_edges = _parse_approval_csv(raw_text)
            extracted_nodes.extend(dec_nodes)
            extracted_edges.extend(dec_edges)
            raw_chunks = [text]
            logger.info(
                f"[data_scout] Parsed {len(dec_nodes)} Decision nodes, "
                f"{len(dec_edges)} edges from {path}"
            )
        else:
            # Standard LLM extraction for non-decision data artifacts
            chunks = chunk_text(text, chunk_size=1200, overlap=150)
            raw_chunks = chunks
            llm = get_llm("capable")

            extractions = []
            for chunk in chunks:
                extraction = await run_extraction(
                    llm, DATA_PROMPT, chunk, path,
                    seeded_nodes_context=seeded_ctx,
                )
                extractions.append(extraction)

            extracted_nodes, extracted_edges = merge_extractions(extractions)

    except Exception as exc:
        msg = f"[data_scout] Failed on {path}: {exc}"
        logger.error(msg)
        errors.append(msg)

    result = ScoutResult(
        scout_type="data",
        artifact_path=path,
        extracted_nodes=extracted_nodes,
        extracted_edges=extracted_edges,
        raw_chunks=raw_chunks,
        errors=errors,
    )
    logger.info(
        f"[data_scout] {path}: "
        f"{len(extracted_nodes)} nodes, {len(extracted_edges)} edges"
    )
    return {"scout_results": [result], "errors": []}
