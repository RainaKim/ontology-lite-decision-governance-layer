"""
Decision Pack Generator - Template-based, Deterministic

Generates execution-ready Decision Packs from evaluated decisions.
Pure Python logic, no LLM, no freeform text.
Optional: Graph reasoning for enhanced insights.
"""

from typing import Optional
import asyncio


def build_decision_pack(
    decision: dict,
    governance: dict,
    company: dict = None,
    graph_insights: dict = None
) -> dict:
    """
    Build a Decision Pack from decision and governance evaluation results.

    Args:
        decision: Decision object as dict (from schemas.Decision)
        governance: Governance evaluation result as dict (from GovernanceResult.to_dict())
        company: Optional company context

    Returns:
        Decision Pack as structured dict with fixed sections
    """
    if company is None:
        company = {}

    # Extract core fields
    decision_statement = decision.get("decision_statement", "")
    goals = decision.get("goals", [])
    kpis = decision.get("kpis", [])
    risks = decision.get("risks", [])
    owners = list(decision.get("owners", []))  # Copy to allow mutation
    assumptions = decision.get("assumptions", [])
    confidence = decision.get("confidence", 0.0)
    strategic_impact = decision.get("strategic_impact")

    # Apply high-confidence inferred owners from graph reasoning
    if graph_insights and graph_insights.get("inferred_owners"):
        for inferred in graph_insights["inferred_owners"]:
            # Only apply high-confidence inferences
            if inferred.get("confidence") == "high":
                owners.append({
                    "name": inferred.get("name"),
                    "role": inferred.get("role"),
                    "responsibility": None
                })

    # Extract governance fields
    flags = list(governance.get("flags", []))  # Copy to avoid mutating original
    requires_human_review = governance.get("requires_human_review", True)
    approval_chain = governance.get("approval_chain", [])
    triggered_rules = governance.get("triggered_rules", [])
    computed_risk_score = governance.get("computed_risk_score", 0.0)

    # Add STRATEGIC_MISALIGNMENT flag if graph insights detected conflicts
    if graph_insights and graph_insights.get("strategic_goal_conflicts"):
        if "STRATEGIC_MISALIGNMENT" not in flags:
            flags.append("STRATEGIC_MISALIGNMENT")

    # Detect missing items
    missing_items = _detect_missing_items(decision, governance, flags)

    # Determine risk level and governance status
    risk_level, governance_status = _determine_risk_and_status(
        flags, requires_human_review, computed_risk_score
    )

    # Generate recommended next actions
    # When o1 graph reasoning ran successfully, use its company-context-aware guidance.
    # It has access to the actual governance rules, thresholds, and personnel hierarchy,
    # so it can generate accurate guidance for any company — not just hardcoded thresholds.
    # Fall back to deterministic generation when o1 was not used or failed.
    o1_next_actions = (graph_insights or {}).get("next_actions", []) if graph_insights else []
    o1_was_used = (graph_insights or {}).get("analysis_method") == "o1-reasoning"

    if o1_was_used and o1_next_actions:
        recommended_next_actions = o1_next_actions
    else:
        recommended_next_actions = _generate_next_actions(
            missing_items, approval_chain, flags, governance_status, triggered_rules, decision
        )

    # Extract rationales from triggered rules and approval chain
    rationales = _extract_rationales(triggered_rules, approval_chain)

    # Map strategic goals with conflict/alignment indicators
    strategic_goals_mapped = _map_strategic_goals(company, graph_insights)

    # Build title
    title = _generate_title(decision_statement, strategic_impact)

    # Assemble Decision Pack
    decision_pack = {
        "title": title,
        "summary": {
            "decision_statement": decision_statement,
            "human_approval_required": requires_human_review,
            "risk_level": risk_level,
            "governance_status": governance_status,
            "confidence_score": confidence,
            "strategic_impact": strategic_impact or "not_specified",
            "graph_analysis_enabled": graph_insights is not None
        },
        "goals_kpis": {
            "strategic_goals": strategic_goals_mapped,
            "decision_objectives": [
                {
                    "description": g.get("description", ""),
                    "metric": g.get("metric")
                }
                for g in goals
            ],
            "kpis": [
                {
                    "name": k.get("name", ""),
                    "target": k.get("target"),
                    "measurement_frequency": k.get("measurement_frequency")
                }
                for k in kpis
            ]
        },
        "risks": [
            {
                "description": r.get("description", ""),
                "severity": r.get("severity", "medium"),
                "mitigation": r.get("mitigation")
            }
            for r in risks
        ],
        "owners": [
            {
                "name": o.get("name", ""),
                "role": o.get("role"),
                "responsibility": o.get("responsibility")
            }
            for o in owners
        ],
        "assumptions": [
            {
                "description": a.get("description", ""),
                "criticality": a.get("criticality")
            }
            for a in assumptions
        ],
        "missing_items": missing_items,
        "approval_chain": [
            {
                "level": step.get("level", ""),
                "role": step.get("role", ""),
                "required": step.get("required", True),
                "rationale": step.get("rationale")
            }
            for step in approval_chain
        ],
        "recommended_next_actions": recommended_next_actions,
        "audit": {
            "flags": flags,
            "triggered_rules": [
                {
                    "rule_id": r.get("rule_id", ""),
                    "name": r.get("name", ""),
                    "description": r.get("description", "")
                }
                for r in triggered_rules
            ],
            "rationales": rationales,
            "computed_risk_score": computed_risk_score
        }
    }

    # Add graph insights if available
    if graph_insights:
        decision_pack["graph_reasoning"] = {
            "analysis_method": graph_insights.get("analysis_method", "not_performed"),
            "graph_context": graph_insights.get("graph_context", {}),
            "logical_contradictions": graph_insights.get("contradictions_found", []),
            "ownership_issues": graph_insights.get("ownership_validation", []),
            "risk_gaps": graph_insights.get("risk_coverage_gaps", []),
            "policy_conflicts": graph_insights.get("policy_conflicts", []),
            "graph_recommendations": graph_insights.get("graph_based_recommendations", []),
            "confidence": graph_insights.get("graph_analysis", {}).get("confidence", 0.0)
        }

    # Add conclusion_reason — one-sentence human-readable "why"
    decision_pack["summary"]["conclusion_reason"] = _summarize_conclusion(
        governance_status, risk_level, flags, triggered_rules,
        approval_chain, missing_items, graph_insights
    )

    return decision_pack


