# Decision Governance Layer

Autonomous AI agents are beginning to make real operational decisions: hiring employees, allocating budgets, launching products, or processing sensitive data. Enterprises cannot allow these decisions to execute without governance. This system sits between AI agents and action execution — when an agent proposes a decision, the platform transforms it into an auditable governance artifact called a **Decision Pack**.

Every AI decision is evaluated against company policy, aligned with strategic goals, quantified for risk across three dimensions, routed through approval chains, and backed by traceable evidence. Amazon Nova powers the intelligence layer (8 call sites across the pipeline) while deterministic engines enforce policy and compute final governance outcomes.

```
"Aggressive hiring of 20 R&D staff under cost-saving guidelines"
                              |
                    [ Amazon Nova extracts ]
                              |
            Decision { involves_hiring: true, headcount_change: 20 }
                              |
              [ Rule Engine evaluates against company policy ]
                              |
          Triggered: R7 (Workforce Hiring Review), R8 (Large-Scale Approval)
                              |
                [ Knowledge Graph builds relationships ]
                              |
     Decision --CONFLICTS_WITH--> Cost Stability Goal
     Decision --SUPPORTS------> Revenue Growth Goal
     R7 --REQUIRES_APPROVAL_BY--> HR Director
     R8 --REQUIRES_APPROVAL_BY--> CEO
                              |
              [ Risk Scoring quantifies across 3 dimensions ]
                              |
         Financial: 35  |  Compliance: 0  |  Strategic: 68
                    Aggregate: 52 (MEDIUM)
                              |
               [ Simulation proposes remediation ]
                              |
     Scenario 1: Defer hiring → risk drops to 28 (LOW)
     Scenario 2: Reduce to 10 hires → risk drops to 41 (MEDIUM)
```

### End-to-End Flow

```
AI Decision → Nova Extraction → Rule Evaluation → Ontology Graph Reasoning → Risk Scoring → Remediation Simulation → Decision Pack
```

---

## System Architecture

```
                          ┌──────────────────────────────────┐
                          │         Frontend (React)         │
                          │    SSE streaming + REST API      │
                          └──────────┬───────────────────────┘
                                     │
                    POST /v1/decisions (202 Accepted)
                    GET  /v1/decisions/{id}/stream (SSE)
                    GET  /v1/decisions/{id} (full result)
                                     │
┌────────────────────────────────────┼────────────────────────────────────────┐
│                          FastAPI Application                               │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     5-Step Async Pipeline                            │  │
│  │                                                                      │  │
│  │  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────┐   ┌──────┐  │  │
│  │  │ 1. Nova   │──▶│ 2. Rule  │──▶│ 3. Graph │──▶│4.Risk│──▶│5.Pack│  │  │
│  │  │ Extract   │   │ Engine   │   │ Builder  │   │Score │   │Build │  │  │
│  │  │ (Lite)    │   │          │   │          │   │      │   │      │  │  │
│  │  └──────────┘   └──────────┘   └──────────┘   └──────┘   └──────┘  │  │
│  │    LLM            Deterministic   Ontology      Quant.    Template   │  │
│  │                                                                      │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐   │  │
│  │  │ Nova Pro      │  │ Simulation   │  │ External Signals         │   │  │
│  │  │ Graph Reason  │  │ + Nova       │  │ + Nova Summarization     │   │  │
│  │  │ (Contradicts, │  │ Rationale    │  │ (Market/Regulatory)      │   │  │
│  │  │  Ownership)   │  │              │  │                          │   │  │
│  │  └──────────────┘  └──────────────┘  └──────────────────────────┘   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                            │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────────────┐  │
│  │  Auth / RBAC      │  │  SQLite + Alembic │  │  In-Memory Stores      │  │
│  │  JWT + SSO        │  │  Users, Companies │  │  DecisionRecord        │  │
│  │  Google, Azure AD │  │  Agents, Decisions│  │  GraphRepository       │  │
│  └──────────────────┘  └──────────────────┘  └─────────────────────────┘  │
└────────────────────────────────────────────────────────────────────────────┘
                                     │
                    ┌────────────────┴────────────────┐
                    │        Amazon Bedrock            │
                    │   ┌────────────────────────┐    │
                    │   │ Nova 2 Lite             │    │
                    │   │ 7 call sites: extract,  │    │
                    │   │ classify, translate,     │    │
                    │   │ propose, summarize       │    │
                    │   └────────────────────────┘    │
                    │   ┌────────────────────────┐    │
                    │   │ Nova Pro                │    │
                    │   │ 1 call site: graph      │    │
                    │   │ contradiction analysis  │    │
                    │   │ (multi-step reasoning)  │    │
                    │   └────────────────────────┘    │
                    │          us-east-1              │
                    └─────────────────────────────────┘
```

