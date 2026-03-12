"""
Evidence Registry Service — Deterministic internal evidence lookup for governance explanations.

Reads company-specific evidence registry JSON files from:
    app/demo_fixtures/companies/{company_id}/evidence_registry/

Provides lookup and assembly methods that return normalized evidence objects
for use in governance console, risk scoring, and decision pack.

Design principles:
- Deterministic: no LLM, no scenario-specific branches
- Registry-driven: all evidence traces to a named internal document + section
- Role resolution is data-driven: alias table built from each company's approval_sources.json
- Safe: missing entries return None or empty list, never raise in assembly methods
- Cached: each company registry is loaded from disk once per process lifetime
"""

import json
import logging
import operator
import re
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Registry root ─────────────────────────────────────────────────────────────
_FIXTURES_ROOT = Path(__file__).parent.parent / "demo_fixtures" / "companies"

# ── In-memory cache: company_id → fully loaded registry dict ─────────────────
_cache: dict[str, dict] = {}

# ── Budget source selection thresholds (structural policy, not company-specific) ──
_CAPEX_THRESHOLD = 50_000_000
_BOARD_THRESHOLD = 1_000_000_000


# ── Agent name → department derivation ───────────────────────────────────────

_AGENT_SUFFIXES = [
    "ai agent", "agent", "에이전트", "ai",
]

def _derive_department_from_agent(agent_name: str) -> Optional[str]:
    """
    Strip common agent-name suffixes to get a department hint.
    '마케팅 에이전트' → '마케팅'  |  'Finance AI Agent' → 'Finance'
    Returns None if the result is empty or the name is the generic default.
    """
    if not agent_name:
        return None
    cleaned = agent_name.strip()
    lowered = cleaned.lower()
    for suffix in _AGENT_SUFFIXES:
        if lowered.endswith(suffix):
            cleaned = cleaned[: len(cleaned) - len(suffix)].strip()
            lowered = cleaned.lower()
    return cleaned or None


# ── Role string normalisation ─────────────────────────────────────────────────

def _strip_parens(text: str) -> str:
    """Remove parenthetical suffixes: '최고재무책임자 (CFO)' → '최고재무책임자'."""
    return re.sub(r"\s*\(.*?\)", "", text).strip()


def _normalize_str(text: str) -> str:
    """Lowercase + strip parens — used as dict key for alias lookup."""
    return _strip_parens(text).lower().strip()


def _build_role_alias_table(approval_sources: list[dict]) -> dict[str, str]:
    """
    Build a {normalized_surface_form: roleKey} mapping from a company's
    approval_sources entries.

    For each entry we register:
      - the roleKey itself (e.g. "cfo")
      - the full roleNameKo (e.g. "최고재무책임자 (cfo)")
      - roleNameKo with parens stripped (e.g. "최고재무책임자")
      - the full roleNameEn (e.g. "chief financial officer (cfo)")
      - roleNameEn with parens stripped (e.g. "chief financial officer")

    This is called once at registry load time — no per-request cost.
    """
    table: dict[str, str] = {}
    for entry in approval_sources:
        role_key = entry.get("roleKey", "")
        if not role_key:
            continue
        candidates = [
            role_key,
            entry.get("roleNameKo", ""),
            entry.get("roleNameEn", ""),
        ]
        for raw in candidates:
            if not raw:
                continue
            # Register both the original normalised form and the paren-stripped form
            table[_normalize_str(raw)] = role_key
            stripped = _strip_parens(raw)
            if stripped:
                table[_normalize_str(stripped)] = role_key
    return table


