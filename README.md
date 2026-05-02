# DecisionGovernance AI

AI agents can now write code, draft contracts, and coordinate workflows — but the next frontier is letting them make decisions that actually change things: hiring someone, committing budget, processing customer data. Most enterprises aren't ready for that. Not because the AI isn't capable, but because there's no layer between the agent's output and real-world consequence.

That's the problem this system solves.

DecisionGovernance AI intercepts every AI-proposed decision before it executes and runs it through the company's actual governance structure — not a generic approval flow, but the specific rules, strategic goals, authority chains, and precedents that define how that company makes decisions. An agent proposing a $450K hiring plan doesn't just get flagged; it gets evaluated against R&D budget headroom, checked for conflicts with the current cost-stability mandate, routed to the right approvers in the right order, and compared against similar decisions that were approved or blocked in the past.

The hard part isn't building the approval workflow. It's knowing what the company's governance actually is — scattered across policy docs, org charts, Slack threads, and institutional memory that no one has ever formally modeled. We solve that too: an onboarding pipeline reads existing artifacts and reverse-constructs the governance ontology automatically. Companies don't define their rules from scratch; we derive the structure from what already exists.

The result is a system where AI agents can operate with real autonomy — and humans retain real accountability.

```
AI Agent proposes: "Build customer scoring using EU PII data"
                              │
               ┌──────────────▼──────────────┐
               │     Onboarding Graph         │
               │   (runs once per client)     │
               │  Scout Swarm → Transform     │
               │  → Neo4j Ontology Graph      │
               └──────────────┬──────────────┘
                              │
               ┌──────────────▼──────────────┐
               │    Validation Pipeline       │
               │  (runs for every decision)   │
               │                             │
               │  Layer 1: Rule Engine        │
               │    Triggered: R3 (PII)       │
               │    Triggered: R6 (flag)      │
               │    Approval: General Counsel │
               │                             │
               │  External Signals (Tavily)   │
               │    "GDPR enforcement up 40%" │
               │    RiskAdjustment: +9 compl. │ ← adjusts score before aggregate
               │                             │
               │  Risk Scoring                │
               │    Compliance: 70 → 83 HIGH  │ ← external signal applied
               │    Aggregate: MEDIUM → HIGH  │
               │                             │
               │  Layer 2: Governance Agent   │
               │    (LangGraph, max 3 rounds) │
               │    Graph RAG + Vector RAG    │
               │    External context in prompt│
               │    Verdict: ESCALATE 0.95    │
               └──────────────┬──────────────┘
                              │
               ┌──────────────▼──────────────┐
               │  Human reviews Decision Pack │
               │  Approves or rejects         │
               └─────────────────────────────┘
```

---

## Architecture

### Two-Phase System

**Phase 1 — Onboarding** (runs once per client)

Builds the company's governance ontology graph in Neo4j from existing artifacts. A LangGraph scout swarm processes documents, email threads, spreadsheets, and interview transcripts in parallel and derives the ontology from them. Structure emerges from data — clients are not asked to model an ontology from scratch.

**Phase 2 — Validation** (runs for every AI decision)

When an AI agent proposes a decision, the validation pipeline runs two layers:

1. **Deterministic governance core** — rule engine, ontology traversal, risk scoring, approval chain derivation
2. **Governance agent** (LangGraph) — dynamic reasoning, gap detection, historical retrieval via hybrid RAG, final verdict

### Three-Layer Ontology

```
Meta-layer       Universal governance primitives — shared across all companies
                 Risk, Authority, Conflict, Resolution, Compliance
                 Seeded once at system init. Never changes.

Domain-layer     Company-specific governance vocabulary
                 Goals, rules, actors, hierarchy — derived at onboarding
                 MERGE semantics (stable, reused across decisions)

Instance-layer   Concrete decisions, outcomes, evidence
                 CREATE semantics (immutable audit trail, grows over time)
```

