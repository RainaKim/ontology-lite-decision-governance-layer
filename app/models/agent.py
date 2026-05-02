"""
app/models/agent.py — Agent ORM model.

Stores AI agent registry with autonomy constraints and financial limits.
id is a UUID stored as VARCHAR(36) for cross-database compatibility.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agents"

    # Primary key — UUID as string
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )

    # Company scoping
    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identity (ko / en)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    department: Mapped[str] = mapped_column(String(100), nullable=False)
    department_en: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Autonomy
    autonomy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Policy Bound"
    )  # Human Controlled | Policy Bound | Conditional | Autonomous

    # Governance constraints
    risk_threshold: Mapped[int] = mapped_column(
        Integer, nullable=False, default=70
    )  # Max risk score for auto-approval (0-100)
    financial_limit: Mapped[Optional[float]] = mapped_column(
        Numeric(precision=15, scale=2), nullable=True
    )  # Max value agent can authorize

    # Status
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="Active"
    )  # Active | Restricted | Inactive

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Agent id={self.id!r} name={self.name!r} autonomy={self.autonomy!r}>"
