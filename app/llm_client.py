"""
LLM Client — Structured decision extraction via the LangChain provider abstraction.

The provider/model are chosen by app/config/llm.py (LLM_PROVIDER, LLM_MODEL_FAST).
The LLM is an extractor only: it returns JSON text, which DecisionExtractor then
validates with Pydantic. Nothing here computes scores or governance outcomes.
"""

import json
import logging
import re
from typing import Optional

from app.config import llm as llm_config

logger = logging.getLogger(__name__)

# Boolean fields the Decision schema requires (non-Optional): never leave them null.
_BOOL_DEFAULT_FALSE = ("uses_pii", "involves_hiring", "involves_compliance_risk")

_SCHEMA = """{
  "decision_statement": "string (10-1000 chars, one clear executable action)",
  "goals": [{"description": "string (3-500 chars)", "metric": "string or null"}],
  "kpis": [{"name": "string (3-200 chars)", "target": "string or null", "measurement_frequency": "string or null"}],
  "risks": [{
    "description": "string (3-500 chars)",
    "description_en": "string or null (concise English paraphrase, max 80 chars)",
    "severity": "Low | Medium | High | Critical | null",
    "mitigation": "string or null",
    "risk_type": "budget_overrun | compliance | operational | strategic | other | null"
  }],
  "owners": [{"name": "string (2-200 chars)", "role": "string or null", "responsibility": "string or null", "name_en": "string or null", "role_en": "string or null"}],
  "required_approvals": ["string"],
  "assumptions": [{"description": "string (3-500 chars)", "criticality": "string or null"}],
  "counterparty_relation": "'related_party' or null",
  "policy_change_type": "'retroactive' or null",
  "strategic_impact": "low | medium | high | critical | null",
  "uses_pii": "boolean",
  "cost": "number or null",
  "cost_estimate_range": "string or null",
  "target_market": "string or null",
  "launch_date": "boolean or null",
  "involves_hiring": "boolean",
  "headcount_change": "integer or null",
  "involves_compliance_risk": "boolean",
  "remaining_budget": "number or null",
  "department": "string or null",
  "confidence": "number between 0.0 and 1.0"
}"""

_SYSTEM_PROMPT = f"""You are a decision extraction system for enterprise governance.

Convert the decision text into JSON matching this schema:
{_SCHEMA}

Principles:
1. STATED ONLY. Extract what the text explicitly says. If a value would require you
   to calculate or assume, use null (scalars) or [] (lists). Convert amounts to full
   numbers (e.g. "$3.5M" -> 3500000, "$100K" -> 100000). When no amount is stated for
   a well-known high-cost asset with an established market price, set cost to the upper
   bound of its typical range and give the full range in cost_estimate_range; otherwise
   leave both null.
2. GOVERNANCE TRIGGER. uses_pii, involves_hiring and involves_compliance_risk are formal
   review gates. Set true only when the decision directly triggers that review:
   - uses_pii: identifiable customer/end-user personal data is processed, shared or exposed
     (not internal financials or employee records).
   - involves_hiring: people are added to payroll / headcount changes as a direct result.
   - involves_compliance_risk: the text raises bribery, ethics-code, gift/entertainment,
     conflict-of-interest or comparable integrity concerns.
   Otherwise false (never null).
3. OWNERS. Only people or roles explicitly named as accountable. If none, use [].
4. counterparty_relation = 'related_party' only for money/contracts with a subsidiary,
   affiliate, parent, major shareholder or board member. policy_change_type = 'retroactive'
   only when new rules are applied to events that already happened.
5. strategic_impact: critical = largely irreversible or company-wide or safety-threatening;
   high = significant but recoverable; medium = department-level; low = local/operational.
6. risks.severity: Critical = irreversible/life-threatening harm; High = severe but
   recoverable; Medium = moderate; Low = minimal.
7. headcount_change: stated net change (additions positive, reductions negative), else null.
8. Write all text fields in the same language as the input, except risks.description_en,
   which is always English.

Output ONLY a single valid JSON object. No markdown, no commentary.
Use [] for missing lists and null for missing scalars. Be conservative with confidence."""


def _extract_json_object(text: str) -> str:
    """Return the JSON object inside an LLM reply (tolerates code fences / stray prose)."""
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            text = text[start : end + 1]
    return text


def _message_text(content) -> str:
    """LangChain content may be a str or a list of content blocks."""
    if isinstance(content, str):
        return content
    return "".join(
        b.get("text", "") if isinstance(b, dict) else str(b) for b in content
    )


class LLMClient:
    """Structured decision extraction using get_llm('fast')."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        # api_key is unused: credentials come from the provider's env var.
        self.model = model or llm_config.LLM_MODEL_FAST
        self._llm = None  # created lazily so app startup never needs a key
        logger.info(
            f"Initialized LLMClient provider={llm_config.LLM_PROVIDER} model={self.model}"
        )

    def _get_llm(self):
        if self._llm is None:
            self._llm = llm_config.get_llm("fast")
        return self._llm

    def extract_decision_json(self, decision_text: str) -> str:
        """Extract structured decision JSON (as a string) from free-form text."""
        reply = self._get_llm().invoke(
            [("system", _SYSTEM_PROMPT), ("human", decision_text)]
        )
        raw = _extract_json_object(_message_text(reply.content))

        # The schema requires real booleans; models sometimes emit null for "not triggered".
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw  # let DecisionExtractor report/retry the parse error
        if isinstance(data, dict):
            for key in _BOOL_DEFAULT_FALSE:
                if data.get(key) is None:
                    data[key] = False
            return json.dumps(data)
        return raw