### Hybrid RAG

Neo4j handles both retrieval modes — no separate vector store:

| Mode | Mechanism | Answers |
|------|-----------|---------|
| **Graph RAG** | Cypher traversal | "Who needs to approve?" "What rules does this trigger?" "What goals does this conflict with?" |
| **Vector RAG** | `decision_embeddings` index (1536d cosine) | "Find similar past decisions and their outcomes" |

---

## Validation Pipeline

```
POST /v1/validate
        │
        ├─ Layer 1 (Deterministic)
        │    ├─ Load company config (configs/{company_id}.json)
        │    ├─ Evaluate governance rules (generic condition operators)
        │    ├─ Derive approval chain
        │    └─ Score risk across 3 dimensions
        │
        └─ Layer 2 (LangGraph Governance Agent)
             ├─ agent_node   ──► tool_node (max 3 rounds)
             │    Tools:
             │    • search_governance_rules   (filtered by decision dimensions)
             │    • search_similar_decisions  (vector RAG)
             │    • get_goal_conflicts        (graph traversal)
             │    • get_governance_gaps       (gap detection)
             │    • query_graph               (safe read-only Cypher)
             │    • get_operational_context   (budget, headcount snapshot)
             └─ synthesize_node ──► END
                  Returns: verdict, confidence, reasoning, gaps, precedents
```

### Governance Rules — Config-Driven

No rule IDs or company names are hardcoded in application logic. Rules live in JSON config:

```json
{
  "rule_id": "R1",
  "name": "CFO Approval Required",
  "condition": { "field": "cost", "operator": ">", "value": 50000 },
  "consequence": { "action": "require_approval", "approver_role": "CFO" }
}
```

The condition evaluator reads `field`, `operator`, `value` generically. Same engine, different config per client.

### Risk Scoring

Three independent dimensions, each 0-100:

| Dimension | Weight | Key Inputs |
|-----------|--------|------------|
| **Financial** | 0.40 | Cost vs. budget (log-scale), threshold bonuses, triggered financial rules |
| **Compliance/Privacy** | 0.35 | PII usage (+60 base), compliance risk flag, critical rule triggers |
| **Strategic** | 0.25 | SUPPORTS vs. CONFLICTS_WITH edge analysis on the ontology graph |

Bands: 0-39 LOW · 40-69 MEDIUM · 70-84 HIGH · 85-100 CRITICAL

Every score carries evidence — human-readable labels, source attribution, and confidence. No score is a black box.

**External signal adjustments** are applied before the aggregate is computed. When Tavily returns a relevant regulatory or market signal, the LLM extracts a structured `RiskAdjustment` (dimension, delta -15 to +15, confidence-weighted) that shifts the affected dimension score. A GDPR enforcement trend pushing compliance from 70 → 83 is treated as a first-class risk input, not a footnote.

### External Signals

Real-time market and regulatory context fetched per decision via Tavily search + LLM synthesis:

```
Decision context → Tavily queries (1-2 targeted)
       │
       ▼
Raw search results → LLM (fast tier) → ExternalSignal[] + RiskAdjustment[]
       │                                       │
       │                               ← applied to risk scores
       │
       ▼
Governance agent receives signal summaries as context
```

| Signal Type | Examples |
|-------------|---------|
| `regulatory_guidance` | "GDPR enforcement actions up 40% in 2024" → +9 compliance |
| `market_benchmark` | "ML engineer median comp $185K — your $150K is below market" → -5 financial |
| `trend_signal` | "Series B hiring freeze trend — 60% of peers paused headcount" → +6 strategic |
| `industry_benchmark` | "AWS reserved pricing dropped 12% this quarter" → -4 financial |

Falls back to curated static signals when `TAVILY_API_KEY` is not set. All failures are non-fatal.

---

## Onboarding Pipeline

