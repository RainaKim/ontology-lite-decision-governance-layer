"""
Response Normalizers — Transform raw engine output to contract-compliant shapes.

These functions operate at the RESPONSE LAYER only.
They do NOT modify the governance engine or decision pack builder.

Contract normalization rules:
1. Flags: raw strings → structured {code, category, severity, message}
2. Rules: add status TRIGGERED/PASSED, build all_rules from company context
3. Approval chain: add status "pending" to each step
"""

from datetime import datetime, timezone
from typing import Optional

from app.schemas.responses import (
    ConsolePayloadResponse,
    CompanySummaryResponse,
    DecisionStatus,
    DecisionSummary,
    DerivedAttributes,
    GovernancePayload,
    GraphPayload,
    GraphNode,
    GraphEdge,
    ReasoningPayload,
    DecisionPackPayload,
    ExtractionMetadata,
    NormalizedFlag,
    NormalizedRule,
    NormalizedApprovalStep,
    FlagCategory,
    FlagSeverity,
    RuleStatus,
)
from app.repositories.decision_store import DecisionRecord
from app.services import company_service


# ---------------------------------------------------------------------------
# Flag Normalization
# ---------------------------------------------------------------------------

# Category mapping: flag prefix/pattern → category
# Evaluated in order; first match wins.
_FLAG_CATEGORY_PATTERNS = [
    (["HIGH_FINANCIAL", "BUDGET", "COST", "FINANCIAL"], FlagCategory.financial),
    (["PRIVACY", "GDPR", "HIPAA", "PII"], FlagCategory.privacy),
    (["CRITICAL_CONFLICT", "BLOCK"], FlagCategory.conflict),
    # BOARD indicates strategic-level escalation, not mere governance process
    (["STRATEGIC", "BOARD"], FlagCategory.strategic),
    (["APPROVAL_REQUIRED", "COMPLIANCE"], FlagCategory.governance),
]

# Severity mapping: flag pattern → severity
_FLAG_SEVERITY_PATTERNS = [
    ("CRITICAL", FlagSeverity.critical),
    ("HIGH", FlagSeverity.high),
    ("MEDIUM", FlagSeverity.medium),
]

# Human-readable messages for common flags
_FLAG_MESSAGES = {
    "HIGH_FINANCIAL_RISK": "고위험 재무 지출이 포함된 의사결정입니다",
    "BOARD_APPROVAL_REQUIRED": "이사회 승인 필요",
    "PRIVACY_REVIEW_REQUIRED": "개인정보/보안 검토 필요",
    "CRITICAL_CONFLICT": "의사결정 내 치명적 상충 항목이 존재합니다",
    "HIGH_RISK": "고위험 의사결정으로 분류되었습니다",
    "STRATEGIC_CRITICAL": "전략적 중요성이 매우 높은 의사결정입니다",
    "MISSING_OWNER": "의사결정 실행 책임자가 지정되지 않았습니다",
    "MISSING_RISK_ASSESSMENT": "리스크 평가가 누락되었습니다",
    "FINANCIAL_THRESHOLD_EXCEEDED": "재무 승인 기준을 초과하였습니다",
    "GOVERNANCE_COVERAGE_GAP": "이 의사결정 유형에 적용 가능한 거버넌스 규정이 없습니다 — 규정 추가 또는 수동 검토를 고려하세요",
}


# Each flag only looks at the rule types that are its root cause.
# This prevents governance flags and strategic flags from showing the same goals
# when they are triggered by fundamentally different rules.
_FLAG_RELEVANT_RULE_TYPES: dict[str, set[str]] = {
    "HIGH_RISK":                   {"compliance", "privacy"},          # risk score driven by compliance violations
    "PRIVACY_REVIEW_REQUIRED":     {"compliance", "privacy"},
    "STRATEGIC_CRITICAL":          {"strategic"},                       # strategic rules only
    "STRATEGIC_MISALIGNMENT":      {"strategic"},
    "FINANCIAL_THRESHOLD_EXCEEDED":{"financial", "capital_expenditure"},
    # default (not in map) → use ALL triggered rule types
}

