"""
app/schemas/requests.py — Inbound request models for the v1 API.

These are the only models routers should accept from HTTP clients.
Business logic uses domain models from app/schemas/domain.py.
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field


class CreateDecisionRequest(BaseModel):
    """
    POST /v1/decisions — submit a decision text for governance evaluation.

    Pipeline runs as a BackgroundTask; caller receives a decision_id immediately.
    Connect to GET /v1/decisions/{id}/stream for real-time SSE progress.
    Fetch GET /v1/decisions/{id} once the stream emits 'event: complete'.
    """

    company_id: str = Field(
        ...,
        description=(
            "Governance context to evaluate against. "
            "Must be one of: nexus_dynamics, mayo_central"
        ),
        examples=["nexus_dynamics"],
    )

    input_text: str = Field(
        ...,
        min_length=20,
        max_length=10_000,
        description=(
            "Free-form decision description. The extractor structures this "
            "into goals, KPIs, risks, owners, and assumptions."
        ),
        examples=["Acquire DataCorp for $3.5M to expand analytics capabilities"],
    )

    use_nova_governance: bool = Field(
        default=False,
        description=(
            "Use Nova for governance evaluation. "
            "Falls back to deterministic engine if unavailable."
        ),
    )

    use_nova_graph: bool = Field(
        default=True,
        description=(
            "Use Nova for graph reasoning. "
            "Falls back to deterministic subgraph analysis if unavailable."
        ),
    )

    lang: Literal["ko", "en"] = Field(
        default="ko",
        description="Language for company context and response labels. 'ko' (default) or 'en'.",
    )

    agent_name: str = Field(
        default="AI Agent",
        max_length=200,
        description="Name of the AI agent that proposed this decision.",
        examples=["마케팅 AI Agent"],
    )

    agent_name_en: str = Field(
        default="AI Agent",
        max_length=200,
        description="English name of the AI agent that proposed this decision.",
        examples=["Marketing AI Agent"],
    )

    workspace_decision_id: Optional[str] = Field(
        default=None,
        description=(
            "DB decision ID from GET /v1/workspace/decisions. "
            "When provided, the pipeline writes analysis results (risk_level, confidence, "
            "contract_value, affected_count) back to that workspace record on completion."
        ),
    )