### Pipeline Step Detail

| Step | Component | Input | Output | Nova Model |
|------|-----------|-------|--------|------------|
| 1 | **LLM Extraction** | Raw decision text | Structured Decision object (goals, KPIs, risks, owners, cost, boolean flags) | Lite |
| 1b | **Decision Context** | Raw text + agent info | Left-panel entities (filtered for safety) | Lite |
| 2 | **Governance Evaluation** | Decision + company rules JSON | Triggered rules, approval chain, flags, risk score | — |
| 3 | **Graph Construction** | Decision + governance + company goals | Knowledge graph (nodes + edges with strategic alignment) | — |
| 2d | **Risk Semantics** | Decision + goals + rules | Goal impacts, compliance facts (fallback for scoring) | Lite |
| 2c | **Risk Scoring** | Decision + governance + graph edges | 3-dimension scores with evidence provenance | — |
| 4 | **Graph Reasoning** | Subgraph + company context | Contradictions, ownership inference, next actions | **Pro** |
| 4b | **Risk Simulation** | Decision + governance + risk scores | 2-3 remediation scenarios with re-evaluated outcomes | Lite (proposals + rationale) |
| 4c | **External Signals** | Company profile + decision context | Market/regulatory/operational benchmarks (additive — never modifies governance outcomes) | Lite |
| 5 | **Decision Pack** | All above (governance + graph reasoning + risk scores + simulation + external signals) | Execution-ready governance artifact with audit trail | — |

The final output of the system is a **Decision Pack** — an approval-ready governance artifact containing rule triggers, approval chains, quantified risk analysis across three dimensions, remediation simulation results, and traceable evidence linking every score back to its source. This is the atomic unit that enables an enterprise to audit, approve, or reject any AI-proposed decision.

External signals (step 4c) provide supplementary benchmarks — industry data, regulatory guidelines, operational studies — that give decision-makers additional context. They flow into the Decision Pack as a separate `external_context` section but **never influence** risk scores, approval chains, or governance status. This separation is intentional: governance decisions must be deterministic and auditable, while external context is advisory.

---

## Why Ontology

AI agents can make decisions — approve budgets, hire staff, process customer data. But enterprises can't let agents act without governance. The problem: governance requires understanding **relationships** between a decision and its organizational context. A hiring decision isn't risky in isolation — it's risky because it conflicts with a cost-stability goal, triggers a workforce review rule, and requires CEO approval.

Relational databases can store these facts. But they can't represent the reasoning chain: *this decision triggers this rule, which requires this approver, because it conflicts with this goal, which generates this risk.* That's a graph problem.

This system applies an **ontology-lite** approach — a typed vocabulary of nodes and edges that captures governance relationships structurally, not as flat records:

```
                          ┌─────────────────────┐
                          │ DECISION             │
                          │ "Hire 20 R&D staff"  │
                          └──┬──────────┬────────┘
                             │          │
                   TRIGGERS_RULE    CONFLICTS_WITH
                             │          │
                    ┌────────▼──┐   ┌───▼──────────────────┐
                    │ RULE      │   │ GOAL_STRATEGIC        │
                    │ R7: Work- │   │ G3: Cost Efficiency   │
                    │ force Rev │   └───┬──────────────────┘
                    └────┬──────┘       │
                         │         GENERATES_RISK
              REQUIRES_APPROVAL_BY      │
                         │       ┌──────▼──────────────┐
                    ┌────▼────┐  │ RISK                 │
                    │ ACTOR   │  │ "Strategic conflict:  │
                    │ HR Dir  │  │  cost efficiency"     │
                    └─────────┘  └──────────────────────┘
```

The vocabulary is small (8 node types, 12 edge predicates) but sufficient to answer governance questions through graph traversal:
- **Why was this blocked?** → Follow TRIGGERS_RULE → GENERATES_RISK edges
- **Who needs to approve?** → Follow REQUIRES_APPROVAL_BY edges from triggered rules
- **Does this align with strategy?** → Check SUPPORTS vs. CONFLICTS_WITH edges to strategic goals
- **What if we change the decision?** → Rebuild the subgraph with patched inputs, compare

This is not a full formal ontology — it's a governance-specific vocabulary designed to make AI agent decisions auditable and traversable. The graph is the system's memory of *why* it made each governance determination.

### Current State → Production Roadmap

