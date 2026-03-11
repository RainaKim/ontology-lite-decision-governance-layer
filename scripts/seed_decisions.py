"""
scripts/seed_decisions.py

demo_fixtures.py의 _FIXTURES_BY_COMPANY 시나리오(조직당 2개)를 기반으로
decisions 테이블에 샘플 데이터를 insert합니다.

fixture text는 원문 그대로 사용하고,
agent_name / department / status / confidence / risk_level 등
workspace 카드에 필요한 필드를 추가합니다.

Run:
    source venv/bin/activate
    python scripts/seed_decisions.py
"""

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.db.session import SessionLocal
from app.models.decision import Decision


def dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


DECISIONS = [
    # ── nexus_dynamics ────────────────────────────────────────────────────────
    # C01: "마케팅 예산 초과 요청"
    {
        "id": str(uuid.uuid4()),
        "company_id": "nexus_dynamics",
        "agent_name": "마케팅 AI Agent",
        "agent_name_en": "Marketing AI Agent",
        "department": "마케팅팀",
        "department_en": "Marketing",
        "status": "pending",
        "proposed_text": (
            "북미 시장 점유율 확대를 위한 광고비 2.5억 원 추가 요청. "
            "현재 부서 잔여 예산 5,000만 원. 전사 KPI는 글로벌 확장임."
        ),
        "proposed_text_en": (
            "Requesting an additional ₩250M in advertising budget to expand market share in North America. "
            "Current remaining departmental budget: ₩50M. Company-wide KPI is global expansion."
        ),
        "confidence": 0.82,
        "risk_level": "medium",
        "impact_label": "₩2.5억",
        "impact_label_en": "₩250M",
        "contract_value": None,
        "affected_count": None,
        "created_at": dt("2026-03-07T10:23:00"),
        "validated_at": None,
    },
    # C02: "전략 목표 불일치 R&D 채용"
    {
        "id": str(uuid.uuid4()),
        "company_id": "nexus_dynamics",
        "agent_name": "인사 AI Agent",
        "agent_name_en": "HR AI Agent",
        "department": "인사팀",
        "department_en": "Human Resources",
        "status": "blocked",
        "proposed_text": (
            "비용 절감 기조 하에서의 R&D 인력 20명 급격한 채용. "
            "Q1 KPI(운영비 -10%)와 충돌. 전략적 재조정 필요."
        ),
        "proposed_text_en": (
            "Rapid hiring of 20 R&D personnel despite a cost-reduction mandate. "
            "Conflicts with Q1 KPI (operating cost -10%). Strategic realignment required."
        ),
        "confidence": 0.71,
        "risk_level": "high",
        "impact_label": None,
        "contract_value": None,
        "affected_count": 20,
        "created_at": dt("2026-03-06T14:10:00"),
        "validated_at": None,
    },

    # ── mayo_central ──────────────────────────────────────────────────────────
    # H01: "비인가 환자 데이터 열람 허용"
    {
        "id": str(uuid.uuid4()),
        "company_id": "mayo_central",
        "agent_name": "Clinical Data Agent",
        "agent_name_en": "Clinical Data Agent",
        "department": "임상관리",
        "department_en": "Clinical Management",
        "status": "blocked",
        "proposed_text": (
            "미인가 외부 연구진에게 환자 식별 정보(PII)가 포함된 임상 데이터 열람 권한 부여 시도. "
            "HIPAA 규정에 따른 엄격한 접근 제어 필요. 비식별화(Anonymization) 조치 미확인."
        ),
        "proposed_text_en": (
            "Attempted to grant unauthorized external researchers access to clinical data containing patient PII. "
            "Strict access controls required under HIPAA. Anonymization measures unconfirmed."
        ),
        "confidence": 0.85,
        "risk_level": "high",
        "impact_label": None,
        "contract_value": None,
        "affected_count": None,
        "created_at": dt("2026-03-07T09:15:00"),
        "validated_at": None,
    },
    # H02: "원격진료 데이터 외부 클라우드 전송"
    {
        "id": str(uuid.uuid4()),
        "company_id": "mayo_central",
        "agent_name": "정보보호 AI Agent",
        "agent_name_en": "Information Security AI Agent",
        "department": "정보보호",
        "department_en": "Information Security",
        "status": "pending",
        "proposed_text": (
            "원격 진료 영상 데이터를 승인되지 않은 외부 퍼블릭 클라우드로 전송 시도. "
            "Local Data Residency 정책 위반. 폐쇄망 운영 원칙 준수 여부 확인."
        ),
        "proposed_text_en": (
            "Attempted to transfer telemedicine video data to an unapproved public cloud provider. "
            "Violates Local Data Residency policy. Compliance with closed-network operation principles requires verification."
        ),
        "confidence": 0.77,
        "risk_level": "high",
        "impact_label": None,
        "contract_value": None,
        "affected_count": None,
        "created_at": dt("2026-03-06T11:30:00"),
        "validated_at": None,
    },

    # ── sool_sool_icecream ────────────────────────────────────────────────────
    # I01: 아이스크림 컵 1,000개 추가 주문
    {
        "id": str(uuid.uuid4()),
        "company_id": "sool_sool_icecream",
        "agent_name": "마케팅 AI Agent",
        "agent_name_en": "Marketing AI Agent",
        "department": "마케팅",
        "department_en": "Marketing",
        "status": "pending",
        "proposed_text": (
            "SNS 홍보 데이터 분석 결과 향후 3개월간 아이스크림 판매량이 1,000유닛에 달할 것으로 예측됨. "
            "아이스크림 컵 1,000개를 온라인 발주하기로 결정. 단가 $1.80, 총 구매 비용 $1,800."
        ),
        "proposed_text_en": (
            "SNS promotional data analysis projects 1,000 unit sales over the next 3 months. "
            "Decided to place an online order for 1,000 ice cream cups at $1.80/unit, total cost $1,800."
        ),
        "confidence": 0.74,
        "risk_level": "medium",
        "impact_label": "$1,800",
        "impact_label_en": "$1,800",
        "contract_value": 1800,
        "affected_count": None,
        "created_at": dt("2026-03-08T09:00:00"),
        "validated_at": None,
    },
    # I02: 신규 아이스크림 맛 개발 착수
    {
        "id": str(uuid.uuid4()),
        "company_id": "sool_sool_icecream",
        "agent_name": "영업 AI Agent",
        "agent_name_en": "Sales AI Agent",
        "department": "영업",
        "department_en": "Sales",
        "status": "pending",
        "proposed_text": (
            "최근 아이스크림 매출 성장세가 낮아 새로운 맛 개발로 매출 성장을 회복하고자 함. "
            "R&D팀에 신규 아이스크림 맛 후보 10개를 선정·제출하기로 결정. "
            "초기 맛 테스트 및 원재료 샘플링 비용 약 $2,500 예상."
        ),
        "proposed_text_en": (
            "Ice cream sales growth has been sluggish recently. "
            "Decided to submit 10 new ice cream flavor candidates to the R&D team to revive sales growth. "
            "Estimated initial flavor testing and ingredient sampling cost: $2,500."
        ),
        "confidence": 0.68,
        "risk_level": "medium",
        "impact_label": "$2,500",
        "impact_label_en": "$2,500",
        "contract_value": 2500,
        "affected_count": None,
        "created_at": dt("2026-03-08T11:30:00"),
        "validated_at": None,
    },
    # I03: Production 직원 채용 공고 게시
    {
        "id": str(uuid.uuid4()),
        "company_id": "sool_sool_icecream",
        "agent_name": "HR AI Agent",
        "agent_name_en": "HR AI Agent",
        "department": "인사",
        "department_en": "Human Resources",
        "status": "blocked",
        "proposed_text": (
            "최근 분기 매출이 전분기 대비 12% 증가하는 추세를 근거로 "
            "생산(Production) 신규 직원 1명을 채용하기로 결정. "
            "LinkedIn에 채용 공고를 게시할 예정."
        ),
        "proposed_text_en": (
            "Decided to hire 1 new production staff member, "
            "citing a 12% quarter-over-quarter revenue increase. "
            "Planning to post a job listing on LinkedIn."
        ),
        "confidence": 0.79,
        "risk_level": "high",
        "impact_label": "신규 채용",
        "impact_label_en": "New Hire",
        "contract_value": None,
        "affected_count": 1,
        "created_at": dt("2026-03-08T14:00:00"),
        "validated_at": None,
    },

]


def seed():
    db = SessionLocal()
    try:
        inserted = 0
        skipped = 0
        for data in DECISIONS:
            # Idempotency: skip if a decision with the same company_id + proposed_text exists
            existing = db.query(Decision).filter(
                Decision.company_id == data["company_id"],
                Decision.proposed_text == data["proposed_text"],
            ).first()
            if existing:
                print(f"  SKIP   [{data['company_id']}] {data['agent_name']} (already exists)")
                skipped += 1
                continue
            decision = Decision(**data)
            db.add(decision)
            print(f"  INSERT [{data['company_id']}] {data['agent_name']} — {data['status']}")
            inserted += 1
        db.commit()
        print(f"\nDone. inserted={inserted}, skipped={skipped}")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
