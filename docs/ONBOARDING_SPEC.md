# DecisionGovernance AI — Onboarding Specification

**Version:** 1.0  
**Status:** Internal planning document

---

## Purpose

This document specifies the onboarding process for new enterprise clients. Onboarding is the process of constructing a company's governance ontology graph in Neo4j — the persistent knowledge structure that all subsequent AI decision validation runs against.

Onboarding happens once per client, before any validation pipeline runs. The quality and completeness of the governance graph produced at onboarding directly determines the quality of every governance verdict the system produces for that client.

> **Key principle:** We do not ask clients to build an ontology from scratch. We ask for what already exists — documents, data, institutional knowledge — and derive the ontology from those artifacts using reverse ontology construction.

---

## Ontology architecture

Three layers. Bottom layer fully isolated per client. Top layer universal across all clients.

| Layer | Contents | Scope | Changes when |
|-------|----------|-------|-------------|
| Meta-layer | Risk, Authority, Conflict, Resolution, Compliance | Universal — all companies | Never |
| Domain-layer | Company-specific rules, goals, vocabulary | Per client | Company policy changes |
| Instance-layer | Actual people, thresholds, decisions, numbers | Fully isolated per client | Every decision run |

Each layer answers four questions:
1. What exists?
2. What is connected to what, and how?
3. What happens, in what order and under what conditions?
4. What criteria judge good from bad, right from wrong?

### Meta-ontological classification

Every node in the system must be classifiable as one of four primitives:

| Primitive | Governance concept | Examples |
|-----------|-------------------|---------|
| Entity | Things that persist | Company, Actor, Rule, Goal |
| Relation | How things connect | Conflict, Authority, Approval |
| Process | Things that happen over time | Decision, Validation, Onboarding |
| Quality | How things are judged | Risk, Compliance, Confidence |

This classification prevents category errors in the graph and ensures interoperability.

---

## Data tiers

| Tier | Contents | Update frequency | Source |
|------|----------|-----------------|--------|
| Tier 1 — Governance config | Goals, rules, org hierarchy, approval chains, thresholds, compliance requirements | Onboarded once, rarely changes | Artifacts + interview |
| Tier 2 — Operational snapshots | Budget remaining, headcount vs plan, active risk flags, pending decisions, audit status | Weekly or on change | Client pushes via `POST /v1/companies/{id}/context` |
| Tier 3 — Decision history | Past decisions, verdicts, outcomes, remediation taken, approval results | Every pipeline run | Generated automatically |

Tier 3 starts empty at onboarding and accumulates with every validation run. No client input required.

---

## Three onboarding phases

### Phase 1 — Artifact collection

Collect what already exists. No schema to fill in from scratch.

**Four artifact categories:**

| Structured | Unstructured |
|-----------|-------------|
| Policy manuals, compliance documents | Meeting minutes where decisions were debated |
| Org charts, authority matrices | Email threads where approvals happened |
| Budget frameworks, approval thresholds | Slack history (if available and permitted) |
| Existing governance frameworks | Past decision logs, audit records |

| Operational data | Undocumented knowledge |
|-----------------|----------------------|
| Budget spreadsheets by department | Interview transcript |
| Historical approval logs | Verbal governance rules never written down |
| Headcount trackers | Informal authority relationships |
| Compliance audit history | Edge cases and exceptions |

**Accepted artifact formats:**
- `.pdf`, `.docx`, `.md` — policy documents, org charts, manuals
- `.csv`, `.xlsx` — spreadsheets, budget data, approval logs
- Slack export `.json` — conversation history
- Jira export `.json` — ticket history
- Email `.eml` or `.txt` — threads, approvals
- `.png`, `.jpg` — visual org charts, process diagrams (image scout)
- `.txt` — meeting minutes, interview transcripts

**The onboarding interview**

Undocumented knowledge is captured through a structured LLM-driven conversation. This is the most valuable part of onboarding — institutional knowledge that exists in no document.

Four question categories:

