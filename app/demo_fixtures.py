"""
Demo Fixtures - Test scenarios for governance validation

Four core scenarios for demo stability:
1. Compliant decision (low risk, passes all checks)
2. Budget violation (triggers financial rules)
3. Privacy violation (requires privacy review)
4. Blocked decision (critical conflicts)
"""

import json
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from app.schemas import (
    Decision, Owner, Goal, KPI, Risk, Assumption,
    StrategicImpact
)


# ---------------------------------------------------------------------------
# Fixture model for API responses
# ---------------------------------------------------------------------------

class Fixture(BaseModel):
    """Demo fixture for frontend consumption."""
    id: str
    company_id: str
    title: str
    text: str
    tags: list[str] = []


# ---------------------------------------------------------------------------
# Fixture data by company
# ---------------------------------------------------------------------------

_FIXTURES_BY_COMPANY: dict[str, list[Fixture]] = {
    "nexus_dynamics": [
        Fixture(
            id="C01",
            company_id="nexus_dynamics",
            title="마케팅 예산 초과 요청",
            text="북미 시장 점유율 확대를 위한 광고비 2.5억 원 추가 요청. 현재 부서 잔여 예산 5,000만 원. 전사 KPI는 글로벌 확장임.",
            tags=["Financial", "Budget", "Marketing"],
        ),
        Fixture(
            id="C02",
            company_id="nexus_dynamics",
            title="특수관계인 거래 체결",
            text="사외이사 친인척 운영 기업(Zephyr Tech)과 파트너십 체결. 이사회 연결 관계 감지됨. 이해충돌 검토 필요.",
            tags=["Compliance", "Ethics", "Related Party"],
        ),
        Fixture(
            id="C03",
            company_id="nexus_dynamics",
            title="비인가 외부 SaaS 도입 시도",
            text="보안 검토 없는 외부 AI CRM 도입 시도. 고객 개인정보 노출 위험. IT 거버넌스 정책 Sec-04 위반.",
            tags=["IT Security", "PII", "Compliance"],
        ),
        Fixture(
            id="C04",
            company_id="nexus_dynamics",
            title="전략 목표 불일치 R&D 채용",
            text="비용 절감 기조 하에서의 R&D 인력 20명 급격한 채용. Q1 KPI(운영비 -10%)와 충돌. 전략적 재조정 필요.",
            tags=["HR", "Strategic", "Cost"],
        ),
        Fixture(
            id="C05",
            company_id="nexus_dynamics",
            title="한도 초과 접대비 승인 요청",
            text="인당 50만 원 상당의 고액 고객 접대비 승인 요청. 뇌물방지 및 윤리강령 위반 위험. 기준 한도는 20만 원.",
            tags=["Compliance", "Ethics", "Expense"],
        )
    ],
    "mayo_central": [
        Fixture(
            id="H01",
            company_id="mayo_central",
            title="비인가 환자 데이터 열람 허용",
            text="미인가 외부 연구진에게 환자 식별 정보(PII)가 포함된 임상 데이터 열람 권한 부여 시도. HIPAA 규정에 따른 엄격한 접근 제어 필요. 비식별화(Anonymization) 조치 미확인.",
            tags=["Privacy", "HIPAA", "PII"],
        ),
        Fixture(
            id="H02",
            company_id="mayo_central",
            title="오프라벨 고위험 약물 처방 승인",
            text="임상 가이드라인에 등재되지 않은 용도로 고위험 약물(오프라벨) 처방 승인 요청. 의료심의위원회(IRB) 승인 경로 확인 필요.",
            tags=["Clinical", "Compliance", "IRB"],
        ),
        Fixture(
            id="H03",
            company_id="mayo_central",
            title="수술실 로봇 장비 점검 미이행",
            text="정기 점검 기한이 도과한 수술실 로봇 장비를 사용한 수술 예약 강행. Safety Protocol Sec-12 위반. 환자 안전 리스크 임계치 초과.",
            tags=["Safety", "Equipment", "Compliance"],
        ),
        Fixture(
            id="H04",
            company_id="mayo_central",
            title="임상시험 이해충돌 연구책임자 선정",
            text="주요 기부 제약사가 후원하는 임상 시험에 병원 고위 관계자를 연구 책임자로 선정. Anti-Bribery 및 연구 윤리 규정 충돌 탐지. 외부 윤리 위원회 통보 대상.",
            tags=["Ethics", "Research", "Conflict of Interest"],
        ),
        Fixture(
            id="H05",
            company_id="mayo_central",
            title="원격진료 데이터 외부 클라우드 전송",
            text="원격 진료 영상 데이터를 승인되지 않은 외부 퍼블릭 클라우드로 전송 시도. Local Data Residency 정책 위반. 폐쇄망 운영 원칙 준수 여부 확인.",
            tags=["Security", "Telemedicine", "Data Residency"],
        ),
        Fixture(
            id="H07",
            company_id="mayo_central",
            title="마약류 재고-시스템 기록 불일치",
            text="마약류 의약품의 실제 재고와 시스템 기록 간의 불일치 발생. Narcotics Control Act 위반. 즉시 자동 감사 모드 및 사법기관 보고 준비.",
            tags=["Pharmacy", "Audit", "Regulatory"],
        ),
    ],
    "delaware_gsa": [
        Fixture(
            id="G01",
            company_id="delaware_gsa",
            title="경쟁 입찰 없는 수의계약 시도",
            text="긴급성 사유가 불분명한 상태에서 특정 IT 업체와 500만 달러 규모의 단일 응찰 수의계약 시도. 공공 조달법상 경쟁 입찰 원칙 위반 가능성. 수의계약 타당성 보고서(Justification) 누락 확인.",
            tags=["Procurement", "Compliance", "Sole Source"],
        ),
        Fixture(
            id="G03",
            company_id="delaware_gsa",
            title="로비스트 연계 업체 이해충돌 계약",
            text="최근 주지사 캠페인에 고액을 후원한 로비스트가 소속된 컨설팅사와 계약 추진. State Ethics Act 2024 위반 리스크. 정치적 유착 가능성 및 이해상충 탐지.",
            tags=["Ethics", "Conflict of Interest", "Lobbyist"],
        ),
        Fixture(
            id="G04",
            company_id="delaware_gsa",
            title="공공 보조금 중복 수혜 탐지",
            text="타 부서에서 이미 동일한 목적으로 보조금을 수령한 중소기업에 추가 지원금 배정. 공공 보조금 중복 수혜 방지 조항 위반. 부처 간 데이터 연동을 통한 부정 수급 차단.",
            tags=["Grant", "Fraud", "Compliance"],
        ),
        Fixture(
            id="G05",
            company_id="delaware_gsa",
            title="긴급 재난 예산 용도 외 전용",
            text="재난 선포가 되지 않은 지역의 도로 정비 사업에 긴급 재난 대응 예산 전용 시도. 예산 용도 외 전용(Misappropriation) 리스크. 긴급성 요건 미충족에 따른 차단.",
            tags=["Budget", "Emergency", "Misappropriation"],
        ),
        Fixture(
            id="G06",
            company_id="delaware_gsa",
            title="환경영향평가 미승인 입찰 공고",
            text="환경 영향 평가 보고서가 최종 승인되지 않은 상태에서 대규모 교량 건설 입찰 공고. Environmental Policy Act 위반. 절차적 결격 사유로 인한 입찰 무효화 가능성.",
            tags=["Environment", "Compliance", "Infrastructure"],
        ),
        Fixture(
            id="G07",
            company_id="delaware_gsa",
            title="공직자 한도 초과 외부 강의료 수령",
            text="조달 담당 공무원이 관련 업체로부터 규정된 한도를 초과하는 외부 강의료 수령. 공직자 윤리 규정 및 부정청탁금지법 위반. 징계 위원회 자동 회부 로직.",
            tags=["Ethics", "Public Official", "Discipline"],
        ),
        Fixture(
            id="G08",
            company_id="delaware_gsa",
            title="노후 시스템 고비용 유지보수 갱신",
            text="신규 전환보다 유지보수 비용이 더 높은 노후 메인프레임 유지보수 계약 갱신 요청. Digital Transformation 전략과 상충. 예산 효율성(Efficiency) 관점의 기각 권고.",
            tags=["IT", "Budget", "Modernization"],
        ),
        Fixture(
            id="G09",
            company_id="delaware_gsa",
            title="사회적 약자 기업 비율 미달 조달",
            text="사회적 약자 기업(MWBE) 우대 비율 15%를 충족하지 못한 연간 조달 계획 승인 요청. State Procurement Goal 미달. 할당량 충족을 위한 공급망 재설계 권고.",
            tags=["Equity", "MWBE", "Procurement"],
        ),
        Fixture(
            id="G10",
            company_id="delaware_gsa",
            title="납세 기록 등 민감 데이터 공개 개방",
            text="주민의 납세 기록 등 민감 정보가 포함된 원시 데이터를 공공 데이터 포털에 개방 시도. 국가 보안 및 개인정보 보호법 위반. 데이터 익명화 검증 단계 강제 호출.",
            tags=["Data", "Privacy", "Security"],
        ),
    ],
}