| Layer | MVP (Current) | Production |
|-------|--------------|------------|
| **Graph Storage** | In-memory (`InMemoryGraphRepository`) | Neo4j via `BaseGraphRepository` interface — same service code, persistent storage |
| **Cross-Decision Queries** | Single-decision subgraph only | "Show all decisions that conflicted with cost-stability goal this quarter" — shared nodes (Policy, Actor, Goal) create natural links between decisions |
| **Graph RAG** | Nova reasons over extracted subgraph per request | Retrieve relevant past decisions + outcomes via graph traversal, feed as context to Nova — enables "a similar hiring decision was blocked last quarter because..." |
| **Ontology** | Ontology-lite (8 node types, 12 edge predicates, typed enums) | Formal OWL/SHACL ontology — enables inference rules (e.g., "any decision that TRIGGERS a RULE with severity=critical automatically REQUIRES_APPROVAL_BY the board"), SPARQL validation of graph consistency |
| **External Signals** | Advisory context (curated demo fixtures) | Live market data feeds promoted to risk scoring inputs — when a real pricing signal contradicts the decision, it raises the strategic risk score with evidence provenance |

The architecture is designed for this migration. `BaseGraphRepository` is an abstract class — Neo4j replaces `InMemoryGraphRepository` without changing any service code. The NovaReasoner's subgraph extraction method documents the exact Cypher queries that replace the mock matching logic. External signals already have typed schemas (`ExternalSignalsPayload`) ready to carry real-time data.

---

## Core Design Decisions

### 1. LLM extracts, rules decide

Amazon Nova extracts structured fields from free-form text — boolean governance flags (`uses_pii`, `involves_hiring`, `involves_compliance_risk`), financial amounts, strategic impact, headcount changes. Every extraction output is Pydantic-validated.

The governance engine evaluates these fields against company-specific rules using generic condition operators (`>`, `>=`, `==`, `contains`, `OR`). No rule IDs or company names are hardcoded in application logic — rules live in JSON configuration:

```json
{
  "rule_id": "R4",
  "name": "Strategic Alignment Rule",
  "condition": {
    "field": "involves_hiring",
    "operator": "==",
    "value": true
  },
  "consequence": {
    "action": "require_approval",
    "approver_role": "HR Director"
  }
}
```

This separation means governance outcomes are deterministic, reproducible, and auditable. The same decision text produces the same approval chain every time.

### 2. Graph-native ontology (not a visualization layer)

The ontology described above isn't a UI feature — it drives actual system behavior. Strategic risk scoring reads SUPPORTS/CONFLICTS_WITH edges from the graph to compute the strategic dimension score. The simulation engine rebuilds subgraphs for each counterfactual scenario. The decision pack traces approval chains by traversing REQUIRES_APPROVAL_BY edges from triggered rules.

Strategic alignment is determined by goal category, not keyword matching. Hiring decisions conflict with cost-stability goals and support revenue-growth goals — derived from the goal's `category` field in company config, not from scanning for budget-related words.

The repository pattern (`BaseGraphRepository` → `InMemoryGraphRepository`) makes the backend swappable. Neo4j enables persistent cross-decision queries ("show me all decisions that conflicted with our cost-stability goal this quarter") without changing service logic.

### 3. Risk scoring with evidence provenance

Three independent dimensions, each scored 0-100:

| Dimension | Weight | Inputs |
|-----------|--------|--------|
| **Financial** | 0.40 | Cost vs. remaining budget (log-scale), threshold bonuses, triggered financial rules |
| **Compliance/Privacy** | 0.35 | PII usage (+60), compliance risk flag, triggered compliance rules. Healthcare: weight increases to 0.50 |
| **Strategic** | 0.25 | Graph edge analysis: SUPPORTS vs. CONFLICTS_WITH edges against company strategic goals |

Risk band: 0-39 LOW, 40-69 MEDIUM, 70-84 HIGH, 85-100 CRITICAL.

Every score carries evidence — human-readable labels, source attribution (`"Rule Engine"`, `"Graph Analysis"`, `"Input Text"`), and confidence. No score is a black box.

### 4. Counterfactual simulation via deterministic re-evaluation

The simulation engine doesn't estimate what would happen — it runs each scenario through the same governance + risk-scoring pipeline and shows the actual result.

**Flow**: Copy decision → apply template patch → re-run `evaluate_governance()` → re-run `RiskScoringService.score()` → compute delta.

9 config-driven templates cover financial, compliance, and strategic remediation strategies. Nova proposes which templates to apply (template selection only — never score computation). If Nova is unavailable, the system falls through to deterministic template matching based on issue classification.

