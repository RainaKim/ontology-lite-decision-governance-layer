"""
Onboarding LangGraph — Step 7.

Orchestrates the full onboarding pipeline as a LangGraph StateGraph:

  START → plan → [fan-out via Send to scouts] → transform → validate → END

Parallel fan-out
----------------
The `plan` node classifies all artifact paths and uses the LangGraph `Send`
API to dispatch each artifact to the correct scout node concurrently.
Each scout node writes {"scout_results": [...]} back into the shared state.
The `operator.add` reducer on `scout_results` accumulates all results
before `transform` runs.

Usage
-----
    from app.onboarding.onboarding_graph import build_onboarding_graph
    from app.graph.in_memory_repository import InMemoryGraphRepository

    repo = InMemoryGraphRepository()
    graph = build_onboarding_graph(repo)

    result = await graph.ainvoke({
        "company_id": "nexus_analytics",
        "artifact_paths": [...],
        "scout_results": [],
        "errors": [],
        "transform_summary": None,
        "report": None,
    })
    report = result["report"]

For production use, pass a Neo4jGraphRepository instead of InMemoryGraphRepository.
"""

from __future__ import annotations

import glob
import logging
import os
from pathlib import Path
from typing import Optional

from langgraph.constants import END, START
from langgraph.types import Send
from langgraph.graph import StateGraph

from app.graph.base import BaseGraphRepository
from app.onboarding.schemas import (
    OnboardingReport,
    OnboardingState,
    ScoutInput,
    TransformSummary,
)
from app.onboarding.scouts.base import classify_artifact
from app.onboarding.scouts.conversation_scout import conversation_scout
from app.onboarding.scouts.data_scout import data_scout
from app.onboarding.scouts.document_scout import document_scout
from app.onboarding.scouts.edge_audit_scout import run_edge_audit
from app.onboarding.transform.writer import transform_scout_results
from app.onboarding.validation import validate_graph_structure

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def plan_node(state: OnboardingState) -> dict:
    """
    Classify artifact paths and return the state unchanged.

    The actual fan-out happens in route_to_scouts() via Send.
    This node exists as a named entry point for clarity and testability.
    """
    logger.info(
        f"[plan] company={state['company_id']} "
        f"artifacts={len(state['artifact_paths'])}"
    )
    return {}


def route_to_scouts(state: OnboardingState) -> list[Send]:
    """
    Conditional edge function: returns Send objects for each artifact.

    Each Send dispatches one artifact to the appropriate scout node.
    LangGraph runs all Sends in parallel.
    """
    sends: list[Send] = []
    seeded_ctx = state.get("seeded_nodes_context") or ""
    for path in state["artifact_paths"]:
        scout_type = classify_artifact(path)
        scout_node = _SCOUT_NODE_MAP.get(scout_type, "document_scout")
        sends.append(
            Send(
                scout_node,
                ScoutInput(
                    company_id=state["company_id"],
                    artifact_path=path,
                    seeded_nodes_context=seeded_ctx,
                ),
            )
        )
    return sends


_SCOUT_NODE_MAP = {
    "document": "document_scout",
    "conversation": "conversation_scout",
    "data": "data_scout",
}


def make_transform_node(repo: BaseGraphRepository):
    """Factory: returns a transform node bound to a specific repository."""

    async def transform_node(state: OnboardingState) -> dict:
        """
        Transform all accumulated scout results into graph nodes and edges.
        Writes to the repository.
        """
        logger.info(
            f"[transform] company={state['company_id']} "
            f"scout_results={len(state['scout_results'])}"
        )
        seeded_rule_ids = set(state.get("seeded_rule_ids") or [])
        seeded_goal_ids = set(state.get("seeded_goal_ids") or [])
        seeded_goal_labels = state.get("seeded_goal_labels") or {}
        summary = await transform_scout_results(
            scout_results=state["scout_results"],
            company_id=state["company_id"],
            repo=repo,
            seeded_rule_ids=seeded_rule_ids if seeded_rule_ids else None,
            seeded_goal_ids=seeded_goal_ids if seeded_goal_ids else None,
            seeded_goal_labels=seeded_goal_labels if seeded_goal_labels else None,
        )
        return {"transform_summary": summary}

    return transform_node