# ── Internal loader ───────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_company_registry(company_id: str) -> dict:
    """
    Load (and cache) the full evidence registry for a company.

    Returns a dict with keys:
        index, policies, strategy, budget, approvals, _role_alias_table

    Raises FileNotFoundError if the registry does not exist for company_id.
    """
    if company_id in _cache:
        return _cache[company_id]

    company_dir = _FIXTURES_ROOT / company_id
    index_path = company_dir / "evidence_registry" / "registry_index.json"

    if not index_path.exists():
        raise FileNotFoundError(
            f"Evidence registry not found for company '{company_id}'. "
            f"Expected: {index_path}"
        )

    index = _load_json(index_path)
    sources = index.get("availableSources", {})

    def _load_source(key: str) -> dict:
        rel = sources.get(key)
        if not rel:
            return {}
        full_path = company_dir / rel
        if not full_path.exists():
            logger.warning(f"[evidence_registry] Missing source file: {full_path}")
            return {}
        return _load_json(full_path)

    approvals = _load_source("approvals")
    role_alias_table = _build_role_alias_table(
        approvals.get("approvalSources", [])
    )

    registry: dict = {
        "index": index,
        "policies": _load_source("policies"),
        "strategy": _load_source("strategy"),
        "budget": _load_source("budget"),
        "approvals": approvals,
        "_role_alias_table": role_alias_table,
    }

    # Load any additional sources listed in availableSources dynamically
    # (e.g. production, rnd, sales, legal) — these extend the registry
    # without requiring changes to this loader when new source types are added.
    _reserved_keys = {"policies", "strategy", "budget", "approvals", "_role_alias_table"}
    for key in sources:
        if key not in _reserved_keys and key not in registry:
            registry[key] = _load_source(key)

    _cache[company_id] = registry
    logger.info(
        f"[evidence_registry] Loaded registry for '{company_id}' "
        f"({len(role_alias_table)} role aliases)"
    )
    return registry


def _clear_cache(company_id: Optional[str] = None) -> None:
    """Clear cache — used in tests to force reload."""
    if company_id:
        _cache.pop(company_id, None)
    else:
        _cache.clear()


# ── Role resolution ───────────────────────────────────────────────────────────

def _resolve_role_key(role_input: str, role_alias_table: dict[str, str]) -> Optional[str]:
    """
    Map any role surface form → canonical roleKey.

    Lookup order:
    1. Exact match after normalize (handles most cases)
    2. Substring scan over alias table keys (handles embedded role names)

    All knowledge comes from the company's own approval_sources.json.
    No hardcoded role names in service code.
    """
    if not role_input:
        return None

    # 1. Exact match
    key = role_alias_table.get(_normalize_str(role_input))
    if key:
        return key

    # 2. Substring scan — handles inputs like "CFO (최고재무책임자)" where the
    #    paren content itself contains a registered alias key
    normalized_input = _normalize_str(role_input)
    for alias, role_key in role_alias_table.items():
        if alias and alias in normalized_input:
            return role_key

    return None


# ── Normalisation helpers ─────────────────────────────────────────────────────

def _normalize_policy(entry: dict) -> dict:
    rule_id = entry.get("ruleId", "")
    return {
        "id": f"policy_{rule_id.lower()}",
        "category": "policy",
        "titleKo": entry.get("titleKo", ""),
        "titleEn": entry.get("titleEn", ""),
        "sourceType": entry.get("sourceType", "policy_document"),
        "documentNameKo": entry.get("documentNameKo", ""),
        "documentNameEn": entry.get("documentNameEn", ""),
        "summaryKo": entry.get("summaryKo", ""),
        "summaryEn": entry.get("summaryEn", ""),
        "citationKo": entry.get("citationKo", ""),
        "citationEn": entry.get("citationEn", ""),
        "metadata": {
            "ruleId": rule_id,
            "section": entry.get("section", ""),
            "ownerRole": entry.get("ownerRole", ""),
            "tags": entry.get("tags", []),
        },
    }


def _normalize_strategy(entry: dict) -> dict:
    goal_id = entry.get("goalId", "")
    return {
        "id": f"strategy_{goal_id.lower()}",
        "category": "strategy",
        "titleKo": entry.get("documentNameKo", ""),
        "titleEn": entry.get("documentNameEn", ""),
        "sourceType": entry.get("sourceType", "strategy_document"),
        "documentNameKo": entry.get("documentNameKo", ""),
        "documentNameEn": entry.get("documentNameEn", ""),
        "summaryKo": entry.get("summaryKo", ""),
        "summaryEn": entry.get("summaryEn", ""),
        "citationKo": entry.get("citationKo", ""),
        "citationEn": entry.get("citationEn", ""),
        "metadata": {
            "goalId": goal_id,
            "ownerRole": entry.get("ownerRole", ""),
            "ownerDepartment": entry.get("ownerDepartment", ""),
            "targetSummaryKo": entry.get("targetSummaryKo", ""),
            "targetSummaryEn": entry.get("targetSummaryEn", ""),
            "kpis": entry.get("kpis", []),
        },
    }