```
Orchestrator
    │
    ├── Document Scout    (PDFs, policy docs, org charts)
    ├── Conversation Scout (email threads, Slack, meeting minutes)
    ├── Data Scout         (spreadsheets, approval logs, CSVs)
    └── Edge Audit Scout   (validates edge quality, removes orphans)
              │
        Transform Pipeline
              │
    ├── Chunker      (splits artifacts into ~512 token chunks)
    ├── Embedder     (OpenAI text-embedding-3-small, 1536d, batch)
    ├── Ontologizer  (LLM: chunk → typed nodes + edges)
    └── Writer       (MERGE domain nodes, CREATE instance nodes → Neo4j)
```

The `onboarding_graph.py` LangGraph application coordinates all agents with `Send` API for parallel fan-out.

---

## Neo4j Design

### Node Identity

```
{company_id}:{node_type}:{semantic_identifier}

Examples:
  nexus_analytics:goal:revenue_growth
  nexus_analytics:rule:R1
  nexus_analytics:actor:cfo
```

### MERGE vs CREATE

| Node Type | Cypher | Reason |
|-----------|--------|--------|
| Goals, Rules, Actors, Hierarchy | `MERGE` | Exist once. All decisions link to the same node. |
| Decisions, Outcomes | `CREATE` | Always new. Timestamped. Permanent audit trail. |
| Chunk nodes | `MERGE` on content hash | Same text from same source = same node. |

### Multi-Tenant Isolation

Separate Neo4j database per company — not shared database with company_id partitioning.

```python
# config/neo4j.py
def get_company_database(company_id: str) -> str:
    env_key = f"NEO4J_DB_{company_id.upper()}"
    return os.getenv(env_key, f"{company_id}_governance")
```

### Vector Index

```cypher
CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
FOR (c:Chunk) ON c.embedding
OPTIONS { indexConfig: { `vector.dimensions`: 1536, `vector.similarity_function`: 'cosine' } }
```

Nodes that get embeddings: `Chunk`, `Decision`, `Outcome`
Nodes without embeddings: `Rule`, `Actor`, `Goal`, `Edge relationships`

---

## LLM Configuration

Provider-agnostic — never hardcoded. All config via env vars:

```bash
LLM_PROVIDER=anthropic       # anthropic | openai
LLM_MODEL_FAST=claude-haiku-4-5-20251001   # extraction, classification, summarization
LLM_MODEL_CAPABLE=claude-sonnet-4-6        # graph reasoning, contradiction analysis, synthesis
```

```python
from app.config.llm import get_llm

fast_llm    = get_llm("fast")     # scout extraction, ontologizer
capable_llm = get_llm("capable")  # governance agent synthesis
```

| Provider | Fast model | Capable model |
|----------|-----------|---------------|
| Anthropic | claude-haiku-4-5 | claude-sonnet-4-6 |
| OpenAI | gpt-5.4-mini | gpt-5.4 |

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Runtime | Python 3.12, FastAPI, Uvicorn |
| LLM abstraction | LangChain (langchain-core, langchain-anthropic, langchain-openai, langchain-aws) |
| Onboarding pipeline | LangGraph — scout swarm orchestration, parallel fan-out, stateful agent graph |
| Validation agent | LangGraph — dynamic reasoning, tool calling, conditional routing |
| Graph + vector storage | Neo4j 5.11+ — native vector index, no separate vector store |
| Embeddings | OpenAI text-embedding-3-small (1536d) |
| Validation | Pydantic v2 — all LLM outputs validated before use |
| External signals | Tavily search + LLM synthesis → `RiskAdjustment[]` (curated fallback when no API key) |
| Database | SQLite (dev) + SQLAlchemy ORM + Alembic |
| Auth | JWT + RBAC + Google OAuth2 + Azure AD OIDC |

---

## Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/validate` | Submit a decision for full governance validation (synchronous) |
| `POST` | `/v1/decisions` | Legacy pipeline submission |
| `GET` | `/v1/decisions/{id}` | Full governance result |
| `POST` | `/v1/companies/{id}/context` | Push Tier 2 operational snapshot (budget, headcount) |
| `GET` | `/v1/auth/sso/{google,azure}/{authorize,callback}` | SSO flows |

### Example: Validate a Decision

```bash
curl -X POST http://localhost:8001/v1/validate \
  -H "Content-Type: application/json" \
  -d '{
    "decision_text": "Hire 3 senior ML engineers at $150K each",
    "decision_dimensions": {
      "cost": 450000,
      "involves_hiring": true,
      "headcount_change": 3
    },
    "company_id": "nexus_analytics"
  }'
```

```json
{
  "verdict": "ESCALATE",
  "confidence": 0.94,
  "reasoning": "The proposal triggers R1 (CFO approval >$50K), R2 (Board approval >$200K), and R5 (hiring review). All three governance steps must complete before this decision can proceed.",
  "triggered_rules": [
    { "rule_id": "R1", "name": "CFO Approval Required" },
    { "rule_id": "R2", "name": "Board Approval Required" },
    { "rule_id": "R5", "name": "Hiring Review" }
  ],
  "approval_chain": [
    { "role": "CFO", "order": 1 },
    { "role": "Board", "order": 2 },
    { "role": "Department Head", "order": 3 }
  ],
  "risk_score": {
    "aggregate": { "score": 61, "band": "MEDIUM" },
    "financial": { "score": 72 },
    "compliance_privacy": { "score": 0 },
    "strategic": { "score": 50 }
  },
  "external_signals": {
    "marketSignals": [
      {
        "title": "ML Engineer Compensation Benchmarks — B2B SaaS 2024",
        "summary": "Median ML engineer comp in B2B SaaS reached $185K in 2024.",
        "decisionRelevance": "Your proposed $150K is 19% below market, which may affect hiring success.",
        "confidence": 0.82
      }
    ],
    "regulatorySignals": [],
    "operationalSignals": [],
    "riskAdjustments": [
      {
        "dimension": "financial",
        "delta": -4,
        "rationale": "Below-market comp reduces absolute spend risk but signals potential quality risk.",
        "confidence": 0.75
      }
    ]
  }
}
```

---

## Project Structure

