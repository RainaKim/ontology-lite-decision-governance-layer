"""
Extraction prompt templates for onboarding scouts.

Each prompt is a system + human message pair passed to the LLM.
All prompts are generic — no hardcoded company names or industry logic.
The system prompt instructs the LLM about valid node types and output format.
The human prompt provides the artifact text and extraction task.
"""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate


def build_seeded_nodes_section(seeded_nodes_context: str) -> str:
    """
    Build the prompt section for seeded nodes context.

    Returns an empty string when no seeded context is available,
    so the prompt degrades gracefully for backward compatibility.
    """
    if not seeded_nodes_context or not seeded_nodes_context.strip():
        return ""
    return (
        "## Known Governance Entities (already in graph)\n"
        "These nodes were seeded from the company config and already exist in the graph.\n"
        "Reference them by semantic_id when creating edges. Do NOT re-extract them as new nodes.\n"
        "If you discover new information about a seeded entity, create an EDGE to it — not a duplicate node.\n\n"
        f"{seeded_nodes_context}\n\n"
        "When you extract edges, check if the target already exists in the table above. "
        "If so, use its exact Semantic ID as the to_semantic_id or from_semantic_id."
    )


# ---------------------------------------------------------------------------
# Shared system context
# ---------------------------------------------------------------------------