def _render_citation_template(template: str, values: dict) -> Optional[str]:
    """
    Substitute {{key}} placeholders with runtime values.

    Returns the rendered string only when ALL placeholders are filled.
    Returns None if any placeholder has no matching value in `values`,
    so callers can fall back to a clean summary instead of a broken sentence.
    """
    import re
    keys_in_template = re.findall(r"\{\{(\w+)\}\}", template)
    if not keys_in_template:
        return template  # no placeholders — return as-is

    # Fail fast if any required key is missing
    if any(values.get(k) is None for k in keys_in_template):
        return None

    def replace(match):
        val = values[match.group(1)]
        if isinstance(val, float) and val == int(val):
            return f"{int(val):,}"
        if isinstance(val, (int, float)):
            return f"{val:,}"
        return str(val)

    return re.sub(r"\{\{(\w+)\}\}", replace, template).strip()


def _normalize_budget(entry: dict, runtime_metadata: Optional[dict] = None) -> dict:
    source_id = entry.get("sourceId", "")
    meta = runtime_metadata or {}

    raw_tpl_ko = entry.get("citationTemplateKo", "")
    raw_tpl_en = entry.get("citationTemplateEn", "")

    # Use rendered template only when all placeholders can be filled;
    # otherwise fall back to the human-readable summary.
    rendered_ko = _render_citation_template(raw_tpl_ko, meta) if meta else None
    rendered_en = _render_citation_template(raw_tpl_en, meta) if meta else None
    citation_ko = rendered_ko or entry.get("summaryKo", "")
    citation_en = rendered_en or entry.get("summaryEn", "")

    return {
        "id": f"budget_{source_id.lower()}",
        "category": "financial",
        "titleKo": entry.get("documentNameKo", ""),
        "titleEn": entry.get("documentNameEn", ""),
        "sourceType": entry.get("sourceType", "budget_sheet"),
        "documentNameKo": entry.get("documentNameKo", ""),
        "documentNameEn": entry.get("documentNameEn", ""),
        "summaryKo": entry.get("summaryKo", ""),
        "summaryEn": entry.get("summaryEn", ""),
        "citationKo": citation_ko,
        "citationEn": citation_en,
        "metadata": {
            "sourceId": source_id,
            "ownerRole": entry.get("ownerRole", ""),
            "relevantFields": entry.get("relevantFields", []),
            # Templates stored for future full-rendering use
            "citationTemplateKo": raw_tpl_ko,
            "citationTemplateEn": raw_tpl_en,
            **meta,
        },
    }


def _normalize_sales(entry: dict, runtime_metadata: Optional[dict] = None) -> dict:
    source_id = entry.get("sourceId", "")
    meta = runtime_metadata or {}

    raw_tpl_ko = entry.get("citationTemplateKo", "")
    raw_tpl_en = entry.get("citationTemplateEn", "")
    rendered_ko = _render_citation_template(raw_tpl_ko, meta) if meta else None
    rendered_en = _render_citation_template(raw_tpl_en, meta) if meta else None
    citation_ko = rendered_ko or entry.get("summaryKo", "")
    citation_en = rendered_en or entry.get("summaryEn", "")

    return {
        "id": f"sales_{source_id.lower()}",
        "category": "financial",
        "titleKo": entry.get("documentNameKo", ""),
        "titleEn": entry.get("documentNameEn", ""),
        "sourceType": entry.get("sourceType", "sales_report"),
        "documentNameKo": entry.get("documentNameKo", ""),
        "documentNameEn": entry.get("documentNameEn", ""),
        "summaryKo": entry.get("summaryKo", ""),
        "summaryEn": entry.get("summaryEn", ""),
        "citationKo": citation_ko,
        "citationEn": citation_en,
        "metadata": {
            "sourceId": source_id,
            "ownerRole": entry.get("ownerRole", ""),
            **meta,
        },
    }