def _summarize_conclusion(
    governance_status: str,
    risk_level: str,
    flags: list[str],
    triggered_rules: list[dict],
    approval_chain: list[dict],
    missing_items: list[str],
    graph_insights: dict = None,
) -> str:
    """
    Generate a human-readable reason for the governance conclusion.

    Cross-references triggered rules with approval chain to express
    *conditional* resolution paths, not just binary outcomes.

    Examples:
      - "Blocked by Budget Approval Rule — resolvable with CFO approval."
      - "Blocked — missing owner and risk assessment. No resolution path until addressed."
      - "Requires human review — risk level is high with 1 rule(s) triggered."
    """
    if governance_status == "blocked":
        # What caused the block?
        block_causes = []
        rule_names = [r.get("name", r.get("rule_id", "unknown rule")) for r in triggered_rules]
        if rule_names:
            block_causes.append(", ".join(rule_names))

        structural_gaps = [m for m in missing_items if m.startswith("Missing")]
        if structural_gaps:
            block_causes.append("; ".join(structural_gaps).lower())

        if graph_insights:
            contradictions = graph_insights.get("contradictions_found", [])
            if contradictions:
                block_causes.append(f"{len(contradictions)} logical contradiction(s)")

        cause_str = "; ".join(block_causes) if block_causes else "governance issues"

        # Is there a resolution path via approvals?
        required_approvers = [
            step.get("role", "unknown")
            for step in approval_chain
            if step.get("required", True)
        ]

        if required_approvers and not structural_gaps:
            # Blocked by rules, but resolvable with approvals
            approver_str = " and ".join(required_approvers)
            return f"Blocked by {cause_str} — resolvable with {approver_str} approval."

        if required_approvers and structural_gaps:
            # Blocked AND has structural issues — approvals alone won't fix it
            approver_str = " and ".join(required_approvers)
            return (
                f"Blocked by {cause_str}. "
                f"Resolve structural gaps first, then obtain {approver_str} approval."
            )

        # No approval chain at all — no known resolution path
        return f"Blocked by {cause_str}. No resolution path available — review decision structure."

    if governance_status == "needs_review":
        required_approvers = [
            step.get("role", "unknown")
            for step in approval_chain
            if step.get("required", True)
        ]
        if required_approvers:
            approver_str = ", ".join(required_approvers)
            return (
                f"Requires human review — risk level is {risk_level} "
                f"with {len(triggered_rules)} rule(s) triggered. "
                f"Proceed after {approver_str} approval."
            )
        return (
            f"Requires human review — risk level is {risk_level} "
            f"with {len(triggered_rules)} rule(s) triggered."
        )

    return "Decision is compliant with governance rules. No blocking issues found."


