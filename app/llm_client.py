"""
LLM Client - OpenAI integration for structured decision extraction.
"""

import json
import logging
from typing import Optional
from openai import OpenAI

logger = logging.getLogger(__name__)


class LLMClient:
    """OpenAI client for structured decision extraction."""

    def __init__(self, api_key: Optional[str] = None, model: str = "gpt-4o"):
        """
        Initialize OpenAI client.

        Args:
            api_key: OpenAI API key (if None, will use OPENAI_API_KEY env var)
            model: Model to use for extraction (default: gpt-4o)
        """
        self.client = OpenAI(api_key=api_key)
        self.model = model
        logger.info(f"Initialized OpenAI client with model: {model}")

    def extract_decision_json(self, decision_text: str) -> str:
        """
        Extract structured decision JSON from free-form text.

        Args:
            decision_text: Free-form decision description

        Returns:
            Raw JSON string containing structured decision

        Raises:
            Exception: If OpenAI API call fails
        """
        schema_description = """
{
  "decision_statement": "string (10-1000 chars, clear executable action)",
  "goals": [
    {
      "description": "string (3-500 chars)",
      "metric": "string or null"
    }
  ],
  "kpis": [
    {
      "name": "string (3-200 chars)",
      "target": "string or null",
      "measurement_frequency": "string or null"
    }
  ],
  "risks": [
    {
      "description": "string (3-500 chars)",
      "severity": "string or null (Low/Medium/High/Critical)",
      "mitigation": "string or null"
    }
  ],
  "owners": [
    {
      "name": "string (2-200 chars)",
      "role": "string or null",
      "responsibility": "string or null"
    }
  ],
  "required_approvals": ["string"],
  "assumptions": [
    {
      "description": "string (3-500 chars)",
      "criticality": "string or null"
    }
  ],
  "counterparty_relation": "string or null ('related_party' ONLY if the decision involves a financial transaction or contract with subsidiaries, affiliates, parent company, major shareholders, or board members; null otherwise)",
  "policy_change_type": "string or null ('retroactive' ONLY if the decision explicitly applies new rules or terms to past events/transactions that already occurred; decisions that conflict with current strategy or KPIs are NOT retroactive; null otherwise)",
  "strategic_impact": "string or null (one of: 'low', 'medium', 'high', 'critical' — assess based on scope, cost, and organizational impact)",
  "uses_pii": "boolean or null (true ONLY if the decision involves processing, transferring, exposing, or accessing identifiable CUSTOMER/end-user personal data — e.g. 고객 개인정보, customer profiles, user behavioral data, patient health records; null otherwise. HR/hiring decisions, internal employee data, budget figures, and operational decisions do NOT trigger this — only customer-facing personal data)",
  "cost": "number or null (explicit amount stated in text → convert: '2.5억 원' → 250000000, '$3.5M' → 3500000; OR for well-known expensive equipment/assets with no stated amount → use UPPER BOUND of typical market range; null for items with variable costs)",
  "cost_estimate_range": "string or null (when cost is inferred from domain knowledge, provide the market range in the INPUT LANGUAGE, e.g. '$1.5M-$3.5M (typical MRI equipment)' or '15억-35억 원 (일반적인 MRI 장비 시장가)'; null if cost was explicitly stated)",
  "target_market": "string or null (target market or geographic region if explicitly mentioned, e.g. '북미', 'EU', 'North America'; null otherwise)",
  "launch_date": "boolean or null (true if the decision involves a product launch, service deployment, or system release; null otherwise)",
  "involves_hiring": "boolean or null (true if the decision involves hiring new employees, expanding headcount, onboarding, or significant workforce change; null otherwise)",
  "headcount_change": "integer or null (net number of people being added as positive integer, e.g. '20명 채용' → 20; reductions as negative, e.g. '10명 감축' → -10; null if not stated)",
  "involves_compliance_risk": "boolean or null (true if the decision explicitly mentions anti-bribery risk, ethics code violation, entertainment/gift policy limit breach, conflict of interest, or similar compliance/integrity concerns; null otherwise)",
  "confidence": 0.0 to 1.0
}
"""

        system_prompt = f"""You are a decision extraction system for enterprise governance.

Convert the decision text into structured JSON matching this schema:
{schema_description}

── CRITICAL: LANGUAGE PRESERVATION ─────────────────────────────────────────

ALL extracted text fields (decision_statement, goals, KPIs, risks, owners,
assumptions, required_approvals) MUST be in the SAME LANGUAGE as the input text.

If the input is in Korean, ALL output text fields must be in Korean.
If the input is in English, ALL output text fields must be in English.

This is a HARD REQUIREMENT. Do not translate, do not mix languages.

── THREE EXTRACTION PRINCIPLES ─────────────────────────────────────────────

Apply these principles to every field. They replace per-field rule lists — reason
from the principle when you encounter a pattern not described below.

1. STATED ONLY (with domain-informed cost inference)
   Extract what the text explicitly says. If arriving at a value requires you to
   calculate, multiply, or assume arbitrary numbers — the answer is null or [].

   EXCEPTION for cost: When the decision involves well-known expensive capital
   equipment or assets with established market prices (medical equipment, enterprise
   systems, vehicles), infer cost using this TWO-FIELD approach:

   a) cost (number): Set to the UPPER BOUND of the typical market range for
      conservative governance evaluation. Rules need a single number to compare.

   b) cost_estimate_range (string): Provide the full market range in the INPUT
      LANGUAGE so users see the uncertainty, e.g. "$1.5M-$3.5M (typical MRI)"
      or "15억-35억 원 (일반적인 MRI 장비)".

   Examples when NO explicit cost is stated:
   - "MRI 장비 구매" → cost: 3500000, cost_estimate_range: "$1.5M-$3.5M (typical MRI equipment)"
   - "신규 CT scanner" → cost: 3000000, cost_estimate_range: "$1M-$3M (CT scanner market range)"
   - "ERP 시스템 도입" → cost: 700000, cost_estimate_range: "$300K-$700K (enterprise ERP)"
   - "사무실 임대" → cost: null, cost_estimate_range: null (too variable by location)
   - "마케팅 캠페인" → cost: null, cost_estimate_range: null (could be $10K or $10M)

   Example when explicit cost IS stated:
   - "2.5억 원 MRI 구매" → cost: 250000000, cost_estimate_range: null (explicit, no estimation)

   For all other fields: extract only what is explicitly stated.
   Applies to: headcount_change (stated count, not implied), counterparty_relation,
   policy_change_type.

2. GOVERNANCE TRIGGER
   Boolean flags (uses_pii, involves_hiring, involves_compliance_risk) represent
   formal governance review gates. Ask: "Would the relevant expert — a data privacy
   officer, HR lead, or compliance officer — need to be formally notified because
   of this specific decision?" Proximity or relevance is not enough. Only set true
   when the decision directly triggers that review process.

3. OWNER BY DOMAIN
   An owner is the person accountable for delivering the outcome. If the decision
   domain unambiguously implies a role (R&D work → 연구개발팀장, marketing campaign
   → 마케팅팀장, IT infrastructure → IT팀장, HR policy → 인사팀장, equipment purchase
   → 재무팀장 or 최고재무책임자), include it even if no name is given. If the domain
   is genuinely ambiguous, use [].

── FIELD NOTES ─────────────────────────────────────────────────────────────

decision_statement  One clear, executable sentence describing the action.

kpis.name           The measurement text only — strip surrounding labels or
                    period identifiers (e.g. 'Q1 KPI(운영비 -10%)' → '운영비 -10%').

cost                The amount that would appear on an approval form. Convert
                    Korean/English amounts to full integers (2.5억 원 → 250000000,
                    $3.5M → 3500000). For well-known expensive equipment/assets
                    (MRI, CT scanner, ERP system) with no stated amount, use the
                    UPPER BOUND of the typical market range for conservative
                    governance evaluation. Null for items with highly variable
                    costs (marketing, consulting, rent) unless explicitly stated.

cost_estimate_range When cost is inferred from domain knowledge (not explicitly
                    stated), provide the full market range in the INPUT LANGUAGE
                    (e.g. "$1.5M-$3.5M (typical MRI)" or "15억-35억 원 (일반적인
                    MRI 장비)"). This shows users the uncertainty. Null when cost
                    was explicitly stated in the input text.

uses_pii            True only when the decision directly handles identifiable
                    customer or end-user records (profiles, behavioral data,
                    health records). Internal financials, employee data, and
                    general marketing spend do not qualify.

counterparty_relation  'related_party' when money or contracts flow to/from a
                    subsidiary, affiliate, parent entity, or board member.
                    Disagreeing with an insider's preferred direction is not
                    a related-party transaction.

policy_change_type  'retroactive' when the decision changes rules for events that
                    have already occurred. Conflicting with current strategy or
                    breaching current limits is not retroactive.

strategic_impact    How severely would this alter the company's trajectory if it
                    went wrong? critical = largely irreversible, company-wide, OR
                    involves patient safety/life-threatening scenarios (healthcare).
                    high = significant but recoverable. medium = department-level.
                    low = local or operational.

                    HEALTHCARE: Patient safety issues, clinical protocol violations
                    (Emergency Care Protocol, Patient Safety Protocol), and emergency
                    care failures are ALWAYS "critical" regardless of scope.

involves_compliance_risk  True when the decision explicitly raises anti-bribery,
                    ethics code, gift/entertainment policy, or conflict-of-interest
                    concerns.

involves_hiring     True only when someone is being added to the payroll or
                    employment headcount changes as a direct result.

risks.severity      Assess actual impact if risk materializes:
                    Critical = life-threatening, irreversible harm, or existential
                             threat (patient death/injury, clinical protocol violations,
                             major compliance breach, company bankruptcy)
                    High = severe but recoverable damage (reputation harm, major
                           financial loss, regulatory penalty)
                    Medium = moderate recoverable impact (delays, minor losses)
                    Low = minimal impact (process inefficiency, minor cost)

                    HEALTHCARE: Clinical protocol violations (Emergency Care Protocol,
                    Patient Safety Protocol) = CRITICAL severity. Quality standard
                    violations = HIGH severity.

── OUTPUT RULES ────────────────────────────────────────────────────────────

- Output ONLY valid JSON, no markdown or explanation
- Use [] for missing list fields, null for missing scalar fields
- Be conservative with confidence scores"""

        user_message = f"""Extract structured decision from this text:

{decision_text}

Output valid JSON only."""

        try:
            logger.info(f"Calling OpenAI API with model: {self.model}")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                temperature=0.0,  # Deterministic extraction
                response_format={"type": "json_object"}  # Force JSON output
            )

            raw_response = response.choices[0].message.content
            logger.info(f"Received response from OpenAI ({len(raw_response)} chars)")
            logger.debug(f"Raw response: {raw_response[:200]}...")

            return raw_response

        except Exception as e:
            logger.error(f"OpenAI API error: {e}")
            raise
