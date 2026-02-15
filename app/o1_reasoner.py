"""
o1 Reasoning Layer - Deep reasoning for ontology and governance.

Uses OpenAI o1 model for:
- Ontology reasoning (goal mapping, ownership validation)
- Governance reasoning (rule conflicts, approval chain optimization)
"""

import json
import logging
from typing import Optional, Dict, List
from openai import OpenAI

logger = logging.getLogger(__name__)


class O1Reasoner:
    """
    OpenAI o1 reasoning client for complex multi-step reasoning tasks.

    Uses o1-mini for fast reasoning or o1-preview for deeper analysis.
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "o1-mini"):
        """
        Initialize o1 reasoner.

        Args:
            api_key: OpenAI API key (if None, will use OPENAI_API_KEY env var)
            model: o1 model to use (o1-mini or o1-preview)
        """
        self.client = OpenAI(api_key=api_key)
        self.model = model
        logger.info(f"Initialized O1Reasoner with model: {model}")

    def reason_about_goal_alignment(self, decision_data: Dict, company_goals: List[Dict]) -> Dict:
        """
        Use o1 to reason about which strategic goals this decision aligns with.

        Args:
            decision_data: Extracted decision object (decision_statement, goals, KPIs, owners)
            company_goals: List of strategic goals from company data

        Returns:
            Reasoning result with mapped goals and alignment analysis
        """
        prompt = f"""You are an expert organizational strategist analyzing decision-to-goal alignment.

DECISION TO ANALYZE:
Decision Statement: {decision_data.get('decision_statement')}
Decision Goals: {json.dumps(decision_data.get('goals', []), indent=2)}
Decision KPIs: {json.dumps(decision_data.get('kpis', []), indent=2)}
Decision Owners: {json.dumps(decision_data.get('owners', []), indent=2)}

COMPANY STRATEGIC GOALS:
{json.dumps(company_goals, indent=2)}

TASK:
Reason through which company strategic goals this decision genuinely aligns with. Consider:

1. KPI Alignment: Do the decision's KPIs measure progress toward any strategic goal KPIs?
2. Ownership Alignment: Are the decision owners the same people who own strategic goals?
3. Semantic Alignment: Does the decision statement support the strategic goal descriptions?
4. Hidden Dependencies: Are there implicit connections between this decision and goals?

Output your reasoning as JSON with this structure:
{{
  "mapped_goals": [
    {{
      "goal_id": "G1",
      "alignment_score": 0.85,
      "reasoning": "Detailed explanation of why this goal aligns",
      "alignment_type": "kpi" | "owner" | "semantic" | "dependency",
      "confidence": 0.9
    }}
  ],
  "primary_goal": "G1",
  "cross_goal_conflicts": ["any potential conflicts between goals"],
  "reasoning_summary": "overall analysis"
}}

Be rigorous. Only map goals with genuine alignment. Low scores for weak connections."""

        try:
            logger.info(f"Calling o1 for goal alignment reasoning")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )

            reasoning_text = response.choices[0].message.content
            logger.info(f"Received o1 reasoning ({len(reasoning_text)} chars)")

            # Parse JSON from response
            # o1 might include markdown code blocks, so extract JSON
            json_start = reasoning_text.find('{')
            json_end = reasoning_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = reasoning_text[json_start:json_end]
                result = json.loads(json_str)
                return result
            else:
                logger.warning("Could not extract JSON from o1 response, returning raw text")
                return {"raw_reasoning": reasoning_text, "mapped_goals": []}

        except Exception as e:
            logger.error(f"o1 goal alignment reasoning failed: {e}")
            return {"error": str(e), "mapped_goals": []}

    def reason_about_ownership_validity(self, decision_data: Dict, personnel: List[Dict]) -> Dict:
        """
        Use o1 to validate if decision owners are appropriate given personnel hierarchy.

        Args:
            decision_data: Extracted decision object
            personnel: List of personnel from company hierarchy

        Returns:
            Reasoning result about ownership validity
        """
        prompt = f"""You are an organizational structure expert validating decision ownership.

DECISION:
Decision Statement: {decision_data.get('decision_statement')}
Proposed Owners: {json.dumps(decision_data.get('owners', []), indent=2)}

COMPANY PERSONNEL HIERARCHY:
{json.dumps(personnel, indent=2)}

TASK:
Analyze if the proposed owners are valid and appropriate. Consider:

1. Personnel Matching: Do the owner names/roles match actual people in the hierarchy?
2. Responsibility Alignment: Are these people responsible for areas related to this decision?
3. Authority Level: Do these owners have sufficient authority for this decision?
4. Reporting Structure: Should higher-level approvers be involved based on org structure?