def _map_strategic_goals(company: dict, graph_insights: dict = None) -> list[dict]:
    """
    Map decision to company strategic goals with alignment/conflict indicators.

    Uses o1 graph reasoning results to determine which strategic goals are relevant
    and whether the decision aligns or conflicts with them.

    Args:
        company: Company data with strategic_goals
        graph_insights: O1 graph reasoning results with strategic_goal_conflicts

    Returns:
        List of strategic goals with alignment status:
        [
            {
                "goal_id": "G3",
                "name": "운영비용 효율화",
                "status": "conflict" | "aligned" | "neutral",
                "reasoning": "사용량 대비 30% 과다 지출이 10% 비용 절감 목표와 상충",
                "kpis": [...],
                "priority": "high"
            }
        ]
    """
    if not company:
        return []

    strategic_goals = company.get("strategic_goals", [])
    if not strategic_goals:
        return []

    # Build goal map
    goal_map = {g["goal_id"]: g for g in strategic_goals}

    # Extract conflicts from o1 insights
    conflicts_by_goal = {}
    if graph_insights and graph_insights.get("strategic_goal_conflicts"):
        for conflict in graph_insights["strategic_goal_conflicts"]:
            goal_id = conflict.get("goal_id")
            if goal_id:
                conflicts_by_goal[goal_id] = conflict

    # Map each strategic goal
    mapped_goals = []
    for goal_id, goal in goal_map.items():
        conflict = conflicts_by_goal.get(goal_id)

        if conflict:
            # Goal has conflict
            mapped_goals.append({
                "goal_id": goal_id,
                "name": goal.get("name"),
                "status": "conflict",
                "reasoning": conflict.get("description", "전략 목표와 상충"),
                "conflict_type": conflict.get("conflict_type"),
                "kpis": goal.get("kpis", []),
                "priority": goal.get("priority"),
                "severity": conflict.get("severity", "high")
            })
        # If no explicit conflict, only show goals that are likely relevant
        # (otherwise we'd show all 3 goals for every decision)
        # For now, we'll rely on o1 to only include relevant goals in the subgraph
        # Future: Add heuristic alignment detection for non-o1 path

    return mapped_goals


def _detect_missing_items(decision: dict, governance: dict, flags: list[str]) -> list[str]:
    """
    Detect missing required items in the decision.

    KPI and goals are only expected for high/critical strategic-impact decisions.
    Operational and approval-request decisions (low/medium/null strategic_impact)
    do not require measurable success criteria — flagging them adds noise.

    Owner uses the governance MISSING_OWNER flag, which already accounts for
    infer_owner_from_approval_chain so we don't double-flag inferred owners.

    Returns list of missing item descriptions.
    """
    missing = []

    # Missing owner — use governance flag (already accounts for inferred owners)
    if "MISSING_OWNER" in flags:
        missing.append("Missing owner")

    # KPI and goals — only meaningful for high/critical strategic-impact decisions.
    # Operational approval requests (low/null strategic_impact) don't need these.
    strategic_impact = decision.get("strategic_impact")
    requires_measurables = strategic_impact in ("high", "critical")
    if requires_measurables:
        if not decision.get("kpis"):
            missing.append("Missing KPI")
        if not decision.get("goals"):
            missing.append("Missing goals")

    # Risks are always expected when the decision has substantive content
    if not decision.get("risks"):
        missing.append("Missing risk")

    # Check for missing approvals flag
    if "MISSING_APPROVAL" in flags:
        missing.append("Missing required approvals")

    # Check for any other MISSING_* flags
    for flag in flags:
        if flag.startswith("MISSING_") and flag not in ("MISSING_APPROVAL", "MISSING_OWNER"):
            field_name = flag.replace("MISSING_", "").replace("_", " ").lower()
            item_text = f"Missing {field_name}"
            if item_text not in missing:
                missing.append(item_text)

    return missing


