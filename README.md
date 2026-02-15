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
   • Load rules (mock_rules.json)
   • Compute risk score (severity-weighted)
   • Evaluate conditions (>=, ==, contains_any)
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
E2E GOVERNANCE VALIDATION - DEMO STABILITY CHECK
================================================================================

[compliant]         ✓ 5/5 checks
[budget_violation]  ✓ 5/5 checks
[privacy_violation] ✓ 5/5 checks
[blocked]           ✓ 5/5 checks

✅ DEMO STABLE - All checks passed
================================================================================
```

### Run Demo with Fixtures

```python
import asyncio
from app.demo_fixtures import get_demo_fixture
from app.governance import evaluate_governance
from app.graph_repository import InMemoryGraphRepository
from app.decision_pack import build_decision_pack

# 1. Load demo fixture
decision = get_demo_fixture("budget_violation")  # or "compliant", "privacy_violation", "blocked"

# 2. Evaluate governance (deterministic, no LLM)
governance_result = evaluate_governance(decision, company_context={}, use_o1=False)

# 3. Store in graph
async def store():
    repo = InMemoryGraphRepository()
    decision_graph = await repo.upsert_decision_graph(
        decision=decision.model_dump(),
        governance=governance_result.to_dict(),
        decision_id="demo_001"
    )
    return decision_graph

graph = asyncio.run(store())

# 4. Generate Decision Pack
pack = build_decision_pack(
    decision=decision.model_dump(),
    governance=governance_result.to_dict()
)

print(f"Status: {pack['summary']['governance_status']}")
print(f"Risk Level: {pack['summary']['risk_level']}")
print(f"Approval Chain: {len(pack['approval_chain'])} steps")
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

Four production-ready test scenarios:

### 1. Compliant Decision
```python
decision = get_demo_fixture("compliant")
# Tool upgrade, low risk, standard approval
# Expected: compliant status, no flags
```

### 2. Budget Violation
```python
decision = get_demo_fixture("budget_violation")
# $3.5M acquisition, high risk, financial review required
# Expected: blocked/needs_review, FINANCIAL_THRESHOLD_EXCEEDED flag
```

### 3. Privacy Violation
```python
decision = get_demo_fixture("privacy_violation")
# GDPR/PII data collection, privacy review required
# Expected: needs_review, PRIVACY_REVIEW_REQUIRED flag
```

### 4. Blocked Decision
```python
decision = get_demo_fixture("blocked")
# Critical conflicts, 9.5 risk score, 0.15 confidence
# Expected: blocked status, CRITICAL_CONFLICT flag
```

---

## 🔧 Governance Rules

Rules are defined in `app/mock_rules.json`. Example:

```json
{
  "rule_id": "R006",
  "name": "Financial Threshold - Major Investment",
  "type": "financial",
  "description": "Decisions > $1M require CFO approval",
  "conditions": {
    "decision_statement_keywords": {
      "operator": "contains_any",
      "value": ["acquisition", "investment", "capital", "million"]
    }
  },
  "approval_chain": [
    {"level": "department_head", "role": "Budget Owner", "required": true},
    {"level": "vp", "role": "VP of Finance", "required": true},
    {"level": "c_level", "role": "CFO", "required": true},
    {"level": "c_level", "role": "CEO", "required": true}
  ],
  "priority": 1
}
```

**Operators supported:**
- `==` (equals)
- `>=` (greater than or equal)
- `<` (less than)
- `in` (value in list)
- `contains_any` (text contains any keyword)

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
- **Optional o1 enhancement:** When `use_o1=True` and 2+ rules trigger, o1-mini can optimize approval chains (disabled by default in tests)

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
│   ├── main.py                    # FastAPI app (Day 3+)
│   ├── schemas.py                 # Pydantic v2 models (Decision, Owner, Goal, etc.)
│   ├── governance.py              # Deterministic governance engine
│   ├── graph_ontology.py          # Graph schema (Node, Edge, NodeType, EdgePredicate)
│   ├── graph_repository.py        # Repository pattern (BaseGraphRepository, InMemory)
│   ├── decision_pack.py           # Template-based pack generator
│   ├── demo_fixtures.py           # Test scenarios (compliant, budget, privacy, blocked)
│   ├── e2e_runner.py              # End-to-end validation tests
│   ├── mock_rules.json            # Governance rules (7 rules with conditions)
│   └── __init__.py
├── docs/
│   ├── README_VISION.md           # Project philosophy & vision
│   ├── BUILD_PLAN.md              # 7-day hackathon plan
│   ├── ARCHITECTURE.md            # Technical architecture details
│   └── QA_SUMMARY.md              # Test results & demo stability
├── mock_company.json              # Company context (alternate rule format)
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
- ✅ Invariant enforcement (never null, never empty)
- ✅ Scenario validation (4 edge cases)

### Invariants Enforced

1. **Decision Pack NEVER null**
2. **Graph NEVER empty after governance**
3. **Approval chain exists when rules triggered**
4. **Action node always created**

**Exit codes:**
- `0` = All tests passed, demo stable ✅
- `1` = Tests failed, DO NOT DEMO ❌

---

## 🧠 Optional o1 Enhancement Layer

### When is o1 Used?

**o1 is OPTIONAL** and only used when:
1. `use_o1=True` (defaults to True in production, False in tests)
2. Multiple rules trigger (2+ rules)
3. Conflict resolution is needed

### What Does o1 Do?

```python
# Deterministic path (always runs)
governance_result = evaluate_governance(decision, use_o1=False)
# ✅ Uses: Pure Python rule evaluation
# ✅ Output: Deterministic, reproducible

# o1-enhanced path (optional)
governance_result = evaluate_governance(decision, use_o1=True)
# ✅ Uses: Deterministic evaluation + o1 conflict resolution
# ✅ Output: Optimized approval chain when 2+ rules conflict
```

### Three o1 Reasoning Functions

From `app/o1_reasoner.py`:

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
   - **Status:** Implemented, called when `use_o1=True` and 2+ rules

### MVP Design Decision

**Day 1-2 (Current):**
- o1 disabled in E2E tests (`use_o1=False`)
- 100% deterministic governance
- No API keys required
- Demo-stable

**Day 3+ (Future):**
- Enable o1 for complex scenarios
- Use for goal mapping and ownership validation
- Optional enhancement, not required

### Why This Design?

✅ **Deterministic Core:** Governance always works without LLM
✅ **Optional Enhancement:** o1 improves complex edge cases
✅ **Test Stability:** Tests run without API dependencies
✅ **Production Ready:** Can enable o1 when needed

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

### Day 1-2 (Current - MVP)
- ✅ Pydantic schemas
- ✅ Deterministic governance (100% rule-based)
- ✅ Graph ontology (5 nodes, 6 edges)
- ✅ InMemory repository
- ✅ Decision Pack generator
- ✅ Demo fixtures (4 scenarios)
- ✅ E2E tests (100% pass rate)
- ✅ o1 reasoner (implemented but disabled in tests)

### Day 3-4 (Enhancement Layer)
- [ ] Enable o1 in production (`use_o1=True`)
- [ ] LLM extraction endpoint (GPT-4o for decision parsing)
- [ ] REST API (FastAPI)
- [ ] Neo4j integration (replace InMemory)
- [ ] Graph query API (context retrieval)

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