Output JSON:
{{
  "validated_owners": [
    {{
      "proposed_owner": "name from decision",
      "matched_person_id": "person_id or null",
      "is_valid": true/false,
      "reasoning": "why valid or invalid",
      "suggested_correction": "if invalid, who should it be"
    }}
  ],
  "missing_owners": ["roles that should be included but aren't"],
  "ownership_issues": ["any structural problems"],
  "reasoning_summary": "overall analysis"
}}"""

        try:
            logger.info(f"Calling o1 for ownership validation reasoning")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )

            reasoning_text = response.choices[0].message.content
            logger.info(f"Received o1 ownership reasoning ({len(reasoning_text)} chars)")

            json_start = reasoning_text.find('{')
            json_end = reasoning_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = reasoning_text[json_start:json_end]
                result = json.loads(json_str)
                return result
            else:
                return {"raw_reasoning": reasoning_text, "validated_owners": []}

        except Exception as e:
            logger.error(f"o1 ownership validation failed: {e}")
            return {"error": str(e), "validated_owners": []}

    def reason_about_governance_conflicts(self, triggered_rules: List[Dict], decision_data: Dict,
                                         company_data: Dict) -> Dict:
        """
        Use o1 to resolve governance rule conflicts and optimize approval chain.

        Args:
            triggered_rules: List of governance rules that were triggered
            decision_data: Extracted decision object
            company_data: Full company context

        Returns:
            Reasoning result with conflict resolution and optimized approval chain
        """
        prompt = f"""You are a governance expert resolving rule conflicts and optimizing approval chains.

DECISION:
{json.dumps(decision_data, indent=2)}

TRIGGERED GOVERNANCE RULES:
{json.dumps(triggered_rules, indent=2)}

COMPANY CONTEXT:
Personnel: {json.dumps(company_data.get('approval_hierarchy', {}).get('personnel', []), indent=2)}
Risk Tolerance: {json.dumps(company_data.get('risk_tolerance', {}), indent=2)}

SITUATION:
Multiple governance rules have been triggered. Some may conflict or overlap in approval requirements.

TASK:
Analyze the triggered rules and reason about:

1. Rule Priority: Which rules take precedence when they conflict?
2. Approval Deduplication: When multiple rules require same approver, how to handle?
3. Approval Sequence: What's the optimal order for approvals?
4. Escalation Logic: When should we escalate to higher authority?
5. Risk-Based Adjustment: Should approval requirements change based on risk level?

Output JSON:
{{
  "conflict_analysis": [
    {{
      "rules": ["R1", "R2"],
      "conflict_type": "overlapping_approvers" | "contradictory_requirements",
      "resolution": "how to resolve this conflict"
    }}
  ],
  "optimized_approval_chain": [
    {{
      "approver_role": "CFO",
      "approver_id": "person_id",
      "level": 3,
      "sequence_order": 1,
      "rationale": "why this approver in this order",
      "is_parallel": false
    }}
  ],
  "escalation_triggers": ["conditions that would require additional approvals"],
  "reasoning_summary": "comprehensive analysis"
}}"""

        try:
            logger.info(f"Calling o1 for governance conflict reasoning")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )

            reasoning_text = response.choices[0].message.content
            logger.info(f"Received o1 governance reasoning ({len(reasoning_text)} chars)")

            json_start = reasoning_text.find('{')
            json_end = reasoning_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = reasoning_text[json_start:json_end]
                result = json.loads(json_str)
                return result
            else:
                return {"raw_reasoning": reasoning_text, "optimized_approval_chain": []}

        except Exception as e:
            logger.error(f"o1 governance reasoning failed: {e}")
            return {"error": str(e), "optimized_approval_chain": []}

    def reason_about_constraint_violations(self, decision_data: Dict, mapped_goals: List[Dict],
                                          company_data: Dict) -> Dict:
        """
        Use o1 to identify organizational constraint violations.

        Args:
            decision_data: Extracted decision
            mapped_goals: Goals this decision maps to
            company_data: Full company context

        Returns:
            Reasoning about constraint violations
        """
        prompt = f"""You are an organizational compliance expert identifying constraint violations.

DECISION:
{json.dumps(decision_data, indent=2)}

MAPPED STRATEGIC GOALS:
{json.dumps(mapped_goals, indent=2)}

COMPANY CONSTRAINTS:
Strategic Goals: {json.dumps(company_data.get('strategic_goals', []), indent=2)}
Risk Tolerance: {json.dumps(company_data.get('risk_tolerance', {}), indent=2)}

TASK:
Identify any organizational constraint violations. Consider:

1. Goal Ownership Misalignment: Decision owners don't match strategic goal owners
2. Cross-Goal Conflicts: Decision spans multiple goals with different priorities
3. Risk Tolerance Violations: Decision risks exceed company tolerance levels
4. Resource Allocation Conflicts: Decision may conflict with other strategic initiatives
5. Timeline Conflicts: Decision timeline doesn't align with goal timelines

Output JSON:
{{
  "violations": [
    {{
      "constraint_type": "goal_ownership_misalignment",
      "severity": "low" | "medium" | "high" | "critical",
      "description": "detailed explanation",
      "impact": "what could go wrong",
      "recommendation": "how to fix"
    }}
  ],
  "compliance_score": 0.75,
  "reasoning_summary": "overall constraint analysis"
}}"""

        try:
            logger.info(f"Calling o1 for constraint violation reasoning")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )

            reasoning_text = response.choices[0].message.content
            logger.info(f"Received o1 constraint reasoning ({len(reasoning_text)} chars)")

            json_start = reasoning_text.find('{')
            json_end = reasoning_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = reasoning_text[json_start:json_end]
                result = json.loads(json_str)
                return result
            else:
                return {"raw_reasoning": reasoning_text, "violations": []}

        except Exception as e:
            logger.error(f"o1 constraint reasoning failed: {e}")
            return {"error": str(e), "violations": []}