def _determine_risk_and_status(
    flags: list[str],
    requires_human_review: bool,
    computed_risk_score: float
) -> tuple[str, str]:
    """
    Determine risk level and governance status.

    Returns (risk_level, governance_status).
    """
    # Check for critical flags
    has_critical_flag = any("CRITICAL" in flag for flag in flags)

    if has_critical_flag:
        return "high", "blocked"

    # Check for high risk score
    if computed_risk_score >= 7.0:
        return "high", "needs_review"

    # Check for medium risk
    if requires_human_review or len(flags) > 0 or computed_risk_score >= 4.0:
        return "medium", "needs_review"

    # Low risk, compliant
    return "low", "compliant"


def _generate_next_actions(
    missing_items: list[str],
    approval_chain: list[dict],
    flags: list[str],
    governance_status: str,
    triggered_rules: list[dict],
    decision: dict = None
) -> list[str]:
    """
    Generate context-aware recommended next actions.

    Derives guidance from actual governance data:
    - Approval chain rationale + rule types → per-approver "approvable path"
    - Flags → structural issue guidance with resolution alternatives
    - Decision content → context when no rules match (GOVERNANCE_COVERAGE_GAP)

    No hardcoded rule-ID lookups. All guidance is derived from data.
    """
    actions = []
    seen = set()
    decision = decision or {}

    def add(action: str):
        if action not in seen:
            seen.add(action)
            actions.append(action)

    # Build rule_id → rule metadata map for type/name lookup
    rule_map = {r.get("rule_id", ""): r for r in triggered_rules}

    # 1. Per-approval-chain step: derive "approvable path" guidance
    for step in approval_chain:
        role = step.get("role", "")
        rationale = step.get("rationale", "")
        rule_id = step.get("source_rule_id", "")
        rule_action = step.get("rule_action", "require_approval")

        rule = rule_map.get(rule_id, {})
        rule_type = rule.get("type", "")

        if rule_action == "require_review":
            add(_build_review_guidance(role, rule_type, rationale, decision))
        else:
            add(_build_approval_guidance(role, rule_type, rationale, decision))

    # 2. Missing item actions — with "OR" alternatives where applicable
    if "Missing owner" in missing_items:
        add("의사결정 실행 책임자를 지정하세요 — 담당 팀장 또는 프로젝트 리더를 명시하거나, 의사결정문에 실행 주체를 추가하세요")

    if "Missing KPI" in missing_items:
        add("측정 가능한 KPI를 정의하세요 — 목표 수치, 달성 시점, 측정 주기를 포함하거나, 기존 전략 목표(G1/G2/G3)의 KPI와 연계하세요")

    if "Missing risk" in missing_items:
        add("리스크 평가를 추가하세요 — 주요 실패 요인과 완화 방안을 1개 이상 명시하거나, 리스크가 없다고 판단되면 그 근거를 기술하세요")

    if "Missing goals" in missing_items:
        add("조직 목표를 연결하세요 — 글로벌 매출 확대(G1), 규제 준수(G2), 운영비 효율화(G3) 중 하나 이상과 연결하세요")

    # 3. GOVERNANCE_COVERAGE_GAP — use decision content for context-aware guidance
    if "GOVERNANCE_COVERAGE_GAP" in flags:
        risks = decision.get("risks", [])
        decision_stmt = decision.get("decision_statement", "")
        if risks:
            first_risk_desc = risks[0].get("description", "")
            snippet = first_risk_desc[:60] + "..." if len(first_risk_desc) > 60 else first_risk_desc
            add(
                f"적용 가능한 거버넌스 규정이 없습니다 — '{snippet}' 리스크를 고려하여 "
                f"수동 검토를 진행하거나 거버넌스팀에 해당 의사결정 유형에 대한 규정 추가를 요청하세요"
            )
        else:
            snippet = decision_stmt[:50] if decision_stmt else "이 의사결정"
            add(
                f"적용 가능한 거버넌스 규정이 없습니다 — '{snippet}' 유형의 의사결정에 대한 "
                f"거버넌스 규정 추가를 검토하거나, 준법감시인에게 수동 검토를 요청하세요"
            )

    # 4. Other flag-specific guidance
    if "CRITICAL_CONFLICT" in flags:
        add("의사결정 내 상충 항목을 해소하세요 — 목표, KPI, 리스크 간 모순 내용을 수정한 후 재제출하세요")

    # 5. Blocked with no actions yet — escalation fallback
    if governance_status == "blocked" and not actions:
        add("차단 원인 해소 전 진행 불가 — 위 항목들을 해결한 후 거버넌스 검토팀에 재제출하세요")

    # 6. Needs review with no actions yet — reviewer assignment fallback
    if governance_status in ("needs_review", "review_required") and not actions:
        add("검토 담당자를 배정하고 의사결정 패키지를 전달하세요")

    # 7. Compliant — confirm and proceed
    if governance_status == "compliant" and not actions:
        add("모든 거버넌스 요건을 충족했습니다 — 최종 검토 후 실행을 진행하세요")

    return actions


