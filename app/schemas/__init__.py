"""
app/schemas — Decision Governance Layer schema package.

Re-exports all domain models from domain.py for backwards compatibility.
Existing imports like `from app.schemas import Decision, Owner, ...` continue to work.

New API-layer models live in:
  app/schemas/requests.py  — inbound request bodies
  app/schemas/responses.py — outbound response payloads (console-locked shape)
"""

from app.schemas.domain import (
    StrategicImpact,
    ApprovalLevel,
    Goal,
    KPI,
    Risk,
    Owner,
    Assumption,
    ApprovalChainStep,
    Decision,
    DecisionExtractionRequest,
    DecisionExtractionResponse,
    DecisionPack,
)

__all__ = [
    "StrategicImpact",
    "ApprovalLevel",
    "Goal",
    "KPI",
    "Risk",
    "Owner",
    "Assumption",
    "ApprovalChainStep",
    "Decision",
    "DecisionExtractionRequest",
    "DecisionExtractionResponse",
    "DecisionPack",
]
