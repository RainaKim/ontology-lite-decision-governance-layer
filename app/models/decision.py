"""
app/models/decision.py — Decision ORM model for workspace dashboard.

Stores workspace-level decision records (agent proposals awaiting governance review).
Separate from the in-memory pipeline decision_store — this table is the persistent
source of truth for the dashboard feed.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Org scoping
    company_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True, index=True)

    # Agent reference — replaces flat agent_name/department strings
    agent_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    agent = relationship("Agent", lazy="joined")

    # Agent metadata (ko / en) — kept for backwards compat with existing rows
    agent_name: Mapped[str] = mapped_column(String(200), nullable=False)
    agent_name_en: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    department_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Content (ko / en)
    proposed_text: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_text_en: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Governance result
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", index=True
    )  # pending | blocked | validated

    # AI assessment
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.75)
    risk_level: Mapped[str] = mapped_column(
        String(10), nullable=False, default="medium"
    )  # low | medium | high

    # Impact metadata (all optional)
    impact_label: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    impact_label_en: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    contract_value: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    affected_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False, index=True
    )
    validated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<Decision id={self.id!r} status={self.status!r} agent={self.agent_name!r}>"
