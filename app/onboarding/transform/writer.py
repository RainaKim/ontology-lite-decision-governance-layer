"""
Writer — orchestrates the full transform pipeline for all scout results.

Two-phase approach to prevent silent edge-drops:

  Phase A: Collect ALL extracted nodes and edges from ALL scout results
  Phase B: Write all chunk nodes to repo
  Phase C: Ontologize ALL nodes at once (dedup across artifacts)
  Phase D: Write all domain nodes to repo
  Phase E: Build GLOBAL node_id_map (extracted nodes + seeded nodes from repo)
  Phase F: Ontologize ALL edges with the global map — cross-artifact edges resolve
  Phase G: Write all edges + DERIVED_FROM provenance edges

Returns a TransformSummary with counts and errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import hashlib
from typing import Optional

from app.graph.base import BaseGraphRepository
from app.ontology.edge_predicates import EdgePredicate
from app.ontology.models import Edge, Node, make_node_id
from app.ontology.node_types import NodeType
from app.onboarding.schemas import ExtractedEdge, ExtractedNode, ScoutResult, TransformSummary
from app.onboarding.transform.chunker import make_chunk_nodes
from app.onboarding.transform.embedder import embed_chunks
from app.onboarding.transform.ontologizer import (
    build_node_confidence_map,
    build_node_id_map,
    ontologize_edges,
    ontologize_nodes,
)

logger = logging.getLogger(__name__)


@dataclass
class _ArtifactCollection:
    """Intermediate structure: collected extractions from one artifact."""

    artifact_path: str
    raw_chunks: list[str] = field(default_factory=list)
    extracted_nodes: list[ExtractedNode] = field(default_factory=list)
    extracted_edges: list[ExtractedEdge] = field(default_factory=list)
    chunk_node_ids: list[str] = field(default_factory=list)


async def transform_scout_results(
    scout_results: list[ScoutResult],
    company_id: str,
    repo: BaseGraphRepository,
    seeded_rule_ids: Optional[set[str]] = None,
    seeded_goal_ids: Optional[set[str]] = None,
    seeded_goal_labels: Optional[dict[str, str]] = None,
) -> TransformSummary:
    """
    Run the full transform pipeline for a list of scout results.

    Uses a two-phase approach: first collect and write all nodes across all
    artifacts, then build a global node map (including seeded nodes from the
    repo) and resolve all edges at once.  This prevents silent edge-drops
    when an edge references a node from a different artifact or a seeded node.

    Args
    ----
    scout_results  Outputs from all parallel scout nodes
    company_id     Company being onboarded
    repo           Graph repository to write to

    Returns
    -------
    TransformSummary with nodes_written, edges_written, edges_dropped,
    chunks_written, errors
    """
    summary = TransformSummary()

    # ------------------------------------------------------------------
    # Phase A: Collect all extracted data from all scout results
    # ------------------------------------------------------------------
    collections: list[_ArtifactCollection] = []
    all_extracted_nodes: list[ExtractedNode] = []
    all_extracted_edges: list[ExtractedEdge] = []

    for result in scout_results:
        coll = _ArtifactCollection(
            artifact_path=result.artifact_path,
            raw_chunks=result.raw_chunks,
            extracted_nodes=result.extracted_nodes,
            extracted_edges=result.extracted_edges,
        )
        collections.append(coll)
        all_extracted_nodes.extend(result.extracted_nodes)
        all_extracted_edges.extend(result.extracted_edges)

    # ------------------------------------------------------------------
    # Phase B: Create and write all chunk nodes
    # ------------------------------------------------------------------
    for coll in collections:
        try:
            embeddings = None
            if coll.raw_chunks:
                embeddings = await embed_chunks(coll.raw_chunks)

            chunk_nodes = make_chunk_nodes(
                chunks=coll.raw_chunks,
                company_id=company_id,
                artifact_path=coll.artifact_path,
                embeddings=embeddings,
            )
            for chunk_node in chunk_nodes:
                await repo.write_node(chunk_node, company_id)
                summary.chunks_written += 1

            coll.chunk_node_ids = [n.id for n in chunk_nodes]
        except Exception as exc:
            msg = f"Chunk creation failed for {coll.artifact_path}: {exc}"
            logger.error(msg)
            summary.errors.append(msg)

    # ------------------------------------------------------------------
    # Phase B2: Create Artifact nodes and CONTAINS edges (Artifact→Chunk)
    # ------------------------------------------------------------------
    artifact_paths_seen: set[str] = set()
    for coll in collections:
        if not coll.chunk_node_ids or coll.artifact_path in artifact_paths_seen:
            continue
        artifact_paths_seen.add(coll.artifact_path)

        # Artifact ID: {company_id}:artifact:{hash_of_path}
        path_hash = hashlib.sha256(
            coll.artifact_path.encode("utf-8")
        ).hexdigest()[:16]
        artifact_node_id = make_node_id(
            company_id, NodeType.ARTIFACT, path_hash
        )

        artifact_node = Node(
            id=artifact_node_id,
            type=NodeType.ARTIFACT,
            label=coll.artifact_path.split("/")[-1] if "/" in coll.artifact_path else coll.artifact_path,
            properties={
                "artifact_path": coll.artifact_path,
                "content_hash": path_hash,
            },
            confidence=1.0,
        )
        try:
            await repo.write_node(artifact_node, company_id)
            summary.nodes_written += 1
        except Exception as exc:
            msg = f"Failed to write Artifact node for {coll.artifact_path}: {exc}"
            logger.error(msg)
            summary.errors.append(msg)
            continue

        # Create CONTAINS edges from Artifact → each Chunk
        for chunk_idx, chunk_id in enumerate(coll.chunk_node_ids):
            contains_edge = Edge(
                from_node=artifact_node_id,
                to_node=chunk_id,
                predicate=EdgePredicate.CONTAINS,
                properties={"chunk_index": chunk_idx},
                confidence=1.0,
            )
            try:
                await repo.write_edge(contains_edge, company_id)
                summary.edges_written += 1
            except Exception as exc:
                msg = f"Failed to write CONTAINS edge {artifact_node_id}->{chunk_id}: {exc}"
                logger.error(msg)
                summary.errors.append(msg)

    # ------------------------------------------------------------------
    # Phase C: Ontologize ALL nodes at once (dedup across artifacts)
    # ------------------------------------------------------------------
    all_chunk_ids: list[str] = []
    for coll in collections:
        all_chunk_ids.extend(coll.chunk_node_ids)

    try:
        domain_nodes, nodes_deduped = ontologize_nodes(
            extracted=all_extracted_nodes,
            company_id=company_id,
            source_chunk_ids=all_chunk_ids,
            seeded_rule_ids=seeded_rule_ids,
            seeded_goal_ids=seeded_goal_ids,
            seeded_goal_labels=seeded_goal_labels,
        )
        summary.nodes_deduped = nodes_deduped
    except Exception as exc:
        msg = f"Node ontologization failed: {exc}"
        logger.error(msg)
        summary.errors.append(msg)
        domain_nodes = []

    # ------------------------------------------------------------------
    # Phase D: Write all domain nodes to repo
    # ------------------------------------------------------------------
    for node in domain_nodes:
        try:
            await repo.write_node(node, company_id)
            summary.nodes_written += 1
        except Exception as exc:
            msg = f"Failed to write node {node.id}: {exc}"
            logger.error(msg)
            summary.errors.append(msg)

    # ------------------------------------------------------------------
    # Phase D2: Embed Decision node descriptions (Fix #5)
    #
    # Decision nodes need embeddings for vector similarity search
    # ("find past decisions similar to this new one"). Embed the
    # description/label and store in the decision_embeddings index.
    # ------------------------------------------------------------------
    decision_nodes = [n for n in domain_nodes if n.type == NodeType.DECISION]
    if decision_nodes:
        decision_texts = [
            n.properties.get("description", n.label) for n in decision_nodes
        ]
        try:
            decision_embeddings = await embed_chunks(decision_texts)
            if decision_embeddings:
                for node, emb in zip(decision_nodes, decision_embeddings):
                    node.embedding = emb
                    # Re-write node with embedding
                    await repo.write_node(node, company_id)
                logger.info(
                    f"Embedded {len(decision_nodes)} Decision node descriptions"
                )
        except Exception as exc:
            msg = f"Decision embedding failed: {exc}"
            logger.warning(msg)
            summary.errors.append(msg)

    # ------------------------------------------------------------------
    # Phase E: Build GLOBAL node_id_map (extracted + seeded nodes)
    # ------------------------------------------------------------------
    global_node_id_map = build_node_id_map(domain_nodes)

    # Merge in all existing nodes from the repo (includes seeded meta/schema
    # nodes and any previously written nodes).  Extracted nodes take priority
    # — repo entries do NOT overwrite freshly extracted ones.
    try:
        repo_node_ids = await repo.get_all_node_ids(company_id)
        for sem_suffix, full_id in repo_node_ids.items():
            if sem_suffix not in global_node_id_map:
                global_node_id_map[sem_suffix] = full_id
    except Exception as exc:
        msg = f"Failed to fetch existing node IDs from repo: {exc}"
        logger.warning(msg)
        summary.errors.append(msg)

    logger.info(
        f"Global node map built: {len(global_node_id_map)} entries "
        f"(company={company_id!r})"
    )

    # ------------------------------------------------------------------
    # Phase F: Ontologize ALL edges with the global map
    # ------------------------------------------------------------------
    # Build confidence map so edges inherit confidence from source nodes.
    # Seeded nodes (from repo) have no confidence field → default 1.0.
    global_confidence_map = build_node_confidence_map(domain_nodes)

    try:
        domain_edges, dropped = ontologize_edges(
            extracted=all_extracted_edges,
            company_id=company_id,
            node_id_map=global_node_id_map,
            node_confidence_map=global_confidence_map,
        )
        summary.edges_dropped = dropped
    except Exception as exc:
        msg = f"Edge ontologization failed: {exc}"
        logger.error(msg)
        summary.errors.append(msg)
        domain_edges = []

    for edge in domain_edges:
        try:
            await repo.write_edge(edge, company_id)
            summary.edges_written += 1
        except Exception as exc:
            msg = f"Failed to write edge {edge.from_node}->{edge.to_node}: {exc}"
            logger.error(msg)
            summary.errors.append(msg)

    # ------------------------------------------------------------------
    # Phase G: Write DERIVED_FROM provenance edges
    #
    # Each domain node is linked to ALL chunk nodes from every artifact
    # that contributed to its extraction — not just the first chunk.
    # ------------------------------------------------------------------
    # Build a set of normalized semantic IDs per artifact so we know which
    # domain nodes came from which artifact's chunks.
    for coll in collections:
        if not coll.chunk_node_ids:
            continue

        # Determine which domain nodes were extracted from this artifact
        artifact_sem_ids = {
            ext.semantic_id.strip().lower().replace(" ", "_")
            for ext in coll.extracted_nodes
        }
        for node in domain_nodes:
            node_sem = node.id.split(":")[-1].lower()
            if node_sem not in artifact_sem_ids:
                continue

            # Link this domain node to ALL chunks of this artifact
            for chunk_id in coll.chunk_node_ids:
                derived_edge = Edge(
                    from_node=node.id,
                    to_node=chunk_id,
                    predicate=EdgePredicate.DERIVED_FROM,
                    confidence=1.0,  # provenance edges are always certain
                    source_chunk_id=chunk_id,
                )
                try:
                    await repo.write_edge(derived_edge, company_id)
                    summary.edges_written += 1
                except Exception as exc:
                    msg = (
                        f"Failed to write DERIVED_FROM edge "
                        f"{node.id}->{chunk_id}: {exc}"
                    )
                    logger.error(msg)
                    summary.errors.append(msg)

    logger.info(
        f"Transform complete: company={company_id!r} "
        f"nodes={summary.nodes_written} nodes_deduped={summary.nodes_deduped} "
        f"edges={summary.edges_written} edges_dropped={summary.edges_dropped} "
        f"chunks={summary.chunks_written} errors={len(summary.errors)}"
    )
    return summary