def make_edge_audit_node(repo: BaseGraphRepository):
    """Factory: returns an edge audit node bound to a specific repository."""

    async def edge_audit_node(state: OnboardingState) -> dict:
        """
        Run a second-pass edge audit after transform.

        Identifies orphan nodes and proposes missing edges via LLM.
        Non-fatal: errors are logged as warnings but do NOT propagate
        to the errors list (which would fail the onboarding report).
        """
        logger.info(f"[edge_audit] company={state['company_id']}")
        try:
            audit_result = await run_edge_audit(repo, state["company_id"])
            logger.info(
                f"[edge_audit] Proposed {audit_result['edges_proposed']} edges, "
                f"wrote {audit_result['edges_written']}"
            )
            # Log but do not propagate errors — edge audit is advisory
            for err in audit_result.get("errors", []):
                logger.warning(f"[edge_audit] {err}")
            return {}
        except Exception as exc:
            logger.warning(f"[edge_audit] Non-fatal error: {exc}")
            return {}

    return edge_audit_node


def make_validate_node(repo: BaseGraphRepository):
    """Factory: returns a validate node bound to a specific repository."""

    async def validate_node(state: OnboardingState) -> dict:
        """
        Traverse the derived graph and produce an OnboardingReport.

        Counts nodes by type, calculates aggregate confidence,
        and flags any expected node types with zero instances.
        """
        logger.info(f"[validate] company={state['company_id']}")
        report = await _build_report(state, repo)
        return {"report": report}

    return validate_node


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


def build_onboarding_graph(repo: BaseGraphRepository) -> StateGraph:
    """
    Build and compile the onboarding LangGraph StateGraph.

    Args
    ----
    repo   Graph repository to write to (Neo4j or InMemory)

    Returns
    -------
    Compiled LangGraph app (call .ainvoke() to run)
    """
    graph = StateGraph(OnboardingState)

    # Register nodes
    graph.add_node("plan", plan_node)
    graph.add_node("document_scout", document_scout)
    graph.add_node("conversation_scout", conversation_scout)
    graph.add_node("data_scout", data_scout)
    graph.add_node("transform", make_transform_node(repo))
    graph.add_node("edge_audit", make_edge_audit_node(repo))
    graph.add_node("validate", make_validate_node(repo))

    # Edges
    graph.add_edge(START, "plan")

    # Fan-out from plan → scouts (parallel, via Send)
    graph.add_conditional_edges(
        "plan",
        route_to_scouts,
        ["document_scout", "conversation_scout", "data_scout"],
    )

    # All scouts feed into transform (LangGraph joins after all parallel nodes complete)
    graph.add_edge("document_scout", "transform")
    graph.add_edge("conversation_scout", "transform")
    graph.add_edge("data_scout", "transform")

    # transform → edge_audit → validate → END
    graph.add_edge("transform", "edge_audit")
    graph.add_edge("edge_audit", "validate")
    graph.add_edge("validate", END)

    return graph.compile()


# ---------------------------------------------------------------------------
# Convenience: enumerate artifact paths from a directory
# ---------------------------------------------------------------------------


def collect_artifact_paths(base_dir: str) -> list[str]:
    """
    Recursively collect all supported artifact file paths under base_dir.

    Skips hidden files, __pycache__, and unsupported extensions.
    """
    supported = {".md", ".txt", ".eml", ".csv", ".json", ".pdf", ".rst"}
    paths = []
    for ext in supported:
        paths.extend(glob.glob(os.path.join(base_dir, "**", f"*{ext}"), recursive=True))

    # Sort for deterministic ordering
    return sorted(
        p for p in paths
        if "__pycache__" not in p
        and not Path(p).name.startswith(".")
    )


# ---------------------------------------------------------------------------
# Convenience: run onboarding from a directory
# ---------------------------------------------------------------------------