| Category | Example questions |
|---------|------------------|
| Failure questions | "Tell me about a decision that went badly in the last 2 years. What should have stopped it? Who should have been consulted but wasn't?" |
| Informal authority | "Who in the org has informal veto power that doesn't appear in any org chart? Are there approvals your team does informally that aren't written down?" |
| Fast approvals | "What's the fastest a major decision has ever been approved? What made it fast? What conditions allow bypassing normal process?" |
| Exception rules | "What's the one rule everyone follows but nobody ever wrote down? What types of decisions always get escalated even when policy doesn't require it?" |

Interview answers are processed by the same transform pipeline as documents. Every captured rule receives `source: "interview"` provenance in the graph.

---

### Phase 2 — Reverse ontology construction

Derive the ontology from artifacts. Structure emerges from data, not the other way around.

**Scout swarm**

Five specialized agents fan out across collected artifacts simultaneously:

| Scout | Handles |
|-------|---------|
| Document scout | PDFs, policy docs, org charts, compliance manuals |
| Conversation scout | Meeting minutes, email threads, Slack exports, interview transcript |
| Data scout | Spreadsheets, approval logs, budget data |
| Web scout | Public regulatory context for this industry and jurisdiction |
| Image scout | Visual artifacts — runs vision model first, then same transform pipeline |

Scouts run in parallel. Each produces candidate ontology nodes and edges with raw evidence attached. They do not write to Neo4j directly — outputs feed into the transform agent.

**Transform pipeline**

Every artifact from every scout passes through the same sequential transform:

```
Parse        → extract clean text from PDFs, HTML, tables, structured documents
Chunk        → split into meaningful semantic units, not arbitrary character counts
Embed        → encode semantic meaning as vectors (OpenAI text-embedding-3-small, 1536d)
Linkback     → connect chunk to existing ontology nodes
               "this chunk is evidence for nexus:rule:R7"
Edge leverage → derive new structural relationships implied by content
               "regulation X implies rule Y should exist"
Ontologize   → write typed nodes and edges into Neo4j
               raw knowledge becomes graph structure
```

**Linkback vs edge leverage — critical distinction:**
- Linkback enriches existing nodes — connects new content to what's already in the graph
- Edge leverage grows the graph — derives new nodes and edges from implications in content
- Both steps assign confidence scores based on evidence strength

**Four-question extraction at each layer:**

| Instance layer | Domain layer | Meta layer |
|---------------|-------------|-----------|
| What concrete entities appear? | What governance concepts recur? | What universal primitives apply? |
| Which specific edges connect instances? | Who approves what? What conflicts with what? | How do domain concepts map to Entity/Relation/Process/Quality? |
| What does the pipeline actually execute? | What triggers what approval chain? | What are the universal governance patterns? |
| What values are used for thresholds? | What risk thresholds determine verdicts? | What is the governance reasoning structure? |

---

### Phase 3 — Validation and gap surfacing

Human reviews the derived ontology. Refine and confirm — not rebuild from scratch.

**Confidence scoring**

Every derived node and edge receives a confidence score:

| Confidence | Evidence | Human action | Example source |
|-----------|---------|-------------|---------------|
| High | 3+ artifacts with explicit language | Quick confirmation | `"policy_manual_p12, interview_Q3"` |
| Medium | Single source or ambiguous language | Review, correct, or expand | `"single_email_thread"` |
| Low | Referenced but never defined | Surfaced as explicit gap | `"inferred_from_threshold"` |

**Gap categories**

| Type | Description | Resolution |
|------|-------------|-----------|
| Governance config gap | Missing rules, undefined approvers, incomplete approval chains | Human governance expert must define explicitly |
| Internal data gap | Budget, headcount, audit status — exists in client systems but not connected | Integration request surfaced in Decision Pack — `POST /v1/companies/{id}/context` |
| External knowledge gap | Market benchmarks, regulatory signals, industry context | Scout agent collects autonomously — advisory only, never modifies verdict |

**Who reviews**

The reviewing human should be a governance expert at the client company — typically a COO, General Counsel, or Head of Compliance. Expected time: 2-4 hours. They are reviewing and refining, not constructing.

---

## What onboarding produces

At the end of Phase 3, Neo4j contains:

