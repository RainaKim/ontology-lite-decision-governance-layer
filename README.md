# Ontology-lite Decision Governance Layer

**Graph-native enterprise decision governance with deterministic rule evaluation and swappable storage.**

[![Demo Stable](https://img.shields.io/badge/demo-stable-brightgreen)]()
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()
[![Architecture](https://img.shields.io/badge/architecture-graph--native-blue)]()

---

## 🎯 What This Is

An **Ontology-lite Decision Governance Layer** that transforms unstructured business decisions into validated, graph-stored, governance-ready artifacts.

**NOT:**
- ❌ A summarization tool
- ❌ An AI auditor
- ❌ A full knowledge graph
- ❌ GraphRAG

**IS:**
- ✅ Decision structuring engine
- ✅ Deterministic governance evaluator
- ✅ Graph-native memory system
- ✅ Template-based Decision Pack generator

---

## 🏗️ Architecture

### Three-Layer Design

```
┌─────────────────────────────────────────────────────┐
│          Decision Pack (Human Layer)                │
│  ┌─────────────────────────────────────────────┐   │
│  │ • Title & Summary                           │   │
│  │ • Goals, KPIs, Risks                        │   │
│  │ • Approval Chain                            │   │
│  │ • Recommended Next Actions                  │   │
│  │ • Audit Trail & Rationales                  │   │
│  └─────────────────────────────────────────────┘   │
│           ▲ Template-based generation               │
└───────────┼─────────────────────────────────────────┘
            │
┌───────────┼─────────────────────────────────────────┐
│           │   Governance Engine (Logic Layer)       │
│  ┌────────▼────────────────────────────────────┐   │
│  │ • Risk Scoring (deterministic)              │   │
│  │ • Flag Detection (keyword + structural)     │   │
│  │ • Rule Evaluation (priority-based)          │   │
│  │ • Approval Chain Computation                │   │
│  └─────────────────────────────────────────────┘   │
│           ▲ Pure Python, NO LLMs                    │
└───────────┼─────────────────────────────────────────┘
            │
┌───────────┼─────────────────────────────────────────┐
│           │  Graph Repository (Memory Layer)        │
│  ┌────────▼────────────────────────────────────┐   │
│  │ Graph Ontology:                             │   │
│  │                                              │   │
│  │  Nodes:  Actor  Action  Policy  Risk        │   │
│  │          Resource                            │   │
│  │                                              │   │
│  │  Edges:  OWNS                               │   │
│  │          REQUIRES_APPROVAL_BY                │   │
│  │          GOVERNED_BY                         │   │
│  │          TRIGGERS                            │   │
│  │          IMPACTS                             │   │
│  │          MITIGATES                           │   │
│  └─────────────────────────────────────────────┘   │
│           Storage: InMemory (MVP) → Neo4j (Prod)    │
└─────────────────────────────────────────────────────┘
```

### End-to-End Flow

```
1. Decision Input
   ↓
2. Governance Evaluation
   • Load rules from company context JSON (mock_company*.json)
   • Compute risk score (severity-weighted)
   • Evaluate conditions (>=, ==, contains, OR)
   • Select approval chain (priority-based)
   • Detect flags (PRIVACY, FINANCIAL, HIGH_RISK, etc.)
   ↓
3. Graph Storage
   • Create Action node (decision)
   • Create Actor nodes (owners, approvers)
   • Create Risk nodes (from decision.risks)
   • Create Policy nodes (from triggered rules)
   • Create edges (OWNS, REQUIRES_APPROVAL_BY, GOVERNED_BY, TRIGGERS)
   ↓
4. Decision Pack Generation
   • Build title (with strategic impact prefix)
   • Generate summary (risk level, status, confidence)
   • Compile goals/KPIs/risks
   • Detect missing items
   • Generate next actions (deterministic rules)
   • Extract rationales (from rules + approval chain)
   ↓
5. Return to Human
```

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- No database required (uses in-memory graph)
- No API keys required (deterministic governance)

### Installation

```bash
# Clone repository
git clone <repo-url>
cd decision-governance-layer

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Run E2E Tests (Validate Demo Stability)

```bash
python -m app.e2e_runner
```

**Expected output:**
```
================================================================================
E2E GOVERNANCE VALIDATION — FULL PIPELINE (with subgraph extraction)
================================================================================

...

================================================================================
VALIDATION SUMMARY
================================================================================

Total checks: 180
Passed: 180 ✓
Failed: 0 ✗
Success rate: 100.0%

================================================================================
✅ DEMO STABLE — All checks passed
```

### Run Demo with Fixtures

```python
import asyncio
from app.demo_fixtures import get_demo_fixture, get_company_context
from app.decision_pipeline import process_decision_with_graph_reasoning

# Load a scenario by key
decision = get_demo_fixture("C03_core_ip_protection")
company = get_company_context()

async def run():
    result = await process_decision_with_graph_reasoning(
        decision=decision,
        company_context=company,
        use_nova_governance=False,
        use_nova_graph=False,
    )
    pack = result["decision_pack"]
    print(f"Status: {pack['summary']['governance_status']}")
    print(f"Risk Level: {pack['summary']['risk_level']}")
    print(f"Approval Chain: {len(pack['approval_chain'])} steps")

asyncio.run(run())
```

---

## 📦 Graph Ontology

### Node Types

| Node Type | Description | Example |
|-----------|-------------|---------|
| **Actor** | People, roles, departments | `Sarah Chen (VP Strategy)` |
| **Action** | Decisions, tasks | `Acquire TechCorp for $2.5M` |
| **Policy** | Rules, constraints | `Financial Threshold Rule` |
| **Risk** | Threats, concerns | `Integration challenges` |
| **Resource** | Budget, systems, assets | `Cloud Infrastructure Budget` |

### Edge Predicates

| Edge | Direction | Meaning |
|------|-----------|---------|
| **OWNS** | Actor → Action | Actor owns/is accountable for Action |
| **REQUIRES_APPROVAL_BY** | Action → Actor | Action requires Actor's approval |
| **GOVERNED_BY** | Action → Policy | Action is governed by Policy |
| **TRIGGERS** | Action → Risk | Action triggers Risk |
| **IMPACTS** | Action → Resource | Action impacts Resource |
| **MITIGATES** | Action → Risk | Action mitigates Risk |

### Example Graph

```
[Sarah Chen (Actor)]
       │ OWNS
       ▼
[Acquire TechCorp (Action)]
       │ REQUIRES_APPROVAL_BY
       ├──→ [CFO (Actor)]
       ├──→ [CEO (Actor)]
       │ GOVERNED_BY
       ├──→ [Financial Threshold Rule (Policy)]
       │ TRIGGERS
       ├──→ [Integration Risk (Risk)]
       └──→ [Retention Risk (Risk)]
```

---

## 🧪 Demo Fixtures

30 production-ready scenarios across three governance frameworks:

### Corporate Finance — Nexus Dynamics (C01–C10)

| Key | Scenario | Status |
|-----|----------|--------|
| `C01_marketing_budget_overrun` | Marketing Budget Overrun | needs_review |
| `C02_related_party_transaction` | Related Party Transaction | needs_review |
| `C03_core_ip_protection` | Core IP Protection | **blocked** |
| `C04_shadow_it_saas` | Shadow IT SaaS Adoption | **blocked** |
| `C05_goal_mismatch_hiring` | Strategic Goal Mismatch Hiring | needs_review |
| `C06_entertainment_expense` | Excessive Entertainment Expense | needs_review |
| `C07_subsidiary_loan` | Subsidiary Financial Support | needs_review |
| `C08_cloud_overprovisioning` | Cloud Infrastructure Over-provisioning | needs_review |
| `C09_esg_supply_chain` | ESG Supply Chain Violation | needs_review |
| `C10_retroactive_bonus` | Retroactive Bonus Application | **blocked** |

### Healthcare & Data Privacy — Mayo Central Hospital (H01–H10)

| Key | Scenario | Status |
|-----|----------|--------|
| `H01_unauthorized_patient_data_access` | Unauthorized Patient Data Access | **blocked** |
| `H02_off_label_prescription_risk` | Off-label Prescription Risk | **blocked** |
| `H03_equipment_maintenance_gap` | Critical Equipment Maintenance Gap | **blocked** |
| `H04_clinical_trial_conflict_of_interest` | Clinical Trial Conflict of Interest | **blocked** |
| `H05_telemedicine_data_leakage` | Telemedicine Data Leakage | **blocked** |
| `H06_nurse_patient_ratio_violation` | Nurse-to-Patient Ratio Violation | **blocked** |
| `H07_redundant_equipment_purchase` | Redundant Medical Equipment Purchase | needs_review |
| `H08_ai_training_without_consent` | AI Training without Consent | **blocked** |
| `H09_er_golden_hour_protocol_failure` | ER Golden Hour Protocol Failure | **blocked** |
| `H10_controlled_substance_inventory_gap` | Controlled Substance Inventory Gap | **blocked** |

### Public Sector & Procurement — State of Delaware GSA (G01–G10)

| Key | Scenario | Status |
|-----|----------|--------|
| `G01_sole_source_procurement` | Sole Source Procurement Violation | needs_review |
| `G02_budget_dumping` | End-of-Year Budget Dumping | needs_review |
| `G03_lobbyist_vendor_conflict` | Lobbyist-Linked Vendor Conflict | **blocked** |
| `G04_double_dipping_grant` | Double Dipping Grant Detection | **blocked** |
| `G05_emergency_fund_misappropriation` | Emergency Fund Misappropriation | **blocked** |
| `G06_missing_environmental_assessment` | Missing Environmental Assessment | **blocked** |
| `G07_public_official_ethics_violation` | Public Official Ethics Violation | **blocked** |
| `G08_legacy_system_overexpenditure` | Legacy System Over-expenditure | needs_review |
| `G09_mwbe_quota_noncompliance` | MWBE Quota Non-compliance | needs_review |
| `G10_sensitive_data_open_access` | Sensitive Data Open-Access Risk | **blocked** |

---

## 🔧 Governance Rules

Rules are embedded in each company context JSON (`mock_company*.json`) under the `governance_rules` key. Each company file represents a different governance framework:

| File | Framework | Approval Chain |
|------|-----------|----------------|
| `mock_company.json` | Corporate Finance (Nexus Dynamics) | CFO > Compliance > CEO |
| `mock_company_healthcare.json` | Healthcare & Data Privacy (Mayo Central Hospital) | Security > Compliance > Medical Director |
| `mock_company_public.json` | Public Sector & Procurement (State of Delaware GSA) | Legal > Compliance > Board |

**Rule structure example:**

```json
{
  "rule_id": "R1",
  "name": "Capital Expenditure Approval",
  "type": "financial",
  "description": "Decisions with expenditure over budget threshold require CFO approval",
  "condition": {
    "field": "cost",
    "operator": ">",
    "value": 50000000
  },
  "consequence": {
    "action": "require_approval",
    "approver_role": "CFO",
    "approver_id": "cfo_001",
    "severity": "high"
  },
  "active": true
}
```

**Condition operators supported:**
- `==` (equals)
- `>` (greater than)
- `contains` (text contains substring)
- `OR` (top-level logical OR over multiple sub-conditions)

---

## 🏛️ Repository Pattern

### Abstract Interface

```python
from app.graph_repository import BaseGraphRepository

class BaseGraphRepository(ABC):
    @abstractmethod
    async def add_node(self, node: Node) -> Node: ...

    @abstractmethod
    async def add_edge(self, edge: Edge) -> Edge: ...

    @abstractmethod
    async def upsert_decision_graph(self, decision, governance) -> DecisionGraph: ...

    @abstractmethod
    async def get_governance_context(self, decision_id, depth=2) -> dict: ...
```

### Implementations

**MVP: InMemoryGraphRepository**
- Dict-based storage
- Fast, no dependencies
- Demo-stable

**Production: Neo4jGraphRepository** (Day 3+)
- Persistent storage
- Cypher queries
- Drop-in replacement

---

## 📊 Decision Pack Output

```json
{
  "title": "[HIGH] Acquire TechStartup Inc for $2.5M to expand AI capabilities",
  "summary": {
    "decision_statement": "Acquire TechStartup Inc for $2.5M...",
    "human_approval_required": true,
    "risk_level": "high",
    "governance_status": "needs_review",
    "confidence_score": 0.75,
    "strategic_impact": "high"
  },
  "goals_kpis": {
    "goals": [...],
    "kpis": [...]
  },
  "risks": [...],
  "owners": [...],
  "missing_items": [],
  "approval_chain": [
    {
      "level": "c_level",
      "role": "CFO",
      "required": true,
      "rationale": "Major financial decision approval"
    }
  ],
  "recommended_next_actions": [
    "Request approvals: Budget Owner, VP Finance, CFO, CEO",
    "Confirm budget justification with CFO"
  ],
  "audit": {
    "flags": ["HIGH_RISK", "FINANCIAL_THRESHOLD_EXCEEDED"],
    "triggered_rules": [...],
    "rationales": [...],
    "computed_risk_score": 7.5
  }
}
```

---

## 🎯 Key Features

### ✅ Deterministic Governance
- **No LLM in critical path** (core governance is 100% deterministic)
- Same input → same output
- Reproducible, auditable
- Pure Python logic
- **Optional Nova enhancement:** When `use_nova=True` and 2+ rules trigger, Nova can optimize approval chains (disabled by default in tests)

### ✅ Graph-Native Architecture
- Nodes: Actor, Action, Policy, Risk, Resource
- Edges: OWNS, REQUIRES_APPROVAL_BY, GOVERNED_BY, TRIGGERS, IMPACTS, MITIGATES
- Swappable backend (InMemory → Neo4j)
- Repository pattern (no framework lock-in)

### ✅ Template-Based Decision Packs
- Fixed JSON structure
- No generative text
- Deterministic formatting
- Legal-safe output

### ✅ Demo Stability
- E2E test coverage
- Invariant enforcement
- 100% pass rate
- No external dependencies

---

## 📁 Project Structure

```
decision-governance-layer/
├── app/
│   ├── schemas.py                 # Pydantic v2 models (Decision, Owner, Goal, etc.)
│   ├── governance.py              # Deterministic governance engine
│   ├── graph_ontology.py          # Graph schema (Node, Edge, NodeType, EdgePredicate)
│   ├── graph_repository.py        # Repository pattern (BaseGraphRepository, InMemory)
│   ├── graph_reasoning.py         # Graph analysis orchestration + deterministic fallback
│   ├── decision_pack.py           # Template-based pack generator
│   ├── decision_pipeline.py       # End-to-end 5-step pipeline orchestration
│   ├── nova_reasoner.py           # Nova API integration + subgraph extraction
│   ├── demo_fixtures.py           # 30 scenarios across 3 governance frameworks
│   ├── e2e_runner.py              # End-to-end validation (180 checks, 30 scenarios)
│   └── __init__.py
├── docs/
│   ├── README_VISION.md           # Project philosophy & vision
│   ├── BUILD_PLAN.md              # Hackathon build plan
│   ├── ARCHITECTURE.md            # Technical architecture details
│   └── QA_SUMMARY.md             # Test results & demo stability
├── mock_company.json              # Corporate Finance governance context (Nexus Dynamics)
├── mock_company_healthcare.json   # Healthcare governance context (Mayo Central Hospital)
├── mock_company_public.json       # Public Sector governance context (State of Delaware GSA)
├── GRAPH_REASONING_SUMMARY.md    # Graph reasoning implementation notes
├── requirements.txt               # Python dependencies
└── README.md                      # This file
```

---

## 🧪 Testing

### Run All E2E Tests

```bash
python -m app.e2e_runner
```

**Test Coverage:**
- ✅ Governance evaluation (deterministic)
- ✅ Graph storage (nodes + edges)
- ✅ Decision Pack generation (all sections)
- ✅ Graph reasoning section (when enabled)
- ✅ Invariant enforcement (never null, never empty)
- ✅ Scenario validation (30 scenarios across 3 frameworks)

### Invariants Enforced

1. **Decision Pack NEVER null**
2. **Graph NEVER empty after governance**
3. **Approval chain exists when rules triggered**
4. **Action node always created**

**Exit codes:**
- `0` = All tests passed, demo stable ✅
- `1` = Tests failed, DO NOT DEMO ❌

---

## 🧠 Optional Nova Enhancement Layer

### When is Nova Used?

**Nova is OPTIONAL** and only used when:
1. `use_nova=True` (defaults to True in production, False in tests)
2. Multiple rules trigger (2+ rules)
3. Conflict resolution is needed

### What Does Nova Do?

```python
# Deterministic path (always runs)
governance_result = evaluate_governance(decision, use_nova=False)
# ✅ Uses: Pure Python rule evaluation
# ✅ Output: Deterministic, reproducible

# Nova-enhanced path (optional)
governance_result = evaluate_governance(decision, use_nova=True)
# ✅ Uses: Deterministic evaluation + Nova conflict resolution
# ✅ Output: Optimized approval chain when 2+ rules conflict
```

### Three Nova Reasoning Functions

From `app/nova_reasoner.py`:

1. **`reason_about_goal_alignment()`**
   - Maps decisions to company strategic goals
   - Analyzes KPI/owner/semantic alignment
   - **Status:** Implemented, not currently called

2. **`reason_about_ownership_validity()`**
   - Validates owners against org hierarchy
   - Checks authority levels
   - **Status:** Implemented, not currently called

3. **`reason_about_governance_conflicts()`**
   - Resolves conflicts when multiple rules trigger
   - Optimizes approval chain sequence
   - **Status:** Implemented, called when `use_nova=True` and 2+ rules

### MVP Design Decision

**Day 1-2 (Current):**
- Nova disabled in E2E tests (`use_nova=False`)
- 100% deterministic governance
- No API keys required
- Demo-stable

**Day 3+ (Future):**
- Enable Nova for complex scenarios
- Use for goal mapping and ownership validation
- Optional enhancement, not required

### Why This Design?

✅ **Deterministic Core:** Governance always works without LLM
✅ **Optional Enhancement:** Nova improves complex edge cases
✅ **Test Stability:** Tests run without API dependencies
✅ **Production Ready:** Can enable Nova when needed

---

## 🔬 Design Principles

### 1. Governance is Deterministic
**Why?**
- Enterprises can't deploy non-deterministic governance
- Legal/compliance requires explainability
- Debugging AI governance is impossible

**How?**
- Pure Python rule evaluation
- Boolean conditions (>=, ==, contains)
- Priority-based matching
- No LLM calls

### 2. Graph is Memory
**Why?**
- Governance is inherently relational (who approves what)
- Traversal queries are natural
- Schema evolution is easier than relational
- Future: graph algorithms (pagerank, path analysis)

**How?**
- 5 node types (Actor, Action, Policy, Risk, Resource)
- 6 edge predicates (OWNS, REQUIRES_APPROVAL_BY, etc.)
- Repository pattern (swappable backend)
- BFS traversal for context retrieval

### 3. Decision Pack is Last
**Why?**
- Single source of truth (graph)
- Always current (re-compute with latest rules)
- No sync issues

**How?**
- Template-based generation
- Deterministic formatting
- Derived from graph + governance
- Never stored (computed on-demand)

---

## 🛣️ Evolution Path

### Completed
- ✅ Pydantic schemas
- ✅ Deterministic governance (100% rule-based)
- ✅ Graph ontology (5 nodes, 6 edges)
- ✅ InMemory repository
- ✅ Decision Pack generator
- ✅ Graph reasoning (deterministic + optional Nova)
- ✅ End-to-end pipeline (`decision_pipeline.py`)
- ✅ 30 demo scenarios across 3 governance frameworks
- ✅ E2E tests (180 checks, 100% pass rate)
- ✅ Multi-company governance contexts (Corporate Finance, Healthcare, Public Sector)

### Next Steps
- [ ] REST API (FastAPI)
- [ ] Neo4j integration (replace InMemory)
- [ ] LLM extraction endpoint (GPT-4o for decision parsing)
- [ ] Enable Nova graph reasoning in production (`use_nova_graph=True`)

### Week 2
- [ ] Graph analytics (approval bottlenecks)
- [ ] Real-time policy updates
- [ ] Audit dashboards

### Month 2
- [ ] Multi-tenant support
- [ ] Policy versioning
- [ ] Decision history/rollback

---

## 📚 Documentation

- **Vision:** [docs/README_VISION.md](docs/README_VISION.md)
- **Build Plan:** [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md)
- **Architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **QA Summary:** [docs/QA_SUMMARY.md](docs/QA_SUMMARY.md)

---

## 🎯 One-Line Summary

> **Graph-native decision governance with deterministic rules, swappable storage, and template-based human outputs — optimized for hackathon speed and enterprise evolution.**

---

## 📄 License

MIT

---

## 🤝 Contributing

Hackathon MVP — contributions welcome after initial demo.