```
decision-governance-layer/
├── app/
│   ├── main.py                        # FastAPI app, lifespan, CORS, routers
│   ├── governance.py                  # Deterministic rule engine (no hardcoded rules)
│   ├── config/
│   │   ├── llm.py                     # Provider-agnostic LLM factory (get_llm)
│   │   ├── company_config.py          # CompanyConfig Pydantic model
│   │   ├── company_registry.py        # Config loader (configs/*.json)
│   │   ├── neo4j.py                   # Neo4j connection + per-company database routing
│   │   └── risk_config.py             # Dimension weights, band thresholds
│   ├── ontology/
│   │   ├── node_types.py              # NodeType enum (8 types with Neo4j labels)
│   │   ├── edge_predicates.py         # EdgePredicate enum (12 typed predicates)
│   │   ├── models.py                  # Node, Edge dataclasses
│   │   └── init_schema.py             # Neo4j constraint + index creation
│   ├── graph/
│   │   ├── base.py                    # BaseGraphRepository abstract interface
│   │   ├── neo4j_repository.py        # Production: Neo4j 5.11+, hybrid RAG, safe Cypher
│   │   └── in_memory_repository.py    # Dev/test: lazy adjacency index, LRU eviction
│   ├── onboarding/
│   │   ├── onboarding_graph.py        # LangGraph app (orchestrator + scout swarm)
│   │   ├── prompts.py                 # Scout + transform prompt templates
│   │   ├── schemas.py                 # Onboarding state + artifact models
│   │   ├── seed.py                    # Initial graph seeding from company config
│   │   ├── validation.py              # Post-onboarding graph validation
│   │   ├── scouts/
│   │   │   ├── base.py                # Base scout interface
│   │   │   ├── document_scout.py      # PDFs, policy docs, org charts
│   │   │   ├── conversation_scout.py  # Email threads, Slack, meeting minutes
│   │   │   ├── data_scout.py          # Spreadsheets, approval logs, CSVs
│   │   │   └── edge_audit_scout.py    # Edge quality validation, orphan removal
│   │   └── transform/
│   │       ├── chunker.py             # ~512 token chunk splitting
│   │       ├── embedder.py            # Batch OpenAI embeddings
│   │       ├── ontologizer.py         # LLM: chunk → typed nodes + edges
│   │       └── writer.py              # MERGE/CREATE → Neo4j
│   ├── validation/
│   │   ├── schemas.py                 # ValidationState (TypedDict), ValidationResult, GovernanceVerdict
│   │   ├── governance_agent.py        # LangGraph governance agent (agent→tools→synthesize)
│   │   └── tools.py                   # 6 LangChain tools (graph RAG, vector RAG, gap detection)
│   ├── providers/
│   │   ├── tavily_live_fetch_provider.py      # Tavily search → ExternalSignal[]
│   │   └── curated_external_signal_provider.py # Static fallback signals (no API key needed)
│   ├── services/
│   │   ├── pipeline_service.py        # Async pipeline orchestrator
│   │   ├── risk_scoring_service.py    # 3-dimension quantified risk scoring with evidence
│   │   ├── risk_response_simulation_service.py  # Counterfactual scenario engine
│   │   ├── risk_evidence_llm.py       # Structured LLM semantics (optional, non-fatal)
│   │   ├── external_signal_service.py # Market/regulatory signal orchestrator
│   │   ├── evidence_registry_service.py # Evidence provenance tracking
│   │   ├── decision_context_service.py  # Decision context enrichment
│   │   ├── company_service.py         # Company CRUD
│   │   ├── user_service.py            # User CRUD
│   │   ├── auth_service.py            # JWT token management
│   │   ├── rbac_service.py            # Role-based access control
│   │   └── sso_service.py             # Google OAuth2, Azure AD OIDC
│   ├── routers/
│   │   ├── validation.py              # POST /v1/validate
│   │   ├── decisions.py               # Legacy pipeline endpoints
│   │   ├── workspace.py               # Dashboard + metrics
│   │   ├── analysis.py                # Decision entity extraction
│   │   ├── agents.py                  # Agent registry + escalation rules
│   │   ├── companies.py               # Company management
│   │   ├── auth.py                    # JWT auth
│   │   ├── sso.py                     # SSO callbacks
│   │   ├── fixtures.py                # Demo data fixtures
│   │   └── normalizers.py             # Response shape enforcement
│   ├── schemas/                       # Pydantic v2 request/response contracts
│   ├── models/                        # SQLAlchemy ORM (User, Company, Agent, Decision)
│   ├── repositories/                  # Data access layer
│   └── demo_fixtures/                 # External profiles + signal sources
│       ├── external_profiles/         # Company external context profiles
│       └── external_sources/          # Curated signal source definitions
├── configs/
│   └── nexus_analytics.json           # Company 1 governance config (rules, goals, hierarchy)
├── dev/
│   └── simulate/
│       ├── simulate_company.py        # Mock artifact generator (gitignored output)
│       ├── personas/                  # Company persona definitions
│       └── ground_truth/              # Expected ontology for eval
├── scripts/
│   ├── generate_decision_history.py   # Seed synthetic Decision nodes into Neo4j (run once)
│   └── run_onboarding.py             # Run onboarding pipeline for a company
├── tests/                             # 301 tests (pytest)
├── alembic/versions/                  # DB migrations
└── docs/
    ├── ONBOARDING_SPEC.md
    └── PHASE2_VALIDATION_TODOS.md
```

---

## Quick Start