def _normalize_approval(entry: dict) -> dict:
    role_key = entry.get("roleKey", "")
    return {
        "id": f"approval_{role_key.lower()}",
        "category": "approval",
        "titleKo": entry.get("roleNameKo", ""),
        "titleEn": entry.get("roleNameEn", ""),
        "sourceType": entry.get("sourceType", "org_chart"),
        "documentNameKo": entry.get("documentNameKo", ""),
        "documentNameEn": entry.get("documentNameEn", ""),
        "summaryKo": entry.get("authoritySummaryKo", ""),
        "summaryEn": entry.get("authoritySummaryEn", ""),
        "citationKo": entry.get("citationKo", ""),
        "citationEn": entry.get("citationEn", ""),
        "metadata": {
            "roleKey": role_key,
            "level": entry.get("level"),
        },
    }


# ── Trigger evaluation helpers ───────────────────────────────────────────────

_TRIGGER_OPS: dict[str, Callable] = {
    "==": operator.eq,
    "!=": operator.ne,
    ">":  operator.gt,
    "<":  operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
}


def _eval_trigger_condition(trigger: dict, decision_payload: dict) -> bool:
    """
    Evaluate a single trigger condition against the decision payload.

    Operator dispatch driven by _TRIGGER_OPS. Numeric operators cast to float;
    equality/inequality compare as-is. Unknown operators return False safely.
    Returns False when the payload field is absent or a type conversion fails.
    """
    field = trigger.get("triggerField")
    if not field:
        return False
    expected = trigger.get("triggerValue")
    op_key = trigger.get("triggerOperator", "==")
    actual = decision_payload.get(field)

    op_fn = _TRIGGER_OPS.get(op_key)
    if op_fn is None:
        return False

    if op_key in (">", "<", ">=", "<="):
        if actual is None:
            return False
        try:
            return op_fn(float(actual), float(expected))
        except (TypeError, ValueError):
            return False
    return op_fn(actual, expected)


def _build_budget_runtime_meta(entry: dict, cost: Optional[float]) -> dict:
    """
    Build runtime metadata for a budget source entry by merging its constants
    with the decision cost and any computed verdict strings.

    Verdict is derived generically by comparing cost against the first
    recognised "available balance" constant (bank_balance_usd or
    free_cash_after_payables_usd).  If neither is found no verdict is added,
    and the citation template will fall back to the human-readable summary.
    """
    constants = entry.get("constants", {})
    meta = dict(constants)

    if cost is not None:
        meta["cost"] = cost
        # Find the first applicable balance constant (priority order)
        balance_val: Optional[float] = None
        for key in ("bank_balance_usd", "free_cash_after_payables_usd"):
            val = constants.get(key)
            if val is not None:
                balance_val = float(val)
                break

        if balance_val is not None:
            ok = cost <= balance_val
            meta["verdict"] = "잔액 범위 내" if ok else "잔액 초과"
            meta["verdictEn"] = "within available balance" if ok else "exceeds available balance"

    return meta


# ── Atomic lookup methods ─────────────────────────────────────────────────────

def get_policy_evidence(company_id: str, rule_id: str) -> Optional[dict]:
    """Return normalized policy evidence for a rule ID, or None if not found."""
    try:
        registry = load_company_registry(company_id)
        for entry in registry["policies"].get("policies", []):
            if entry.get("ruleId") == rule_id:
                return _normalize_policy(entry)
    except Exception as e:
        logger.warning(f"[evidence_registry] get_policy_evidence failed for '{rule_id}': {e}")
    return None


def get_strategy_evidence(company_id: str, goal_id: str) -> Optional[dict]:
    """Return normalized strategy evidence for a goal ID, or None if not found."""
    try:
        registry = load_company_registry(company_id)
        for entry in registry["strategy"].get("strategySources", []):
            if entry.get("goalId") == goal_id:
                return _normalize_strategy(entry)
    except Exception as e:
        logger.warning(f"[evidence_registry] get_strategy_evidence failed for '{goal_id}': {e}")
    return None


