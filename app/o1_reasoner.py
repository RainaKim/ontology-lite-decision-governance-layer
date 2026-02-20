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

    def __init__(self, api_key: Optional[str] = None, model: str = "o4-mini"):
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

    def reason_about_graph_contradictions(
        self,
        decision_id: str,
        decision_data: Dict,
        company_data: Dict,
        graph_context: Optional[Dict] = None
    ) -> Dict:
        """
        Extract relevant subgraph, then use o1 to find logical contradictions.

        For MVP: builds a mock subgraph from in-memory decision + company data.
        Future: graph_context from Neo4j replaces/enriches the mock subgraph.

        Args:
            decision_id: The decision identifier
            decision_data: Extracted decision object (statement, goals, KPIs, owners, risks)
            company_data: Company context (strategic_goals, personnel, risk_tolerance)
            graph_context: Optional pre-fetched graph context from repository.
                           When provided (e.g. from Neo4j), used to enrich the subgraph.
                           When None, full subgraph is built from mock data.

        Returns:
            Reasoning result with contradictions, recommendations, subgraph metadata
        """
        # Step 1: Extract relevant subgraph
        subgraph = self._extract_mock_subgraph(
            decision_id, decision_data, company_data, graph_context
        )

        # Step 2: Build structured prompt from subgraph
        prompt = self._build_contradiction_prompt(decision_id, subgraph)

        # Step 3: Call o1
        try:
            logger.info(
                f"Calling o1 for graph contradiction analysis "
                f"(decision={decision_id}, nodes={len(subgraph['nodes'])}, "
                f"edges={len(subgraph['edges'])})"
            )
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )

            reasoning_text = response.choices[0].message.content
            logger.info(f"Received o1 graph reasoning ({len(reasoning_text)} chars)")

            # Extract JSON from response
            json_start = reasoning_text.find('{')
            json_end = reasoning_text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = reasoning_text[json_start:json_end]
                result = json.loads(json_str)
                result["subgraph_metadata"] = subgraph["metadata"]
                return result
            else:
                logger.warning("Could not extract JSON from o1 response")
                return {
                    "raw_reasoning": reasoning_text,
                    "contradictions": [],
                    "recommendations": [],
                    "confidence": 0.5,
                    "subgraph_metadata": subgraph["metadata"]
                }

        except Exception as e:
            logger.error(f"o1 graph reasoning failed: {e}")
            return {
                "error": str(e),
                "contradictions": [],
                "recommendations": [],
                "confidence": 0.0,
                "subgraph_metadata": subgraph["metadata"]
            }

    # ── Subgraph extraction (mock for MVP, swap for Neo4j later) ──────────

    def _extract_mock_subgraph(
        self,
        decision_id: str,
        decision_data: Dict,
        company_data: Dict,
        graph_context: Optional[Dict] = None
    ) -> Dict:
        """
        Build a relevant subgraph from in-memory data for contradiction analysis.

        Selection criteria (mirrors what a real graph traversal would return):
        1. The decision itself (root node)
        2. Decision's owners → matched to personnel → their reporting chain (up to 2 levels)
        3. Decision's goals/KPIs → matched to strategic goals sharing KPIs or owners
        4. Decision's risks → connected to risk tolerance thresholds
        5. Governance rules triggered by this decision

        When graph_context is provided (from repository.get_governance_context),
        it is merged in so that stored graph nodes enrich the mock subgraph.

        TODO (Neo4j migration):
            Replace this method with:
                MATCH path = (d:Decision {id: $id})-[*1..3]-(related)
                RETURN d, related, relationships(path)
            and remove the mock matching logic below.

            This also unlocks "과거에 비슷한 결정으로 리스크가 있었나?"
            (past similar decisions with risk) because Neo4j persists all
            decisions as connected subgraphs. Shared Policy/Risk/Actor nodes
            create natural links between decisions:
                MATCH (current:Action {id: $id})-[:TRIGGERS]->(r:Risk)
                      <-[:TRIGGERS]-(past:Action)
                WHERE past.id <> $id
                RETURN past, r
            The o1 prompt already asks for historical analysis — it just
            needs the data, which requires persistence (Neo4j).

        Args:
            decision_id: Decision identifier (root of subgraph)
            decision_data: Decision dict with statement, goals, kpis, owners, risks
            company_data: Company context with strategic_goals, personnel, risk_tolerance
            graph_context: Optional pre-fetched context from graph repository

        Returns:
            Dict with nodes, edges, and metadata
        """
        nodes = []
        edges = []
        seen_ids = set()

        def _add_node(node_id: str, label: str, node_type: str, properties: Dict):
            if node_id not in seen_ids:
                nodes.append({
                    "id": node_id,
                    "label": label,
                    "type": node_type,
                    "properties": properties
                })
                seen_ids.add(node_id)

        def _add_edge(source: str, target: str, rel_type: str, properties: Optional[Dict] = None):
            edges.append({
                "source": source,
                "target": target,
                "type": rel_type,
                "properties": properties or {}
            })

        # ── 1. Root node: the decision itself ─────────────────────────────
        _add_node(decision_id, "Decision", "Action", {
            "statement": decision_data.get("decision_statement", ""),
            "status": decision_data.get("status", "pending"),
            "risk_score": decision_data.get("risk_score"),
            "strategic_impact": decision_data.get("strategic_impact"),
        })

        # ── 2. Decision owners → personnel match → reporting chain ────────
        personnel = company_data.get("approval_hierarchy", {}).get("personnel", [])
        personnel_by_id = {p.get("id"): p for p in personnel}
        decision_owner_names = set()
        matched_person_ids = set()

        explicit_owners = decision_data.get("owners", [])

        if explicit_owners:
            # Owners were stated in input — match them to real personnel
            for i, owner in enumerate(explicit_owners):
                owner_name = owner.get("name", owner.get("role", "")).strip().lower()
                decision_owner_names.add(owner_name)
                owner_node_id = f"{decision_id}_owner_{i}"

                _add_node(owner_node_id, "DecisionOwner", "Actor", owner)
                _add_edge(decision_id, owner_node_id, "OWNED_BY")

                for person in personnel:
                    p_name = person.get("name", "").lower()
                    p_role = person.get("role", "").lower()
                    p_id = person.get("id")

                    if owner_name and (owner_name in p_name or owner_name in p_role
                                       or p_name in owner_name or p_role in owner_name):
                        _add_node(p_id, "Person", "Actor", person)
                        _add_edge(owner_node_id, p_id, "MATCHES_PERSON")
                        matched_person_ids.add(p_id)

                        # Walk reporting chain upward (2 hops max)
                        current_id = p_id
                        for _ in range(2):
                            reports_to = personnel_by_id.get(current_id, {}).get("reports_to")
                            if reports_to and reports_to in personnel_by_id:
                                mgr = personnel_by_id[reports_to]
                                _add_node(reports_to, "Person", "Actor", mgr)
                                _add_edge(current_id, reports_to, "REPORTS_TO")
                                matched_person_ids.add(reports_to)
                                current_id = reports_to
                            else:
                                break
        else:
            # No owners stated — inject full personnel hierarchy as candidates
            # so o1 can reason about who should be accountable.
            for person in personnel:
                p_id = person.get("id")
                p_name = person.get("name", "")
                _add_node(p_id, "CandidateOwner", "Actor", person)
                matched_person_ids.add(p_id)

            # Add reporting chain edges between candidates
            for person in personnel:
                p_id = person.get("id")
                reports_to = person.get("reports_to")
                if reports_to and reports_to in personnel_by_id:
                    _add_edge(p_id, reports_to, "REPORTS_TO")

        # ── 3. Decision KPIs → match to strategic goal KPIs ──────────────
        decision_kpi_names = set()
        decision_kpi_keywords = set()  # Extract keywords for fuzzy matching
        for i, kpi in enumerate(decision_data.get("kpis", [])):
            kpi_id = kpi.get("id", f"{decision_id}_kpi_{i}")
            kpi_name = kpi.get("name", kpi.get("metric", "")).strip().lower()
            decision_kpi_names.add(kpi_name)

            # Extract keywords from KPI name (e.g., "운영비 -10%" → {"운영비"})
            # Remove numbers, percentages, and common filler words
            keywords = [w for w in kpi_name.replace("-", " ").replace("%", " ").split()
                       if len(w) >= 2 and not w.isdigit()]
            decision_kpi_keywords.update(keywords)

            _add_node(kpi_id, "KPI", "Resource", kpi)
            _add_edge(decision_id, kpi_id, "MEASURED_BY")

        # ── 4. Decision goals ────────────────────────────────────────────
        decision_goal_texts = set()
        for i, goal in enumerate(decision_data.get("goals", [])):
            goal_id = goal.get("id", f"{decision_id}_goal_{i}")
            goal_text = goal.get("description", goal.get("name", str(goal))).strip().lower()
            decision_goal_texts.add(goal_text)
            _add_node(goal_id, "DecisionGoal", "Action", goal if isinstance(goal, dict) else {"description": goal})
            _add_edge(decision_id, goal_id, "HAS_GOAL")

        # ── 5. Strategic goals (only those sharing KPIs, owners, or semantic overlap) ─
        for sg in company_data.get("strategic_goals", []):
            sg_id = sg.get("goal_id", sg.get("id"))
            sg_owner_id = sg.get("owner_id", "")
            sg_name = sg.get("name", "").lower()
            sg_desc = sg.get("description", "").lower()

            # Check KPI overlap (keyword-based for fuzzy matching)
            sg_kpi_keywords = set()
            for kpi in sg.get("kpis", []):
                kpi_name = kpi.get("name", "").strip().lower()
                # Extract keywords from strategic goal KPI (e.g., "운영비 절감률" → {"운영비", "절감률"})
                keywords = [w for w in kpi_name.replace("%", " ").split()
                           if len(w) >= 2 and not w.isdigit()]
                sg_kpi_keywords.update(keywords)

            # Match on keyword overlap instead of exact name (e.g., "운영비" in both)
            kpi_overlap = bool(decision_kpi_keywords & sg_kpi_keywords)

            # Check owner overlap
            owner_overlap = sg_owner_id in matched_person_ids

            # Check semantic overlap (simple keyword match for MVP)
            semantic_overlap = any(
                word in sg_name or word in sg_desc
                for word in decision_goal_texts
                if len(word) > 3  # skip short words
            )

            # Include this strategic goal if any overlap found
            if kpi_overlap or owner_overlap or semantic_overlap:
                overlap_types = []
                if kpi_overlap:
                    overlap_types.append("shared_kpi")
                if owner_overlap:
                    overlap_types.append("shared_owner")
                if semantic_overlap:
                    overlap_types.append("semantic")

                _add_node(sg_id, "StrategicGoal", "Action", sg)
                _add_edge(decision_id, sg_id, "ALIGNS_TO", {
                    "overlap_types": overlap_types,
                    "confidence": 0.9 if kpi_overlap else (0.7 if owner_overlap else 0.5)
                })

                # Also link the strategic goal's owner if not already in subgraph
                if sg_owner_id and sg_owner_id in personnel_by_id:
                    owner_person = personnel_by_id[sg_owner_id]
                    _add_node(sg_owner_id, "Person", "Actor", owner_person)
                    _add_edge(sg_id, sg_owner_id, "GOAL_OWNED_BY")

        # ── 6. Decision risks ────────────────────────────────────────────
        for i, risk in enumerate(decision_data.get("risks", [])):
            risk_id = risk.get("id", f"{decision_id}_risk_{i}") if isinstance(risk, dict) else f"{decision_id}_risk_{i}"
            risk_props = risk if isinstance(risk, dict) else {"description": risk}
            _add_node(risk_id, "Risk", "Risk", risk_props)
            _add_edge(decision_id, risk_id, "TRIGGERS_RISK")

        # ── 7. Risk tolerance context (as a single reference node) ────────
        risk_tolerance = company_data.get("risk_tolerance", {})
        if risk_tolerance:
            _add_node("risk_tolerance", "RiskTolerance", "Policy", risk_tolerance)
            _add_edge(decision_id, "risk_tolerance", "EVALUATED_AGAINST")

        # ── 8. Merge in graph_context from repository (if available) ──────
        # This enriches the mock subgraph with nodes already stored in the
        # graph repository (e.g. policies, approval chain actors from
        # InMemoryGraphRepository). When Neo4j is added, this path becomes
        # the primary data source and the mock matching above can be removed.
        if graph_context:
            self._merge_graph_context(
                graph_context, nodes, edges, seen_ids,
                _add_node, _add_edge, decision_id
            )

        metadata = {
            "nodes_total": len(nodes),
            "edges_total": len(edges),
            "source": "mock+repository" if graph_context else "mock",
            "selection_criteria": [
                "owner_match → personnel → reporting_chain (2 hops)",
                "kpi_overlap → strategic_goals",
                "owner_overlap → strategic_goals",
                "semantic_overlap → strategic_goals",
                "risks → risk_tolerance",
                "graph_context merge (policies, approval actors)"
            ],
            "matched_personnel": list(matched_person_ids),
        }

        logger.info(
            f"Subgraph extracted: {len(nodes)} nodes, {len(edges)} edges "
            f"(source={metadata['source']}, matched_personnel={len(matched_person_ids)})"
        )

        return {"nodes": nodes, "edges": edges, "metadata": metadata}

    def _merge_graph_context(
        self,
        graph_context: Dict,
        nodes: list,
        edges: list,
        seen_ids: set,
        _add_node,
        _add_edge,
        decision_id: str
    ):
        """
        Merge pre-fetched graph repository context into the subgraph.

        This bridges InMemoryGraphRepository data (policies, approval actors)
        with the mock company-data matching above.
        """
        # Merge actors (approval chain members stored in graph)
        for actor in graph_context.get("actors", []):
            actor_id = actor.id if hasattr(actor, 'id') else actor.get("id")
            actor_label = actor.label if hasattr(actor, 'label') else actor.get("label", "")
            actor_props = actor.properties if hasattr(actor, 'properties') else actor.get("properties", {})

            _add_node(actor_id, actor_label, "Actor", actor_props)

        # Merge policies (governance rules stored in graph)
        for policy in graph_context.get("policies", []):
            policy_id = policy.id if hasattr(policy, 'id') else policy.get("id")
            policy_label = policy.label if hasattr(policy, 'label') else policy.get("label", "")
            policy_props = policy.properties if hasattr(policy, 'properties') else policy.get("properties", {})

            _add_node(policy_id, policy_label, "Policy", policy_props)
            _add_edge(decision_id, policy_id, "GOVERNED_BY")

        # Merge risks from graph
        for risk in graph_context.get("risks", []):
            risk_id = risk.id if hasattr(risk, 'id') else risk.get("id")
            risk_label = risk.label if hasattr(risk, 'label') else risk.get("label", "")
            risk_props = risk.properties if hasattr(risk, 'properties') else risk.get("properties", {})

            _add_node(risk_id, risk_label, "Risk", risk_props)

        # Merge edges from graph
        for edge in graph_context.get("edges", []):
            source = edge.from_node if hasattr(edge, 'from_node') else edge.get("from_node", edge.get("from"))
            target = edge.to_node if hasattr(edge, 'to_node') else edge.get("to_node", edge.get("to"))
            predicate = edge.predicate if hasattr(edge, 'predicate') else edge.get("predicate", edge.get("type"))
            edge_props = edge.properties if hasattr(edge, 'properties') else edge.get("properties", {})

            _add_edge(source, target, str(predicate), edge_props)

    def _build_contradiction_prompt(self, decision_id: str, subgraph: Dict) -> str:
        """
        Build a structured prompt from the extracted subgraph.

        Organizes nodes by type so o1 can reason about structure clearly.
        """
        # Group nodes by type for readability
        nodes_by_type = {}
        for node in subgraph["nodes"]:
            ntype = node.get("type", "Unknown")
            nodes_by_type.setdefault(ntype, []).append(node)

        # Format nodes section
        nodes_section = ""
        for ntype, type_nodes in nodes_by_type.items():
            nodes_section += f"\n  {ntype} nodes ({len(type_nodes)}):\n"
            for n in type_nodes:
                props_summary = {k: v for k, v in n.get("properties", {}).items() if v is not None}
                nodes_section += f"    - [{n['id']}] {n['label']}"
                if props_summary:
                    nodes_section += f"  | {json.dumps(props_summary)}"
                nodes_section += "\n"

        # Format edges section
        edges_section = ""
        for e in subgraph["edges"]:
            edges_section += f"    {e['source']} --[{e['type']}]--> {e['target']}"
            if e.get("properties"):
                edges_section += f"  | {json.dumps(e['properties'])}"
            edges_section += "\n"

        return f"""You are a decision governance expert analyzing a decision subgraph for logical contradictions and structural issues.

This subgraph was extracted around decision "{decision_id}" by finding all nodes connected through shared owners, shared KPIs, shared strategic goals, and reporting chains. Only relevant context is included.

SUBGRAPH NODES ({len(subgraph['nodes'])} total):
{nodes_section}

SUBGRAPH EDGES ({len(subgraph['edges'])} total):
{edges_section}

EXTRACTION METADATA:
  Source: {subgraph['metadata']['source']}
  Selection: {', '.join(subgraph['metadata']['selection_criteria'][:3])}

ANALYSIS TASKS:

1. **LOGICAL CONTRADICTIONS**
   - Do any connected strategic goals conflict with each other?
   - Are KPIs measuring opposing outcomes (e.g. "reduce cost" vs "increase spend")?
   - Do risk mitigations contradict decision goals?

2. **STRATEGIC GOAL CONFLICTS** (CRITICAL)
   - Does this decision CONTRADICT any company strategic goals (StrategicGoal nodes)?
   - Examples of contradictions:
     * Decision increases costs significantly but G3 targets cost reduction
     * Decision creates compliance risk but G2 targets zero violations
     * Decision causes delays but G1 targets faster time-to-market
     * Decision violates safety protocols but G1 targets patient safety excellence
   - Look at decision risks, costs, and impacts vs. strategic goal descriptions and KPI targets
   - If contradiction found, mark as severity "critical" and add to contradictions list
   - This is the MOST IMPORTANT check - strategic misalignment must be flagged

3. **OWNERSHIP & AUTHORITY ISSUES**

   CRITICAL: Owner ≠ Approver. These are SEPARATE roles:
   - **Owner** (Person nodes linked via OWNED_BY): Accountable for delivering the outcome
   - **Approver** (ApprovalActor nodes via REQUIRES_APPROVAL): Reviews/signs off for governance

   The same person can be BOTH owner and approver, but they're distinct responsibilities.

   Ownership analysis when CandidateOwner nodes exist (no owner stated in input):

   **HIGH CONFIDENCE inference → Add to inferred_owners array:**
   - Decision domain has clear 1:1 role mapping AND that role exists in personnel:
     * R&D work → 연구개발팀장 exists → confidence: "high"
     * Finance/budget → CFO exists → confidence: "high"
     * IT infrastructure → IT팀장 exists → confidence: "high"
     * Marketing → 마케팅팀장 exists → confidence: "high"
   - Strategic goal ownership aligns with decision domain → confidence: "high"
   - Return person_id, name, role, confidence="high", reasoning

   **LOW CONFIDENCE / Ambiguous → Add to ownership_issues only:**
   - Multiple possible owners → "Consider assigning to X or Y"
   - No clear domain match → "Missing owner - please specify"
   - Required role doesn't exist in personnel → "Missing owner"

   DO NOT just pick from the approval chain. Approvers review; owners execute.

   Other ownership checks:
   - Does the decision owner have sufficient authority per the reporting chain?
   - Are there strategic goals owned by different people that this decision spans?
   - Are critical stakeholders missing from the subgraph?

4. **RISK COVERAGE GAPS**
   - Are decision risks within company risk tolerance thresholds?
   - Are there obvious risks not captured?
   - Do mitigations actually address the identified risks?

5. **ALIGNMENT GAPS**
   - Does the decision connect to appropriate strategic goals?
   - Are there orphaned goals or KPIs with no clear link?
   - Do KPI targets conflict across connected goals?

6. **STRUCTURAL ISSUES**
   - Circular dependencies between nodes
   - Missing critical relationships
   - Approval chain inconsistencies

7. **NEXT ACTIONS** (Korean language required)
   Based on the subgraph — specifically the triggered Policy nodes (governance rules with
   their actual conditions and thresholds), the approval hierarchy from Actor/Approver nodes,
   and any missing elements — generate a prioritized list of concrete actions the decision
   submitter should take to move this decision toward approval.

   Guidelines:
   - Each action must be specific and actionable, not generic
   - Where a governance rule sets a financial threshold, name it explicitly
     (e.g. "예산을 X원 미만으로 조정하거나 — 또는 CFO 승인 요청서와 비용 편익 분석을 첨부하세요")
   - Where an approver is required, specify what document/evidence to prepare
   - If a compliance risk must be resolved first, say what to prepare
   - If owner is missing, suggest which role based on the decision domain
   - Output in Korean only

Output JSON:
{{
  "contradictions": [
    {{
      "type": "goal_conflict" | "kpi_conflict" | "risk_conflict" | "authority_gap" | "alignment_gap",
      "severity": "critical" | "high" | "medium" | "low",
      "nodes_involved": ["node_id1", "node_id2"],
      "description": "Clear description of the contradiction",
      "evidence": "Specific edges/nodes that prove this",
      "impact": "What could go wrong",
      "recommendation": "How to resolve"
    }}
  ],
  "strategic_goal_conflicts": [
    {{
      "goal_id": "G1" | "G2" | "G3",
      "goal_name": "Strategic goal name from StrategicGoal node",
      "conflict_type": "cost_contradiction" | "compliance_contradiction" | "timeline_contradiction" | "safety_contradiction" | "quality_contradiction",
      "severity": "critical" | "high" | "medium",
      "description": "How the decision contradicts this strategic goal",
      "evidence": "Specific decision properties (cost, risks, timeline) vs. goal KPI targets",
      "impact": "Impact on achieving the strategic goal",
      "recommendation": "How to align decision with goal"
    }}
  ],
  "inferred_owners": [
    {{
      "person_id": "string (person ID from CandidateOwner nodes, e.g. 'rd_dir_001')",
      "name": "string (actual person name from company personnel, e.g. '오세훈')",
      "role": "string (person's role, e.g. '연구개발팀장')",
      "confidence": "high" | "medium" | "low",
      "reasoning": "string (why this person should be the owner)"
    }}
  ],
  "ownership_issues": [
    {{
      "issue_type": "missing_owner" | "missing_stakeholder" | "insufficient_authority" | "wrong_owner" | "cross_goal_conflict",
      "severity": "critical" | "high" | "medium" | "low",
      "description": "What's wrong",
      "recommendation": "Who should be involved or what to change"
    }}
  ],
  "risk_gaps": [
    {{
      "gap_type": "missing_risk" | "insufficient_mitigation" | "tolerance_violation",
      "severity": "critical" | "high" | "medium" | "low",
      "description": "What's missing or inadequate",
      "recommendation": "What should be added"
    }}
  ],
  "recommendations": [
    {{
      "priority": "critical" | "high" | "medium" | "low",
      "action": "Specific actionable step",
      "affected_nodes": ["node_ids"],
      "reasoning": "Why this is needed based on subgraph analysis"
    }}
  ],
  "next_actions": [
    "Korean string: concrete step toward approval — e.g. 'CFO 승인을 받으세요 — 2.5억 원 규모로 자본적 지출 승인 규정(R1)이 적용됩니다. 비용 편익 분석 및 예산 근거를 첨부하거나, 예산을 5,000만 원 이하로 조정하세요'",
    "Korean string: next step..."
  ],
  "graph_health_score": 0.0-1.0,
  "confidence": 0.0-1.0,
  "reasoning_summary": "Overall assessment based on subgraph structure"
}}

Be rigorous. Focus on LOGICAL reasoning from the graph structure. Identify contradictions a human reviewer might miss.
For next_actions: use the actual rule conditions and thresholds visible in the Policy nodes — do not invent generic guidance."""
