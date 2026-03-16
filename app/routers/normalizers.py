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
    DecisionContextPayload,
    DecisionContextEntity,
    DecisionSourcePayload,  # noqa: F401 (used in _build_decision_context_from_record)
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
    RiskScoringPayload,
    RiskAggregateResponse,
    RiskDimensionResponse,
    RiskSignalResponse,
    RiskEvidenceResponse,
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

# Severity mapping: flag pattern → severity (insertion order = priority)
_FLAG_SEVERITY_MAP: dict[str, FlagSeverity] = {
    "CRITICAL": FlagSeverity.critical,
    "HIGH":     FlagSeverity.high,
    "MEDIUM":   FlagSeverity.medium,
}

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
        for key, sev in _FLAG_SEVERITY_MAP.items():
            if key in flag_upper:
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
    effective_lang: str = "ko",
) -> tuple[list[NormalizedRule], list[NormalizedRule]]:
    """
    Transform triggered rules and derive all_rules from company context.

    Returns (triggered_rules with TRIGGERED status, all_rules with TRIGGERED/PASSED status)
    """
    # Get all rules from company in the effective language
    all_company_rules = company_service.get_governance_rules(company_id, lang=effective_lang)
    triggered_ids = {r.get("rule_id") for r in triggered_rules}

    # Build a lookup so triggered rules can use lang-appropriate name/description
    # (stored triggered_rules may have been evaluated with a different lang)
    company_rule_by_id = {r.get("rule_id"): r for r in all_company_rules}

    def truncate_description(desc: str, max_len: int = 80) -> str:
        """Truncate description for dashboard display."""
        if len(desc) <= max_len:
            return desc
        return desc[:max_len - 3].rsplit(' ', 1)[0] + "..."

    # Build triggered list with TRIGGERED status
    normalized_triggered = []
    for rule in triggered_rules:
        rule_id = rule.get("rule_id", "")

        # Prefer lang-appropriate text from company file; fall back to stored value
        canonical = company_rule_by_id.get(rule_id, rule)
        name = canonical.get("name") or rule.get("name", "")
        desc = canonical.get("description") or rule.get("description", "")
        rule_type = canonical.get("type") or rule.get("type") or rule.get("rule_type", "governance")
        consequence = canonical.get("consequence") or rule.get("consequence", {})
        severity = (
            rule.get("severity")
            or (consequence.get("severity") if isinstance(consequence, dict) else None)
            or "medium"
        )

        # Attach internal policy evidence from registry (non-fatal)
        policy_evidence = None
        try:
            from app.services import evidence_registry_service as ers
            ev = ers.get_policy_evidence(company_id, rule_id)
            if ev:
                policy_evidence = [ev]
        except Exception:
            pass

        normalized_triggered.append(NormalizedRule(
            rule_id=rule_id,
            name=name,
            type=rule_type,
            description=desc,
            short_description=truncate_description(desc),
            status=RuleStatus.TRIGGERED,
            severity=severity,
            consequence=consequence,
            evidence=policy_evidence,
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
    company_id: str = None,
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

    # Build rule_id → lang-appropriate approver_role lookup
    # so stored KO role names ("인사팀장") are re-read in the correct lang at response time.
    rules_by_id: dict[str, dict] = {}
    if company_data:
        for rule in company_data.get("governance_rules", []):
            rid = rule.get("rule_id")
            if rid:
                rules_by_id[rid] = rule

    normalized = []
    for step in raw_chain:
        source_rule_id = step.get("source_rule_id")

        # Re-read role from lang-appropriate rule when source_rule_id is available.
        # NOTE: Only use approver_role (singular) as override — rules with approver_roles
        # (plural) store the correct per-step role on the ApprovalChainStep already.
        stored_role = step.get("role", "")
        if source_rule_id and source_rule_id in rules_by_id:
            rule_consequence = rules_by_id[source_rule_id].get("consequence", {})
            # approver_roles (plural) means per-step role is authoritative; don't override
            if not rule_consequence.get("approver_roles"):
                role = rule_consequence.get("approver_role") or stored_role
            else:
                role = stored_role
        else:
            role = stored_role

        reason = step.get("rationale")

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

        # Attach org-chart authority evidence from registry (non-fatal)
        authority_evidence = None
        if company_id:
            try:
                from app.services import evidence_registry_service as ers
                authority_evidence = ers.get_approval_evidence(company_id, role)
            except Exception:
                pass

        normalized.append(NormalizedApprovalStep(
            role=role,
            name=person_name,
            level=level,
            status="pending",
            reason=reason,
            source_rule_id=source_rule_id,
            auth_type=auth_type,
            evidence=authority_evidence,
        ))

    # Assign sequential_order for steps that belong to a sequential rule.
    # Group by source_rule_id; for groups whose rule has requires_sequential=true
    # and more than one step, stamp 1-based position so the frontend can enforce order.
    from collections import defaultdict
    _rule_step_indices: dict[str, list[int]] = defaultdict(list)
    for idx, step in enumerate(normalized):
        if step.source_rule_id:
            _rule_step_indices[step.source_rule_id].append(idx)

    for rule_id, indices in _rule_step_indices.items():
        rule = rules_by_id.get(rule_id, {})
        if rule.get("consequence", {}).get("requires_sequential") and len(indices) > 1:
            for order, idx in enumerate(indices, start=1):
                normalized[idx] = normalized[idx].model_copy(update={"sequential_order": order})

    return normalized


# ---------------------------------------------------------------------------
# Decision Context — passthrough from LLM-extracted record.decision_context
# ---------------------------------------------------------------------------


def _build_decision_context_from_record(
    decision_context_dict: dict,
) -> DecisionContextPayload:
    """
    Convert the serialised decision_context dict (stored by pipeline step 1b)
    into a validated DecisionContextPayload for the response.

    The dict was produced and filtered by decision_context_service and already
    contains only left-panel-safe entities.
    """
    raw_source = decision_context_dict.get("source") or {}
    entities = [
        DecisionContextEntity(
            key=e.get("key", ""),
            label=e.get("label", ""),
            value=e.get("value", ""),
            category=e.get("category"),
            kind=e.get("kind"),
            confidence=e.get("confidence"),
        )
        for e in decision_context_dict.get("entities", [])
    ]
    return DecisionContextPayload(
        proposal=decision_context_dict.get("proposal", ""),
        proposal_en=decision_context_dict.get("proposal_en"),
        source=DecisionSourcePayload(
            type=raw_source.get("type", "AI_AGENT"),
            label=raw_source.get("label", "AI Agent"),
        ),
        entities=entities,
    )


# ---------------------------------------------------------------------------
# Full Console Payload Builder
# ---------------------------------------------------------------------------

def build_console_payload(record: DecisionRecord, lang: Optional[str] = None) -> ConsolePayloadResponse:
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

    # Resolve effective lang: query param override → record lang → default "ko"
    effective_lang = lang or getattr(record, "lang", "ko") or "ko"

    # Build company summary
    company_data = company_service.get_company_v1(record.company_id, lang=effective_lang)
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
    company_raw_data = company_service.get_company_data(record.company_id, lang=effective_lang)

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

        normalized_triggered, normalized_all = _normalize_rules(raw_triggered, record.company_id, effective_lang)
        normalized_chain = _normalize_approval_chain(raw_chain, raw_triggered, company_raw_data, company_id=record.company_id)

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

        # EN lookups for label_en resolution (always use EN company data)
        _en_rules_by_id: dict[str, dict] = {}
        _en_goals_by_id: dict[str, dict] = {}
        _en_company_data = company_service.get_company_data(record.company_id, lang="en")
        if _en_company_data:
            for _r in _en_company_data.get("governance_rules", []):
                _rid = _r.get("rule_id")
                if _rid:
                    _en_rules_by_id[_rid] = _r
            for _g in _en_company_data.get("strategic_goals", []):
                _gid = _g.get("goal_id")
                if _gid:
                    _en_goals_by_id[_gid] = _g

        _SEVERITY_EN = {"low": "Low Risk", "medium": "Medium Risk", "high": "High Risk", "critical": "Critical Risk"}

        # Convert raw nodes to GraphNode objects
        nodes = []
        for n in raw_nodes:
            props = n.get("properties") or {}
            node_type = n.get("type", n.get("node_type", "Unknown")) or "Unknown"
            label = n.get("label", n.get("name", n.get("id", ""))) or ""
            label_en = None

            _nt = node_type.upper()
            if _nt == "ACTOR":
                # owner actors: name_en/role_en in properties
                # approver actors: look up consequence.approver_role from EN company rules
                label_en = props.get("name_en") or props.get("role_en") or None
                if not label_en:
                    source_rule_id = props.get("source_rule_id")
                    if source_rule_id and source_rule_id in _en_rules_by_id:
                        label_en = (_en_rules_by_id[source_rule_id]
                                    .get("consequence", {})
                                    .get("approver_role")) or None

            elif _nt == "RULE":
                # Extract rule_id from node_id (e.g. "rule_R1" → "R1")
                node_id_str = n.get("id", "")
                _rule_id = node_id_str[5:] if node_id_str.startswith("rule_") else node_id_str
                if _rule_id in _en_rules_by_id:
                    label_en = _en_rules_by_id[_rule_id].get("name") or None

            elif _nt == "GOAL_STRATEGIC":
                # Extract goal_id from node_id (e.g. "goal_G1" → "G1")
                node_id_str = n.get("id", "")
                _goal_id = node_id_str[5:] if node_id_str.startswith("goal_") else node_id_str
                if _goal_id in _en_goals_by_id:
                    label_en = _en_goals_by_id[_goal_id].get("name") or None

            elif _nt == "RISK":
                # 1. Explicitly stored English description (only if ASCII)
                _desc_en = props.get("description_en") or ""
                label_en = _desc_en if _desc_en and _desc_en.isascii() else None
                if not label_en:
                    # 2. Pipeline-translated label (from batch Nova call)
                    label_en = props.get("label_en") or None
                if not label_en:
                    # 3. Strategic conflict risks: build from EN goal name
                    _goal_id = props.get("goal_id")
                    if _goal_id and _goal_id in _en_goals_by_id:
                        _en_goal_name = _en_goals_by_id[_goal_id].get("name", "")
                        label_en = f"Strategic Conflict: {_en_goal_name}" if _en_goal_name else "Strategic Conflict Risk"
                if not label_en:
                    # 4. Last resort: severity band
                    _sev = (props.get("severity") or "").lower()
                    label_en = _SEVERITY_EN.get(_sev, "Risk")

            elif _nt == "KPI":
                # Use KPI name only if it's already English (ASCII); otherwise let
                # the universal fallback below pick up the pipeline-translated label_en
                _kpi_name = props.get("name") or props.get("target") or ""
                label_en = _kpi_name if _kpi_name and _kpi_name.isascii() else None

            elif _nt == "REGION":
                # Use stored English name if available; fall back to label if it's ASCII
                label_en = props.get("name_en") or (label if label.isascii() else None)

            elif _nt == "COST":
                # label is already ASCII (e.g. "250000000 KRW")
                label_en = label if label.isascii() else None

            elif _nt in ("DATA_TYPE", "DATATYPE"):
                # label is already ASCII (e.g. "PII")
                label_en = label if label.isascii() else None

            elif _nt == "DECISION":
                # Root decision node — English label injected by pipeline label enrichment step.
                label_en = props.get("label_en") or (label if label.isascii() else None)

            # Universal fallback: label_en stored by the pipeline enrichment step
            if label_en is None:
                label_en = props.get("label_en") or (label if label.isascii() else None)

            nodes.append(GraphNode(
                id=n.get("id", "") or "",
                type=node_type,
                label=label,
                label_en=label_en,
                properties=props,
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
    # Nova pipeline stores: {"source": "nova", "graph_reasoning": <formatted>, "nova_available": True}
    reasoning = None
    if record.reasoning:
        r = record.reasoning
        gr = r.get("graph_reasoning") or {}
        is_nova = r.get("source") == "nova" and gr
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

        if is_nova:
            reasoning = ReasoningPayload(
                analysis_method="nova_reasoner",
                logical_contradictions=contradictions,
                graph_recommendations=recommendations,
                confidence=graph_analysis.get("confidence", 0.0),
                raw_analysis=gr,
            )
        else:
            # Deterministic fallback — use extraction confidence as proxy
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

    # Build risk scoring (available when complete)
    risk_scoring = None
    if record.risk_scoring:
        rs = record.risk_scoring
        raw_agg = rs.get("aggregate", {})
        risk_scoring = RiskScoringPayload(
            aggregate=RiskAggregateResponse(
                score=raw_agg.get("score", 0),
                band=raw_agg.get("band", "LOW"),
                confidence=raw_agg.get("confidence", 0.5),
            ),
            dimensions=[
                RiskDimensionResponse(
                    id=d.get("id", ""),
                    label=d.get("label", ""),
                    label_en=d.get("label_en"),
                    score=d.get("score", 0),
                    band=d.get("band", "LOW"),
                    signals=[
                        RiskSignalResponse(
                            id=s.get("id", ""),
                            label=s.get("label", ""),
                            value=s.get("value", 0.0),
                            unit=s.get("unit"),
                            severity=s.get("severity"),
                            evidence=[
                                RiskEvidenceResponse(
                                    type=e.get("type", "evidence"),
                                    ref=e.get("ref", {}),
                                    label=e.get("label"),
                                    source=e.get("source"),
                                    confidence=e.get("confidence"),
                                    note=e.get("note"),
                                )
                                for e in s.get("evidence", [])
                            ],
                        )
                        for s in d.get("signals", [])
                    ],
                    evidence=[
                        RiskEvidenceResponse(
                            type=e.get("type", "note"),
                            ref=e.get("ref", {}),
                            label=e.get("label"),
                            source=e.get("source"),
                            confidence=e.get("confidence"),
                            note=e.get("note"),
                        )
                        for e in d.get("evidence", [])
                    ],
                    kpi_impact_estimate=d.get("kpi_impact_estimate"),
                )
                for d in rs.get("dimensions", [])
            ],
        )

    # Assemble top-level governance evidence from registry (non-fatal, additive)
    governance_evidence = None
    if record.governance:
        try:
            from app.services import evidence_registry_service as ers

            triggered_rule_ids = list(dict.fromkeys(
                r.get("rule_id") for r in raw_triggered if r.get("rule_id")
            ))
            # Merge rule_ids used by risk scoring (e.g. R6 inferred via semantics
            # but not in governance triggered_rules) so complianceEvidence is populated
            if record.risk_scoring:
                for dim in record.risk_scoring.get("dimensions", []):
                    for rid in dim.get("source_rule_ids", []):
                        if rid and rid not in triggered_rule_ids:
                            triggered_rule_ids.append(rid)
            # Goal IDs: only goals that appear as GOAL_STRATEGIC nodes in the graph.
            # add_strategic_goals() only creates these nodes when there is an actual
            # SUPPORTS or CONFLICTS_WITH relationship to this decision — so pulling
            # evidence for them is always relevant. Unrelated goals (e.g. G2 Product
            # Innovation for a hiring decision) are not in the graph and are skipped.
            # Node IDs are "goal_G1", "goal_G2" etc. — strip the "goal_" prefix.
            graph_goal_ids = []
            if record.graph_payload:
                for _node in record.graph_payload.get("nodes", []):
                    _ntype = (_node.get("type") or "").upper()
                    _nid = _node.get("id", "")
                    if _ntype == "GOAL_STRATEGIC" and _nid.startswith("goal_"):
                        _gid = _nid[len("goal_"):]
                        if _gid:
                            graph_goal_ids.append(_gid)
            company_goal_ids = graph_goal_ids
            governance_evidence = ers.assemble_governance_evidence(
                company_id=record.company_id,
                triggered_rule_ids=triggered_rule_ids,
                goal_ids=company_goal_ids,
                approval_chain=[{"approver_role": s.role} for s in normalized_chain],
                decision_payload={**(record.decision or {}), "agent_name": record.agent_name, "agent_name_en": record.agent_name_en},
            )
        except Exception:
            pass

    # Assemble risk response simulation payload (additive, non-fatal)
    simulation_payload = None
    if record.simulation:
        try:
            from app.schemas.responses import (
                RiskResponseSimulationPayload,
                SimulationOutcomeResponse,
                SimulationScenarioResponse,
                SimulationDeltaResponse,
            )
            sim = record.simulation
            baseline = SimulationOutcomeResponse(**sim["baseline"])
            scenarios = [
                SimulationScenarioResponse(
                    scenarioId=s["scenarioId"],
                    templateId=s["templateId"],
                    titleKo=s["titleKo"],
                    titleEn=s.get("titleEn"),
                    changeSummaryKo=s["changeSummaryKo"],
                    changeSummaryEn=s.get("changeSummaryEn"),
                    issueTypes=s.get("issueTypes", []),
                    expectedOutcome=SimulationOutcomeResponse(**s["expectedOutcome"]),
                    delta=SimulationDeltaResponse(**s.get("delta", {})),
                    resolvedIssues=s.get("resolvedIssues", []),
                    resolvedIssuesEn=s.get("resolvedIssuesEn", []),
                    remainingIssues=s.get("remainingIssues", []),
                    remainingIssuesEn=s.get("remainingIssuesEn", []),
                    confidence=s.get("confidence"),
                    isRecommended=s.get("isRecommended", False),
                    rationaleKo=s.get("rationaleKo"),
                    rationaleEn=s.get("rationaleEn"),
                )
                for s in sim.get("scenarios", [])
            ]
            simulation_payload = RiskResponseSimulationPayload(
                baseline=baseline,
                scenarios=scenarios,
                generatedAt=sim.get("generatedAt"),
            )
        except Exception:
            pass

    # Assemble external signals (additive, non-fatal)
    # Separate from governance_evidence — external sources only, never internal.
    external_signals_payload = None
    if getattr(record, "external_signals", None):
        try:
            from app.schemas.external_signals import ExternalSignalsPayload as _ExtPayload
            external_signals_payload = _ExtPayload(**record.external_signals)
        except Exception:
            pass

    # Build decision context (left-panel entities) from LLM-extracted store field
    decision_context = None
    if getattr(record, "decision_context", None):
        try:
            decision_context = _build_decision_context_from_record(record.decision_context)
        except Exception:
            pass

    return ConsolePayloadResponse(
        decision_id=record.decision_id,
        status=status,
        agent_name=getattr(record, "agent_name", "AI Agent") or "AI Agent",
        agent_name_en=getattr(record, "agent_name_en", "AI Agent") or "AI Agent",
        company=company_summary,
        decision=decision_summary,
        decision_context=decision_context,
        derived_attributes=derived_attrs,
        governance=governance,
        graph_payload=graph_payload,
        reasoning=reasoning,
        decision_pack=decision_pack,
        extraction_metadata=extraction_metadata,
        risk_scoring=risk_scoring,
        governance_evidence=governance_evidence,
        risk_response_simulation=simulation_payload,
        external_signals=external_signals_payload,
    )