# Rule-type → broad keyword hints to ensure goals are found even when
# rule descriptions don't explicitly repeat the goal's vocabulary
_TYPE_HINT_KEYWORDS: dict[str, set[str]] = {
    "compliance": {"규제", "준수", "COMPLIANCE", "HIPAA", "GDPR", "프라이버시", "데이터", "개인정보"},
    "privacy":    {"프라이버시", "PII", "PHI", "데이터", "개인정보", "규제"},
    "financial":  {"비용", "예산", "효율", "절감", "COST", "BUDGET"},
    "strategic":  {"안전", "SAFETY", "환자", "PATIENT", "전략", "STRATEGIC", "임상"},
}


def _compute_affected_goals(
    flag_code: str,
    triggered_rules: list[dict],
    company_goals: list[dict],
) -> list[dict]:
    """
    Identify which strategic goals are at risk for a given flag.

    Strategy: match goals against the *type-hint vocabulary* of the rule types
    that caused this flag — NOT against the raw rule description text.

    Rule description text is avoided because it shares incidental vocabulary
    (e.g. "환자" appears in both a compliance rule and a patient-safety goal)
    that would create misleading cross-category goal attribution.

    Example for this HIPAA scenario:
      HIGH_RISK (compliance rule R2) → hint vocab {규제, HIPAA, 데이터, …}
        → G2 "규제 및 데이터 준수" matches; G1 "환자 안전" does NOT
      STRATEGIC_CRITICAL (strategic rules R3/R4) → hint vocab {안전, 환자, 임상, …}
        → G1 "환자 안전 우수성" matches; G2 also matches via "임상"

    Returns a deduplicated list of {goal_id, name, priority} dicts.
    """
    if not triggered_rules or not company_goals:
        return []

    flag_upper = flag_code.upper()

    # Flags that do not benefit from goal annotation
    skip_flags = {"MISSING_OWNER", "MISSING_RISK_ASSESSMENT", "CRITICAL_CONFLICT", "GOVERNANCE_COVERAGE_GAP"}
    if flag_upper in skip_flags:
        return []

    # Collect which rule types were actually triggered, filtered by this flag's scope
    relevant_type_filter = _FLAG_RELEVANT_RULE_TYPES.get(flag_upper)  # None → accept all
    active_rule_types: set[str] = set()
    for r in triggered_rules:
        rt = (r.get("rule_type") or r.get("type", "")).lower()
        if relevant_type_filter is None or rt in relevant_type_filter:
            active_rule_types.add(rt)

    if not active_rule_types:
        return []

    # Build the matching vocabulary from type hints only (not rule description text)
    hint_vocab: set[str] = set()
    for rt in active_rule_types:
        hint_vocab |= _TYPE_HINT_KEYWORDS.get(rt, set())

    if not hint_vocab:
        return []

    # Build keyword set for a goal (name + description + KPI names)
    def _goal_keywords(goal: dict) -> set:
        parts = [goal.get("name", ""), goal.get("description", "")]
        for kpi in goal.get("kpis", []):
            parts.append(kpi.get("name", "") if isinstance(kpi, dict) else str(kpi))
        return set(w.upper() for part in parts for w in part.replace("-", " ").split() if len(w) >= 2)

    affected = []
    for goal in company_goals:
        goal_id = goal.get("goal_id", "")
        if not goal_id:
            continue
        if _goal_keywords(goal) & hint_vocab:
            affected.append({
                "goal_id": goal_id,
                "name": goal.get("name", ""),
                "priority": goal.get("priority"),
            })

    return affected


