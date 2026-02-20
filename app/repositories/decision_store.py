"""
Decision Store - In-memory lifecycle store for decisions.

Tracks the full lifecycle: pending → processing → complete | failed
No DB. Dict-based. Thread-safe enough for single-process hackathon use.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field


STEP_LABELS = {
    0: "queued",
    1: "extracting",
    2: "evaluating_governance",
    3: "building_graph",
    4: "reasoning",
    5: "building_decision_pack",
    6: "complete",
}


@dataclass
class DecisionRecord:
    decision_id: str
    company_id: str
    status: str              # pending | processing | complete | failed
    input_text: str
    created_at: str
    updated_at: str
    current_step: int = 0    # 0-6, maps to STEP_LABELS
    # Request flags (captured at submission, control pipeline behavior)
    use_o1_governance: bool = False
    use_o1_graph: bool = False
    # Pipeline outputs — all optional until pipeline completes
    decision: Optional[dict] = None
    governance: Optional[dict] = None
    graph_payload: Optional[dict] = None
    reasoning: Optional[dict] = None
    decision_pack: Optional[dict] = None
    derived_attributes: Optional[dict] = None
    extraction_metadata: Optional[dict] = None
    error: Optional[str] = None


# ── In-memory store ──────────────────────────────────────────────────────────

_store: dict[str, DecisionRecord] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(
    company_id: str,
    input_text: str,
    use_o1_governance: bool = False,
    use_o1_graph: bool = False,
) -> DecisionRecord:
    """Create a new pending DecisionRecord and return it."""
    decision_id = str(uuid.uuid4())
    now = _now()
    record = DecisionRecord(
        decision_id=decision_id,
        company_id=company_id,
        status="pending",
        input_text=input_text,
        created_at=now,
        updated_at=now,
        use_o1_governance=use_o1_governance,
        use_o1_graph=use_o1_graph,
    )
    _store[decision_id] = record
    return record


def get(decision_id: str) -> Optional[DecisionRecord]:
    """Return record or None."""
    return _store.get(decision_id)


def update_status(decision_id: str, status: str, current_step: int = None) -> None:
    """Update status (and optionally current_step)."""
    record = _store.get(decision_id)
    if not record:
        return
    record.status = status
    if current_step is not None:
        record.current_step = current_step
    record.updated_at = _now()


def store_results(
    decision_id: str,
    *,
    decision: dict = None,
    governance: dict = None,
    graph_payload: dict = None,
    reasoning: dict = None,
    decision_pack: dict = None,
    derived_attributes: dict = None,
    extraction_metadata: dict = None,
) -> None:
    """Persist pipeline outputs onto the record."""
    record = _store.get(decision_id)
    if not record:
        return
    if decision is not None:
        record.decision = decision
    if governance is not None:
        record.governance = governance
    if graph_payload is not None:
        record.graph_payload = graph_payload
    if reasoning is not None:
        record.reasoning = reasoning
    if decision_pack is not None:
        record.decision_pack = decision_pack
    if derived_attributes is not None:
        record.derived_attributes = derived_attributes
    if extraction_metadata is not None:
        record.extraction_metadata = extraction_metadata
    record.updated_at = _now()


def store_error(decision_id: str, error: str) -> None:
    """Mark record as failed with error message."""
    record = _store.get(decision_id)
    if not record:
        return
    record.status = "failed"
    record.error = error
    record.updated_at = _now()


# NOTE: to_status_payload and to_full_payload removed.
# All response assembly uses app/routers/normalizers.py:build_console_payload()
# which returns a validated ConsolePayloadResponse with no extra fields.