| Contents | Detail |
|----------|--------|
| Company nodes (goals, rules, actors, hierarchy) | All with confidence scores and source provenance |
| Meta-layer alignment | Universal governance concepts mapped |
| Domain-layer vocabulary | Company-specific rules and relationships |
| Instance-layer data | Actual names, actual thresholds, actual budgets |
| Tier 2 operational snapshot | Current budget, headcount, risk flags |
| Source provenance on every node | Which artifact or interview question produced it |

Every node has a `source` property recording which artifact it came from, which interview question produced it, and what confidence level it was derived at. This is the audit trail for the ontology itself.

---

## Node identity scheme

Stable IDs for all company-level nodes:

```
{company_id}:{node_type}:{semantic_identifier}

Examples:
  nexus:goal:cost_stability
  nexus:rule:R7
  nexus:actor:hr_director
  mayo:goal:hipaa_compliance
  acme:actor:safety_director
```

**MERGE vs CREATE:**
- Company nodes (goals, rules, actors, hierarchy) → `MERGE` — exist once, shared across all decisions
- Decision nodes → `CREATE` — always new, always timestamped, permanent audit trail

---

## Gap handling during validation

When a gap is detected at validation time, the governance agent does not block. It produces a verdict with calibrated confidence and surfaces actionable next steps.

| Gap type | Example | Agent response |
|---------|---------|---------------|
| Governance config gap | No rule defined for this decision type | Flag in Decision Pack. Human must define rule before re-evaluation. |
| Internal data gap | No budget data for engineering department | Surface integration request: "Connect finance system via `POST /v1/companies/{id}/context`" |
| External knowledge gap | No market benchmark for this spend type | Agent autonomously collects public signals. Advisory only. Does not modify governance verdict. |

**Example gap section in Decision Pack:**
```
GOVERNANCE VERDICT: REVIEW REQUIRED  |  Confidence: MEDIUM (2 gaps)

Gap 1 — external knowledge [auto-filled]
  Market benchmark for engineering hiring costs retrieved from industry sources.
  Used for: financial risk calibration.

Gap 2 — internal data missing [integration needed]
  Current engineering budget remaining: unknown.
  Action: connect finance system via POST /v1/companies/{id}/context

Gap 3 — governance config incomplete [human required]
  No approval rule defined for APAC region decisions.
  Action: define APAC governance rules in company config.
```

---

## Ongoing graph maintenance

Onboarding is not a one-time event. The governance graph must stay current.

| Trigger | Description |
|---------|-------------|
| Triggered updates | Client signals a change — restructure, new policy, new executive. Re-run relevant scouts on new artifacts. |
| Scheduled refresh | Monthly re-scout of public regulatory sources for this industry and jurisdiction. |
| Organic growth | Every decision pipeline run appends Tier 3 decision and outcome nodes automatically. |
| Gap-driven updates | Validation flags a gap → integration request surfaces → client connects system → Tier 2 improves. |

Maintenance runs in the background and never blocks validation.

---

## Technology stack

| Component | Role |
|-----------|------|
| LangGraph | Scout swarm orchestration + interview agent |
| LangChain | LLM provider abstraction (swap Claude/GPT/Bedrock in config) |
| Neo4j | Persistent graph storage + vector index (hybrid RAG) |
| LangChain Neo4jGraph | Neo4j connection, schema introspection, query helpers |
| OpenAI embeddings | text-embedding-3-small, 1536 dimensions |
| FastAPI | Onboarding API endpoints |
| Pydantic v2 | Schema contracts for all ontology nodes, edges, payloads |

---

## Open questions

The following require further design decisions before implementation:

- **Interview agent depth** — full question set, probing logic, completion criteria
- **Confidence thresholds** — at what score does a node become active vs flagged
- **Re-onboarding** — full re-onboard vs targeted update on major policy change
- **Multi-tenant isolation** — separate Neo4j databases vs shared with `company_id` partitioning (current decision: separate databases)
- **Onboarding time SLA** — target end-to-end time for complete onboarding
- **Image scout vision model** — which vision model, what extraction schema