def _normalize_flags(
    raw_flags: list[str],
    inferred_owner: bool = False,
    triggered_rules: list[dict] = None,
    company_goals: list[dict] = None,
) -> list[NormalizedFlag]:
    """
    Transform raw string flags to structured NormalizedFlag objects.

    - Suppresses MISSING_OWNER if inferred_owner is True.
    - Deduplicates flags (engine may emit duplicates in edge cases).
    - Annotates STRATEGIC_CRITICAL / PRIVACY_REVIEW_REQUIRED / HIGH_RISK flags
      with the list of strategic goals they put at risk.
    """
    normalized = []
    seen_codes: set[str] = set()  # deduplication

    for flag in raw_flags:
        if flag.upper() == "MISSING_OWNER" and inferred_owner:
            continue
        if flag in seen_codes:
            continue  # drop duplicate
        seen_codes.add(flag)

        flag_upper = flag.upper()

        # Determine category
        category = FlagCategory.governance  # default
        for patterns, cat in _FLAG_CATEGORY_PATTERNS:
            if any(p in flag_upper for p in patterns):
                category = cat
                break

        # Determine severity
        severity = FlagSeverity.low  # default
        for pattern, sev in _FLAG_SEVERITY_PATTERNS:
            if pattern in flag_upper:
                severity = sev
                break

        # Get message
        message = _FLAG_MESSAGES.get(flag, f"Governance flag: {flag}")

        # Compute affected strategic goals for strategic/compliance/risk flags
        affected_goals = _compute_affected_goals(
            flag_code=flag,
            triggered_rules=triggered_rules or [],
            company_goals=company_goals or [],
        )

        normalized.append(NormalizedFlag(
            code=flag,
            category=category,
            severity=severity,
            message=message,
            affected_goals=affected_goals,
        ))

    return normalized


# ---------------------------------------------------------------------------
# Rule Normalization
# ---------------------------------------------------------------------------

def _normalize_rules(
    triggered_rules: list[dict],
    company_id: str,
) -> tuple[list[NormalizedRule], list[NormalizedRule]]:
    """
    Transform triggered rules and derive all_rules from company context.

    Returns (triggered_rules with TRIGGERED status, all_rules with TRIGGERED/PASSED status)
    """
    # Get all rules from company
    all_company_rules = company_service.get_governance_rules(company_id)
    triggered_ids = {r.get("rule_id") for r in triggered_rules}

    def truncate_description(desc: str, max_len: int = 80) -> str:
        """Truncate description for dashboard display."""
        if len(desc) <= max_len:
            return desc
        return desc[:max_len - 3].rsplit(' ', 1)[0] + "..."

    # Build triggered list with TRIGGERED status
    normalized_triggered = []
    for rule in triggered_rules:
        desc = rule.get("description", "")
        normalized_triggered.append(NormalizedRule(
            rule_id=rule.get("rule_id", ""),
            name=rule.get("name", ""),
            type=rule.get("type", rule.get("rule_type", "governance")),
            description=desc,
            short_description=truncate_description(desc),
            status=RuleStatus.TRIGGERED,
            severity=rule.get("severity", "medium"),
            consequence=rule.get("consequence", {}),
        ))

    # Build all_rules: triggered ones + passed ones
    normalized_all = list(normalized_triggered)  # copy triggered

    for rule in all_company_rules:
        rule_id = rule.get("rule_id")
        if rule_id not in triggered_ids:
            # This rule was evaluated but not triggered → PASSED
            desc = rule.get("description", "")
            normalized_all.append(NormalizedRule(
                rule_id=rule_id,
                name=rule.get("name", ""),
                type=rule.get("type", "governance"),
                description=desc,
                short_description=truncate_description(desc),
                status=RuleStatus.PASSED,
                severity=rule.get("consequence", {}).get("severity", "medium"),
                consequence=rule.get("consequence", {}),
            ))

    return normalized_triggered, normalized_all


# ---------------------------------------------------------------------------
# Approval Chain Normalization
# ---------------------------------------------------------------------------

def _normalize_approval_chain(
    raw_chain: list[dict],
    triggered_rules: list[dict],
    company_data: dict = None,
) -> list[NormalizedApprovalStep]:
    """
    Add status: "pending", reason, source_rule_id, and auth_type to each approval step.

    auth_type is derived from rule_action:
    - require_approval → REQUIRED
    - require_review   → ESCALATION
    - require_goal_mapping → REQUIRED (CEO-level strategic alignment)

    name is resolved from the company personnel hierarchy by role match so the UI
    can show the person's identifier alongside their role title.

    level is resolved from personnel data when the raw value is a string enum
    (ApprovalLevel serializes as "vp", "c_level", etc. — not a plain integer).
    """
    # Build role (uppercase) → personnel record lookup
    personnel_by_role: dict[str, dict] = {}
    if company_data:
        for person in company_data.get("approval_hierarchy", {}).get("personnel", []):
            key = person.get("role", "").upper()
            if key:
                personnel_by_role[key] = person

    normalized = []
    for step in raw_chain:
        role = step.get("role", "")
        reason = step.get("rationale")
        source_rule_id = step.get("source_rule_id")

        # Look up the person by role to get their ID and numeric level
        person = personnel_by_role.get(role.upper(), {})

        # name: prefer value already on the step, fall back to person's actual name (e.g. "이수진")
        person_name = step.get("name") or person.get("name")

        # Derive auth_type from rule_action stored on the step
        rule_action = step.get("rule_action", "")
        if rule_action == "require_review":
            auth_type = "ESCALATION"
        else:
            # require_approval and require_goal_mapping are both mandatory approvals
            auth_type = "REQUIRED"

        # Resolve level: ApprovalLevel serializes as string enum ("vp", "c_level").
        # int() will throw ValueError for those — fall back to the numeric level from
        # the personnel record, which is always an integer.
        raw_level = step.get("level")
        try:
            level = int(raw_level)
        except (TypeError, ValueError):
            level = person.get("level", 0)

        normalized.append(NormalizedApprovalStep(
            role=role,
            name=person_name,
            level=level,
            status="pending",
            reason=reason,
            source_rule_id=source_rule_id,
            auth_type=auth_type,
        ))

    return normalized