_NODE_TYPE_GUIDE = """\
You extract governance ontology nodes AND their relationships from company artifacts.
This is an onboarding extraction — you are building the company's governance knowledge graph
from existing documents. There are no live decisions yet; you are capturing the standing
rules, goals, people, and structure that will later be used to evaluate decisions.

Valid node types (domain-layer and instance-layer):
  Goal         — a LONG-TERM strategic objective the company is trying to achieve.
                 Goals are broad, enduring targets like "Revenue Growth" or "Data Compliance".
                 Do NOT create Goal nodes for:
                   - Actions or tasks: "Hire engineers", "Migrate to AWS", "Build dashboard"
                   - Time-bound initiatives: "Q2 hiring push", "Q4 cost reduction program"
                   - KPIs or metrics: "$4.5M expansion revenue", "120% NRR"
                   - Restatements of existing goals: if a goal matches a known seeded goal
                     (even with slightly different wording like "Revenue Growth Improvement"
                     vs "Revenue Growth"), do NOT create a new Goal — reference the seeded one.
                 Those should be KPI, Action, or Decision nodes instead.
                 If in doubt, check the seeded goals list — if your extracted goal is just
                 a more specific version of a seeded goal, do NOT create a new node.
                 Properties: goal_id (see rules below), priority (critical/high/medium/low),
                             description, owner_role
                 Temporal properties (include when stated):
                   effective_date — when it takes effect (ISO date or "YYYY-QN", e.g. "2024-Q4")
                   expiry_date — when it expires (if stated)
                   temporal_scope — "Q1"|"Q2"|"Q3"|"Q4"|"H1"|"H2"|"annual"|"permanent"
                   recurring — true if this applies every year/quarter, false if one-time
  Rule         — a REUSABLE governance policy that applies across multiple decisions.
                 A Rule is a standing constraint like "CFO must approve spend > $50K".
                 Rules are GENERIC and apply to any decision that meets their conditions.
                 Examples of Rules:
                   YES: "CFO must approve spend > $50K" (generic, reusable)
                   YES: "Legal sign-off required for customer data usage" (generic)
                   YES: "Board approval needed for contracts > $200K" (generic)
                 Examples of things that are NOT Rules (use Decision instead):
                   NO: "TestCo Contract Approval" — this is a specific past decision
                   NO: "Q2 Hiring Budget Decision" — this is a specific budget decision
                   NO: "Enterprise BI Reseller Partnership" — this is a specific deal
                   NO: "Monthly Billing for First 6 Months" — a specific pricing decision
                 If the text describes an APPLICATION of an existing rule (e.g. "this contract
                 was reviewed under R4"), create a GOVERNED_BY edge to that rule — do NOT
                 create a new Rule node.
                 Properties: rule_id, conditions (list of field/operator/value dicts),
                              consequence (action + approver_role), source (documented/inferred/interview)
                 Temporal properties (include when stated):
                   effective_date — when it takes effect (ISO date or "YYYY-QN", e.g. "2024-Q4")
                   expiry_date — when it expires (if stated)
                   temporal_scope — "Q1"|"Q2"|"Q3"|"Q4"|"H1"|"H2"|"annual"|"permanent"
                   recurring — true if this applies every year/quarter, false if one-time
  Decision     — a SPECIFIC past decision, approval, contract, or budget action (instance-layer).
                 Use this for concrete events: "TestCo contract approval", "Q2 hiring decision".
                 Properties: decision_id, date, requester, amount, status, description,
                             decision_type
                 Connect to the Rule(s) it triggered via TRIGGERED edges, to the Actor who
                 approved via APPROVED_BY edges, and to the Goal it relates to via GOVERNED_BY.
  Actor        — person, role, or group with authority to approve or review
                 Properties: role, approval_limit (number in base currency), reports_to
  Department   — organizational unit
                 Properties: dept_id, parent_dept_id
  KPI          — measurable metric that tracks a goal
                 Properties: kpi_id, unit, target
  Jurisdiction — legal jurisdiction or regulatory body
                 Properties: code, regulation_type
  Gap          — missing governance control or unresolved inconsistency you observe
                 Properties: gap_type, description
  Conflict     — incompatibility between two governance entities you observe
                 Properties: description
  GovernanceRisk — a standing governance risk category that exists before any decision.
                 These represent ongoing organizational risks that governance rules either
                 generate (when triggered) or mitigate. Examples: budget overrun, compliance
                 violation, key-person dependency, vendor lock-in.
                 Properties: risk_category (financial/compliance/operational/strategic),
                             severity (critical/high/medium/low), description

Valid edge predicates for onboarding (use EXACTLY these strings):

  Governance structure edges — THE MOST IMPORTANT edges to extract:
    GOVERNED_BY           — Rule → Goal OR Decision → Rule: this rule exists to protect or enforce
                            this strategic goal, or this decision was governed by this rule.
                            Every rule should link to the goal(s) it serves.
                            When assigning GOVERNED_BY edges, consider ALL goals — not just the most obvious one.
                            A rule about data handling could serve data_compliance AND cost_stability.
                            A spending rule could serve both cost_stability AND revenue_growth (by protecting margins).
                            If a rule plausibly serves multiple goals, create multiple GOVERNED_BY edges.
                            IMPORTANT: Rule → Rule GOVERNED_BY is NOT allowed. Rules govern goals,
                            not other rules. If two rules are related, they both govern the same goal.
    SUPPORTS              — Goal → Goal: this sub-goal advances or contributes to the parent goal.
                            "A SUPPORTS B" means achieving A directly advances B.
                            If A merely depends on B, do NOT create a SUPPORTS edge.
                            If A and B are the same concept with different names, do NOT create
                            a SUPPORTS edge — they should be merged into one node.
    CONFLICTS_WITH        — Goal ↔ Goal: pursuing one goal actively hinders or creates tension
                            with the other. Common conflict patterns:
                              - Speed/velocity vs compliance (shipping fast vs thorough review)
                              - Growth vs cost control (spending to grow vs staying within budget)
                              - Revenue vs compliance (revenue targets vs regulatory constraints)
                            Check ALL known seeded goals for conflicts, not just goals in the current chunk.
                            If the text mentions tension between ANY two seeded goals, create a
                            CONFLICTS_WITH edge even if only one goal is directly discussed.
    TRIGGERED             — Decision → Rule: this past decision triggered or was evaluated under
                            this governance rule.
    APPROVED_BY           — Decision → Actor: this past decision was approved by this actor/role.
    HAS_GAP               — Rule → Gap or Goal → Gap: a governance gap or missing process
                            associated with this entity.

  Risk edges:
    GENERATES_RISK        — Rule → GovernanceRisk: triggering this rule generates this risk.
                            E.g. "large spend rule" → "budget_overrun_risk"
    MITIGATES             — Rule → GovernanceRisk: this rule mitigates or controls this risk.
                            E.g. "CFO approval rule" → "budget_overrun_risk"
    HAS_RISK              — Goal → GovernanceRisk: this goal is exposed to this standing risk.
                            E.g. "cost_stability" → "budget_overrun_risk"

  Authority / approval edges:
    REQUIRES_APPROVAL_FROM — Rule → Actor: rule mandates full approval from this role.
    REQUIRES_REVIEW_FROM  — Rule → Actor: rule mandates advisory review from this role.
    ESCALATES_TO          — Actor → Actor: approval escalates to this higher-authority role.
    BELONGS_TO            — Actor → Department: actor is a member of this department.

  Measurement edges:
    MEASURED_BY           — Goal → KPI: goal is measured by this KPI.

  Provenance edges:
    DERIVED_FROM          — any node → Chunk: node was derived from this text chunk.

  Decision instance edges:
    TRIGGERED             — Decision → Rule: this past decision triggered this governance rule.
    APPROVED_BY           — Decision → Actor: this past decision was approved by this actor.

IMPORTANT — Edges are as important as nodes. For every node you extract, produce at least one
edge connecting it to another entity. A node with zero edges is almost always incomplete.
Ask yourself: "What goal does this rule protect? Who approves it? What department owns it?"
For Decision nodes: "What rule did this decision trigger? Who approved it? Which goal is it related to?"

CRITICAL rules for goal_id:
  - If the text contains an explicit identifier for the goal (e.g. "G1", "O2", "OBJ-3"),
    use that exact identifier as goal_id.
  - If no explicit identifier is stated in the text, set goal_id to null.
    Do NOT guess or reuse another goal's ID. Do NOT default to "G1".

CRITICAL rules for semantic_id:
  - Must be a short lowercase slug using ONLY a-z, 0-9, underscore, hyphen, or dot
  - NO spaces allowed — use underscores instead of spaces (e.g. "revenue_growth" not "revenue growth")
  - Use the explicit ID from the text if one exists (e.g. "R1", "G2", "K3")
  - Otherwise derive a 2-4 word slug (e.g. "cfo", "data_privacy_rule", "engineering_dept")
  - Examples of VALID semantic_ids: "r1", "cfo", "revenue_growth", "legal_counsel", "gdpr"
  - Examples of INVALID semantic_ids: "Revenue Growth", "CFO Role", "rule 1"

Rules for extraction:
  - Only extract what is clearly stated or strongly implied in the text
  - For Rule nodes: each condition must be a dict with "field" (e.g. "cost", "headcount_change"),
    "operator" (one of: ">", "<", ">=", "<=", "==", "is_true", "is_false"), and "value"
  - For Rule consequence: must have "action" (require_approval or require_review) and "approver_role"
  - Set confidence=1.0 for explicitly documented items, 0.7 for clear implications, 0.4 for inferences
  - source_excerpt must be ≤100 characters, verbatim from the text
  - Do NOT invent nodes not supported by the text
  - Return empty lists if nothing relevant is found
  - When creating edges, from_semantic_id and to_semantic_id must exactly match the semantic_id
    of nodes you extracted (not the label, not the full node ID)

## Temporal Properties (add to ANY Goal or Rule node when time context is present)
  effective_date   — when the rule/goal takes effect (ISO date "YYYY-MM-DD" or quarter "YYYY-QN")
  expiry_date      — when it expires or becomes inactive (ISO date or null if permanent)
  temporal_scope   — "Q1"|"Q2"|"Q3"|"Q4"|"H1"|"H2"|"annual"|"permanent"
  recurring        — true if this applies every year/quarter, false if one-time

CRITICAL: If a rule or goal mentions ANY time reference (quarter, year, freeze period,
review cycle, annual, "by end of"), you MUST populate these fields on the node. Missing temporal
data on time-referenced rules is a quality failure. Add these as top-level fields on the node
(alongside node_type, semantic_id, etc.), not inside properties.

You MUST respond with a JSON object matching this EXACT schema:
{{
  "nodes": [
    {{
      "node_type": "<Goal|Rule|Decision|Actor|Department|KPI|Jurisdiction|Gap|Conflict|GovernanceRisk>",
      "semantic_id": "<lowercase_slug>",
      "label": "<Human-readable name>",
      "properties": {{}},
      "confidence": <0.0-1.0>,
      "source_excerpt": "<verbatim text ≤100 chars>",
      "effective_date": "<YYYY-MM-DD or null>",
      "expiry_date": "<YYYY-MM-DD or null>",
      "temporal_scope": "<Q1|Q2|Q3|Q4|H1|H2|annual|permanent or null>",
      "recurring": "<true|false or null>"
    }}
  ],
  "edges": [
    {{
      "from_semantic_id": "<semantic_id of source node>",
      "to_semantic_id": "<semantic_id of target node>",
      "predicate": "<EXACT predicate string from list above>",
      "evidence": "<short evidence text>"
    }}
  ]
}}

Every node MUST have "node_type" (not "type") and "label" fields. Return {{"nodes": [], "edges": []}} if nothing relevant.

{seeded_nodes_section}"""