def _build_review_guidance(role: str, rule_type: str, rationale: str, decision: dict) -> str:
    """
    Build context-aware guidance for a review-type (require_review) approval step.
    Tells the user what to prepare and attach for this reviewer.
    """
    if rule_type == "compliance":
        if rationale:
            return (
                f"{role} 검토를 받으세요 — {rationale} 관련 내용을 사전에 정리하고 "
                f"관련 문서(정책 근거, 위험 완화 방안)를 첨부하세요"
            )
        return f"{role} 검토를 받으세요 — 준법 리스크 관련 서류(정책 근거, 위험 완화 방안)를 첨부하세요"

    if rule_type == "hr":
        headcount = decision.get("headcount_change")
        if headcount and headcount > 0:
            return (
                f"{role} 검토를 받으세요 — {headcount}명 채용에 대한 "
                f"직무 기술서, 예산, 채용 일정이 포함된 인력 계획서를 첨부하세요"
            )
        return f"{role} 검토를 받으세요 — 인력 계획서 및 채용 요건을 첨부하세요"

    if rule_type == "financial":
        cost = decision.get("cost")
        if cost:
            cost_str = f"{int(cost):,}원"
            return (
                f"{role} 검토를 받으세요 — {cost_str} 규모 지출에 대한 "
                f"예산 근거 및 비용 편익 분석을 첨부하세요"
            )
        return f"{role} 검토를 받으세요 — 예산 근거 및 비용 편익 분석을 첨부하세요"

    if rationale:
        return f"{role} 검토를 받으세요 — {rationale}"
    return f"{role} 검토를 받으세요"


def _build_approval_guidance(role: str, rule_type: str, rationale: str, decision: dict) -> str:
    """
    Build context-aware 'approve OR adjust' guidance for a hard approval step.
    Where possible, offers a concrete alternative path (e.g. reduce below threshold).
    """
    if rule_type == "financial":
        cost = decision.get("cost")
        if cost:
            cost_str = f"{int(cost):,}원"
            if cost > 1_000_000_000:
                return (
                    f"{role} 승인을 받으세요 — {cost_str} 규모로 이사회급 승인이 필요합니다. "
                    f"CFO 및 CEO 순차 승인 문서를 준비하거나, 예산 규모를 10억 원 미만으로 조정하세요"
                )
            elif cost > 50_000_000:
                return (
                    f"{role} 승인을 받으세요 — {cost_str} 규모로 CFO 승인이 필요합니다. "
                    f"비용 편익 분석 및 예산 근거를 포함한 승인 요청서를 제출하거나, "
                    f"예산을 5,000만 원 이하로 조정하세요"
                )
            else:
                return f"{role} 승인을 받으세요 — {cost_str} 규모 지출에 대한 승인 요청서를 제출하세요"
        if rationale:
            return f"{role} 승인을 받으세요 — {rationale}. 예산 근거 및 비용 편익 분석을 첨부하세요"
        return f"{role} 승인을 받으세요 — 예산 근거 및 비용 편익 분석을 첨부하세요"

    if rule_type == "strategic":
        strategic_impact = decision.get("strategic_impact", "")
        if strategic_impact == "critical":
            return (
                f"{role} 승인을 받으세요 — 전사적 전략 영향도가 '중대(critical)'로 평가되었습니다. "
                f"전략 검토 보고서 및 이해관계자 분석을 포함한 경영진 보고서를 준비하세요"
            )
        if rationale:
            return f"{role} 승인을 받으세요 — {rationale}. 전략 정합성 검토 자료를 첨부하세요"
        return f"{role} 승인을 받으세요 — 전략적 영향도 검토 자료를 첨부하세요"

    if rule_type == "hr":
        headcount = decision.get("headcount_change")
        if headcount and headcount >= 10:
            return (
                f"{role} 승인을 받으세요 — {headcount}명 이상 대규모 인력 변경으로 CEO 승인이 필요합니다. "
                f"조직 변경 계획서(인력 계획, 예산, 전략적 근거)를 준비하거나, 채용 규모를 10명 미만으로 조정하세요"
            )
        return f"{role} 승인을 받으세요 — 인력 변경 계획서를 제출하세요"

    if rationale:
        return f"{role} 승인을 받으세요 — {rationale}"
    return f"{role} 승인을 받으세요"