# ---------------------------------------------------------------------------
# Full Console Payload Builder
# ---------------------------------------------------------------------------

def build_console_payload(record: DecisionRecord) -> ConsolePayloadResponse:
    """
    Build the full ConsolePayloadResponse from a DecisionRecord.

    Applies all normalization rules at the response layer.
    """
    # Map internal status to DecisionStatus enum
    status_map = {
        "pending": DecisionStatus.pending,
        "processing": DecisionStatus.processing,
        "complete": DecisionStatus.complete,
        "failed": DecisionStatus.failed,
    }
    status = status_map.get(record.status, DecisionStatus.pending)

    # Build company summary
    company_data = company_service.get_company_v1(record.company_id)
    company_summary = None
    if company_data:
        company_summary = CompanySummaryResponse(
            id=company_data.id,
            name=company_data.name,
            industry=company_data.industry,
            size=company_data.size,
            governance_framework=company_data.governance_framework,
        )
    else:
        # Fallback for unknown company
        company_summary = CompanySummaryResponse(
            id=record.company_id,
            name=record.company_id,
            industry="Unknown",
            size="Unknown",
            governance_framework="Unknown",
        )

    # Raw company data (personnel hierarchy, rules) — used for owner enrichment
    # and approval chain name resolution throughout this function.
    company_raw_data = company_service.get_company_data(record.company_id)

    # Build personnel role → person lookup once, shared across all enrichment steps
    _personnel_by_role: dict[str, dict] = {}
    if company_raw_data:
        for _p in company_raw_data.get("approval_hierarchy", {}).get("personnel", []):
            _k = _p.get("role", "").upper()
            if _k:
                _personnel_by_role[_k] = _p

    # Build decision summary (available after step 1)
    decision_summary = None
    if record.decision:
        d = record.decision

        # Enrich owners: when the LLM puts a role title in the `name` field
        # (e.g. "연구개발팀장") because no personal name was in the text,
        # swap in the actual person name from the personnel hierarchy.
        raw_owners = d.get("owners", [])
        enriched_owners = []
        for owner in raw_owners:
            if not isinstance(owner, dict):
                enriched_owners.append(owner)
                continue
            owner_name = owner.get("name", "")
            owner_role = owner.get("role")
            # If name matches a known role title and role is not separately set,
            # treat name as the role and look up the actual person name.
            person = _personnel_by_role.get(owner_name.upper())
            if person and not owner_role:
                enriched_owners.append({
                    "name": person.get("name", owner_name),
                    "role": person.get("role", owner_name),
                    "responsibility": owner.get("responsibility"),
                })
            else:
                enriched_owners.append(owner)

        decision_summary = DecisionSummary(
            statement=d.get("decision_statement", ""),
            goals=d.get("goals", []),
            kpis=d.get("kpis", []),
            risks=d.get("risks", []),
            owners=enriched_owners,
            assumptions=d.get("assumptions", []),
            required_approvals=d.get("required_approvals", []),
        )

    # Build derived attributes (available after step 2)
    derived_attrs = None
    if record.derived_attributes:
        da = record.derived_attributes
        derived_attrs = DerivedAttributes(
            risk_level=da.get("risk_level", "medium"),
            confidence=da.get("confidence", 0.0),
            strategic_impact=da.get("strategic_impact", "medium"),
            completeness_score=da.get("completeness_score"),
        )

    # Build governance payload with normalization (available after step 2)
    governance = None
    if record.governance:
        gov = record.governance
        raw_flags = gov.get("flags", [])
        raw_triggered = gov.get("triggered_rules", [])
        raw_chain = gov.get("approval_chain", [])

        # Owner inference: suppress MISSING_OWNER if owner is inferred
        # Improved logic: Only escalate to CEO if no department-level owner is found
        inferred_owner = False
        owner_roles = set()
        if record.decision:
            owners = record.decision.get("owners", [])
            for owner in owners:
                role = owner.get("role", "") if isinstance(owner, dict) else str(owner)
                owner_roles.add(role)
            # If department-level owner exists, prefer them
            department_owner_roles = {"재무팀장", "내부감사실장", "준법감시인", "정보보호최고책임자"}
            if owner_roles & department_owner_roles:
                inferred_owner = True
            elif owners:
                # If only escalation roles (CEO, CFO), do not infer owner
                inferred_owner = False
        elif record.decision_pack:
            owners = record.decision_pack.get("owners", [])
            for owner in owners:
                role = owner.get("role", "") if isinstance(owner, dict) else str(owner)
                owner_roles.add(role)
            department_owner_roles = {"재무팀장", "내부감사실장", "준법감시인", "정보보호최고책임자"}
            if owner_roles & department_owner_roles:
                inferred_owner = True
            elif owners:
                inferred_owner = False
        company_goals = (company_raw_data or {}).get("strategic_goals", [])
        normalized_flags = _normalize_flags(
            raw_flags,
            inferred_owner=inferred_owner,
            triggered_rules=raw_triggered,
            company_goals=company_goals,
        )

        normalized_triggered, normalized_all = _normalize_rules(raw_triggered, record.company_id)
        normalized_chain = _normalize_approval_chain(raw_chain, raw_triggered, company_raw_data)

        # Map governance status
        gov_status = gov.get("governance_status", "review_required")
        if gov_status == "blocked":
            gov_status = "blocked"
        elif gov_status == "compliant":
            gov_status = "compliant"
        else:
            gov_status = "review_required"

        # Risk score calculation
        risk_score = gov.get("computed_risk_score")
        if risk_score is None or risk_score == 0:
            # Infer from triggered rules and flags
            severity = "low"
            for rule in normalized_triggered:
                if getattr(rule, "severity", "low") == "critical":
                    risk_score = 9
                    severity = "critical"
                    break
                elif getattr(rule, "severity", "low") == "high":
                    risk_score = 7
                    severity = "high"
            if risk_score is None or risk_score == 0:
                for flag in normalized_flags:
                    if getattr(flag, "severity", "low") == "critical":
                        risk_score = 8
                        severity = "critical"
                        break
                    elif getattr(flag, "severity", "low") == "high":
                        risk_score = 6
                        severity = "high"
            if risk_score is None or risk_score == 0:
                risk_score = 3 if normalized_flags else 1

        governance = GovernancePayload(
            status=gov_status,
            requires_human_review=gov.get("requires_human_review", True),
            risk_score=risk_score,
            flags=normalized_flags,
            triggered_rules=normalized_triggered,
            all_rules=normalized_all,
            approval_chain=normalized_chain,
        )

    # Build graph payload (available after step 3)
    graph_payload = None
    if record.graph_payload:
        gp = record.graph_payload
        metadata = gp.get("metadata", {}) or {}
        raw_nodes = gp.get("nodes", []) or []
        raw_edges = gp.get("edges", []) or []

        # Convert raw nodes to GraphNode objects
        nodes = []
        for n in raw_nodes:
            nodes.append(GraphNode(
                id=n.get("id", "") or "",
                type=n.get("type", n.get("node_type", "Unknown")) or "Unknown",
                label=n.get("label", n.get("name", n.get("id", ""))) or "",
                properties=n.get("properties") or {},
            ))

        # Convert raw edges to GraphEdge objects
        edges = []
        for e in raw_edges:
            # Edge model uses from_node/to_node (or from/to as aliases)
            source = e.get("from_node") or e.get("from") or e.get("source") or ""
            target = e.get("to_node") or e.get("to") or e.get("target") or ""
            relation = e.get("predicate") or e.get("relation") or e.get("type") or "RELATED_TO"
            edges.append(GraphEdge(
                source=source,
                target=target,
                relation=relation,
                properties=e.get("properties") or {},
            ))

        graph_payload = GraphPayload(
            nodes=nodes,
            edges=edges,
            node_count=len(nodes),
            edge_count=len(edges),
            analysis_method="deterministic_subgraph",
            subgraph_summary=metadata.get("subgraph_summary"),
        )

    # Build reasoning payload (available after step 4)
    # Prefer O1 Reasoner output if present
    reasoning = None
    if record.reasoning:
        r = record.reasoning
        o1 = r.get("o1_reasoner")
        if o1:
            # O1 Reasoner output present
            contradictions = [
                c.get("description", str(c)) if isinstance(c, dict) else str(c)
                for c in o1.get("contradictions_found", [])
            ]
            recommendations = [
                rec.get("action", str(rec)) if isinstance(rec, dict) else str(rec)
                for rec in o1.get("graph_based_recommendations", [])
            ]
            for issue in o1.get("ownership_validation", []):
                if isinstance(issue, dict):
                    desc = issue.get("description", "")
                    if desc:
                        recommendations.append(desc)
            reasoning = ReasoningPayload(
                analysis_method="o1_reasoner",
                logical_contradictions=contradictions,
                graph_recommendations=recommendations,
                confidence=o1.get("confidence", 0.0),
                raw_analysis=o1,
            )
        else:
            # Fallback to graph_reasoning
            gr = r.get("graph_reasoning") or {}
            graph_analysis = gr.get("graph_analysis") or {}
            contradictions = [
                c.get("description", str(c)) if isinstance(c, dict) else str(c)
                for c in gr.get("contradictions_found", [])
            ]
            recommendations = [
                rec.get("action", str(rec)) if isinstance(rec, dict) else str(rec)
                for rec in gr.get("graph_based_recommendations", [])
            ]
            for issue in gr.get("ownership_validation", []):
                if isinstance(issue, dict):
                    desc = issue.get("description", "")
                    if desc:
                        recommendations.append(desc)

            # For deterministic reasoning, graph_analysis has no confidence value.
            # Use the decision's extraction confidence instead: it reflects how
            # completely the LLM understood the input, which determines how
            # reliably the deterministic rules can be applied.
            extraction_confidence = (
                record.decision.get("confidence", 1.0)
                if record.decision else 1.0
            )
            reasoning_confidence = graph_analysis.get("confidence") or extraction_confidence

            reasoning = ReasoningPayload(
                analysis_method=r.get("source", "deterministic"),
                logical_contradictions=contradictions,
                graph_recommendations=recommendations,
                confidence=reasoning_confidence,
                raw_analysis=None,
            )

    # Build decision pack payload (available after step 5)
    decision_pack = None
    if record.decision_pack:
        dp = record.decision_pack
        decision_pack = DecisionPackPayload(
            title=dp.get("title", ""),
            summary=dp.get("summary", {}),
            goals_kpis=dp.get("goals_kpis", {}),
            risks=dp.get("risks", []),
            approval_chain=dp.get("approval_chain", []),
            recommended_next_actions=dp.get("recommended_next_actions", []),
            audit=dp.get("audit", {}),
            graph_reasoning=dp.get("graph_reasoning"),
        )

    # Build extraction metadata (available after step 1)
    extraction_metadata = None
    if record.extraction_metadata:
        em = record.extraction_metadata
        extraction_metadata = ExtractionMetadata(
            completeness_score=em.get("completeness_score"),
            completeness_issues=em.get("completeness_issues", []),
            extraction_method=em.get("extraction_method", "llm"),
            company_id=record.company_id,
            processed_at=record.updated_at,
        )

    return ConsolePayloadResponse(
        decision_id=record.decision_id,
        status=status,
        company=company_summary,
        decision=decision_summary,
        derived_attributes=derived_attrs,
        governance=governance,
        graph_payload=graph_payload,
        reasoning=reasoning,
        decision_pack=decision_pack,
        extraction_metadata=extraction_metadata,
    )