# ---------------------------------------------------------------------------
# Document scout prompt (policy docs, strategy docs, handbooks)
# ---------------------------------------------------------------------------

DOCUMENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            _NODE_TYPE_GUIDE
            + "\nFocus: formal policies, approval thresholds, governance rules, "
            "strategic goals, KPIs, and organizational roles from document text.\n\n"
            "For rules or goals with time constraints (e.g. 'Q4 hiring freeze', "
            "'budget review by end of H1'), capture the temporal properties "
            "(effective_date, expiry_date, temporal_scope, recurring).",
        ),
        (
            "human",
            "Extract governance entities AND their relationships from this document.\n\n"
            "Document: {artifact_path}\n\n"
            "---\n{text}\n---\n\n"
            "Extract all Rules, Goals, Actors, KPIs, Departments, Jurisdictions, "
            "and any Gaps or Conflicts you observe.\n\n"
            "Then build edges — this is critical:\n"
            "  For EVERY Rule: identify which Goal it protects → create a GOVERNED_BY edge\n"
            "  For EVERY Goal: check if it supports or conflicts with other goals "
            "→ create SUPPORTS or CONFLICTS_WITH edges\n"
            "  For EVERY Gap: link to the Rule or Goal it affects → create a HAS_GAP edge\n"
            "  For EVERY Actor: link to Department via BELONGS_TO, "
            "to supervisor via ESCALATES_TO\n"
            "  For EVERY Rule with an approver: create REQUIRES_APPROVAL_FROM or "
            "REQUIRES_REVIEW_FROM edge\n"
            "  For EVERY KPI: link to the Goal it measures → create a MEASURED_BY edge\n\n"
            "A good extraction has roughly as many edges as nodes. "
            "Nodes without edges are almost always incomplete.",
        ),
    ]
)