def _extract_rationales(triggered_rules: list[dict], approval_chain: list[dict]) -> list[str]:
    """
    Extract rationales from triggered rules and approval chain.

    Returns list of rationale strings.
    """
    rationales = []

    # Extract from triggered rules
    for rule in triggered_rules:
        name = rule.get("name", "")
        description = rule.get("description", "")
        if description:
            rationales.append(f"{name}: {description}")
        elif name:
            rationales.append(name)

    # Extract from approval chain
    for step in approval_chain:
        rationale = step.get("rationale")
        if rationale:
            role = step.get("role", "")
            if rationale not in rationales:
                rationales.append(f"{role} - {rationale}")

    return rationales


def _generate_title(decision_statement: str, strategic_impact: Optional[str]) -> str:
    """
    Generate a title for the decision pack.

    Returns title string.
    """
    # Truncate decision statement if too long
    max_length = 80
    truncated = decision_statement[:max_length]
    if len(decision_statement) > max_length:
        truncated += "..."

    # Add strategic impact prefix if critical or high
    if strategic_impact in ["critical", "high"]:
        prefix = f"[{strategic_impact.upper()}] "
        return prefix + truncated

    return truncated


# Example usage and demo
def demo_decision_pack():
    """
    Demo case: High-risk acquisition decision
    """
    # Example decision (as dict)
    decision = {
        "decision_statement": "Acquire TechStartup Inc for $2.5M to expand our AI capabilities",
        "goals": [
            {
                "description": "Expand AI/ML product offerings",
                "metric": "Number of AI features launched"
            },
            {
                "description": "Acquire engineering talent",
                "metric": "Team size increase"
            }
        ],
        "kpis": [
            {
                "name": "Revenue from AI products",
                "target": "$5M ARR within 18 months",
                "measurement_frequency": "Quarterly"
            }
        ],
        "risks": [
            {
                "description": "Integration challenges with existing systems",
                "severity": "high",
                "mitigation": "Dedicated integration team and 6-month timeline"
            },
            {
                "description": "Key personnel may leave post-acquisition",
                "severity": "critical",
                "mitigation": "Retention bonuses and equity grants"
            },
            {
                "description": "Cultural mismatch between organizations",
                "severity": "medium",
                "mitigation": "Cultural assessment and integration planning"
            }
        ],
        "owners": [
            {
                "name": "Sarah Chen",
                "role": "VP of Strategy",
                "responsibility": "Overall acquisition execution"
            }
        ],
        "assumptions": [
            {
                "description": "TechStartup's tech stack is compatible",
                "criticality": "high"
            }
        ],
        "required_approvals": ["CFO", "CEO", "Board"],
        "confidence": 0.75,
        "strategic_impact": "high",
        "risk_score": 7.5
    }

    # Example governance result (as dict)
    governance = {
        "approval_chain": [
            {
                "level": "department_head",
                "role": "Budget Owner",
                "required": True,
                "rationale": "Budget accountability"
            },
            {
                "level": "vp",
                "role": "VP of Finance",
                "required": True,
                "rationale": "Financial review and approval"
            },
            {
                "level": "c_level",
                "role": "CFO",
                "required": True,
                "rationale": "Major financial decision approval"
            },
            {
                "level": "c_level",
                "role": "CEO",
                "required": True,
                "rationale": "Executive approval for major investments"
            }
        ],
        "flags": ["HIGH_RISK", "FINANCIAL_THRESHOLD_EXCEEDED"],
        "requires_human_review": True,
        "triggered_rules": [
            {
                "rule_id": "R006",
                "name": "Financial Threshold - Major Investment",
                "description": "Decisions implying budget > $1M or containing 'acquisition', 'investment', 'capital' require CFO approval",
                "priority": 1
            }
        ],
        "computed_risk_score": 7.5
    }

    # Build decision pack
    pack = build_decision_pack(decision, governance)

    return pack


if __name__ == "__main__":
    """
    Run demo to show example input/output
    """
    import json

    print("=" * 80)
    print("DECISION PACK GENERATOR - DEMO")
    print("=" * 80)
    print()

    pack = demo_decision_pack()

    print(json.dumps(pack, indent=2))
    print()
    print("=" * 80)