def get_fixtures(company_id: str) -> list[Fixture] | None:
    """
    Get demo fixtures for a company.

    Args:
        company_id: nexus_dynamics | mayo_central | delaware_gsa

    Returns:
        List of Fixture objects, or None if company_id not found.
    """
    return _FIXTURES_BY_COMPANY.get(company_id)


def get_all_company_ids() -> list[str]:
    """Get list of valid company IDs that have fixtures."""
    return list(_FIXTURES_BY_COMPANY.keys())


# ---------------------------------------------------------------------------
# Company context loader
# ---------------------------------------------------------------------------

_COMPANY_DATA_CACHE: Optional[dict] = None


def load_mock_company_data(path: Optional[str] = None) -> dict:
    """
    Load mock company data from JSON file.

    Used by:
    - e2e_runner for passing company_data through the pipeline
    - subgraph extraction (owner matching, KPI overlap, reporting chain)

    Args:
        path: Optional override path. Defaults to project-root mock_company.json.

    Returns:
        Parsed company data dict (personnel, strategic_goals, risk_tolerance, etc.)
    """
    global _COMPANY_DATA_CACHE
    if _COMPANY_DATA_CACHE is not None and path is None:
        return _COMPANY_DATA_CACHE

    if path is None:
        path = str(Path(__file__).parent.parent / "mock_company.json")

    with open(path, "r") as f:
        data = json.load(f)

    if path is None or path == str(Path(__file__).parent.parent / "mock_company.json"):
        _COMPANY_DATA_CACHE = data

    return data


