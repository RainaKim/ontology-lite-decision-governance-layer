"""
Ontologizer — converts ExtractedNode / ExtractedEdge into Node / Edge graph objects.

This is the bridge between unvalidated LLM output and the typed ontology models.
It enforces:
  - Valid NodeType (unknown types are skipped with a warning)
  - Stable node ID scheme via make_node_id()
  - Valid EdgePredicate (unknown predicates are skipped)
  - Deduplication: same (node_type, semantic_id) → same node ID
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

from app.ontology.edge_predicates import EDGE_REGISTRY, EdgePredicate
from app.ontology.models import Edge, Node, make_node_id
from app.ontology.node_types import NodeType
from app.onboarding.schemas import ExtractedEdge, ExtractedNode

logger = logging.getLogger(__name__)


def _flatten_properties(props: dict[str, Any]) -> dict[str, Any]:
    """Flatten nested dicts/lists-of-dicts to JSON strings for Neo4j compatibility."""
    flat = {}
    for k, v in props.items():
        if isinstance(v, dict):
            flat[k] = json.dumps(v)
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            flat[k] = json.dumps(v)
        else:
            flat[k] = v
    return flat


def _normalize_semantic_id(raw: str) -> str:
    """Normalize a semantic_id for map lookup: lowercase, strip, spaces to underscores."""
    return raw.strip().lower().replace(" ", "_")


# Regex for characters NOT allowed in semantic_id segment of a node ID
_INVALID_SEM_CHARS = re.compile(r"[^a-z0-9_.\-]")


def _sanitize_semantic_id(raw: str) -> str:
    """Sanitize an LLM-produced semantic_id into a valid node ID segment.

    Lowercases, replaces spaces with underscores, strips invalid chars,
    and collapses consecutive underscores. Returns empty string if nothing remains.
    """
    s = raw.strip().lower().replace(" ", "_")
    s = _INVALID_SEM_CHARS.sub("", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


# ---------------------------------------------------------------------------
# Deterministic entity deduplication — canonical ID normalization
# ---------------------------------------------------------------------------

_DEPARTMENT_SUFFIXES = {"_dept", "_department", "_team", "_group", "_division"}

_COMMON_ALIASES: dict[str, str] = {
    "nrr": "net_revenue_retention",
    "arr": "annual_recurring_revenue",
    "mrr": "monthly_recurring_revenue",
    "cac": "customer_acquisition_cost",
    "ltv": "lifetime_value",
}


def _canonical_semantic_id(node_type: str, raw_id: str) -> str:
    """Normalise a semantic ID to a canonical form for deduplication.

    Applies *after* basic sanitization so the input is already lowercase,
    underscore-separated, and free of invalid characters.

    Rules applied (in order):
      1. Strip department-style suffixes for Department nodes
      2. Expand common KPI abbreviations
      3. Remove filler word ``_and_`` and collapse double underscores
      4. Collapse underscore-digit variants (``soc_2`` → ``soc2``)
    """
    s = _sanitize_semantic_id(raw_id)

    # 1. Strip department suffixes
    if node_type == "Department":
        for suffix in _DEPARTMENT_SUFFIXES:
            if s.endswith(suffix):
                s = s[: -len(suffix)]
                break

    # 2. Expand common KPI abbreviations
    if node_type == "KPI" and s in _COMMON_ALIASES:
        s = _COMMON_ALIASES[s]

    # 3. Collapse filler words and double underscores
    s = s.replace("_and_", "_").replace("__", "_").rstrip("_")

    # 4. Normalize underscore-digit variants (soc_2 → soc2)
    s = re.sub(r"_(\d)", r"\1", s)

    return s


# ---------------------------------------------------------------------------
# Temporal inference patterns (Change 4.3)
# Purely structural patterns — no semantic classification keywords.
# Per review S4: "freeze" is excluded (semantic, not structural).
# ---------------------------------------------------------------------------

_TEMPORAL_QUARTER_RE = re.compile(r"\bQ([1-4])\b", re.IGNORECASE)
_TEMPORAL_HALF_RE = re.compile(r"\bH([12])\b", re.IGNORECASE)
_TEMPORAL_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_TEMPORAL_ANNUAL_RE = re.compile(r"\bannual\b", re.IGNORECASE)
_TEMPORAL_QUARTERLY_RE = re.compile(r"\bquarterly\b", re.IGNORECASE)
_TEMPORAL_PERMANENT_RE = re.compile(r"\bpermanent\b", re.IGNORECASE)


def _infer_temporal_fields(ext: ExtractedNode, props: dict[str, Any]) -> None:
    """
    Infer temporal_scope from label/properties when not already set.

    Only applies to Goal and Rule nodes. Uses unambiguous structural patterns:
    Q[1-4], H[12], 20XX, annual, quarterly, permanent.

    Sets confidence to 0.6 for inferred temporal values by storing a
    ``_temporal_inferred`` flag in properties.
    """
    if props.get("temporal_scope"):
        return  # Already set — do not override

    # Combine label + description + source_excerpt for scanning
    text_to_scan = " ".join(filter(None, [
        ext.label,
        props.get("description", ""),
        ext.source_excerpt,
        props.get("name", ""),
    ]))

    inferred_scope: Optional[str] = None

    m = _TEMPORAL_QUARTER_RE.search(text_to_scan)
    if m:
        inferred_scope = f"Q{m.group(1)}"
    elif _TEMPORAL_HALF_RE.search(text_to_scan):
        m2 = _TEMPORAL_HALF_RE.search(text_to_scan)
        inferred_scope = f"H{m2.group(1)}"
    elif _TEMPORAL_ANNUAL_RE.search(text_to_scan):
        inferred_scope = "annual"
    elif _TEMPORAL_QUARTERLY_RE.search(text_to_scan):
        inferred_scope = "quarterly"  # recurring quarterly — map to nearest scope
    elif _TEMPORAL_PERMANENT_RE.search(text_to_scan):
        inferred_scope = "permanent"

    if inferred_scope:
        props["temporal_scope"] = inferred_scope
        props["_temporal_inferred"] = True
        logger.debug(
            f"Temporal inference: '{ext.semantic_id}' → temporal_scope={inferred_scope}"
        )

    # Infer effective_date from year references if not already set
    if not props.get("effective_date"):
        m_year = _TEMPORAL_YEAR_RE.search(text_to_scan)
        if m_year:
            props["effective_date"] = f"{m_year.group(1)}-01-01"
            props["_temporal_inferred"] = True


def _match_seeded_rule(
    ext: ExtractedNode,
    seeded_rule_ids: set[str],
) -> Optional[str]:
    """
    Check if an LLM-extracted Rule references a known seeded rule_id.

    Checks the semantic_id, label, description, and properties for mentions
    of seeded rule IDs (e.g. "R1", "R2"). Returns the matching rule_id if found,
    None otherwise.
    """
    # Normalize seeded IDs to lowercase for case-insensitive matching
    seeded_lower = {rid.lower(): rid for rid in seeded_rule_ids}

    # Check if semantic_id IS a seeded rule_id
    sem_lower = ext.semantic_id.strip().lower()
    if sem_lower in seeded_lower:
        return seeded_lower[sem_lower]

    # Check if properties contain a rule_id reference
    rule_id_prop = ext.properties.get("rule_id", "")
    if isinstance(rule_id_prop, str) and rule_id_prop.strip().lower() in seeded_lower:
        return seeded_lower[rule_id_prop.strip().lower()]

    # Check if label or description references a seeded rule_id
    text_fields = " ".join(filter(None, [
        ext.label,
        ext.properties.get("description", ""),
        ext.source_excerpt,
    ]))
    for rid_lower, rid_original in seeded_lower.items():
        # Match word-boundary rule_id references (e.g. "R1" but not "R10" matching "R1")
        pattern = re.compile(rf"\b{re.escape(rid_lower)}\b", re.IGNORECASE)
        if pattern.search(text_fields):
            return rid_original

    return None


def _normalize_label(label: str) -> str:
    """Normalize a label for fuzzy comparison: lowercase, strip, remove filler words."""
    s = label.strip().lower()
    # Remove common filler words that don't change meaning
    for filler in ("improvement", "initiative", "program", "project", "plan",
                   "strategy", "objective", "target", "increase", "enhancement"):
        s = s.replace(filler, "")
    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _label_matches_seeded(extracted_label: str, seeded_label: str) -> bool:
    """
    Check if an extracted label is a near-duplicate of a seeded goal label.

    Returns True if:
      - normalized extracted label contains normalized seeded label, or vice versa
      - they share enough significant words (>=2 words in common out of seeded words)
    """
    norm_ext = _normalize_label(extracted_label)
    norm_seed = _normalize_label(seeded_label)

    if not norm_ext or not norm_seed:
        return False

    # Direct containment check
    if norm_seed in norm_ext or norm_ext in norm_seed:
        return True

    # Word overlap check: if extracted shares all significant words with seeded
    seed_words = set(norm_seed.split())
    ext_words = set(norm_ext.split())
    if len(seed_words) >= 2:
        overlap = seed_words & ext_words
        if len(overlap) >= len(seed_words):
            return True

    return False


def _match_seeded_goal(
    ext: ExtractedNode,
    seeded_goal_ids: set[str],
    seeded_goal_labels: Optional[dict[str, str]] = None,
) -> Optional[str]:
    """
    Check if an LLM-extracted Goal is a near-duplicate of a seeded goal.

    Checks the semantic_id, label, and properties for mentions of seeded
    goal IDs (e.g. "G1", "G2") or their canonical slugs. Also checks
    label similarity when seeded_goal_labels is provided.

    Args
    ----
    ext                 Extracted node to check
    seeded_goal_ids     Set of goal_id strings (e.g. {"G1", "G2"})
    seeded_goal_labels  Optional mapping of goal_id → label (e.g. {"G1": "Revenue Growth"})

    Returns the matching goal_id if found, None otherwise.
    """
    seeded_lower = {gid.lower(): gid for gid in seeded_goal_ids}

    # Check if semantic_id IS a seeded goal_id
    sem_lower = ext.semantic_id.strip().lower()
    if sem_lower in seeded_lower:
        return seeded_lower[sem_lower]

    # Check if properties contain a goal_id reference
    goal_id_prop = ext.properties.get("goal_id", "")
    if isinstance(goal_id_prop, str) and goal_id_prop.strip().lower() in seeded_lower:
        return seeded_lower[goal_id_prop.strip().lower()]

    # Check if label or description references a seeded goal_id
    text_fields = " ".join(filter(None, [
        ext.label,
        ext.properties.get("description", ""),
        ext.source_excerpt,
    ]))
    for gid_lower, gid_original in seeded_lower.items():
        pattern = re.compile(rf"\b{re.escape(gid_lower)}\b", re.IGNORECASE)
        if pattern.search(text_fields):
            return gid_original

    # --- Label similarity matching (V4 Fix #2) ---
    if seeded_goal_labels and ext.label:
        for gid, seeded_label in seeded_goal_labels.items():
            if _label_matches_seeded(ext.label, seeded_label):
                logger.debug(
                    f"Label match: extracted Goal '{ext.label}' matches "
                    f"seeded goal '{seeded_label}' ({gid})"
                )
                return gid

    return None


# ---------------------------------------------------------------------------
# Decision-vs-Rule reclassification heuristic (V4 Fix #4)
# ---------------------------------------------------------------------------

# Patterns that indicate a specific event/decision, not a reusable rule.
# These are structural patterns, not semantic keywords.
_SPECIFIC_DECISION_PATTERNS = [
    re.compile(r"\b(20\d{2})\b"),              # year reference (e.g. "2024")
    re.compile(r"\bQ[1-4]\s+\d{4}\b", re.I),   # "Q2 2024"
    re.compile(r"\b(contract|partnership|agreement)\s+\w+\b", re.I),  # "contract approval"
    re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d", re.I),  # date ref
]

# Words that strongly suggest a specific instance, not a reusable policy
_INSTANCE_INDICATORS = re.compile(
    r"\b(approval|approved|rejected|purchased|hired|signed|completed|"
    r"terminated|renewed|cancelled|negotiated)\b",
    re.IGNORECASE,
)


def _is_specific_decision_not_rule(ext: ExtractedNode) -> bool:
    """
    Heuristic to detect if an LLM-extracted 'Rule' is actually a specific
    decision instance that should be reclassified as a Decision node.

    Returns True if the node's label/description contains patterns indicating
    a specific event rather than a reusable governance policy.
    """
    text = " ".join(filter(None, [
        ext.label,
        ext.properties.get("description", ""),
        ext.source_excerpt,
    ]))

    # Check for proper noun patterns (capitalized multi-word names that look like
    # company/project names, e.g. "TestCo Contract Approval")
    # A Rule label should be generic like "CFO approval for large spend"
    words = ext.label.split() if ext.label else []
    capitalized_words = [w for w in words if w[0].isupper() and len(w) > 1] if words else []

    # If most words are capitalized and it contains an instance indicator, it's likely a decision
    has_instance_indicator = bool(_INSTANCE_INDICATORS.search(text))
    has_date_or_specific = any(p.search(text) for p in _SPECIFIC_DECISION_PATTERNS)

    # Strong signal: both a specific date/entity AND an action verb
    if has_date_or_specific and has_instance_indicator:
        return True

    # If the label looks like a specific named event (3+ capitalized words with action)
    if len(capitalized_words) >= 3 and has_instance_indicator:
        return True

    return False


# Domain-layer and instance-layer node types the scouts are allowed to create.
# Decision is instance-layer (CREATE semantics) but extracted during onboarding
# from past_decisions.json and approval_logs.csv.
_ALLOWED_NODE_TYPES = {
    "Goal", "Rule", "Decision", "Actor", "Department", "KPI",
    "Jurisdiction", "Gap", "Conflict", "GovernanceRisk",
}

# Map predicate strings to EdgePredicate enum members
_PREDICATE_MAP: dict[str, EdgePredicate] = {
    ep.value: ep for ep in EdgePredicate
}


def ontologize_nodes(
    extracted: list[ExtractedNode],
    company_id: str,
    source_chunk_ids: Optional[list[str]] = None,
    seeded_rule_ids: Optional[set[str]] = None,
    seeded_goal_ids: Optional[set[str]] = None,
    seeded_goal_labels: Optional[dict[str, str]] = None,
) -> tuple[list[Node], int]:
    """
    Convert a list of ExtractedNode objects to Node objects.

    Skips nodes with invalid or unsupported node types.
    Deduplicates by canonical node ID — when two extracted nodes map to the
    same canonical ID, the one with **higher confidence** is kept.

    Seeded-rule-ID matching: when ``seeded_rule_ids`` is provided and a Rule
    node's label, description, properties, or semantic_id references a known
    seeded rule_id (e.g. "R1"), the extracted node is skipped as a duplicate
    of the seeded rule.

    Seeded-goal-ID matching: when ``seeded_goal_ids`` is provided and a Goal
    node references a known seeded goal_id (e.g. "G1"), the extracted node
    is skipped as a duplicate of the seeded goal. Also matches by label
    similarity when ``seeded_goal_labels`` is provided.

    Rule→Decision reclassification: when an extracted Rule node's label
    indicates a specific event (contains dates, contract references, etc.),
    it is reclassified as a Decision node.

    Args
    ----
    extracted          LLM-extracted nodes
    company_id         Company prefix for node IDs
    source_chunk_ids   Chunk node IDs to attach as provenance
    seeded_rule_ids    Set of rule_id strings from CompanyConfig (e.g. {"R1","R2",...})
    seeded_goal_ids    Set of goal_id strings from CompanyConfig (e.g. {"G1","G2",...})
    seeded_goal_labels Mapping of goal_id → label for label similarity matching

    Returns
    -------
    Tuple of (validated Node list ready for write_node(), dedup count)
    """
    # Maps canonical node_id → (index in nodes list, confidence)
    seen: dict[str, tuple[int, float]] = {}
    nodes: list[Node] = []
    deduped = 0
    _seeded_rules = seeded_rule_ids or set()
    _seeded_goals = seeded_goal_ids or set()
    _seeded_goal_labels = seeded_goal_labels or {}

    for ext in extracted:
        if ext.node_type not in _ALLOWED_NODE_TYPES:
            logger.warning(f"Skipping unsupported node_type '{ext.node_type}'")
            continue

        try:
            node_type = NodeType(ext.node_type)
        except ValueError:
            logger.warning(f"Unknown NodeType '{ext.node_type}' — skipping")
            continue

        # --- Seeded-rule-ID matching (Change 3.2) ---
        if ext.node_type == "Rule" and _seeded_rules:
            matched_rule_id = _match_seeded_rule(ext, _seeded_rules)
            if matched_rule_id:
                logger.info(
                    f"Rule dedup: extracted Rule '{ext.semantic_id}' / '{ext.label}' "
                    f"matches seeded rule '{matched_rule_id}' — skipping duplicate"
                )
                deduped += 1
                continue

        # --- Seeded-goal-ID matching (Fix #2) ---
        if ext.node_type == "Goal" and _seeded_goals:
            matched_goal_id = _match_seeded_goal(
                ext, _seeded_goals, _seeded_goal_labels
            )
            if matched_goal_id:
                logger.info(
                    f"Goal dedup: extracted Goal '{ext.semantic_id}' / '{ext.label}' "
                    f"matches seeded goal '{matched_goal_id}' — skipping duplicate"
                )
                deduped += 1
                continue

        # --- Rule → Decision reclassification (V4 Fix #4) ---
        if ext.node_type == "Rule" and _is_specific_decision_not_rule(ext):
            logger.info(
                f"Reclassify: extracted Rule '{ext.semantic_id}' / '{ext.label}' "
                f"appears to be a specific decision — reclassifying as Decision"
            )
            ext = ExtractedNode(
                node_type="Decision",
                semantic_id=ext.semantic_id,
                label=ext.label,
                properties=ext.properties,
                confidence=ext.confidence,
                source_excerpt=ext.source_excerpt,
                effective_date=ext.effective_date,
                expiry_date=ext.expiry_date,
                temporal_scope=ext.temporal_scope,
                recurring=ext.recurring,
            )

        canonical_sem = _canonical_semantic_id(ext.node_type, ext.semantic_id)
        if not canonical_sem:
            logger.warning(
                f"Semantic ID '{ext.semantic_id}' for {ext.node_type} "
                "is empty after canonicalization — skipping"
            )
            continue

        try:
            node_id = make_node_id(company_id, node_type, canonical_sem)
        except ValueError as exc:
            logger.warning(f"Invalid node ID for {ext.node_type}/{ext.semantic_id}: {exc}")
            continue

        props = _flatten_properties(ext.properties)
        if ext.source_excerpt:
            props["source_excerpt"] = ext.source_excerpt

        # Promote temporal fields from ExtractedNode to properties
        if ext.effective_date:
            props["effective_date"] = ext.effective_date
        if ext.expiry_date:
            props["expiry_date"] = ext.expiry_date
        if ext.temporal_scope:
            props["temporal_scope"] = ext.temporal_scope
        if ext.recurring is not None:
            props["recurring"] = ext.recurring

        # Normalize gap_type to snake_case for Gap nodes
        if ext.node_type == "Gap" and "gap_type" in props:
            props["gap_type"] = props["gap_type"].strip().lower().replace(" ", "_").replace("-", "_")

        # --- Temporal inference (Change 4.3) ---
        if ext.node_type in ("Goal", "Rule"):
            _infer_temporal_fields(ext, props)

        new_node = Node(
            id=node_id,
            type=node_type,
            label=ext.label,
            properties=props,
            confidence=ext.confidence,
            source_chunk_ids=list(source_chunk_ids or []),
        )

        if node_id in seen:
            # Keep the higher-confidence version
            existing_idx, existing_conf = seen[node_id]
            if ext.confidence > existing_conf:
                logger.debug(
                    f"Dedup: replacing '{node_id}' (conf {existing_conf:.2f}) "
                    f"with higher-confidence version ({ext.confidence:.2f})"
                )
                nodes[existing_idx] = new_node
                seen[node_id] = (existing_idx, ext.confidence)
            else:
                logger.debug(f"Dedup: discarding duplicate '{node_id}' (conf {ext.confidence:.2f})")
            deduped += 1
            continue

        seen[node_id] = (len(nodes), ext.confidence)
        nodes.append(new_node)

    if deduped:
        logger.info(
            f"ontologize_nodes: {deduped} duplicate(s) resolved for "
            f"company={company_id!r} ({len(nodes)} unique nodes)"
        )

    return nodes, deduped


def _resolve_endpoint(
    bare_key: str,
    predicate: EdgePredicate,
    role: str,  # "domain" or "range"
    node_id_map: dict[str, str],
) -> Optional[str]:
    """
    Resolve a semantic_id to a full node_id, handling ambiguous bare keys.

    When the bare key maps to _AMBIGUOUS_SENTINEL, iterate the predicate's
    domain/range types from EDGE_REGISTRY and try type-prefixed lookups.
    """
    direct = node_id_map.get(bare_key)
    if direct is not None and direct != _AMBIGUOUS_SENTINEL:
        return direct

    if direct == _AMBIGUOUS_SENTINEL:
        # Try type-prefixed lookups using EDGE_REGISTRY hints
        meta = EDGE_REGISTRY.get(predicate)
        if meta:
            candidate_types = meta.domain_types if role == "domain" else meta.range_types
            for nt in candidate_types:
                prefixed_key = f"{nt.value.lower()}:{bare_key}"
                resolved = node_id_map.get(prefixed_key)
                if resolved is not None:
                    return resolved
        # All type-prefixed attempts failed — return None
        logger.warning(
            f"Ambiguous bare key '{bare_key}' could not be resolved "
            f"via type-prefixed lookup for predicate {predicate.value} ({role})"
        )
        return None

    # Not found at all — try type-prefixed as last resort
    meta = EDGE_REGISTRY.get(predicate)
    if meta:
        candidate_types = meta.domain_types if role == "domain" else meta.range_types
        for nt in candidate_types:
            prefixed_key = f"{nt.value.lower()}:{bare_key}"
            resolved = node_id_map.get(prefixed_key)
            if resolved is not None:
                return resolved

    return None


def ontologize_edges(
    extracted: list[ExtractedEdge],
    company_id: str,
    node_id_map: dict[str, str],
    node_confidence_map: Optional[dict[str, float]] = None,
) -> tuple[list[Edge], int]:
    """
    Convert a list of ExtractedEdge objects to Edge objects.

    Args
    ----
    extracted            LLM-extracted edges
    company_id           Used for logging context
    node_id_map          Maps semantic_id → node_id (built from ontologize_nodes output)
    node_confidence_map  Maps node_id → confidence (for deriving edge confidence)

    Returns
    -------
    Tuple of (validated Edge objects ready for write_edge(), count of dropped edges)
    """
    edges: list[Edge] = []
    seen: set[tuple] = set()
    dropped = 0
    conf_map = node_confidence_map or {}

    for ext in extracted:
        from_key = _normalize_semantic_id(ext.from_semantic_id)
        to_key = _normalize_semantic_id(ext.to_semantic_id)

        predicate = _PREDICATE_MAP.get(ext.predicate)
        if predicate is None:
            logger.warning(f"Unknown edge predicate '{ext.predicate}' — skipping")
            dropped += 1
            continue

        # Resolve endpoints, using type-prefixed lookup for ambiguous bare keys
        from_id = _resolve_endpoint(
            from_key, predicate, "domain", node_id_map
        )
        to_id = _resolve_endpoint(
            to_key, predicate, "range", node_id_map
        )

        if not from_id:
            logger.warning(
                f"Edge dropped: from_semantic_id '{ext.from_semantic_id}' "
                f"not found in node map (company={company_id})"
            )
            dropped += 1
            continue
        if not to_id:
            logger.warning(
                f"Edge dropped: to_semantic_id '{ext.to_semantic_id}' "
                f"not found in node map (company={company_id})"
            )
            dropped += 1
            continue

        # --- Block Rule→Rule GOVERNED_BY (Fix #4) ---
        # Rules govern goals, not other rules. This is semantically wrong.
        if predicate == EdgePredicate.GOVERNED_BY:
            from_type_check = _node_type_from_id(from_id)
            to_type_check = _node_type_from_id(to_id)
            if (from_type_check == NodeType.RULE and to_type_check == NodeType.RULE):
                logger.warning(
                    f"Edge dropped: Rule→Rule GOVERNED_BY is not allowed "
                    f"({from_id} → {to_id})"
                )
                dropped += 1
                continue

        # --- Edge validation against EDGE_REGISTRY (Change 3.3) ---
        # Check source/target node types against domain/range constraints.
        # Soft check: drop and log, never crash.
        registry_meta = EDGE_REGISTRY.get(predicate)
        if registry_meta:
            from_type = _node_type_from_id(from_id)
            to_type = _node_type_from_id(to_id)
            if from_type and from_type not in registry_meta.domain_types:
                logger.warning(
                    f"Edge dropped: {predicate.value} from '{from_id}' "
                    f"(type={from_type.value}) violates domain constraint "
                    f"(allowed: {[t.value for t in registry_meta.domain_types]})"
                )
                dropped += 1
                continue
            if to_type and to_type not in registry_meta.range_types:
                logger.warning(
                    f"Edge dropped: {predicate.value} to '{to_id}' "
                    f"(type={to_type.value}) violates range constraint "
                    f"(allowed: {[t.value for t in registry_meta.range_types]})"
                )
                dropped += 1
                continue

        key = (from_id, to_id, predicate.value)
        if key in seen:
            continue
        seen.add(key)

        props = {}
        if ext.evidence:
            props["evidence"] = ext.evidence

        # Derive edge confidence from the source node's confidence.
        # Use the minimum of from/to node confidence when both are available.
        from_conf = conf_map.get(from_id)
        to_conf = conf_map.get(to_id)
        if from_conf is not None and to_conf is not None:
            edge_confidence = min(from_conf, to_conf)
        elif from_conf is not None:
            edge_confidence = from_conf
        elif to_conf is not None:
            edge_confidence = to_conf
        else:
            edge_confidence = 1.0  # default for seeded/unknown nodes

        # --- Edge-level confidence enhancement (Change 5.3) ---
        # If evidence is empty or < 10 chars, apply 0.9 multiplier
        if not ext.evidence or len(ext.evidence.strip()) < 10:
            edge_confidence *= 0.9

        # Store confidence in properties as well for persistence through Neo4j
        props["confidence"] = round(edge_confidence, 4)

        edges.append(
            Edge(
                from_node=from_id,
                to_node=to_id,
                predicate=predicate,
                properties=props or None,
                confidence=edge_confidence,
            )
        )

    if dropped:
        logger.warning(
            f"ontologize_edges: {dropped} edge(s) dropped for company={company_id} "
            f"({len(edges)} resolved successfully)"
        )

    return edges, dropped


def build_node_id_map(nodes: list[Node]) -> dict[str, str]:
    """
    Build a mapping from semantic_id slug → full node_id.

    Used by ontologize_edges() to resolve edge endpoints.

    Adds BOTH bare key and type-prefixed key for each node:
      - "engineering" → "nexus:department:engineering"
      - "department:engineering" → "nexus:department:engineering"

    When a bare key collides (multiple node types share the same semantic_id),
    the bare key is marked as _AMBIGUOUS so callers must use type-prefixed lookup.
    """
    result: dict[str, str] = {}
    bare_key_types: dict[str, list[str]] = {}  # bare_key → list of node_ids

    for node in nodes:
        parts = node.id.split(":")
        if len(parts) < 3:
            continue
        bare_key = parts[-1].lower()
        node_type_slug = parts[1].lower()
        type_prefixed_key = f"{node_type_slug}:{bare_key}"

        # Type-prefixed key always wins (no collisions possible)
        result[type_prefixed_key] = node.id

        # Track bare key for collision detection
        bare_key_types.setdefault(bare_key, []).append(node.id)

    # Assign bare keys: if unique, set directly; if ambiguous, mark sentinel
    for bare_key, node_ids in bare_key_types.items():
        if len(node_ids) == 1:
            result[bare_key] = node_ids[0]
        else:
            # Ambiguous bare key — store sentinel so ontologize_edges knows
            # to try type-prefixed lookup instead
            result[bare_key] = _AMBIGUOUS_SENTINEL
            logger.debug(
                f"Bare key '{bare_key}' is ambiguous — "
                f"maps to {len(node_ids)} nodes: {node_ids}"
            )

    return result


# Sentinel value for ambiguous bare keys in node_id_map
_AMBIGUOUS_SENTINEL = "__AMBIGUOUS__"


def _node_type_from_id(node_id: str) -> Optional[NodeType]:
    """
    Extract NodeType from a full node ID string.

    Node ID format: {company_id}:{type_slug}:{semantic_id}
    The type_slug is the lowercase version of NodeType.value.
    Returns None if the type cannot be determined.
    """
    parts = node_id.split(":")
    if len(parts) < 3:
        return None
    type_slug = parts[1]
    # Build a reverse lookup from lowercase value to NodeType
    for nt in NodeType:
        if nt.value.lower() == type_slug:
            return nt
    return None


def build_node_confidence_map(nodes: list[Node]) -> dict[str, float]:
    """
    Build a mapping from node_id → confidence score.

    Used by ontologize_edges() to derive edge confidence from source nodes.
    Nodes without a confidence value (manually authored / seeded) default to 1.0.
    """
    return {
        node.id: (node.confidence if node.confidence is not None else 1.0)
        for node in nodes
    }
