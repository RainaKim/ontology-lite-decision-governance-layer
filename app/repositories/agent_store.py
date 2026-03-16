"""
app/repositories/agent_store.py — In-memory agent registry.

Seeded with 5 demo agents matching the AgentBoundaries page.
Supports CRUD operations with sequential ID generation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentRecord:
    id: str
    name: str
    version: str
    department: str
    domain: str
    autonomy: str              # Policy Bound | Conditional | Human Controlled | Autonomous
    autonomy_level: int        # 0-100
    policy: str
    status: str                # Active | Restricted
    constraints: list[str] = field(default_factory=list)
    linked_policies: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------

_SEED_AGENTS: list[AgentRecord] = [
    AgentRecord(
        id="AGT-001",
        name="PricingBot",
        version="v2.3",
        department="Revenue Operations",
        domain="Pricing & Margin Control",
        autonomy="Policy Bound",
        autonomy_level=45,
        policy="POL-FIN-012",
        status="Active",
        constraints=[
            "Max +15% price adjustment per quarter",
            "APAC region only — no cross-region decisions",
            "Board notification required above $5M impact",
        ],
        linked_policies=["POL-FIN-012", "POL-RISK-003", "POL-REG-001"],
    ),
    AgentRecord(
        id="AGT-002",
        name="ContractBot",
        version="v1.8",
        department="Legal & Compliance",
        domain="Contract Review & Approval",
        autonomy="Conditional",
        autonomy_level=60,
        policy="POL-LEGAL-007",
        status="Active",
        constraints=[
            "Cannot approve contracts above $500K autonomously",
            "Legal counsel review required for IP clauses",
            "Renewal terms must match original within ±5%",
        ],
        linked_policies=["POL-LEGAL-007", "POL-COMP-002", "POL-FIN-015"],
    ),
    AgentRecord(
        id="AGT-003",
        name="HRBot",
        version="v3.1",
        department="Human Resources",
        domain="Headcount & Org Design",
        autonomy="Human Controlled",
        autonomy_level=20,
        policy="POL-HR-003",
        status="Active",
        constraints=[
            "All headcount decisions require CHRO approval",
            "No involuntary separations without legal review",
            "Salary adjustments capped at +10% without CFO sign-off",
        ],
        linked_policies=["POL-HR-003", "POL-COMP-001", "POL-LEGAL-009"],
    ),
    AgentRecord(
        id="AGT-004",
        name="SupplyChainBot",
        version="v2.0",
        department="Operations",
        domain="Vendor & Procurement",
        autonomy="Policy Bound",
        autonomy_level=55,
        policy="POL-OPS-005",
        status="Active",
        constraints=[
            "Single-vendor spend capped at 30% of category budget",
            "New vendors require 3-bid minimum",
            "Emergency procurement above $200K needs COO approval",
        ],
        linked_policies=["POL-OPS-005", "POL-FIN-010", "POL-RISK-007"],
    ),
    AgentRecord(
        id="AGT-005",
        name="DataBot",
        version="v1.2",
        department="Data & Analytics",
        domain="Data Access & Privacy",
        autonomy="Restricted",
        autonomy_level=10,
        policy="POL-DATA-001",
        status="Restricted",
        constraints=[
            "PII access requires DPO approval",
            "Cross-border data transfer blocked without legal clearance",
            "Model training on customer data suspended pending audit",
        ],
        linked_policies=["POL-DATA-001", "POL-COMP-004", "POL-LEGAL-011"],
    ),
]

_SEED_ESCALATION_RULES = [
    {
        "id": "ESC-001",
        "severity": "CRITICAL",
        "trigger": "Risk score exceeds 0.85 or financial impact > $5M",
        "action": "Immediate suspension of agent decision authority. Alert CISO and CFO.",
        "responsible": "CISO + CFO",
    },
    {
        "id": "ESC-002",
        "severity": "HIGH",
        "trigger": "Compliance violation detected or PII exposure risk flagged",
        "action": "Decision quarantined. Legal and Compliance team notified within 1 hour.",
        "responsible": "CLO + DPO",
    },
    {
        "id": "ESC-003",
        "severity": "MEDIUM",
        "trigger": "Sequential approval chain stalled for >24 hours",
        "action": "Escalate to next-level approver. Notify department head.",
        "responsible": "Department Head",
    },
]

# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_store: dict[str, AgentRecord] = {}
_counter: int = len(_SEED_AGENTS)

# Escalation rules are static (read-only)
ESCALATION_RULES = _SEED_ESCALATION_RULES


def _init_store() -> None:
    for agent in _SEED_AGENTS:
        _store[agent.id] = agent


_init_store()


def _next_id() -> str:
    global _counter
    with _lock:
        _counter += 1
        return f"AGT-{_counter:03d}"


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def list_agents(
    status: Optional[str] = None,
    department: Optional[str] = None,
) -> list[AgentRecord]:
    with _lock:
        agents = list(_store.values())

    if status:
        agents = [a for a in agents if a.status == status]
    if department:
        lower = department.lower()
        agents = [a for a in agents if lower in a.department.lower()]
    return agents


def get_agent(agent_id: str) -> Optional[AgentRecord]:
    return _store.get(agent_id)


def create_agent(
    name: str,
    version: str,
    department: str,
    domain: str,
    autonomy: str,
    autonomy_level: int,
    policy: str,
    status: str = "Active",
    constraints: Optional[list[str]] = None,
    linked_policies: Optional[list[str]] = None,
) -> AgentRecord:
    agent_id = _next_id()
    record = AgentRecord(
        id=agent_id,
        name=name,
        version=version,
        department=department,
        domain=domain,
        autonomy=autonomy,
        autonomy_level=autonomy_level,
        policy=policy,
        status=status,
        constraints=constraints or [],
        linked_policies=linked_policies or [],
    )
    with _lock:
        _store[agent_id] = record
    return record


def update_agent(agent_id: str, **kwargs) -> Optional[AgentRecord]:
    with _lock:
        record = _store.get(agent_id)
        if not record:
            return None
        for key, value in kwargs.items():
            if value is not None and hasattr(record, key):
                setattr(record, key, value)
        return record