def get_budget_evidence(
    company_id: str,
    source_id: Optional[str] = None,
    runtime_metadata: Optional[dict] = None,
) -> list[dict]:
    """
    Return normalized budget evidence records.
    If source_id is given, return only that entry (or empty list if not found).
    If source_id is None, return all budget sources.
    """
    try:
        registry = load_company_registry(company_id)
        entries = registry["budget"].get("budgetSources", [])
        if source_id:
            entries = [e for e in entries if e.get("sourceId") == source_id]
        return [_normalize_budget(e, runtime_metadata) for e in entries]
    except Exception as e:
        logger.warning(f"[evidence_registry] get_budget_evidence failed: {e}")
    return []


def get_approval_evidence(company_id: str, role_input: str) -> Optional[dict]:
    """
    Return normalized approval evidence for any surface form of a role name.
    Alias resolution is driven entirely by the company's approval_sources.json —
    no hardcoded role names in service code.
    Returns None if no matching role is found.
    """
    try:
        registry = load_company_registry(company_id)
        role_key = _resolve_role_key(role_input, registry["_role_alias_table"])
        if not role_key:
            logger.debug(
                f"[evidence_registry] Could not resolve role key for: '{role_input}'"
            )
            return None
        for entry in registry["approvals"].get("approvalSources", []):
            if entry.get("roleKey") == role_key:
                return _normalize_approval(entry)
    except Exception as e:
        logger.warning(
            f"[evidence_registry] get_approval_evidence failed for '{role_input}': {e}"
        )
    return None


# ── Assembly methods ──────────────────────────────────────────────────────────

def assemble_rule_evidence(
    company_id: str, triggered_rule_ids: list[str]
) -> list[dict]:
    """Return policy evidence for each triggered rule ID. Unknown IDs are skipped."""
    result = []
    for rule_id in triggered_rule_ids:
        evidence = get_policy_evidence(company_id, rule_id)
        if evidence:
            result.append(evidence)
        else:
            logger.debug(
                f"[evidence_registry] No policy entry for rule '{rule_id}' — skipped"
            )
    return result


def assemble_goal_evidence(
    company_id: str, goal_ids: list[str]
) -> list[dict]:
    """Return strategy evidence for each goal ID. Unknown IDs are skipped."""
    result = []
    for goal_id in goal_ids:
        evidence = get_strategy_evidence(company_id, goal_id)
        if evidence:
            result.append(evidence)
        else:
            logger.debug(
                f"[evidence_registry] No strategy entry for goal '{goal_id}' — skipped"
            )
    return result


def _collect_triggered_evidence(
    registry: dict,
    decision_payload: dict,
    trigger_key: str,
    category: str,
) -> list[dict]:
    """
    Shared helper: evaluate trigger conditions from registry_index[trigger_key]
    and return normalised evidence items tagged with the given category label.

    Handles three source types per trigger entry:
    - budgetSourceIds  → looked up from registry["budget"]["budgetSources"]
    - salesSourceIds   → looked up from registry["sales"]["salesSources"]
    - sourceIds        → checked against both lists (budget first, then sales)

    Runtime metadata (cost + computed verdicts) is added for budget sources.
    All items are deep-copied so callers can mutate the category without affecting
    cached registry data.
    """
    triggers = registry.get("index", {}).get(trigger_key, [])
    if not triggers:
        return []

    cost = decision_payload.get("cost")
    budget_entries = registry.get("budget", {}).get("budgetSources", [])
    sales_entries = registry.get("sales", {}).get("salesSources", [])
    seen: set[str] = set()
    result: list[dict] = []

    for trigger in triggers:
        if not _eval_trigger_condition(trigger, decision_payload):
            continue

        # Budget source IDs
        for sid in trigger.get("budgetSourceIds", []) + trigger.get("sourceIds", []):
            if sid in seen:
                continue
            entry = next((e for e in budget_entries if e.get("sourceId") == sid), None)
            if not entry:
                continue
            seen.add(sid)
            meta = _build_budget_runtime_meta(entry, cost)
            item = _normalize_budget(entry, meta)
            item["category"] = category
            result.append(item)

        # Sales source IDs
        for sid in trigger.get("salesSourceIds", []):
            if sid in seen:
                continue
            entry = next((e for e in sales_entries if e.get("sourceId") == sid), None)
            if not entry:
                continue
            seen.add(sid)
            meta = dict(entry.get("constants", {}))
            item = _normalize_sales(entry, meta)
            item["category"] = category
            result.append(item)

    return result


