"""Seed mock decisions into decisions table.

Uses fixed UUIDs so the migration is idempotent across environments.

Revision ID: 0009
Revises: 0008
Create Date: 2026-03-11 00:00:00.000000
"""

from typing import Sequence, Union
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=None)


_DECISIONS = [
    # ── nexus_dynamics ────────────────────────────────────────────────────────
    {
        "id": "11111111-0001-0001-0001-000000000001",
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
        "created_at": _dt("2026-03-07T10:23:00"),
        "validated_at": None,
    },
    {
        "id": "11111111-0001-0001-0001-000000000002",
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
        "impact_label_en": None,
        "contract_value": None,
        "affected_count": 20,
        "created_at": _dt("2026-03-06T14:10:00"),
        "validated_at": None,
    },

    # ── mayo_central ──────────────────────────────────────────────────────────
    {
        "id": "22222222-0002-0002-0002-000000000001",
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
        "impact_label_en": None,
        "contract_value": None,
        "affected_count": None,
        "created_at": _dt("2026-03-07T09:15:00"),
        "validated_at": None,
    },
    {
        "id": "22222222-0002-0002-0002-000000000002",
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
        "impact_label_en": None,
        "contract_value": None,
        "affected_count": None,
        "created_at": _dt("2026-03-06T11:30:00"),
        "validated_at": None,
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    for d in _DECISIONS:
        if dialect == "postgresql":
            bind.execute(
                sa.text(
                    """
                    INSERT INTO decisions
                        (id, company_id, agent_name, agent_name_en,
                         department, department_en, status,
                         proposed_text, proposed_text_en,
                         confidence, risk_level,
                         impact_label, impact_label_en,
                         contract_value, affected_count,
                         created_at, validated_at)
                    VALUES
                        (:id, :company_id, :agent_name, :agent_name_en,
                         :department, :department_en, :status,
                         :proposed_text, :proposed_text_en,
                         :confidence, :risk_level,
                         :impact_label, :impact_label_en,
                         :contract_value, :affected_count,
                         :created_at, :validated_at)
                    ON CONFLICT (id) DO NOTHING
                    """
                ),
                d,
            )
        else:
            bind.execute(
                sa.text(
                    """
                    INSERT OR IGNORE INTO decisions
                        (id, company_id, agent_name, agent_name_en,
                         department, department_en, status,
                         proposed_text, proposed_text_en,
                         confidence, risk_level,
                         impact_label, impact_label_en,
                         contract_value, affected_count,
                         created_at, validated_at)
                    VALUES
                        (:id, :company_id, :agent_name, :agent_name_en,
                         :department, :department_en, :status,
                         :proposed_text, :proposed_text_en,
                         :confidence, :risk_level,
                         :impact_label, :impact_label_en,
                         :contract_value, :affected_count,
                         :created_at, :validated_at)
                    """
                ),
                d,
            )


def downgrade() -> None:
    bind = op.get_bind()
    ids = [d["id"] for d in _DECISIONS]
    for decision_id in ids:
        bind.execute(
            sa.text("DELETE FROM decisions WHERE id = :id"),
            {"id": decision_id},
        )