```
Baseline:  Risk 52 (MEDIUM), 2 approvals required
Scenario 1 (defer_hiring):     Risk 28 (LOW),    0 approvals  ← Recommended
Scenario 2 (reduce_headcount): Risk 41 (MEDIUM), 1 approval
```

---

## Amazon Nova Integration

Amazon Nova is the reasoning backbone of the governance pipeline. It performs four distinct roles: **structured decision extraction** (converting free-form text into Pydantic-validated governance objects), **ontology-aware graph reasoning** (analyzing contradictions, ownership gaps, and strategic conflicts across the knowledge graph), **remediation scenario proposal** (selecting and explaining counterfactual templates), and **external signal summarization** (synthesizing market and regulatory context). Nova provides intelligence and reasoning; deterministic engines enforce every governance outcome. This separation ensures that the system produces complete, auditable results even when Nova is unavailable.

Nova is deeply integrated across the entire pipeline — **8 distinct call sites**, each with strict boundaries separating LLM intelligence from deterministic governance logic.

### Tiered Model Selection

| Model | Role | Why |
|-------|------|-----|
| **Nova Pro** (`us.amazon.nova-pro-v1:0`) | Graph contradiction analysis, governance conflict resolution, strategic reasoning | Complex multi-step reasoning over subgraph structure |
| **Nova 2 Lite** (`us.amazon.nova-2-lite-v1:0`) | Extraction, classification, translation, scenario proposals, signal summarization | Fast structured I/O where latency matters |

### Nova Call Sites (8 total)

| # | Call Site | Model | Purpose | Fallback |
|---|----------|-------|---------|----------|
| 1 | **Decision Extraction** | Lite | Free-text → Pydantic schema (goals, risks, owners, governance flags) | 3 retries → blocked fallback decision |
| 2 | **Decision Context** | Lite | Entity extraction for left-panel display (filtered for safety) | Skip (non-fatal) |
| 3 | **Risk Semantics** | Lite | Classify goal impacts + compliance facts as structured JSON | Skip — risk scoring uses extractor fields |
| 4 | **Graph Contradiction Analysis** | **Pro** | Multi-step reasoning over ontology subgraph — finds strategic conflicts, ownership gaps, authority issues | Deterministic subgraph analysis |
| 5 | **Scenario Proposal** | Lite | Select remediation templates + generate Korean copy | Config-driven template matching |
| 6 | **Simulation Rationale** | Lite | Generate natural-language explanation of WHY each remediation works | Scenarios remain valid without rationale |
| 7 | **External Signal Summarization** | Lite | Synthesize market/regulatory context from curated sources | Curated deterministic signals |
| 8 | **Node Label Translation** | Lite | Korean graph node labels → English | Labels remain Korean-only |

### Architecture Contract

Nova is the **classifier and extractor** — it never computes final scores, governance outcomes, or approval chains. All quantitative outputs come from deterministic engines (rule evaluation, risk scoring, graph algorithms). This separation means:

- Every Nova call has a **deterministic fallback** — the system produces complete governance artifacts with or without Nova
- Nova outputs are always **Pydantic-validated** before use — invalid JSON or schema violations trigger fallback
- Nova **proposes**, deterministic engines **decide** — e.g., Nova suggests which remediation template to apply, but the simulation re-evaluates the patched decision through the same governance pipeline

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Runtime** | Python 3.12, FastAPI, Uvicorn |
| **AI/LLM** | Amazon Nova Pro + Nova 2 Lite via AWS Bedrock (8 call sites, tiered model selection) |
| **Validation** | Pydantic v2 (schema contracts, LLM output validation) |
| **Database** | SQLite (dev) + SQLAlchemy ORM + Alembic (11 migrations) |
| **Auth** | JWT Bearer tokens, RBAC (User/Manager/Admin), Google OAuth2, Azure AD OIDC |
| **HTTP** | httpx (async, Bedrock API calls) |
| **Streaming** | Server-Sent Events (SSE) for real-time pipeline progress |
| **Graph** | Custom ontology-lite graph (abstract repository, in-memory MVP, Neo4j-ready) |

---

## Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/v1/decisions` | Submit decision for async governance analysis (202) |
| GET | `/v1/decisions/{id}/stream` | SSE stream — real-time pipeline progress |
| GET | `/v1/decisions/{id}` | Full governance result after completion |

Additional endpoints cover workspace dashboard (metrics, decision feed, agent management), agent registry with escalation rules, auth (JWT + Google/Azure SSO), and company management — 25+ endpoints total.

---

## Project Structure