```bash
# 1. Create virtualenv
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Environment
cp .env.example .env
# Required:
#   LLM_PROVIDER=anthropic     (or openai)
#   ANTHROPIC_API_KEY=sk-...   (or OPENAI_API_KEY)
#   JWT_SECRET=<random secret>
# Optional (Neo4j):
#   NEO4J_URI=bolt://localhost:7687
#   NEO4J_USER=neo4j
#   NEO4J_PASSWORD=password
#   NEO4J_DB_NEXUS_ANALYTICS=neo4j
# Optional (live external signals):
#   TAVILY_API_KEY=tvly-...   ← without this, falls back to curated static signals

# 3. Database migrations
alembic upgrade head

# 4. Run
uvicorn app.main:app --reload --port 8001

# 5. Test
python -m pytest tests/ -v    # 301 tests
```

### Neo4j (optional, for full Phase 2)

```bash
# Start local Neo4j via Docker
docker run -d \
  --name neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/password \
  neo4j:5.11

# Run onboarding to build the knowledge graph
python -m app.onboarding.onboarding_graph --company nexus_analytics

# Seed synthetic decision history for vector RAG
python scripts/generate_decision_history.py
```

---

## Frontend Repo

https://github.com/RainaKim/Sentra

## Demo Companies

| Company | Industry | Size | Primary Governance Focus |
|---------|----------|------|--------------------------|
| **Nexus Analytics** | B2B SaaS | 120 employees, Series B | Spend approvals, headcount, vendor contracts, data privacy |
| Architecture firm (TBD) | Architecture/construction | — | Image artifacts, building codes, permit workflows |

Company 1 governance rules:

| Rule | Condition | Consequence |
|------|-----------|-------------|
| R1 | cost > $50,000 | CFO approval |
| R2 | cost > $200,000 | Board approval |
| R3 | uses_pii = true | General Counsel review |
| R4 | vendor_contract_value > $100,000 | Procurement review |
| R5 | involves_hiring = true | Department Head approval |
| R6 | headcount_change > 0 | Workforce tracking flag |
| R7 | discount_pct > 20 | VP Sales approval |

---

## Core Design Principles

1. **No industry-specific logic in application code** — everything domain-specific lives in `configs/*.json`
2. **MERGE company nodes, CREATE decision nodes** — never the other way around
3. **Deterministic core, dynamic agent layer** — governance rules are never probabilistic
4. **One Neo4j database per company** — never mix company data
5. **Stable node IDs** — `{company_id}:{node_type}:{semantic_id}` always
6. **Validate all LLM output with Pydantic** — never trust raw LLM JSON
7. **No separate vector store** — Neo4j vector index only
8. **LangChain in `app/`, direct Anthropic SDK in `dev/`** — never mix

---

## Test Coverage

301 tests across 16 test files (4 additional files skipped pending refactor):

| Area | Tests |
|------|-------|
| Onboarding Pipeline (scout swarm, transform, graph seeding) | 47 |
| Phase 2: Graph RAG (hybrid retrieval, Cypher safety) | 32 |
| Phase 2: Governance Agent (LangGraph, tool calling) | 32 |
| Risk Scoring (3 dimensions, bands, evidence provenance) | 32 |
| Graph Validation (ontology constraints, edge predicates) | 29 |
| Auth (JWT, signup, login) | 23 |
| Neo4j Schema (constraints, indexes, init) | 22 |
| Onboarding Seed (config → graph seeding) | 21 |
| Phase 2: Decision Pack wiring | 20 |
| SSO (Google OAuth2, Azure AD OIDC) | 15 |
| RBAC (role enforcement, tenant isolation) | 14 |
| Risk Semantics (LLM fallback layer) | 14 |

4 test files currently skipped (depend on old fixtures pending refactor):
`test_evidence_registry_service`, `test_external_signal_service`,
`test_governance_evidence_integration`, `test_risk_response_simulation`