def assemble_financial_evidence(
    company_id: str, decision_payload: dict
) -> list[dict]:
    """
    Select budget evidence (bank statement, cash-flow plan, headcount) for the
    decision payload.

    Registry-driven path (preferred):
      Uses financialTriggers from registry_index.json — purely affordability/
      budget-health sources (BS_BANK_STATEMENT, BS_CASHFLOW_PLAN, BS_HEADCOUNT_BUDGET).
      Inventory and sales demand evidence goes to procurementEvidence instead.

    Legacy path (fallback):
      For companies without financialTriggers, uses the original threshold-based
      logic (BS_DEPT_BUDGET / BS_SPEND_AUTHORITY / BS_OPEX_BASELINE).
    """
    # ── Registry-driven path ─────────────────────────────────────────────────
    try:
        registry = load_company_registry(company_id)
        if registry.get("index", {}).get("financialTriggers"):
            return _collect_triggered_evidence(
                registry, decision_payload, "financialTriggers", "financial"
            )
    except Exception as e:
        logger.warning(
            f"[evidence_registry] assemble_financial_evidence (trigger path) failed "
            f"for '{company_id}': {e}"
        )

    # ── Legacy path (companies without financialTriggers in registry) ────────
    cost = decision_payload.get("cost")
    if cost is None:
        return []

    remaining_budget = decision_payload.get("remaining_budget")
    # department (KO): explicit extraction > agent_name(KO) derivation > "해당" fallback
    department = (
        decision_payload.get("department")
        or _derive_department_from_agent(decision_payload.get("agent_name", ""))
        or "해당"
    )
    # department (EN): explicit extraction > agent_name_en derivation > "relevant" fallback
    department_en = (
        decision_payload.get("department")
        or _derive_department_from_agent(decision_payload.get("agent_name_en", ""))
        or "relevant"
    )

    # Compute verdict deterministically when remaining_budget is known
    if remaining_budget is not None:
        verdict_ko = "예산 초과" if cost > remaining_budget else "예산 내 처리 가능"
        verdict_en = "over budget" if cost > remaining_budget else "within budget"
    else:
        verdict_ko = None
        verdict_en = None

    dept_budget_meta: dict = {"cost": cost, "department": department, "departmentEn": department_en}
    if remaining_budget is not None:
        dept_budget_meta["remaining_budget"] = remaining_budget
        dept_budget_meta["verdict"] = verdict_ko
        dept_budget_meta["verdictEn"] = verdict_en

    result = []

    for src in get_budget_evidence(company_id, "BS_DEPT_BUDGET", dept_budget_meta):
        result.append(src)

    if cost > _CAPEX_THRESHOLD:
        # Read spendTiers from the registry entry to compute approver_role and max_budget_authority
        try:
            registry = load_company_registry(company_id)
            spend_entry = next(
                (e for e in registry["budget"].get("budgetSources", []) if e.get("sourceId") == "BS_SPEND_AUTHORITY"),
                {}
            )
            tiers = spend_entry.get("spendTiers", [])
            exceeded = [t for t in tiers if cost > t["limit"]]
            relevant_tier = max(exceeded, key=lambda t: t["limit"]) if exceeded else None
        except Exception:
            relevant_tier = None

        if relevant_tier:
            authority_meta = {
                "cost": cost,
                "approver_role": relevant_tier["roleNameKo"],
                "approverRoleEn": relevant_tier["roleNameEn"],
                "max_budget_authority": relevant_tier["limit"],
                "verdict": "초과",
                "verdictEn": "exceeds",
            }
        else:
            authority_meta = {"cost": cost}
        for src in get_budget_evidence(company_id, "BS_SPEND_AUTHORITY", authority_meta):
            result.append(src)

    # Read opex constants from the registry entry
    try:
        registry = load_company_registry(company_id)
        opex_entry = next(
            (e for e in registry["budget"].get("budgetSources", []) if e.get("sourceId") == "BS_OPEX_BASELINE"),
            {}
        )
        constants = opex_entry.get("constants", {})
        opex_baseline = constants.get("opex_baseline")
        cost_reduction_target_pct = constants.get("cost_reduction_target_pct")
    except Exception:
        opex_baseline = None
        cost_reduction_target_pct = None

    if opex_baseline and cost_reduction_target_pct is not None:
        reduction_target = opex_baseline * (cost_reduction_target_pct / 100)
        if cost > reduction_target:
            opex_verdict_ko = "G3 절감 목표 초과 우려"
            opex_verdict_en = "a concern for the G3 cost reduction target"
        else:
            opex_verdict_ko = "G3 절감 목표 범위 내"
            opex_verdict_en = "within the G3 cost reduction target"
        opex_meta = {
            "cost": cost,
            "opex_baseline": opex_baseline,
            "cost_reduction_target_pct": cost_reduction_target_pct,
            "verdict": opex_verdict_ko,
            "verdictEn": opex_verdict_en,
        }
    else:
        opex_meta = {"cost": cost}

    for src in get_budget_evidence(company_id, "BS_OPEX_BASELINE", opex_meta):
        result.append(src)

    return result