def get_company_context() -> dict:
    """
    Get company context dict suitable for pipeline consumption.

    Returns the full mock_company.json contents. The pipeline and
    O1Reasoner._extract_mock_subgraph use keys like:
    - approval_hierarchy.personnel (owner matching, reporting chain)
    - strategic_goals (KPI overlap, goal alignment)
    - risk_tolerance (risk gap analysis)
    - governance_rules (policy context)
    """
    return load_mock_company_data()


def create_compliant_decision() -> Decision:
    """
    Low-risk, compliant decision.
    Expected: Low risk, standard approval chain, no flags.
    """
    return Decision(
        decision_statement="Upgrade development tools to latest versions for improved productivity",
        goals=[
            Goal(
                description="Improve developer productivity",
                metric="Deployment frequency"
            ),
            Goal(
                description="Reduce technical debt",
                metric="Code quality score"
            )
        ],
        kpis=[
            KPI(
                name="Deployment frequency",
                target="10% increase within 3 months",
                measurement_frequency="Weekly"
            ),
            KPI(
                name="Developer satisfaction",
                target="4.5/5 rating",
                measurement_frequency="Quarterly"
            )
        ],
        risks=[
            Risk(
                description="Learning curve for new tools",
                severity="low",
                mitigation="Provide training sessions and documentation"
            ),
            Risk(
                description="Temporary productivity dip during transition",
                severity="low",
                mitigation="Phased rollout over 2 weeks"
            )
        ],
        owners=[
            Owner(
                name="Alex Johnson",
                role="Engineering Manager",
                responsibility="Tool selection and rollout"
            )
        ],
        required_approvals=["Engineering Manager"],
        assumptions=[
            Assumption(
                description="Team has capacity for training",
                criticality="medium"
            )
        ],
        confidence=0.85,
        strategic_impact=StrategicImpact.LOW
    )


