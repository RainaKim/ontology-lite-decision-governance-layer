"""
Risk Scoring Service — Generic, durable quantified risk engine.

Produces a structured RiskScoringResult with per-dimension scores and an
aggregate.  All logic is driven by company config (risk_tolerance, strategic
goals, governance rules) and normalised extracted decision fields — no
per-scenario hardcoding.

Dimensions (v1):
  A) financial          — cost vs thresholds, triggered financial rules
  B) compliance — PII / PHI / cross-border, triggered compliance rules
  C) strategic          — goal supports vs conflicts from graph + governance

Aggregate uses industry-adjusted weights and confidence decay for missing data.

UI output contract (enforced by _summarize_dimension_evidence):
  signals[0]   SUMMARY signal — Korean 핵심 근거 one-liner, severity = band
  signals[1..] detail signals — up to 3, sorted by severity desc then value desc
  Each signal carries evidence[]: 1-2 items, each with Korean label + source.
  Dimension-level evidence[] is kept empty (evidence lives on signals now).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Band thresholds and confidence constants
# ---------------------------------------------------------------------------

_BAND_LOW_MAX    = 40
_BAND_MEDIUM_MAX = 70
_BAND_HIGH_MAX   = 85

_CONF_BASE  = 0.9
_CONF_DECAY = 0.1
_CONF_MIN   = 0.4
_CONF_MAX   = 0.95


# ---------------------------------------------------------------------------
# Band + severity helpers
# ---------------------------------------------------------------------------

def _band(score: int) -> str:
    """Map 0-100 score to risk band label."""
    if score < _BAND_LOW_MAX:
        return "LOW"
    if score < _BAND_MEDIUM_MAX:
        return "MEDIUM"
    if score < _BAND_HIGH_MAX:
        return "HIGH"
    return "CRITICAL"


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


_SEVERITY_ORDER: dict[Optional[str], int] = {
    "CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, None: 4,
}

_BAND_KO: dict[str, str] = {
    "LOW": "낮음", "MEDIUM": "보통", "HIGH": "높음", "CRITICAL": "매우 높음",
}


# ---------------------------------------------------------------------------
# Signal code → Korean label (generic mapping table; no scenario values)
# ---------------------------------------------------------------------------

_SIGNAL_LABEL_KO: dict[str, str] = {
    # Financial
    "OVERSPEND_RATIO":           "잔여 예산 대비 초과 배수",
    "THRESHOLD_BREACH":          "회사 예산 기준 초과",
    "FIN_RULE_TRIGGERED":        "재무 승인 규칙 적용",
    # Compliance / Privacy
    "PII_DETECTED":              "PII/PHI 포함 가능성",
    "COMPLIANCE_RULE_TRIGGERED": "개인정보 보호 규칙 적용",
    "ANONYMIZATION_MISSING":     "비식별화 조치 미확인",
    "CROSS_BORDER_TRANSFER":     "국경 간 데이터 이전",
    # Strategic
    "GOAL_SUPPORT":              "전략 목표 기여",
    "GOAL_CONFLICT":             "전략 목표 충돌",
    "NO_GOAL_MAPPING":           "전략 목표 연결 불충분",
    "STRAT_RULE_TRIGGERED":      "전략 검토 규칙 적용",
    # Procurement / Inventory
    "STORAGE_UTILIZATION":       "보관 용량 사용률",
    "IN_TRANSIT_OVERLAP":        "배송 중 기존 주문 중복",
    "DEMAND_UNCERTAINTY":        "수요 예측 불확실성",
    # Special
    "SUMMARY":                   "핵심 근거",
}

# Signal code → Korean provenance badge
_SIGNAL_SOURCE_KO: dict[str, str] = {
    "OVERSPEND_RATIO":           "입력 텍스트",
    "THRESHOLD_BREACH":          "회사 정책",
    "FIN_RULE_TRIGGERED":        "규칙 엔진",
    "PII_DETECTED":              "입력 텍스트",
    "COMPLIANCE_RULE_TRIGGERED": "규칙 엔진",
    "ANONYMIZATION_MISSING":     "입력 텍스트",
    "CROSS_BORDER_TRANSFER":     "입력 텍스트",
    "GOAL_SUPPORT":              "그래프 분석",
    "GOAL_CONFLICT":             "그래프 분석",
    "NO_GOAL_MAPPING":           "시스템 분석",
    "STRAT_RULE_TRIGGERED":      "규칙 엔진",
    "STORAGE_UTILIZATION":       "재고·구매 데이터",
    "IN_TRANSIT_OVERLAP":        "재고·구매 데이터",
    "DEMAND_UNCERTAINTY":        "재고·구매 데이터",
}

# Dimension key → Korean provenance for the SUMMARY signal
_DIM_SUMMARY_SOURCE_KO: dict[str, str] = {
    "financial":   "재무 분석 (규칙 엔진 + 회사 정책)",
    "compliance":  "컴플라이언스 분석 (규칙 엔진 + 입력 텍스트)",
    "strategic":   "전략 분석 (그래프 + 거버넌스)",
    "procurement": "구매·조달 분석 (재고 데이터 + 판매 예측)",
}


def _signal_label(code: str) -> str:
    """Return Korean label for signal code; safe fallback if code unknown."""
    return _SIGNAL_LABEL_KO.get(code, f"위험 지표 ({code})")


def _first_matching_rationale(
    rs: dict,
    direction_filter: Optional[str],
    fallback: str,
) -> str:
    """
    Return the first rationale_ko from semantics goal_impacts matching direction.
    If direction_filter is None, return any non-empty rationale.
    Falls back to `fallback` if nothing is found.
    """
    for impact in (rs.get("goal_impacts") or []):
        if direction_filter is not None and impact.get("direction") != direction_filter:
            continue
        rationale = (impact.get("rationale_ko") or "").strip()
        if rationale:
            return rationale
    return fallback


def _signal_source(code: str) -> str:
    return _SIGNAL_SOURCE_KO.get(code, "시스템 분석")


# ---------------------------------------------------------------------------
# Internal data classes
# ---------------------------------------------------------------------------


@dataclass
class RiskEvidence:
    """Internal evidence item — carries both audit ref and UI-friendly fields."""
    type: str                    # internal: "field"|"rule"|"graph_edge"|"note"
    ref: dict[str, Any] = field(default_factory=dict)
    label: Optional[str] = None  # Korean user-facing description
    source: Optional[str] = None # Korean provenance badge
    confidence: Optional[float] = None
    note: Optional[str] = None


@dataclass
class RiskSignal:
    id: str                      # signal code, e.g. "OVERSPEND_RATIO"
    label: str                   # Korean label
    value: float
    unit: Optional[str] = None
    severity: Optional[str] = None        # LOW|MEDIUM|HIGH|CRITICAL
    evidence: list[RiskEvidence] = field(default_factory=list)


@dataclass
class RiskDimension:
    id: str
    label: str
    score: int    # 0-100
    band: str
    signals: list[RiskSignal] = field(default_factory=list)
    evidence: list[RiskEvidence] = field(default_factory=list)  # kept for compat, empty now
    kpi_impact_estimate: Optional[dict[str, Any]] = None
    source_rule_ids: list[str] = field(default_factory=list)  # rule_ids used to compute this dimension's score


@dataclass
class RiskAggregate:
    score: int
    band: str
    confidence: float


@dataclass
class RiskScoringResult:
    aggregate: RiskAggregate
    dimensions: list[RiskDimension]

    def to_dict(self) -> dict:
        """Serialise to plain dict for storage / JSON response."""

        def _ev_dict(e: RiskEvidence) -> dict:
            return {k: v for k, v in {
                "type":       e.type,
                "ref":        e.ref,
                "label":      e.label,
                "source":     e.source,
                "confidence": e.confidence,
                "note":       e.note,
            }.items() if v is not None}

        def _sig_dict(s: RiskSignal) -> dict:
            d: dict = {
                "id":       s.id,
                "label":    s.label,
                "value":    s.value,
            }
            if s.unit is not None:
                d["unit"] = s.unit
            if s.severity is not None:
                d["severity"] = s.severity
            if s.evidence:
                d["evidence"] = [_ev_dict(e) for e in s.evidence]
            return d

        return {
            "aggregate": {
                "score":      self.aggregate.score,
                "band":       self.aggregate.band,
                "confidence": round(self.aggregate.confidence, 3),
            },
            "dimensions": [
                {
                    "id":     d.id,
                    "label":  d.label,
                    "score":  d.score,
                    "band":   d.band,
                    "signals": [_sig_dict(s) for s in d.signals],
                    "evidence": [_ev_dict(e) for e in d.evidence],
                    **({"kpi_impact_estimate": d.kpi_impact_estimate}
                       if d.kpi_impact_estimate is not None else {}),
                    **({"source_rule_ids": d.source_rule_ids}
                       if d.source_rule_ids else {}),
                }
                for d in self.dimensions
            ],
        }


# ---------------------------------------------------------------------------
# Priority weight helper
# ---------------------------------------------------------------------------

_PRIORITY_WEIGHTS: dict[str, int] = {
    "critical": 40,
    "high":     25,
    "medium":   10,
    "low":      5,
}


def _priority_weight(priority: Optional[str]) -> int:
    return _PRIORITY_WEIGHTS.get((priority or "medium").lower(), 10)


# ---------------------------------------------------------------------------
# Evidence builder helper
# ---------------------------------------------------------------------------

def _make_evidence(
    id: str,
    label_ko: str,
    source_ko: str,
    confidence: Optional[float] = None,
    note: Optional[str] = None,
) -> RiskEvidence:
    """
    Construct a UI-friendly evidence item.

    label_ko  — Korean sentence shown in "근거 보기". Must NOT contain
                internal key names like "field:", "rule_id:", etc.
    source_ko — Korean provenance badge: "규칙 엔진", "그래프 분석",
                "입력 텍스트", "회사 정책", "시스템 분석"
    """
    return RiskEvidence(
        type="evidence",
        ref={"id": id},
        label=label_ko,
        source=source_ko,
        confidence=confidence,
        note=note,
    )


# ---------------------------------------------------------------------------
# Registry evidence builder — fetches internal policy/strategy/budget sources
# ---------------------------------------------------------------------------

def _fetch_registry_evidence(
    company_id: Optional[str],
    rule_ids: list[str] = (),
    goal_ids: list[str] = (),
    budget_source_ids: list[str] = (),
) -> list[RiskEvidence]:
    """
    Look up internal evidence registry and return RiskEvidence items for the
    given rule/goal/budget source IDs.

    Non-fatal: returns [] if company_id is absent, registry is missing, or any
    lookup fails.  Evidence items use source_ko="내부 정책" to distinguish
    registry-backed items from generic signal evidence.
    """
    if not company_id:
        return []
    result: list[RiskEvidence] = []
    try:
        from app.services import evidence_registry_service as ers

        for rid in rule_ids:
            ev = ers.get_policy_evidence(company_id, rid)
            if ev:
                result.append(_make_evidence(
                    id=f"registry_policy_{rid.lower()}",
                    label_ko=(ev.get("citationKo") or ev.get("summaryKo") or "")[:120],
                    source_ko="내부 정책",
                    note=ev.get("documentNameKo"),
                ))

        for gid in goal_ids:
            ev = ers.get_strategy_evidence(company_id, gid)
            if ev:
                result.append(_make_evidence(
                    id=f"registry_strategy_{gid.lower()}",
                    label_ko=(ev.get("citationKo") or ev.get("summaryKo") or "")[:120],
                    source_ko="내부 전략 문서",
                    note=ev.get("documentNameKo"),
                ))

        for bid in budget_source_ids:
            evs = ers.get_budget_evidence(company_id, bid)
            if evs:
                b = evs[0]
                result.append(_make_evidence(
                    id=f"registry_budget_{bid.lower()}",
                    label_ko=(b.get("summaryKo") or "")[:120],
                    source_ko="내부 예산 문서",
                    note=b.get("documentNameKo"),
                ))
    except Exception as _e:
        logger.debug(f"[risk_scoring] registry evidence lookup failed (non-fatal): {_e}")
    return result


# ---------------------------------------------------------------------------
# Summary label builder (per-dimension, data-driven — no scenario text)
# ---------------------------------------------------------------------------

def _build_summary_label(
    dimension_key: str,
    signals: list[RiskSignal],
    band: str,
) -> str:
    """
    Produce a one-line Korean 핵심 근거 from computed signal values.
    Branches on dimension_key (structural enum), not on scenario text.
    All inserted values come from the already-computed signals.
    """
    band_ko = _BAND_KO.get(band, band)

    if dimension_key == "financial":
        overspend = next((s for s in signals if s.id == "OVERSPEND_RATIO"), None)
        if overspend and overspend.value >= 1.0:
            return (
                f"핵심 근거: 요청 금액이 잔여 예산의 {overspend.value:.1f}배로 "
                f"초과 — 재무 위험 {band_ko}"
            )
        threshold = next((s for s in signals if s.id == "THRESHOLD_BREACH"), None)
        if threshold:
            return f"핵심 근거: 지출 금액이 회사 예산 기준 초과 — 재무 위험 {band_ko}"
        return f"핵심 근거: 재무 위험 수준 {band_ko}"

    if dimension_key == "compliance":
        has_pii = any(s.id == "PII_DETECTED" for s in signals)
        anon_missing = any(s.id == "ANONYMIZATION_MISSING" for s in signals)
        if has_pii and anon_missing:
            return (
                "핵심 근거: 개인정보(PII/PHI) 포함 및 비식별화 조치 미확인 "
                f"— 컴플라이언스 위험 {band_ko}"
            )
        if has_pii:
            return f"핵심 근거: 개인정보(PII/PHI) 처리 포함 — 컴플라이언스 검토 필요"
        return f"핵심 근거: 규정 준수 위험 수준 {band_ko}"

    if dimension_key == "strategic":
        conflict = next((s for s in signals if s.id == "GOAL_CONFLICT"), None)
        no_mapping = any(s.id == "NO_GOAL_MAPPING" for s in signals)
        if conflict and conflict.value > 0:
            n = int(conflict.value)
            return f"핵심 근거: {n}개 전략 목표와 충돌 확인 — 전략 위험 {band_ko}"
        if no_mapping:
            return "핵심 근거: 전략 목표 연결 정보 부족 — 중간 수준 위험으로 처리"
        return f"핵심 근거: 전략 정합성 위험 수준 {band_ko}"

    if dimension_key == "procurement":
        storage = next((s for s in signals if s.id == "STORAGE_UTILIZATION"), None)
        in_transit = next((s for s in signals if s.id == "IN_TRANSIT_OVERLAP"), None)
        demand = next((s for s in signals if s.id == "DEMAND_UNCERTAINTY"), None)
        if storage and storage.value >= 0.80:
            pct = int(storage.value * 100)
            return (
                f"핵심 근거: 창고 보관 용량 {pct}% 사용 중"
                + (" + 배송 중 주문 중복" if in_transit else "")
                + f" — 구매·조달 위험 {band_ko}"
            )
        if demand:
            return f"핵심 근거: 수요 예측 불확실성 확인 — 구매·조달 위험 {band_ko}"
        return f"핵심 근거: 구매·조달 위험 수준 {band_ko}"

    return f"핵심 근거: 위험 수준 {band_ko}"


# ---------------------------------------------------------------------------
# Signal summarizer — enforces output contract
# ---------------------------------------------------------------------------

def _summarize_dimension_evidence(
    dimension_key: str,
    raw_signals: list[RiskSignal],
    band: str,
) -> list[RiskSignal]:
    """
    Transform raw signals into the final UI-ready list:
      [0]   SUMMARY signal (Korean 핵심 근거, severity = band)
      [1..3] detail signals sorted by severity desc → value desc → id asc

    Each detail signal is pruned to max 2 evidence items.
    Output length: 1 (summary only) to 4 (summary + 3 details).
    """
    # Build SUMMARY signal
    summary_label = _build_summary_label(dimension_key, raw_signals, band)
    summary_ev = _make_evidence(
        id="summary_source",
        label_ko=_DIM_SUMMARY_SOURCE_KO.get(dimension_key, "종합 분석"),
        source_ko=_DIM_SUMMARY_SOURCE_KO.get(dimension_key, "시스템 분석"),
    )
    summary_signal = RiskSignal(
        id="SUMMARY",
        label=summary_label,
        value=0.0,
        severity=band,
        evidence=[summary_ev],
    )

    # Sort non-summary detail signals
    details = [s for s in raw_signals if s.id != "SUMMARY"]
    sorted_details = sorted(
        details,
        key=lambda s: (
            _SEVERITY_ORDER.get(s.severity, 4),
            -(s.value or 0.0),
            s.id,
        ),
    )

    # Prune each detail to max 2 evidence items
    pruned_details: list[RiskSignal] = []
    for s in sorted_details[:3]:
        pruned_details.append(RiskSignal(
            id=s.id,
            label=s.label,
            value=s.value,
            unit=s.unit,
            severity=s.severity,
            evidence=s.evidence[:2],
        ))

    return [summary_signal] + pruned_details


# ---------------------------------------------------------------------------
# Procurement registry data loader
# ---------------------------------------------------------------------------

def _fetch_procurement_registry_data(company_id: Optional[str]) -> Optional[dict]:
    """
    Load procurement constants from all sources listed in procurementTriggers.

    Returns a flat dict keyed by sourceId → constants dict, e.g.:
      {
        "BS_INVENTORY_STATUS": {"on_hand_units": 200, "in_transit_units": 500, ...},
        "SALES_REVENUE_PROJECTION": {"monthly_revenue_growth_rate_pct": 5, ...},
        ...
      }

    Returns None if:
    - company_id is absent
    - no evidence registry exists for the company
    - no procurementTriggers are configured
    All failures are non-fatal (logged at DEBUG level).
    """
    if not company_id:
        return None
    try:
        from app.services import evidence_registry_service as ers
        registry = ers.load_company_registry(company_id)
        triggers = registry.get("index", {}).get("procurementTriggers", [])
        if not triggers:
            return None

        budget_entries = registry.get("budget", {}).get("budgetSources", [])
        sales_entries = registry.get("sales", {}).get("salesSources", [])
        result: dict[str, dict] = {}

        for trigger in triggers:
            for sid in trigger.get("budgetSourceIds", []):
                if sid not in result:
                    entry = next((e for e in budget_entries if e.get("sourceId") == sid), None)
                    if entry:
                        result[sid] = entry.get("constants", {})
            for sid in trigger.get("salesSourceIds", []):
                if sid not in result:
                    entry = next((e for e in sales_entries if e.get("sourceId") == sid), None)
                    if entry:
                        result[sid] = entry.get("constants", {})

        return result if result else None
    except Exception as _e:
        logger.debug(f"[risk_scoring] _fetch_procurement_registry_data failed (non-fatal): {_e}")
        return None


# ---------------------------------------------------------------------------
# Main service
# ---------------------------------------------------------------------------


class RiskScoringService:
    """
    Generic risk scoring engine.

    Usage::

        service = RiskScoringService()
        result  = service.score(
            decision_payload   = record.decision,      # dict
            company_payload    = company_data,         # dict (raw company JSON)
            governance_result  = record.governance,    # dict
            graph_payload      = record.graph_payload, # dict | None
        )

    Returns a RiskScoringResult which can be serialised with .to_dict().
    """

    def score(
        self,
        decision_payload: dict,
        company_payload: dict,
        governance_result: dict,
        graph_payload: Optional[dict],
        risk_semantics: Optional[dict] = None,
        company_id: Optional[str] = None,
    ) -> RiskScoringResult:
        """
        Compute risk score.

        risk_semantics (optional) — pre-parsed RiskSemantics.model_dump() from
        the optional LLM semantics step. Used ONLY as a fallback when structural
        data (graph edges, extractor fields) are absent. Never overrides
        deterministic inputs.
        """
        dp = decision_payload or {}
        cp = company_payload or {}
        gv = governance_result or {}
        gr = graph_payload or {}
        rs = risk_semantics or {}

        triggered_rules: list[dict] = gv.get("triggered_rules", [])

        dims: list[RiskDimension] = []
        confidence_deductions = 0

        fin_dim, fin_ded = self._financial(dp, cp, triggered_rules, company_id=company_id)
        if fin_dim is not None:
            dims.append(fin_dim)
            confidence_deductions += fin_ded

        comp_dim, comp_ded = self._compliance(dp, cp, triggered_rules, rs, company_id=company_id)
        if comp_dim is not None:
            dims.append(comp_dim)
            confidence_deductions += comp_ded

        strat_dim, strat_ded = self._strategic(dp, cp, triggered_rules, gr, rs, company_id=company_id)
        if strat_dim is not None:
            dims.append(strat_dim)
            confidence_deductions += strat_ded

        proc_dim, proc_ded = self._procurement(dp, triggered_rules, company_id=company_id)
        if proc_dim is not None:
            dims.append(proc_dim)
            confidence_deductions += proc_ded

        aggregate = self._aggregate(dims, cp, confidence_deductions)

        return RiskScoringResult(aggregate=aggregate, dimensions=dims)

    # -----------------------------------------------------------------------
    # A) Financial Risk
    # -----------------------------------------------------------------------

    def _financial(
        self,
        dp: dict,
        cp: dict,
        triggered_rules: list[dict],
        company_id: Optional[str] = None,
    ) -> tuple[Optional[RiskDimension], int]:
        cost: Optional[float] = dp.get("cost")
        if cost is None:
            return None, 0

        risk_tol = cp.get("risk_tolerance", {}).get("financial", {})
        unbudgeted_thresh = risk_tol.get("unbudgeted_spend_threshold") or 50_000_000
        high_thresh       = risk_tol.get("high_cost_threshold") or 250_000_000
        critical_thresh   = risk_tol.get("critical_cost_threshold") or 1_000_000_000

        raw_signals: list[RiskSignal] = []
        confidence_deductions = 0

        # ── OVERSPEND_RATIO: only when remaining_budget available ──
        remaining_budget: Optional[float] = dp.get("remaining_budget")
        base_from_overspend = 0.0

        if remaining_budget and remaining_budget > 0:
            overspend_ratio = cost / remaining_budget
            # Severity from ratio magnitude
            if overspend_ratio >= 10:
                overspend_sev = "CRITICAL"
            elif overspend_ratio >= 5:
                overspend_sev = "HIGH"
            elif overspend_ratio >= 2:
                overspend_sev = "MEDIUM"
            else:
                overspend_sev = "LOW"

            raw_signals.append(RiskSignal(
                id="OVERSPEND_RATIO",
                label=_signal_label("OVERSPEND_RATIO"),
                value=round(overspend_ratio, 2),
                unit="x",
                severity=overspend_sev,
                evidence=[
                    _make_evidence(
                        id="overspend_ratio_calc",
                        label_ko="요청 금액과 잔여 예산을 비교하여 초과 배수 산출",
                        source_ko=_signal_source("OVERSPEND_RATIO"),
                    )
                ],
            ))
            base_from_overspend = _clamp(
                math.log1p(overspend_ratio) / math.log1p(10) * 60, 0, 60
            )
        else:
            confidence_deductions += 1  # no budget baseline

        # ── THRESHOLD_BREACH: always when cost data present ──
        threshold_ratio = cost / unbudgeted_thresh
        if cost > critical_thresh:
            thresh_sev = "CRITICAL"
            threshold_bonus = 25
        elif cost > high_thresh:
            thresh_sev = "HIGH"
            threshold_bonus = 15
        elif cost > unbudgeted_thresh:
            thresh_sev = "MEDIUM"
            threshold_bonus = 10
        else:
            thresh_sev = "LOW"
            threshold_bonus = 0

        raw_signals.append(RiskSignal(
            id="THRESHOLD_BREACH",
            label=_signal_label("THRESHOLD_BREACH"),
            value=round(threshold_ratio, 2),
            unit="x",
            severity=thresh_sev,
            evidence=[
                _make_evidence(
                    id="threshold_policy",
                    label_ko="회사 재무 정책 기준과 비교하여 초과 여부 판단",
                    source_ko=_signal_source("THRESHOLD_BREACH"),
                )
            ],
        ))

        # ── FIN_RULE_TRIGGERED: triggered financial governance rules ──
        fin_triggered = [
            r for r in triggered_rules
            if (r.get("rule_type") or r.get("type") or "").lower() in
               {"financial", "capital_expenditure"}
            and r.get("status", "").upper() == "TRIGGERED"
        ]
        rule_bonus = 10 if fin_triggered else 0

        if fin_triggered:
            # Aggregate rule severity from first triggered rule
            first_rule = fin_triggered[0]
            rsev = ""
            if isinstance(first_rule.get("consequence"), dict):
                rsev = (first_rule["consequence"].get("severity") or "").upper()
            rule_sev = rsev if rsev in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "HIGH"

            rule_name = first_rule.get("name") or "재무 승인 규칙"
            raw_signals.append(RiskSignal(
                id="FIN_RULE_TRIGGERED",
                label=_signal_label("FIN_RULE_TRIGGERED"),
                value=float(len(fin_triggered)),
                severity=rule_sev,
                evidence=[
                    _make_evidence(
                        id="fin_rule_engine",
                        label_ko=f"거버넌스 규칙 발동: {rule_name}",
                        source_ko=_signal_source("FIN_RULE_TRIGGERED"),
                    )
                ],
            ))

        # ── Compute final score ──
        if remaining_budget and remaining_budget > 0:
            base = base_from_overspend
        else:
            base = _clamp(
                math.log1p(threshold_ratio) / math.log1p(10) * 45, 0, 45
            )

        score = int(_clamp(base + threshold_bonus + rule_bonus, 0, 100))
        band = _band(score)

        # Apply summarizer
        final_signals = _summarize_dimension_evidence("financial", raw_signals, band)

        # Registry evidence: triggered financial rule policies + spend authority source
        fin_rule_ids = [r.get("rule_id") for r in fin_triggered if r.get("rule_id")]
        budget_sources = ["BS_SPEND_AUTHORITY"] if cost > unbudgeted_thresh else []
        dim_registry_ev = _fetch_registry_evidence(
            company_id,
            rule_ids=fin_rule_ids[:2],
            budget_source_ids=budget_sources,
        )

        return RiskDimension(
            id="financial",
            label="재무 위험",
            score=score,
            band=band,
            signals=final_signals,
            evidence=dim_registry_ev,
        ), confidence_deductions

    # -----------------------------------------------------------------------
    # B) Compliance / Privacy Risk
    # -----------------------------------------------------------------------

    def _compliance(
        self,
        dp: dict,
        cp: dict,
        triggered_rules: list[dict],
        rs: dict = None,
        company_id: Optional[str] = None,
    ) -> tuple[Optional[RiskDimension], int]:
        rs = rs or {}
        sem_facts: dict = rs.get("compliance_facts") or {}

        # Deterministic extractor values take priority.
        # Semantics fill in only when extractor returned None/absent.
        uses_pii_raw = dp.get("uses_pii")
        uses_pii: bool = bool(
            uses_pii_raw
            if uses_pii_raw is not None
            else sem_facts.get("uses_pii")
        )

        involves_compliance_raw = dp.get("involves_compliance_risk")
        involves_compliance: bool = bool(
            involves_compliance_raw
            if involves_compliance_raw is not None
            else sem_facts.get("involves_compliance_risk")
        )

        # Track if semantics provided the PII signal (for evidence labelling)
        _pii_from_semantics: bool = (
            uses_pii_raw is None
            and uses_pii
            and sem_facts.get("uses_pii") is True
        )

        compliance_rule_types = {"compliance", "privacy", "hipaa", "gdpr", "phi"}
        has_compliance_rules = any(
            (r.get("rule_type") or r.get("type") or "").lower() in compliance_rule_types
            for r in triggered_rules
            if r.get("status", "").upper() == "TRIGGERED"
        )

        if not uses_pii and not involves_compliance and not has_compliance_rules:
            return None, 0

        raw_signals: list[RiskSignal] = []
        confidence_deductions = 0
        score = 0

        # ── PII_DETECTED ──
        if uses_pii:
            score += 60
            if _pii_from_semantics:
                # Semantics filled the gap — use its Korean rationale in evidence
                sem_rationale = _first_matching_rationale(rs, direction_filter=None, fallback="LLM 분석에서 개인정보 처리 관련성이 도출됨")
                pii_ev = _make_evidence(
                    id="pii_semantics",
                    label_ko=sem_rationale,
                    source_ko="LLM(구조화)",
                    confidence=rs.get("global_confidence"),
                )
            else:
                pii_ev = _make_evidence(
                    id="pii_field",
                    label_ko="의사결정 내용에 개인정보 처리 여부가 명시됨",
                    source_ko=_signal_source("PII_DETECTED"),
                )
            raw_signals.append(RiskSignal(
                id="PII_DETECTED",
                label=_signal_label("PII_DETECTED"),
                value=1.0,
                unit="bool",
                severity="HIGH",
                evidence=[pii_ev],
            ))
        else:
            confidence_deductions += 1  # only indirect signals

        # ── compliance risk flag ──
        if involves_compliance:
            score += 10

        # ── Data-type markers (ANONYMIZATION_MISSING, CROSS_BORDER_TRANSFER) ──
        anonymization_missing = dp.get("anonymization_missing") is True
        cross_border = bool(dp.get("cross_border_transfer"))

        if anonymization_missing:
            score += 10
            raw_signals.append(RiskSignal(
                id="ANONYMIZATION_MISSING",
                label=_signal_label("ANONYMIZATION_MISSING"),
                value=1.0,
                unit="bool",
                severity="HIGH",
                evidence=[
                    _make_evidence(
                        id="anon_missing",
                        label_ko="비식별화 처리 여부가 확인되지 않음",
                        source_ko=_signal_source("ANONYMIZATION_MISSING"),
                    )
                ],
            ))

        if cross_border:
            score += 5
            raw_signals.append(RiskSignal(
                id="CROSS_BORDER_TRANSFER",
                label=_signal_label("CROSS_BORDER_TRANSFER"),
                value=1.0,
                unit="bool",
                severity="MEDIUM",
                evidence=[
                    _make_evidence(
                        id="cross_border",
                        label_ko="국경 간 데이터 이전이 수반될 가능성 있음",
                        source_ko=_signal_source("CROSS_BORDER_TRANSFER"),
                    )
                ],
            ))

        # ── COMPLIANCE_RULE_TRIGGERED ──
        crit_triggered = [
            r for r in triggered_rules
            if (r.get("rule_type") or r.get("type") or "").lower() in compliance_rule_types
            and r.get("status", "").upper() == "TRIGGERED"
        ]
        for r in crit_triggered:
            sev = ""
            if isinstance(r.get("consequence"), dict):
                sev = (r["consequence"].get("severity") or "").lower()
            elif isinstance(r.get("severity"), str):
                sev = r["severity"].lower()

            sev_upper = sev.upper() if sev.upper() in ("CRITICAL", "HIGH", "MEDIUM", "LOW") else "HIGH"
            if sev_upper == "CRITICAL":
                score += 20
            elif sev_upper == "HIGH":
                score += 10

            rule_name = r.get("name") or "개인정보 보호 규칙"
            raw_signals.append(RiskSignal(
                id="COMPLIANCE_RULE_TRIGGERED",
                label=_signal_label("COMPLIANCE_RULE_TRIGGERED"),
                value=1.0,
                severity=sev_upper,
                evidence=[
                    _make_evidence(
                        id="compliance_rule_engine",
                        label_ko=f"거버넌스 규칙 발동: {rule_name}",
                        source_ko=_signal_source("COMPLIANCE_RULE_TRIGGERED"),
                    )
                ],
            ))

        score = int(_clamp(score, 0, 100))
        band = _band(score)

        final_signals = _summarize_dimension_evidence("compliance", raw_signals, band)

        # Registry evidence: compliance/privacy rule policies (R6, R2, etc.)
        comp_rule_ids = [
            r.get("rule_id") for r in crit_triggered if r.get("rule_id")
        ]
        if uses_pii:
            # Include any PII/privacy rules from triggered list (regardless of status)
            pii_rule_ids_from_triggered = [
                r.get("rule_id") for r in triggered_rules
                if r.get("rule_id")
                and (r.get("rule_type") or r.get("type") or "").lower() == "privacy"
            ]
            comp_rule_ids = list(dict.fromkeys(comp_rule_ids + pii_rule_ids_from_triggered))
            # Fallback: if uses_pii=True but no privacy rule appeared in triggered_rules
            # (e.g. semantics-inferred), find the privacy rule from company config
            if not pii_rule_ids_from_triggered and cp:
                fallback_ids = [
                    r.get("rule_id") for r in cp.get("governance_rules", [])
                    if (r.get("type") or "").lower() == "privacy" and r.get("rule_id")
                ]
                comp_rule_ids = list(dict.fromkeys(comp_rule_ids + fallback_ids[:1]))
        if involves_compliance:
            # Include any compliance rules from triggered list
            comp_rule_ids_from_triggered = [
                r.get("rule_id") for r in triggered_rules
                if r.get("rule_id")
                and (r.get("rule_type") or r.get("type") or "").lower() == "compliance"
            ]
            comp_rule_ids = list(dict.fromkeys(comp_rule_ids + comp_rule_ids_from_triggered))
            # Fallback: if involves_compliance=True but no compliance rule in triggered_rules
            # (e.g. semantics-inferred), find the compliance rule from company config
            if not comp_rule_ids_from_triggered and cp:
                fallback_ids = [
                    r.get("rule_id") for r in cp.get("governance_rules", [])
                    if (r.get("type") or "").lower() == "compliance" and r.get("rule_id")
                ]
                comp_rule_ids = list(dict.fromkeys(comp_rule_ids + fallback_ids[:1]))
        dim_registry_ev = _fetch_registry_evidence(
            company_id,
            rule_ids=comp_rule_ids[:2],
        )

        return RiskDimension(
            id="compliance",
            label="컴플라이언스 / 개인정보 위험",
            score=score,
            band=band,
            signals=final_signals,
            evidence=dim_registry_ev,
            source_rule_ids=comp_rule_ids[:2],
        ), confidence_deductions

    # -----------------------------------------------------------------------
    # C) Strategic Alignment / Conflict
    # -----------------------------------------------------------------------

    def _strategic(
        self,
        dp: dict,
        cp: dict,
        triggered_rules: list[dict],
        gr: dict,
        rs: dict = None,
        company_id: Optional[str] = None,
    ) -> tuple[Optional[RiskDimension], int]:
        company_goals: list[dict] = cp.get("strategic_goals", [])
        raw_signals: list[RiskSignal] = []
        confidence_deductions = 0

        edges: list[dict] = gr.get("edges", [])
        nodes: list[dict] = gr.get("nodes", [])

        node_by_id: dict[str, dict] = {}
        for n in nodes:
            nid = n.get("id") or n.get("node_id", "")
            if nid:
                node_by_id[nid] = n

        _SUPPORT_RELATIONS  = {"supports_goal", "aligned_to", "has_goal", "supports", "achieves"}
        _CONFLICT_RELATIONS = {"conflicts_with", "strategic_conflict", "opposes", "contradicts"}

        supported_goal_ids: set[str] = set()
        conflicted_goal_ids: set[str] = set()

        # Track graph edge evidence per relation type (avoid dumping all edges)
        support_edge_ev: list[RiskEvidence] = []
        conflict_edge_ev: list[RiskEvidence] = []

        for edge in edges:
            rel = (
                edge.get("relation") or
                edge.get("predicate") or
                edge.get("type") or ""
            ).lower().replace(" ", "_")

            tgt = edge.get("target") or edge.get("to_node") or edge.get("to") or ""
            tgt_node = node_by_id.get(tgt, {})
            tgt_label = tgt_node.get("label") or tgt_node.get("name") or tgt

            if rel in _SUPPORT_RELATIONS:
                supported_goal_ids.add(tgt)
                if len(support_edge_ev) < 2:
                    support_edge_ev.append(_make_evidence(
                        id=f"graph_support_{tgt}",
                        label_ko=f"그래프 분석: '{tgt_label}' 목표와 연계 관계 확인",
                        source_ko="그래프 분석",
                    ))
            elif rel in _CONFLICT_RELATIONS:
                conflicted_goal_ids.add(tgt)
                if len(conflict_edge_ev) < 2:
                    conflict_edge_ev.append(_make_evidence(
                        id=f"graph_conflict_{tgt}",
                        label_ko=f"그래프 분석: '{tgt_label}' 목표와 충돌 관계 확인",
                        source_ko="그래프 분석",
                    ))

        # ── Decision goals → word-intersection match to company goals ──
        # NOTE: word-intersection is a structural heuristic, not a scenario rule.
        # TODO(dev_rules): replace with LLM structured classification for precision.
        decision_goals: list[dict] = dp.get("goals", [])
        for dg in decision_goals:
            dg_text = (dg.get("description") or dg.get("name") or "").lower()
            for cg in company_goals:
                cg_name = cg.get("name", "").lower()
                cg_desc = cg.get("description", "").lower()
                dg_words = set(w for w in dg_text.split() if len(w) > 3)
                cg_words = set(w for w in (cg_name + " " + cg_desc).split() if len(w) > 3)
                if dg_words & cg_words:
                    supported_goal_ids.add(cg.get("goal_id", ""))

        # ── Semantics fallback: use goal_impacts when graph has no edges ──
        # Applied ONLY when both graph edges AND word-intersection produced nothing.
        # Semantics never overrides structural data; it fills the gap.
        rs = rs or {}
        sem_goal_impacts: list[dict] = rs.get("goal_impacts") or []
        _sem_support_ev: list[RiskEvidence] = []   # populated below if used
        _sem_conflict_ev: list[RiskEvidence] = []  # populated below if used

        if sem_goal_impacts and not supported_goal_ids and not conflicted_goal_ids:
            for impact in sem_goal_impacts:
                gid       = impact.get("goal_id", "")
                direction = impact.get("direction", "neutral")
                rationale = impact.get("rationale_ko", "")
                conf      = impact.get("confidence", 0.5)

                if direction == "support":
                    supported_goal_ids.add(gid)
                    if len(_sem_support_ev) < 2:
                        _sem_support_ev.append(_make_evidence(
                            id=f"sem_support_{gid}",
                            label_ko=rationale or f"LLM 분석: '{gid}' 목표와 기여 관계",
                            source_ko="LLM(구조화)",
                            confidence=conf,
                        ))
                elif direction == "conflict":
                    conflicted_goal_ids.add(gid)
                    if len(_sem_conflict_ev) < 2:
                        _sem_conflict_ev.append(_make_evidence(
                            id=f"sem_conflict_{gid}",
                            label_ko=rationale or f"LLM 분석: '{gid}' 목표와 충돌 관계",
                            source_ko="LLM(구조화)",
                            confidence=conf,
                        ))

            if _sem_support_ev or _sem_conflict_ev:
                logger.debug(
                    f"_strategic: semantics fallback applied — "
                    f"{len(supported_goal_ids)} supports, {len(conflicted_goal_ids)} conflicts"
                )

        # ── Triggered strategic rules ──
        strat_triggered = [
            r for r in triggered_rules
            if (r.get("rule_type") or r.get("type") or "").lower() == "strategic"
            and r.get("status", "").upper() == "TRIGGERED"
        ]

        # ── Compute scores ──
        goal_by_id: dict[str, dict] = {
            g.get("goal_id", ""): g for g in company_goals
        }

        supports_score = sum(
            _priority_weight(goal_by_id[gid]["priority"]) if (gid in goal_by_id) else 5
            for gid in supported_goal_ids
        )
        conflict_score = sum(
            _priority_weight(goal_by_id[gid]["priority"]) if (gid in goal_by_id) else 10
            for gid in conflicted_goal_ids
        )
        conflict_score += len(strat_triggered) * 8

        no_goal_mapping = (
            not supported_goal_ids and not conflicted_goal_ids and not strat_triggered
        )

        if no_goal_mapping:
            confidence_deductions += 1
            raw_signals.append(RiskSignal(
                id="NO_GOAL_MAPPING",
                label=_signal_label("NO_GOAL_MAPPING"),
                value=0.0,
                severity="MEDIUM",
                evidence=[
                    _make_evidence(
                        id="no_goal_mapping",
                        label_ko="그래프 및 거버넌스 결과에서 목표 연결 정보를 찾을 수 없음",
                        source_ko="시스템 분석",
                        note="전략 정합성 수치화 불가 — 중간 기준값 적용",
                    )
                ],
            ))
            final_signals = _summarize_dimension_evidence("strategic", raw_signals, "MEDIUM")
            return RiskDimension(
                id="strategic",
                label="전략 정합성 / 충돌",
                score=50,
                band="MEDIUM",
                signals=final_signals,
                evidence=[],
            ), confidence_deductions  # no goal IDs to look up

        # ── Build signals ──
        if conflicted_goal_ids:
            # Evidence priority: graph edges → semantics → generic fallback
            conflict_ev = (
                conflict_edge_ev[:2]
                or _sem_conflict_ev[:2]
                or [_make_evidence(
                    id="conflict_governance",
                    label_ko="거버넌스 규칙 분석을 통해 목표 충돌 가능성 도출",
                    source_ko="규칙 엔진",
                )]
            )
            raw_signals.append(RiskSignal(
                id="GOAL_CONFLICT",
                label=_signal_label("GOAL_CONFLICT"),
                value=float(len(conflicted_goal_ids)),
                severity="HIGH" if conflict_score >= 25 else "MEDIUM",
                evidence=conflict_ev,
            ))

        if supported_goal_ids:
            # Evidence priority: graph edges → semantics → generic fallback
            support_ev = (
                support_edge_ev[:2]
                or _sem_support_ev[:2]
                or [_make_evidence(
                    id="support_graph",
                    label_ko="그래프 분석을 통해 전략 목표 기여 관계 확인",
                    source_ko="그래프 분석",
                )]
            )
            raw_signals.append(RiskSignal(
                id="GOAL_SUPPORT",
                label=_signal_label("GOAL_SUPPORT"),
                value=float(len(supported_goal_ids)),
                severity="LOW",
                evidence=support_ev,
            ))

        if strat_triggered:
            rule_name = strat_triggered[0].get("name") or "전략 검토 규칙"
            raw_signals.append(RiskSignal(
                id="STRAT_RULE_TRIGGERED",
                label=_signal_label("STRAT_RULE_TRIGGERED"),
                value=float(len(strat_triggered)),
                severity="HIGH",
                evidence=[
                    _make_evidence(
                        id="strat_rule_engine",
                        label_ko=f"거버넌스 규칙 발동: {rule_name}",
                        source_ko=_signal_source("STRAT_RULE_TRIGGERED"),
                    )
                ],
            ))

        # ── Score ──
        conflict_capped  = min(conflict_score, 100)
        supports_capped  = min(supports_score, 100)
        net = conflict_capped - supports_capped
        dim_score = int(_clamp((net + 100) / 2, 0, 100))
        band = _band(dim_score)

        final_signals = _summarize_dimension_evidence("strategic", raw_signals, band)

        # ── KPI impact estimate ──
        kpi_estimate = self._kpi_impact_estimate(
            dp=dp,
            cp=cp,
            supported_goal_ids=supported_goal_ids,
            conflicted_goal_ids=conflicted_goal_ids,
            goal_by_id=goal_by_id,
            rs=rs,
        )

        # Registry evidence: goal sources for all detected goal IDs (conflict + support)
        all_detected_goal_ids = list(
            (conflicted_goal_ids | supported_goal_ids) & {g.get("goal_id") for g in company_goals}
        )
        strat_rule_ids = [r.get("rule_id") for r in strat_triggered if r.get("rule_id")]
        dim_registry_ev = _fetch_registry_evidence(
            company_id,
            rule_ids=strat_rule_ids[:1],
            goal_ids=all_detected_goal_ids[:2],
        )

        return RiskDimension(
            id="strategic",
            label="전략 정합성 / 충돌",
            score=dim_score,
            band=band,
            signals=final_signals,
            evidence=dim_registry_ev,
            kpi_impact_estimate=kpi_estimate,
        ), confidence_deductions

    # -----------------------------------------------------------------------
    # D) Procurement / Inventory Risk
    # -----------------------------------------------------------------------

    def _procurement(
        self,
        dp: dict,
        triggered_rules: list[dict],
        company_id: Optional[str] = None,
    ) -> tuple[Optional[RiskDimension], int]:
        """
        Procurement risk dimension — fires only when the company registry has
        procurementTriggers configured (e.g. sool_sool_icecream).

        Data sources (registry-driven, no hardcoded source IDs in scoring logic):
          All constants are read from whichever sources appear in procurementTriggers.
          The scoring logic uses well-known field names (on_hand_units, etc.) that
          are part of the registry data schema, not scenario-specific branches.

        Signals:
          STORAGE_UTILIZATION — (on_hand + in_transit) / capacity
          IN_TRANSIT_OVERLAP  — existing in-transit order adds duplication risk
          DEMAND_UNCERTAINTY  — demand forecast reliability + post-promo drop risk
        """
        proc_data = _fetch_procurement_registry_data(company_id)
        if not proc_data:
            return None, 0

        # Flatten all constants from all loaded procurement sources into one dict
        all_constants: dict = {}
        for constants in proc_data.values():
            all_constants.update(constants)

        raw_signals: list[RiskSignal] = []
        score = 0
        confidence_deductions = 0

        # ── STORAGE_UTILIZATION ───────────────────────────────────────────────
        on_hand    = all_constants.get("on_hand_units")
        in_transit = all_constants.get("in_transit_units")
        capacity   = all_constants.get("storage_capacity_units")

        if on_hand is not None and in_transit is not None and capacity and capacity > 0:
            utilization = (on_hand + in_transit) / capacity
            if utilization >= 0.95:
                storage_sev = "CRITICAL"
                storage_bonus = 45
            elif utilization >= 0.80:
                storage_sev = "HIGH"
                storage_bonus = 30
            elif utilization >= 0.60:
                storage_sev = "MEDIUM"
                storage_bonus = 15
            else:
                storage_sev = "LOW"
                storage_bonus = 0

            score += storage_bonus
            raw_signals.append(RiskSignal(
                id="STORAGE_UTILIZATION",
                label=_signal_label("STORAGE_UTILIZATION"),
                value=round(utilization, 3),
                unit="ratio",
                severity=storage_sev,
                evidence=[
                    _make_evidence(
                        id="storage_registry",
                        label_ko=(
                            f"현재 재고 {int(on_hand)}개 + 배송 중 {int(in_transit)}개 = "
                            f"{int(on_hand + in_transit)}개로 창고 용량 "
                            f"({int(capacity)}개)의 {utilization*100:.0f}% 사용 중"
                        ),
                        source_ko=_signal_source("STORAGE_UTILIZATION"),
                    )
                ],
            ))
        else:
            confidence_deductions += 1

        # ── IN_TRANSIT_OVERLAP ────────────────────────────────────────────────
        # Check governance triggered_rules for procurement-type (e.g. R2) or
        # read directly from registry constant.
        in_transit_val = all_constants.get("in_transit_units", 0)
        proc_rule_types = {"procurement", "inventory"}
        proc_triggered = [
            r for r in triggered_rules
            if (r.get("rule_type") or r.get("type") or "").lower() in proc_rule_types
            and r.get("status", "").upper() == "TRIGGERED"
        ]

        if in_transit_val and in_transit_val > 0:
            score += 15
            rule_note = f" (거버넌스 규칙 {proc_triggered[0].get('rule_id')} 발동)" if proc_triggered else ""
            raw_signals.append(RiskSignal(
                id="IN_TRANSIT_OVERLAP",
                label=_signal_label("IN_TRANSIT_OVERLAP"),
                value=float(in_transit_val),
                unit="units",
                severity="MEDIUM",
                evidence=[
                    _make_evidence(
                        id="in_transit_registry",
                        label_ko=f"동일 품목 {int(in_transit_val)}개 현재 배송 중{rule_note} — 중복 주문 위험",
                        source_ko=_signal_source("IN_TRANSIT_OVERLAP"),
                    )
                ],
            ))

        # ── DEMAND_UNCERTAINTY ────────────────────────────────────────────────
        reliability     = all_constants.get("sns_forecast_reliability")  # "medium" | "high" | "low"
        growth_trend    = all_constants.get("growth_trend")              # "decelerating" | "accelerating" | "stable"
        promo_drop_pct  = all_constants.get("post_promotion_demand_drop_est_pct")
        promo_active    = all_constants.get("current_promotion_active", False)

        demand_score = 0
        demand_notes: list[str] = []

        _RELIABILITY_SCORES: dict[str, int] = {"low": 15, "medium": 8, "high": 0}
        _TREND_SCORES: dict[str, int] = {"decelerating": 8, "stable": 3, "accelerating": 0}

        if reliability:
            r_score = _RELIABILITY_SCORES.get(str(reliability).lower(), 0)
            demand_score += r_score
            if r_score > 0:
                demand_notes.append(f"SNS 판매 예측 신뢰도 '{reliability}'")

        if growth_trend:
            t_score = _TREND_SCORES.get(str(growth_trend).lower(), 0)
            demand_score += t_score
            if t_score > 0:
                demand_notes.append(f"매출 성장 추세 '{growth_trend}'")

        if promo_active and promo_drop_pct is not None:
            drop = float(promo_drop_pct)
            if drop >= 25:
                demand_score += 12
                demand_notes.append(f"프로모션 종료 후 수요 약 {int(drop)}% 감소 예상")
            elif drop >= 10:
                demand_score += 6

        if demand_score > 0:
            demand_sev = "HIGH" if demand_score >= 20 else "MEDIUM" if demand_score >= 10 else "LOW"
            score += demand_score
            raw_signals.append(RiskSignal(
                id="DEMAND_UNCERTAINTY",
                label=_signal_label("DEMAND_UNCERTAINTY"),
                value=float(demand_score),
                severity=demand_sev,
                evidence=[
                    _make_evidence(
                        id="demand_registry",
                        label_ko="; ".join(demand_notes) if demand_notes else "수요 예측 불확실 요인 감지",
                        source_ko=_signal_source("DEMAND_UNCERTAINTY"),
                    )
                ],
            ))
        elif reliability is None and growth_trend is None:
            confidence_deductions += 1

        if not raw_signals:
            return None, 0

        score = int(_clamp(score, 0, 100))
        band = _band(score)
        final_signals = _summarize_dimension_evidence("procurement", raw_signals, band)

        # Registry evidence: procurement rule policies
        proc_rule_ids = [r.get("rule_id") for r in proc_triggered if r.get("rule_id")]
        dim_registry_ev = _fetch_registry_evidence(
            company_id,
            rule_ids=proc_rule_ids[:2],
        )

        return RiskDimension(
            id="procurement",
            label="구매·조달 위험",
            score=score,
            band=band,
            signals=final_signals,
            evidence=dim_registry_ev,
            source_rule_ids=proc_rule_ids,
        ), confidence_deductions

    # -----------------------------------------------------------------------
    # KPI Impact Estimate (generic, best-effort)
    # -----------------------------------------------------------------------

    def _kpi_impact_estimate(
        self,
        dp: dict,
        cp: dict,
        supported_goal_ids: set[str],
        conflicted_goal_ids: set[str],
        goal_by_id: dict[str, dict],
        rs: dict = None,
    ) -> Optional[dict]:
        """
        Best-effort KPI impact estimate.
        Only produced when cost data + a matched cost-related goal exist.

        TODO(dev_rules §1): _COST_REDUCTION_KEYWORDS below is a semantic keyword
        list — a dev_rules violation.  Replace with LLM structured classification
        (GoalCategory Pydantic model) in a future iteration. The semantics fallback
        (rs.numeric_estimates) partially reduces this smell by providing an LLM-derived
        estimate when the keyword match misses.
        """
        rs = rs or {}
        cost: Optional[float] = dp.get("cost")
        if cost is None:
            return None

        _COST_REDUCTION_KEYWORDS = {
            "cost", "비용", "efficiency", "절감", "reduction", "savings",
            "budget", "operating", "운영", "spend",
        }

        target_goal: Optional[dict] = None
        for gid in list(supported_goal_ids) + list(conflicted_goal_ids):
            g = goal_by_id.get(gid)
            if not g:
                continue
            text = (g.get("name", "") + " " + g.get("description", "")).lower()
            if any(kw in text for kw in _COST_REDUCTION_KEYWORDS):
                target_goal = g
                break

        if target_goal is None:
            return None

        baseline_cost: Optional[float] = (
            cp.get("financials", {}).get("baseline_operating_cost")
            or dp.get("baseline_cost")
        )

        kpi_target_str: Optional[str] = None
        for kpi in target_goal.get("kpis", []):
            if isinstance(kpi, dict):
                kpi_name = kpi.get("name", "").lower()
                if any(kw in kpi_name for kw in _COST_REDUCTION_KEYWORDS):
                    kpi_target_str = kpi.get("target")
                    break

        if baseline_cost and baseline_cost > 0:
            pct_of_baseline = round(cost / baseline_cost * 100, 1)
            direction = "+" if cost > 0 else "-"
            return {
                "goal_id":               target_goal.get("goal_id"),
                "goal_name":             target_goal.get("name"),
                "kpi_target":            kpi_target_str,
                "estimated_impact_pct":  f"{direction}{pct_of_baseline}% vs baseline",
                "baseline_source":       "company_financials",
                "confidence":            "medium",
            }

        # ── Semantics fallback: use LLM numeric estimate as a note ──
        # Does NOT alter the formula — provides an enriched note field only.
        sem_numeric: dict = rs.get("numeric_estimates") or {}
        cost_delta = sem_numeric.get("cost_delta_pct")

        risk_tol = cp.get("risk_tolerance", {}).get("financial", {})
        unbudgeted = risk_tol.get("unbudgeted_spend_threshold")
        if unbudgeted and unbudgeted > 0:
            strain_pct = round(cost / unbudgeted * 100, 1)
            result: dict = {
                "goal_id":              target_goal.get("goal_id"),
                "goal_name":            target_goal.get("name"),
                "kpi_target":           kpi_target_str,
                "estimated_impact_pct": None,
                "baseline_source":      "threshold_proxy",
                "budget_strain_pct":    f"{strain_pct}% of unbudgeted threshold",
                "confidence":           "low",
                "note":                 "insufficient baseline; cannot quantify exact KPI impact",
            }
            if cost_delta is not None:
                result["llm_cost_delta_pct"] = cost_delta
                result["note"] = (
                    f"insufficient baseline; LLM estimate: 비용 변화율 {cost_delta:+.1f}%"
                )
            return result

        result = {
            "goal_id":              target_goal.get("goal_id"),
            "goal_name":            target_goal.get("name"),
            "kpi_target":           kpi_target_str,
            "estimated_impact_pct": None,
            "baseline_source":      None,
            "confidence":           "very_low",
            "note":                 "insufficient baseline; cannot quantify KPI impact",
        }
        if cost_delta is not None:
            result["llm_cost_delta_pct"] = cost_delta
            result["note"] = (
                f"insufficient baseline; LLM estimate: 비용 변화율 {cost_delta:+.1f}%"
            )
        return result

    # -----------------------------------------------------------------------
    # Aggregate
    # -----------------------------------------------------------------------

    def _aggregate(
        self,
        dims: list[RiskDimension],
        cp: dict,
        confidence_deductions: int,
    ) -> RiskAggregate:
        if not dims:
            return RiskAggregate(score=0, band="LOW", confidence=_CONF_MIN)

        industry_code = (cp.get("company", {}).get("industry_code") or "").upper()
        industry_text = (cp.get("company", {}).get("industry") or "").lower()

        if industry_code:
            is_healthcare = industry_code == "HEALTHCARE"
            is_public = industry_code in ("PUBLIC_SECTOR", "GOVERNMENT")
        else:
            # Legacy fallback: substring matching when industry_code absent
            is_healthcare = any(kw in industry_text for kw in ("health", "hospital", "medical", "헬스", "의료"))
            is_public = any(kw in industry_text for kw in ("government", "public", "정부", "공공", "gsa"))

        default_weights: dict[str, float] = {
            "financial":   0.40,
            "compliance":  0.35,
            "strategic":   0.25,
            "procurement": 0.20,
        }
        if is_healthcare:
            default_weights["compliance"] = 0.50
        elif is_public:
            default_weights["compliance"] = 0.45

        active_weights = {d.id: default_weights.get(d.id, 0.20) for d in dims}
        total_w = sum(active_weights.values())
        if total_w == 0:
            return RiskAggregate(score=0, band="LOW", confidence=0.5)

        weighted_sum = sum(
            (active_weights[d.id] / total_w) * d.score for d in dims
        )
        agg_score = int(round(_clamp(weighted_sum, 0, 100)))
        confidence = _clamp(_CONF_BASE - confidence_deductions * _CONF_DECAY, _CONF_MIN, _CONF_MAX)

        return RiskAggregate(
            score=agg_score,
            band=_band(agg_score),
            confidence=round(confidence, 3),
        )