def assemble_procurement_evidence(
    company_id: str, decision_payload: dict
) -> list[dict]:
    """
    Select procurement-relevant evidence: inventory status, order capacity,
    and demand-side sources (sales projections, promotion plans).

    Uses procurementTriggers from registry_index.json.  Returns [] for companies
    that have no procurementTriggers configured (non-fatal by design).
    """
    try:
        registry = load_company_registry(company_id)
        if registry.get("index", {}).get("procurementTriggers"):
            return _collect_triggered_evidence(
                registry, decision_payload, "procurementTriggers", "procurement"
            )
    except Exception as e:
        logger.warning(
            f"[evidence_registry] assemble_procurement_evidence failed "
            f"for '{company_id}': {e}"
        )
    return []


def assemble_approval_evidence(
    company_id: str, approval_chain: list[dict]
) -> list[dict]:
    """
    Map approval chain entries to org-chart authority evidence.

    Each entry may contain any of: 'approver_role', 'role', 'title'.
    Duplicate roles are deduplicated (first occurrence wins).
    Role resolution is entirely data-driven from the company's approval_sources.json.
    """
    seen: set[str] = set()
    result = []

    try:
        registry = load_company_registry(company_id)
        alias_table = registry["_role_alias_table"]
    except Exception as e:
        logger.warning(f"[evidence_registry] assemble_approval_evidence: registry load failed: {e}")
        return []

    for entry in approval_chain:
        role_input = (
            entry.get("approver_role")
            or entry.get("role")
            or entry.get("title")
            or ""
        )
        if not role_input:
            continue

        role_key = _resolve_role_key(role_input, alias_table)
        if not role_key or role_key in seen:
            continue

        evidence = get_approval_evidence(company_id, role_input)
        if evidence:
            result.append(evidence)
            seen.add(role_key)

    return result


def _normalize_legal(entry: dict) -> dict:
    source_id = entry.get("sourceId", "")
    constants = entry.get("constants") or {}

    # Flatten any list values to comma-separated strings so templates render cleanly.
    # e.g. "approver_roles": ["CEO", "OPERATIONS_MANAGER"] → "CEO, OPERATIONS_MANAGER"
    template_values = {
        k: (", ".join(str(i) for i in v) if isinstance(v, list) else v)
        for k, v in constants.items()
    }

    raw_tpl_ko = entry.get("citationTemplateKo", "")
    raw_tpl_en = entry.get("citationTemplateEn", "")
    citation_ko = _render_citation_template(raw_tpl_ko, template_values) or entry.get("summaryKo", "")
    citation_en = _render_citation_template(raw_tpl_en, template_values) or entry.get("summaryEn", "")

    return {
        "id": f"legal_{source_id.lower()}",
        "category": "compliance",
        "titleKo": entry.get("documentNameKo", ""),
        "titleEn": entry.get("documentNameEn", ""),
        "sourceType": entry.get("sourceType", "legal_guideline"),
        "documentNameKo": entry.get("documentNameKo", ""),
        "documentNameEn": entry.get("documentNameEn", ""),
        "summaryKo": entry.get("summaryKo", ""),
        "summaryEn": entry.get("summaryEn", ""),
        "citationKo": citation_ko,
        "citationEn": citation_en,
        "metadata": {
            "sourceId": source_id,
            "ownerRole": entry.get("ownerRole", ""),
            "tags": entry.get("tags", []),
            **constants,
        },
    }