def create_budget_violation_decision() -> Decision:
    """
    Decision triggering financial threshold rules.
    Expected: Financial flags, CFO approval required.
    """
    return Decision(
        decision_statement="Strategic acquisition of DataCorp for $3.5M to expand our data analytics capabilities",
        goals=[
            Goal(
                description="Expand data analytics offerings",
                metric="New analytics features"
            ),
            Goal(
                description="Acquire data engineering talent",
                metric="Team size increase"
            ),
            Goal(
                description="Enter new market segment",
                metric="Revenue from analytics"
            )
        ],
        kpis=[
            KPI(
                name="Revenue from analytics products",
                target="$8M ARR within 24 months",
                measurement_frequency="Quarterly"
            ),
            KPI(
                name="Customer acquisition in analytics",
                target="50 enterprise customers",
                measurement_frequency="Monthly"
            )
        ],
        risks=[
            Risk(
                description="Integration complexity with existing data infrastructure",
                severity="high",
                mitigation="Dedicated integration team for 9 months"
            ),
            Risk(
                description="Key data scientists may leave post-acquisition",
                severity="critical",
                mitigation="Retention packages and equity grants"
            ),
            Risk(
                description="Market demand uncertainty for analytics products",
                severity="medium",
                mitigation="Pre-acquisition customer validation"
            )
        ],
        owners=[
            Owner(
                name="Maria Rodriguez",
                role="VP of Product",
                responsibility="Product integration and strategy"
            ),
            Owner(
                name="David Chen",
                role="VP of M&A",
                responsibility="Acquisition execution"
            )
        ],
        required_approvals=["CFO", "CEO", "Board"],
        assumptions=[
            Assumption(
                description="DataCorp valuation is accurate",
                criticality="high"
            ),
            Assumption(
                description="No major regulatory hurdles",
                criticality="high"
            )
        ],
        confidence=0.72,
        strategic_impact=StrategicImpact.HIGH,
        risk_score=7.5  # High risk score
    )


def create_privacy_violation_decision() -> Decision:
    """
    Decision requiring privacy review.
    Expected: PRIVACY_REVIEW_REQUIRED flag, CTO involvement.
    """
    return Decision(
        decision_statement="Implement user behavior tracking to collect personal data for ML model training and GDPR-compliant analytics",
        goals=[
            Goal(
                description="Improve product recommendations",
                metric="Click-through rate"
            ),
            Goal(
                description="Enable personalization features",
                metric="User engagement score"
            )
        ],
        kpis=[
            KPI(
                name="Recommendation accuracy",
                target="25% improvement",
                measurement_frequency="Weekly"
            ),
            KPI(
                name="User engagement",
                target="15% increase in session duration",
                measurement_frequency="Daily"
            )
        ],
        risks=[
            Risk(
                description="GDPR compliance violations if not properly implemented",
                severity="critical",
                mitigation="Legal review and privacy-by-design architecture"
            ),
            Risk(
                description="User privacy concerns and potential backlash",
                severity="high",
                mitigation="Transparent privacy policy and opt-in mechanism"
            ),
            Risk(
                description="Data breach exposure of PII",
                severity="critical",
                mitigation="End-to-end encryption and minimal data collection"
            )
        ],
        owners=[
            Owner(
                name="Sarah Kim",
                role="VP of Product",
                responsibility="Feature requirements and user experience"
            ),
            Owner(
                name="James Lee",
                role="Head of Data Science",
                responsibility="ML model development"
            )
        ],
        required_approvals=["CTO", "Legal", "Privacy Officer"],
        assumptions=[
            Assumption(
                description="Users will consent to data collection",
                criticality="high"
            ),
            Assumption(
                description="Privacy infrastructure is scalable",
                criticality="medium"
            )
        ],
        confidence=0.68,
        strategic_impact=StrategicImpact.MEDIUM,
        risk_score=8.0,  # High risk due to privacy concerns
        uses_pii=True,
        data_type="PHI"
    )


