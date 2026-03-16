"""
app/schemas/nova_scenarios.py — Nova scenario proposal schemas.

Nova is used ONLY to propose which remediation templates to apply.
It never computes risk scores or governance outcomes.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator

# Canonical set of templateIds defined in simulation_templates.json.
# Keep in sync when adding new templates.
ALLOWED_TEMPLATE_IDS: frozenset[str] = frozenset({
    "reduce_to_remaining_budget",
    "reduce_to_high_threshold",
    "phased_rollout",
    "apply_anonymization",
    "add_compliance_review",
    "add_goal_mapping",
    "reduce_strategic_conflict",
    "defer_hiring",
    "reduce_headcount",
})


class NovaScenarioProposal(BaseModel):
    """A single remediation scenario candidate proposed by Nova."""
    templateId: str
    titleKo: str
    changeSummaryKo: str
    reasoningKo: str
    parameters: Optional[Dict] = None


class NovaScenarioResponse(BaseModel):
    """Validated JSON response from Nova — list of 1-3 scenario proposals."""
    scenarios: List[NovaScenarioProposal]

    @field_validator("scenarios")
    @classmethod
    def validate_length(cls, v: list) -> list:
        if not (1 <= len(v) <= 3):
            raise ValueError(f"scenarios must have 1-3 items, got {len(v)}")
        return v
