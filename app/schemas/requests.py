"""
app/schemas/requests.py — Inbound request models for the v1 API.

These are the only models routers should accept from HTTP clients.
Business logic uses domain models from app/schemas/domain.py.
"""

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
            "Must be one of: nexus_dynamics, mayo_central, delaware_gsa"
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

    use_o1_governance: bool = Field(
        default=False,
        description=(
            "Use OpenAI o1 for governance evaluation. Requires OPENAI_API_KEY. "
            "Falls back to deterministic engine if key is missing."
        ),
    )

    use_o1_graph: bool = Field(
        default=True,
        description=(
            "Use OpenAI o1 for graph reasoning. Requires OPENAI_API_KEY. "
            "Falls back to deterministic subgraph analysis if key is missing."
        ),
    )