def create_blocked_decision() -> Decision:
    """
    Decision with critical conflicts that should be blocked.
    Expected: CRITICAL_CONFLICT flag, blocked status, high risk.
    """
    return Decision(
        decision_statement="Launch new product in 2 weeks without QA testing to meet arbitrary deadline",
        goals=[
            Goal(description="Meet marketing deadline", metric="Launch date"),
            Goal(description="Increase revenue", metric="Sales"),
            Goal(description="Beat competitor", metric="Market share"),
            Goal(description="Satisfy investors", metric="Growth rate"),
            Goal(description="Improve brand", metric="Brand awareness"),
            Goal(description="Expand market", metric="Customer base"),
            Goal(description="Reduce costs", metric="Budget"),  # Conflicting with quality
            Goal(description="Maximize quality", metric="Defect rate"),  # Conflicts with speed
        ],
        kpis=[
            KPI(name="Launch by target date", target="2 weeks"),
            KPI(name="Zero defects", target="0 bugs"),  # Impossible given timeline
            KPI(name="Cost reduction", target="50% below budget"),
            KPI(name="Revenue target", target="$10M in month 1"),
            KPI(name="Customer satisfaction", target="5/5 rating"),
            KPI(name="Market share", target="25% capture"),
            KPI(name="Feature completeness", target="100% of backlog"),
        ],
        risks=[
            Risk(
                description="Critical production bugs due to no QA",
                severity="critical",
                mitigation="None - skipping QA"
            ),
            Risk(
                description="Customer data loss from untested code",
                severity="critical",
                mitigation="None planned"
            ),
            Risk(
                description="System downtime and outages",
                severity="critical",
                mitigation="Hope for the best"
            ),
            Risk(
                description="Regulatory violations from compliance gaps",
                severity="critical",
                mitigation="Deal with it later"
            ),
        ],
        owners=[
            Owner(
                name="Unknown",
                role="Product Manager",
                responsibility="Unclear"
            )
        ],
        required_approvals=[],  # No approvals identified - red flag
        assumptions=[
            Assumption(
                description="Nothing will go wrong",
                criticality="critical"
            ),
            Assumption(
                description="Customers won't notice bugs",
                criticality="critical"
            )
        ],
        confidence=0.15,  # Very low confidence + high risk = blocked
        strategic_impact=StrategicImpact.CRITICAL,
        risk_score=9.5  # Nearly maximum risk
    )


# Demo fixture dictionary for easy access
DEMO_FIXTURES = {
    "compliant": create_compliant_decision,
    "budget_violation": create_budget_violation_decision,
    "privacy_violation": create_privacy_violation_decision,
    "blocked": create_blocked_decision,
}


def get_demo_fixture(name: str) -> Decision:
    """
    Get a demo fixture by name.

    Args:
        name: One of "compliant", "budget_violation", "privacy_violation", "blocked"

    Returns:
        Decision object

    Raises:
        ValueError if name not found
    """
    if name not in DEMO_FIXTURES:
        available = ", ".join(DEMO_FIXTURES.keys())
        raise ValueError(f"Unknown fixture '{name}'. Available: {available}")

    return DEMO_FIXTURES[name]()


def get_all_fixtures() -> dict[str, Decision]:
    """Get all demo fixtures as a dictionary."""
    return {name: factory() for name, factory in DEMO_FIXTURES.items()}
