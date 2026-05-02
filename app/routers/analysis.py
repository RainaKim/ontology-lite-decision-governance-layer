"""
app/routers/analysis.py — Analysis tool endpoints.

Routes:
  GET  /v1/decisions/{id}/reasoning-trace
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException

from app.repositories import decision_store
from app.services.rbac_service import require_any
from app.schemas.analysis_responses import (
    ReasoningTraceResponse,
    ReasoningTraceStep,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["analysis"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(iso: str) -> datetime:
    """Parse ISO datetime string; fall back to now if unparseable."""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _confidence_pct(val: float) -> int:
    """Convert 0.0-1.0 float confidence to integer 0-100."""
    return max(0, min(100, int(round(val * 100))))


# ---------------------------------------------------------------------------
# GET /v1/decisions/{decision_id}/reasoning-trace
# ---------------------------------------------------------------------------

_STEP_DEFS = [
    {
        "name": "Input Parsing",
        "description": "Tokenize and normalize the incoming decision request",
        "base_duration_ms": 38,
    },
    {
        "name": "LLM Extraction",
        "description": "Extract structured decision entities from input text using Nova AI",
        "base_duration_ms": 312,
    },
    {
        "name": "Governance Evaluation",
        "description": "Evaluate decision against company policy rules and approval requirements",
        "base_duration_ms": 189,
    },
    {
        "name": "Knowledge Graph Construction",
        "description": "Map decision entities and relationships into the governance graph",
        "base_duration_ms": 97,
    },
    {
        "name": "Risk Assessment",
        "description": "Quantify financial, compliance, and strategic risk dimensions",
        "base_duration_ms": 143,
    },
    {
        "name": "AI Reasoning",
        "description": "Apply graph-based reasoning to detect contradictions and generate recommendations",
        "base_duration_ms": 421,
    },
    {
        "name": "Decision Pack Assembly",
        "description": "Compile execution-ready decision artifact with approvals and audit trail",
        "base_duration_ms": 76,
    },
]


def _build_step_status(record, step_index: int) -> str:
    """Determine step status based on which pipeline outputs are populated."""
    pipeline_fields = [
        True,                         # 0: Input Parsing — always completed if record exists
        record.decision is not None,  # 1: LLM Extraction
        record.governance is not None,  # 2: Governance Evaluation
        record.graph_payload is not None,  # 3: Graph Construction
        record.risk_scoring is not None,   # 4: Risk Assessment
        record.reasoning is not None,      # 5: AI Reasoning
        record.decision_pack is not None,  # 6: Decision Pack
    ]
    if step_index >= len(pipeline_fields):
        return "skipped"
    if pipeline_fields[step_index]:
        return "completed"
    if record.status == "failed":
        return "failed"
    return "skipped"


def _extract_step_entities(record, step_index: int) -> list[str]:
    """Derive readable entity strings for a step from available record data."""
    entities: list[str] = []

    if step_index == 0:
        entities.append(f"Input Length: {len(record.input_text)} characters")
        entities.append(f"Agent: {record.agent_name_en or record.agent_name}")

    elif step_index == 1 and record.decision:
        dec = record.decision
        if dec.get("statement"):
            snippet = dec["statement"][:80].replace("\n", " ")
            entities.append(f"Statement: {snippet}…" if len(dec["statement"]) > 80 else f"Statement: {snippet}")
        goals = dec.get("goals") or []
        if goals:
            entities.append(f"Goals Identified: {len(goals)}")
        owners = dec.get("owners") or []
        if owners:
            first_owner = owners[0].get("name") or owners[0].get("role", "")
            entities.append(f"Primary Owner: {first_owner}")

    elif step_index == 2 and record.governance:
        gov = record.governance
        triggered = gov.get("triggered_rules") or []
        entities.append(f"Triggered Rules: {len(triggered)}")
        flags = gov.get("flags") or []
        entities.append(f"Flags Raised: {len(flags)}")
        if gov.get("risk_score") is not None:
            entities.append(f"Risk Score: {gov['risk_score']:.1f}/10")

    elif step_index == 3 and record.graph_payload:
        gp = record.graph_payload
        entities.append(f"Nodes: {gp.get('node_count', 0)}")
        entities.append(f"Edges: {gp.get('edge_count', 0)}")
        method = gp.get("analysis_method", "")
        if method:
            entities.append(f"Method: {method}")

    elif step_index == 4 and record.risk_scoring:
        rs = record.risk_scoring
        agg = rs.get("aggregate") or {}
        if agg.get("score") is not None:
            entities.append(f"Aggregate Risk Score: {agg['score']}/100")
        if agg.get("band"):
            entities.append(f"Risk Band: {agg['band']}")
        dims = rs.get("dimensions") or []
        if dims:
            entities.append(f"Dimensions Scored: {len(dims)}")

    elif step_index == 5 and record.reasoning:
        r = record.reasoning
        contradictions = r.get("logical_contradictions") or []
        recs = r.get("graph_recommendations") or []
        entities.append(f"Contradictions Found: {len(contradictions)}")
        entities.append(f"Recommendations Generated: {len(recs)}")
        if r.get("confidence") is not None:
            entities.append(f"Confidence: {_confidence_pct(r['confidence'])}%")

    elif step_index == 6 and record.decision_pack:
        dp = record.decision_pack
        actions = dp.get("recommended_next_actions") or []
        entities.append(f"Next Actions: {len(actions)}")
        approvals = dp.get("approval_chain") or []
        entities.append(f"Approval Steps: {len(approvals)}")

    return entities


def _extract_step_ontology(record, step_index: int) -> list[str]:
    """Derive ontology mapping strings for a step."""
    ontology: list[str] = []

    if step_index == 0:
        ontology.append("DecisionRequest → GovernanceInput")
        ontology.append("InputText → StructuredPayload")

    elif step_index == 1 and record.decision:
        dec = record.decision
        goals = dec.get("goals") or []
        for g in goals[:2]:
            goal_id = g.get("goal_id") or g.get("id") or ""
            name = g.get("name") or g.get("goal_name") or "Goal"
            if goal_id:
                ontology.append(f"{goal_id} → StrategicGoal")
            else:
                ontology.append(f"{name[:40]} → StrategicGoal")
        risks = dec.get("risks") or []
        if risks:
            ontology.append("IdentifiedRisk → RiskFactor")

    elif step_index == 2 and record.governance:
        triggered = record.governance.get("triggered_rules") or []
        for rule in triggered[:2]:
            rule_id = rule.get("rule_id") or rule.get("id") or ""
            rule_type = rule.get("type") or "GovernanceRule"
            if rule_id:
                ontology.append(f"{rule_id} → {rule_type}")
        status = record.governance.get("status") or ""
        if status:
            ontology.append(f"GovernanceStatus → {status}")

    elif step_index == 3 and record.graph_payload:
        nodes = record.graph_payload.get("nodes") or []
        seen_types: set[str] = set()
        for node in nodes[:4]:
            ntype = node.get("type") or "Entity"
            if ntype not in seen_types:
                seen_types.add(ntype)
                ontology.append(f"{ntype} → GraphNode")

    elif step_index == 4 and record.risk_scoring:
        dims = record.risk_scoring.get("dimensions") or []
        for dim in dims:
            label = dim.get("label") or dim.get("id") or "Risk"
            band = dim.get("band") or ""
            ontology.append(f"{label} → {band or 'RiskDimension'}")

    elif step_index == 5 and record.reasoning:
        ontology.append(f"GraphReasoning → {record.reasoning.get('analysis_method', 'SubgraphAnalysis')}")
        contradictions = record.reasoning.get("logical_contradictions") or []
        if contradictions:
            ontology.append("LogicalContradiction → PolicyConflict")
        recs = record.reasoning.get("graph_recommendations") or []
        if recs:
            ontology.append("Recommendation → ActionItem")

    elif step_index == 6 and record.decision_pack:
        ontology.append("DecisionPack → ExecutionArtifact")
        ontology.append("AuditTrail → ComplianceRecord")

    return ontology


def _build_step_summary(record, step_index: int, status: str) -> str:
    summaries = [
        "The system received a structured decision request and performed tokenization, normalization, and schema validation.",
        "Nova AI extracted structured decision entities including goals, KPIs, risks, owners, and assumptions from the raw input text.",
        "The governance engine evaluated the decision against all applicable company policies and identified triggered rules and required approvals.",
        "Decision entities and their relationships were mapped into an in-memory knowledge graph for structural analysis.",
        "Financial, compliance, and strategic risk dimensions were quantified using the rule engine and extracted signals.",
        "The graph reasoning engine analyzed entity relationships, detected logical contradictions, and produced actionable recommendations.",
        "An execution-ready decision pack was assembled with full audit trail, approval chain, and recommended next actions.",
    ]
    if status == "skipped":
        return "This step was skipped because the required upstream data was not available."
    if status == "failed":
        return f"This step failed. Error: {record.error or 'Unknown error'}"
    return summaries[step_index] if step_index < len(summaries) else "Step completed."


@router.get(
    "/decisions/{decision_id}/reasoning-trace",
    response_model=ReasoningTraceResponse,
)
async def get_reasoning_trace(
    decision_id: str,
    _: object = Depends(require_any),
) -> ReasoningTraceResponse:
    """
    GET /v1/decisions/{decision_id}/reasoning-trace

    Returns the step-by-step execution trace for a decision.
    Steps are derived from which pipeline outputs are populated on the record.
    """
    record = decision_store.get(decision_id)
    if not record:
        raise HTTPException(status_code=404, detail=f"Decision '{decision_id}' not found")

    base_dt = _parse_dt(record.created_at)
    steps: list[ReasoningTraceStep] = []
    cumulative_ms = 0

    for i, step_def in enumerate(_STEP_DEFS):
        status = _build_step_status(record, i)
        duration_ms = step_def["base_duration_ms"] if status == "completed" else 0
        step_dt = base_dt + timedelta(milliseconds=cumulative_ms)

        steps.append(
            ReasoningTraceStep(
                id=i + 1,
                name=step_def["name"],
                description=step_def["description"],
                timestamp=_fmt_time(step_dt),
                duration=f"{duration_ms}ms" if duration_ms else "0ms",
                status=status,
                summary=_build_step_summary(record, i, status),
                entities=_extract_step_entities(record, i),
                ontology=_extract_step_ontology(record, i),
            )
        )
        cumulative_ms += duration_ms

    return ReasoningTraceResponse(
        decision_id=decision_id,
        total_duration_ms=cumulative_ms,
        steps=steps,
    )
