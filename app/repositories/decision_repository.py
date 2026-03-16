"""
app/repositories/decision_repository.py — DB access for workspace Decision records.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.decision import Decision

_ALLOWED_STATUSES = {"pending", "blocked", "validated"}
_SORT_MAP = {
    "created_at:desc": Decision.created_at.desc(),
    "created_at:asc": Decision.created_at.asc(),
    "risk_level:desc": Decision.risk_level.desc(),
}


def create(
    db: Session,
    *,
    company_id: str,
    agent_id: Optional[str] = None,
    agent_name: str,
    department: str,
    proposed_text: str,
    agent_name_en: Optional[str] = None,
    department_en: Optional[str] = None,
    proposed_text_en: Optional[str] = None,
    impact_label: Optional[str] = None,
    impact_label_en: Optional[str] = None,
) -> Decision:
    """Create and persist a new workspace decision record (status=pending)."""
    record = Decision(
        company_id=company_id,
        agent_id=agent_id,
        agent_name=agent_name,
        agent_name_en=agent_name_en,
        department=department,
        department_en=department_en,
        proposed_text=proposed_text,
        proposed_text_en=proposed_text_en,
        impact_label=impact_label,
        impact_label_en=impact_label_en,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_decisions(
    db: Session,
    company_id: Optional[str],
    statuses: Optional[list[str]] = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = "created_at:desc",
) -> tuple[list[Decision], int]:
    """
    Return (items, total) for workspace decision feed.

    Filters by company_id when provided. statuses=None means no filter (all).
    """
    q = db.query(Decision).filter(Decision.company_id == company_id)
    if statuses:
        q = q.filter(Decision.status.in_(statuses))

    total = q.count()

    order = _SORT_MAP.get(sort, Decision.created_at.desc())
    items = q.order_by(order).offset(offset).limit(limit).all()
    return items, total


def count_today(db: Session, company_id: str) -> int:
    """Count decisions created since 00:00 UTC today."""
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return db.query(func.count(Decision.id)).filter(
        Decision.company_id == company_id,
        Decision.created_at >= today,
    ).scalar() or 0


def count_by_status(db: Session, company_id: str, status: str) -> int:
    """Count decisions with a given status."""
    return db.query(func.count(Decision.id)).filter(
        Decision.company_id == company_id,
        Decision.status == status,
    ).scalar() or 0


def update_from_analysis(
    db: Session,
    decision_id: str,
    *,
    risk_level: Optional[str] = None,
    confidence: Optional[float] = None,
    contract_value: Optional[int] = None,
    affected_count: Optional[int] = None,
    status: Optional[str] = None,
) -> bool:
    """
    Update a workspace decision record with pipeline analysis results.
    Only updates fields that are explicitly passed (not None).
    Returns True if the record was found and updated.
    """
    record = db.query(Decision).filter(Decision.id == decision_id).first()
    if not record:
        return False
    if risk_level is not None:
        record.risk_level = risk_level
    if confidence is not None:
        record.confidence = confidence
    if contract_value is not None:
        record.contract_value = contract_value
    if affected_count is not None:
        record.affected_count = affected_count
    if status is not None and status in _ALLOWED_STATUSES:
        record.status = status
    db.commit()
    return True