def get_legal_evidence(company_id: str, source_id: str) -> Optional[dict]:
    """Return normalized legal evidence for a source ID, or None if not found."""
    try:
        registry = load_company_registry(company_id)
        for entry in registry.get("legal", {}).get("legalSources", []):
            if entry.get("sourceId") == source_id:
                return _normalize_legal(entry)
    except Exception as e:
        logger.warning(f"[evidence_registry] get_legal_evidence failed for '{source_id}': {e}")
    return None


def assemble_legal_evidence(company_id: str, decision_payload: dict) -> list[dict]:
    """
    Return legal compliance evidence entries triggered by decision attributes.

    Trigger mapping is entirely config-driven via legalTriggers in registry_index.json.
    Each trigger specifies a decision field + expected value + list of source IDs to surface.
    No scenario-specific branches in service code.
    """
    try:
        registry = load_company_registry(company_id)
        triggers = registry.get("index", {}).get("legalTriggers", [])
        seen: set[str] = set()
        result = []
        for trigger in triggers:
            field = trigger.get("triggerField")
            expected = trigger.get("triggerValue")
            if field and decision_payload.get(field) == expected:
                for source_id in trigger.get("sourceIds", []):
                    if source_id in seen:
                        continue
                    evidence = get_legal_evidence(company_id, source_id)
                    if evidence:
                        result.append(evidence)
                        seen.add(source_id)
        return result
    except Exception as e:
        logger.warning(f"[evidence_registry] assemble_legal_evidence failed: {e}")
        return []


# Tags that route a policy evidence entry to complianceEvidence instead of policyEvidence.
_COMPLIANCE_TAGS = {"compliance", "privacy", "security", "pii", "gdpr", "hipaa", "phi"}


def assemble_governance_evidence(
    company_id: str,
    triggered_rule_ids: list[str],
    goal_ids: list[str],
    approval_chain: list[dict],
    decision_payload: dict,
) -> dict:
    """
    Convenience method: assembles all five evidence categories in one call.

    Returns:
    {
      "policyEvidence":     [...],   # financial / strategic / hr governance rules
      "complianceEvidence": [...],   # compliance / privacy / security rules (tag-based split)
      "strategyEvidence":   [...],
      "financialEvidence":  [...],
      "approvalEvidence":   [...],
    }

    Each category fails independently — one failure does not block others.
    """
    def _safe(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            logger.error(
                f"[evidence_registry] Assembly error in {fn.__name__}: {e}",
                exc_info=True,
            )
            return []

    # All triggered rule evidence, then split by tag
    all_rule_evidence = _safe(assemble_rule_evidence, company_id, triggered_rule_ids)
    policy_ev = []
    compliance_ev = []
    for ev in all_rule_evidence:
        tags = set(ev.get("metadata", {}).get("tags", []))
        if tags & _COMPLIANCE_TAGS:
            compliance_ev.append(ev)
        else:
            policy_ev.append(ev)

    # Legal evidence is always compliance — append directly to compliance_ev.
    # Trigger logic is config-driven (legalTriggers in registry_index.json).
    legal_ev = _safe(assemble_legal_evidence, company_id, decision_payload)
    compliance_ev.extend(legal_ev)

    return {
        "policyEvidence":      policy_ev,
        "complianceEvidence":  compliance_ev,
        "strategyEvidence":    _safe(assemble_goal_evidence, company_id, goal_ids),
        "financialEvidence":   _safe(assemble_financial_evidence, company_id, decision_payload),
        "procurementEvidence": _safe(assemble_procurement_evidence, company_id, decision_payload),
        "approvalEvidence":    _safe(assemble_approval_evidence, company_id, approval_chain),
    }