# ---------------------------------------------------------------------------
# Conversation scout prompt (emails, Slack, meeting minutes)
# ---------------------------------------------------------------------------

CONVERSATION_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            _NODE_TYPE_GUIDE
            + "\nFocus: informal authority patterns, undocumented approval practices, "
            "budget constraints mentioned in passing, and role relationships revealed "
            "through conversation. These become Rules with source='inferred' or source='interview'.\n\n"
            "Conversations often reveal time-sensitive rules (e.g. 'freeze hiring until Q2'). "
            "Capture temporal properties when mentioned.",
        ),
        (
            "human",
            "Extract governance entities AND their relationships from this conversation.\n\n"
            "Artifact: {artifact_path}\n\n"
            "---\n{text}\n---\n\n"
            "Look for:\n"
            "  - Spending thresholds mentioned in conversation → Rule nodes\n"
            "  - Approval requests and sign-off patterns → Rule + REQUIRES_APPROVAL_FROM edges\n"
            "  - Role relationships → Actor nodes + ESCALATES_TO / BELONGS_TO edges\n"
            "  - Informal rules ('we always get CFO sign-off on...') → Rule with source='inferred'\n"
            "  - Direct policy quotes → Rule with source='interview'\n"
            "  - Policy gaps visible from context → Gap + HAS_GAP edges\n"
            "  - Goal tensions ('we want to cut costs but also hire fast') → CONFLICTS_WITH edges\n\n"
            "For every Rule you extract, ask: which Goal does it protect? "
            "Create a GOVERNED_BY edge.\n"
            "For every Actor, ask: what department? who do they report to? "
            "Create BELONGS_TO and ESCALATES_TO edges.",
        ),
    ]
)

# ---------------------------------------------------------------------------
# Data scout prompt (CSVs, spreadsheets, org charts, approval logs)
# ---------------------------------------------------------------------------

DATA_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            _NODE_TYPE_GUIDE
            + "\nFocus: organizational structure (Actor, Department), numeric thresholds "
            "found in data, approval limits from spreadsheets, and authority matrices. "
            "Structured data often makes implicit rules explicit.",
        ),
        (
            "human",
            "Extract governance entities AND their relationships from this structured data.\n\n"
            "Artifact: {artifact_path}\n\n"
            "---\n{text}\n---\n\n"
            "Extract from the data:\n"
            "  - Org chart hierarchy → Actor + Department nodes, BELONGS_TO + ESCALATES_TO edges\n"
            "  - Approval limits by role → Rule nodes + REQUIRES_APPROVAL_FROM edges to Actor\n"
            "  - Budget thresholds → Rule nodes + GOVERNED_BY edges to the Goal they protect\n"
            "  - Authority matrix entries → Rule nodes linking Actors to approval responsibilities\n\n"
            "Each unique role becomes an Actor node. Each department becomes a Department node.\n"
            "Every Actor must have a BELONGS_TO edge to a Department.\n"
            "Every Rule derived from the data must have at least one GOVERNED_BY edge to a Goal "
            "and one REQUIRES_APPROVAL_FROM edge to an Actor.",
        ),
    ]
)
