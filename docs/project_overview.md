# DecisionGovernance AI — Project Overview

## What this is

DecisionGovernance AI is **AI Decision Governance Infrastructure** — a governance layer that sits between AI agents and real-world execution. When an AI agent proposes a decision (hire engineers, allocate budget, process customer data, launch a product), the system validates it against company governance rules, organizational strategy, compliance requirements, and historical precedent before a human approves or rejects it.

This is not a chatbot. Not a copilot. It is the infrastructure layer that makes AI agents safe to deploy in enterprise operations.

> The biggest obstacle to enterprise AI adoption is not model capability — it is trust, accountability, and governance.

---

## The problem

Enterprises cannot allow AI agents to act autonomously because:

- AI can violate internal policies or budget limits
- Sensitive data can be processed without compliance checks
- Actions can execute without the correct approval chain
- Accountability is unclear when something goes wrong

Today, companies lack a structured way to ensure that AI decisions follow internal rules, authority structures, and strategic goals.

---

## What it does

The system intercepts AI-generated decisions and converts them into structured, governable decision objects. These are evaluated through a multi-layer governance engine and produce a **Decision Pack** — an approval-ready artifact that tells an executive exactly what was decided, why it is or isn't safe, who needs to approve it, and what alternatives exist.

### Pipeline

```
AI agent proposes decision (natural language)
              ↓
LLM extraction — structured decision object
              ↓
Ontology graph mapping — typed nodes + edges
              ↓
Deterministic governance engine — rule evaluation
              ↓
Risk scoring — 3 dimensions: financial, compliance, strategic
              ↓
Governance agent — dynamic reasoning, gap detection, historical retrieval
              ↓
Decision Pack — verdict + evidence + approval chain + recommendations
```

---

## Architecture

### Two-phase system

**Phase 1 — Onboarding (once per client)**
Builds the company's governance ontology graph in Neo4j from existing artifacts — policy documents, org charts, emails, Slack history, Jira tickets, spreadsheets, and interview transcripts. Uses reverse ontology construction: structure is derived from data, not imposed on it.

**Phase 2 — Validation (every AI decision)**
Runs each proposed decision through the governance pipeline against the populated ontology graph. Produces a Decision Pack with full reasoning trail.

### Three-layer ontology

```
Meta-layer      Universal governance primitives
                Risk · Authority · Conflict · Resolution · Compliance
                Shared across all companies and industries

Domain-layer    Company-specific governance vocabulary
                Derived at onboarding from client artifacts
                Different per client

Instance-layer  Concrete data — actual people, rules, numbers, decisions
                Fully isolated per client
                Grows with every decision run
```

### Hybrid RAG

**Graph RAG** — traverses typed edges in Neo4j to find structurally related past decisions. Answers governance-structural questions: who approved similar decisions, what happened when this conflict was overridden, what did history show about this pattern.

**Vector RAG** — semantic similarity search over embedded artifact chunks. Answers context questions: what policy is relevant to this decision, what past email threads discussed similar situations. Uses Neo4j's built-in vector index — no separate vector store.

---

## Current tech stack

| Layer | Technology |
|-------|-----------|
| Runtime | Python 3.12, FastAPI, Uvicorn |
| LLM abstraction | LangChain — provider-agnostic (Claude, GPT-4, Bedrock) |
| Agent orchestration | LangGraph — onboarding pipeline + validation agent |
| Graph + vector storage | Neo4j 5.11+ with native vector index |
| Embeddings | OpenAI text-embedding-3-small (1536d) |
| Validation | Pydantic v2 |
| Database | SQLite (dev) + SQLAlchemy ORM + Alembic |
| Auth | JWT + RBAC + Google OAuth2 + Azure AD OIDC |

---

## Key design principles

### Deterministic core, dynamic agent layer
Governance rules produce the same result for the same inputs every time. The LLM agent layer reasons over that deterministic output — it explains, enriches, and recommends. It never overrides the deterministic verdict.

### Reverse ontology construction
We do not ask clients to define an ontology schema. We ask for what already exists — documents, data, institutional knowledge — and derive the ontology from those artifacts. The scout swarm fans out across all artifact types, the transform pipeline extracts governance knowledge, and the resulting graph captures both documented and undocumented governance rules.

### Industry-agnostic by design
No industry-specific logic in application code. Everything domain-specific lives in company config. The same pipeline handles a fintech, a hospital, and an architecture firm — only the config differs.

### Organizational memory
Every decision that runs through the system is permanently stored in the governance graph. Past decisions, verdicts, outcomes, and remediations accumulate as Tier 3 history. This enables Graph RAG to retrieve structurally similar past decisions and tell the governance agent what happened the last time this situation occurred.

---

## Three data tiers

| Tier | Contents | Update frequency |
|------|----------|-----------------|
| Tier 1 — Governance config | Goals, rules, org hierarchy, approval chains, thresholds | Onboarded once, rarely changes |
| Tier 2 — Operational snapshots | Budget remaining, headcount vs plan, active risk flags | Weekly or on change via API |
| Tier 3 — Decision history | Past decisions, verdicts, outcomes, remediation taken | Every pipeline run, automatic |

---

## Onboarding agent team

Eight agents in two tiers, orchestrated by LangGraph:

```
Orchestrator                    — coordinates entire onboarding run

Scout swarm (parallel):
  Document scout                — PDFs, policy docs, org charts
  Conversation scout            — emails, Slack, meeting minutes, interview
  Data scout                    — spreadsheets, approval logs, budget data
  Web scout                     — public regulatory context for industry
  Image scout                   — visual artifacts, blueprints, diagrams

Transform + synthesis (sequential):
  Transform agent               — parse → chunk → embed → linkback → edge leverage → ontologize
  Validation agent              — confidence scoring, gap report, human review prep

Interview agent (parallel track):
  LLM-driven conversation       — captures undocumented governance knowledge
  Four question categories:     failure history, informal authority,
                                 fast approval conditions, unwritten rules
```

---

## Validation pipeline

### Layer 1 — Deterministic governance core
```
Extraction → Rule engine → Ontology traversal →
Risk scoring → Approval chain → Governance result
```

### Layer 2 — Governance agent
Receives Layer 1 result. Dynamically decides what additional context is needed.

Tools: `query_graph`, `get_operational_context`, `search_external_signals`

Gap handling:
- External knowledge gap → auto-collect via web search
- Internal data gap → surface integration request in Decision Pack
- Governance config gap → flag for human, issue verdict with lower confidence

---

## Decision Pack

The final output. Contains:

- Governance verdict — approved / review required / blocked
- Risk scores — financial, compliance, strategic (0-100 with evidence)
- Approval chain — who must approve, in what order
- Reasoning trail — why each rule was triggered, what each score means
- Historical precedents — structurally similar past decisions and outcomes
- Simulation scenarios — alternative approaches with re-evaluated risk
- Gap section — what's missing, what integration would improve accuracy
- Recommended next actions — what should happen after this verdict

---

## What's next

- Persistent governance graph (Neo4j) with cross-decision reasoning
- Graph-RAG decision memory — organizational memory for AI governance
- Formal OWL/SHACL ontology inference rules
- Enterprise integrations — Slack, Notion, Jira, policy repositories
- AI agent governance boundaries — define what agents may execute autonomously
- Live Tier 2 operational context — real-time budget and headcount signals

---

## Positioning

DecisionGovernance AI is the governance gate that sits in front of any AI execution layer. It answers "should this happen?" with deep reasoning before any system answers "make it happen." Complementary to platforms like Palantir AIP — governance first, execution second.

> DecisionGovernance AI is designed as long-term governance infrastructure for the AI agent era.