```
decision-governance-layer/
├── app/
│   ├── main.py                          # FastAPI app, lifespan, CORS, routers
│   ├── extractor.py                     # LLM extraction with retry + fallback
│   ├── llm_client.py                    # Nova prompt engineering
│   ├── bedrock_client.py                # AWS Bedrock HTTP client
│   ├── governance.py                    # Generic rule engine (no hardcoded rules)
│   ├── graph_ontology.py                # Node types, edge predicates, schema
│   ├── graph_repository.py              # Abstract repo + InMemory implementation
│   ├── graph_enrichment.py              # Strategic goals, rules, alignment edges
│   ├── decision_pack.py                 # Template-based decision artifact assembly
│   ├── nova_reasoner.py                 # Nova graph reasoning + goal alignment
│   ├── config/
│   │   ├── bedrock_config.py            # Tiered model IDs (Pro + Lite), region, timeouts
│   │   └── risk_config.py               # Dimension weights, band thresholds
│   ├── models/                          # SQLAlchemy ORM (User, Company, Agent, Decision)
│   ├── routers/                         # FastAPI endpoints
│   │   ├── decisions.py                 # Pipeline submission + SSE streaming
│   │   ├── workspace.py                 # Dashboard + agent management
│   │   ├── agents.py                    # Agent registry + escalation rules
│   │   └── normalizers.py               # Response shape enforcement
│   ├── services/
│   │   ├── pipeline_service.py          # 5-step async pipeline orchestrator
│   │   ├── risk_scoring_service.py      # 3-dimension quantified risk scoring
│   │   ├── risk_response_simulation_service.py  # Counterfactual scenario engine
│   │   ├── nova_scenario_proposer.py    # Nova template proposal
│   │   ├── external_signal_service.py   # Market/regulatory signal orchestrator
│   │   ├── rbac_service.py              # Role-based access control
│   │   └── sso_service.py              # Google OAuth2, Azure AD OIDC
│   ├── schemas/                         # Pydantic v2 request/response contracts
│   ├── repositories/                    # Data access (decision_store, agent_store, DB repos)
│   ├── demo_fixtures/                   # 2 companies with governance rules, evidence, signals
│   │   ├── companies/{nexus_dynamics,mayo_central}/
│   │   ├── external_profiles/           # Company-specific signal categories
│   │   ├── external_sources/            # Curated industry benchmarks
│   │   └── simulation_templates.json    # 9 remediation scenario templates
│   └── db/                              # SQLAlchemy session, base
├── alembic/versions/                    # 11 migrations (users → companies → decisions → agents)
├── tests/                               # 276 tests (pytest)
└── requirements.txt
```

---

## Quick Start

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Environment
cp .env.example .env
# Set BEDROCK_API_KEY (AWS Bedrock Bearer token)
# Set JWT_SECRET

# Database
alembic upgrade head

# Run
uvicorn app.main:app --reload --port 8000

# Test
python -m pytest tests/ -v    # 276 tests
```

---

## Demo Companies

Two company profiles with distinct governance frameworks:

| Company | Industry | Governance Focus | Rules |
|---------|----------|-----------------|-------|
| **Nexus Dynamics** | Finance/Tech | Capital expenditure, strategic alignment, workforce changes | R1-R8 |
| **Mayo Central Hospital** | Healthcare | HIPAA compliance, patient data, clinical equipment | R1-R8 |

Each company has: governance rules (JSON-configurable), strategic goals with categories, approval hierarchies, evidence registries, and external signal profiles. No company-specific logic exists in application code.

---

## Test Coverage

276 unit tests + 8 integration tests across 15 test files:

| Area | Tests | Coverage |
|------|-------|----------|
| Risk Scoring (3 dimensions, bands, evidence) | 26 | Dimension formulas, edge cases, confidence |
| Risk Response Simulation (templates, re-evaluation) | 21 | 3-pass architecture, patch strategies |
| Governance Evidence Integration | 18 | Evidence registry, signal assembly |
| External Signals (Nova + curated fallback) | 23 | Profile loading, source matching |
| Nova External Signal Summarizer | 19 | Prompt construction, response parsing |
| Risk Semantics (LLM fallback layer) | 16 | Goal impacts, compliance facts |
| Decision Context Extraction | 12 | Entity extraction, proposal generation |
| Bedrock Extractor | 5 | Nova integration, markdown stripping |
| **Bedrock Integration** (live API) | **8** | **End-to-end Nova Lite + Pro, extraction roundtrip, scenario proposals, graph reasoning** |
| RBAC | 14 | Role enforcement, tenant isolation |
| SSO | 15 | Google OAuth2, Azure AD OIDC flows |
| Auth | 12 | Signup, login, token validation |