async def run_onboarding(
    company_id: str,
    artifact_dir: str,
    repo: BaseGraphRepository,
    artifact_paths: Optional[list[str]] = None,
    seeded_nodes_context: str = "",
    seeded_rule_ids: Optional[list[str]] = None,
    seeded_goal_ids: Optional[list[str]] = None,
    seeded_goal_labels: Optional[dict[str, str]] = None,
) -> OnboardingReport:
    """
    Run the full onboarding pipeline for a company.

    Args
    ----
    company_id              Company being onboarded
    artifact_dir            Root directory of company artifacts
    repo                    Graph repository (initialize() should be called before this)
    artifact_paths          Override artifact list (default: auto-discover from artifact_dir)
    seeded_nodes_context    Markdown table of seeded nodes (from serialize_seeded_nodes)

    Returns
    -------
    OnboardingReport with node counts, confidence, and gaps
    """
    paths = artifact_paths or collect_artifact_paths(artifact_dir)
    logger.info(
        f"Starting onboarding: company={company_id!r} "
        f"artifact_dir={artifact_dir!r} "
        f"artifacts={len(paths)}"
    )

    compiled = build_onboarding_graph(repo)
    result = await compiled.ainvoke(
        {
            "company_id": company_id,
            "artifact_paths": paths,
            "seeded_nodes_context": seeded_nodes_context,
            "seeded_rule_ids": seeded_rule_ids or [],
            "seeded_goal_ids": seeded_goal_ids or [],
            "seeded_goal_labels": seeded_goal_labels or {},
            "scout_results": [],
            "errors": [],
            "transform_summary": None,
            "report": None,
        }
    )
    return result.get("report") or OnboardingReport(company_id=company_id)


# ---------------------------------------------------------------------------
# Internal: report builder
# ---------------------------------------------------------------------------


async def _build_report(
    state: OnboardingState,
    repo: BaseGraphRepository,
) -> OnboardingReport:
    """
    Build the OnboardingReport by aggregating scout results and transform summary.

    Uses scout_results for node/edge counts (repo traversal requires Neo4j).
    """
    from collections import Counter

    scout_results = state.get("scout_results") or []
    transform_summary: Optional[TransformSummary] = state.get("transform_summary")
    company_id = state["company_id"]

    # Count extracted nodes by type from scout results
    node_type_counter: Counter = Counter()
    edge_type_counter: Counter = Counter()
    confidence_values: list[float] = []
    total_artifacts = len(scout_results)
    all_errors: list[str] = list(state.get("errors") or [])

    for sr in scout_results:
        all_errors.extend(sr.errors)
        for node in sr.extracted_nodes:
            node_type_counter[node.node_type] += 1
            confidence_values.append(node.confidence)
        for edge in sr.extracted_edges:
            edge_type_counter[edge.predicate] += 1

    # Aggregate confidence
    aggregate_confidence = (
        sum(confidence_values) / len(confidence_values)
        if confidence_values
        else 0.0
    )

    # Gap detection: expected domain classes with zero extracted instances
    expected_domain_classes = {"Goal", "Rule", "Actor", "KPI"}
    gaps = [
        f"No {cls} nodes extracted — check if artifacts contain {cls.lower()} definitions"
        for cls in expected_domain_classes
        if node_type_counter.get(cls, 0) == 0
    ]

    warnings: list[str] = []
    if transform_summary and transform_summary.errors:
        warnings.extend(transform_summary.errors[:5])  # cap at 5

    edges_dropped = transform_summary.edges_dropped if transform_summary else 0

    # --- Structural validation ---
    structural_warnings: list[str] = []
    orphan_rate = 0.0
    edge_to_node_ratio = 0.0

    try:
        validation = await validate_graph_structure(repo, company_id)
        orphan_rate = validation.orphan_rate
        edge_to_node_ratio = validation.edge_to_node_ratio
        structural_warnings = validation.warnings

        if not validation.passed:
            warnings.append(
                f"Structural validation failed: "
                f"{len(validation.orphan_nodes)} orphan(s), "
                f"{len(validation.missing_patterns)} missing pattern(s)"
            )
    except Exception as exc:
        logger.warning(f"Structural validation error (non-fatal): {exc}")
        structural_warnings.append(f"Validation error: {exc}")

    return OnboardingReport(
        company_id=company_id,
        nodes_by_type=dict(node_type_counter),
        edges_by_type=dict(edge_type_counter),
        total_artifacts_processed=total_artifacts,
        confidence=round(aggregate_confidence, 3),
        gaps=gaps,
        warnings=warnings,
        completed=len(gaps) == 0 and len(all_errors) == 0,
        orphan_rate=orphan_rate,
        edge_to_node_ratio=edge_to_node_ratio,
        structural_warnings=structural_warnings,
        edges_dropped=edges_dropped,
    )
