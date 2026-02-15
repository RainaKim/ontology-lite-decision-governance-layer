# Architecture - Ontology-lite Decision Governance Layer

## Core Philosophy

**Governance determines the decision.**
**Graph stores the reasoning structure.**
**Decision Pack is the final human-facing artifact.**

---

## Three-Layer Architecture

```
┌─────────────────────────────────────┐
│   Decision Pack (Human Layer)       │  ← Template-based output
│   - Approval chains                 │
│   - Recommended actions             │
│   - Audit trails                    │
└─────────────────────────────────────┘
              ▲
              │
┌─────────────────────────────────────┐
│   Governance Engine (Logic Layer)   │  ← Deterministic rules
│   - Risk scoring                    │
│   - Flag detection                  │
│   - Approval routing                │
└─────────────────────────────────────┘
              ▲
              │
┌─────────────────────────────────────┐
│   Graph Repository (Memory Layer)   │  ← Structural memory
│   - Node/edge storage               │
│   - Relationship traversal          │
│   - Context retrieval               │
└─────────────────────────────────────┘
```

---

## Why This Architecture?

### 1. Governance is Deterministic

**No LLM in the critical path.**

- Rule evaluation uses pure Python logic
- Conditions are boolean expressions (>=, ==, contains)
- Priority-based rule matching (highest priority wins)
- Output is reproducible and auditable

**Why?**
- Enterprises cannot deploy non-deterministic governance
- Legal/compliance requires explainable decisions
- Debugging AI governance is impossible

### 2. Graph is Memory

**Not GraphRAG. Not a knowledge graph. Structural memory.**

The graph stores:
- **What** was decided (Action nodes)
- **Who** owns/approves it (Actor nodes)
- **Why** it matters (Risk nodes)
- **How** it's governed (Policy nodes)
- **Relationships** between them (edges)

**Why graph vs relational?**
- Governance is inherently relational (who approves what, what triggers what)
- Traversal queries are natural ("show me all decisions this actor approved")
- Schema evolution is easier (add node types without migrations)
- Future: Graph algorithms (pagerank for critical actors, path analysis for bottlenecks)

**Why NOT GraphRAG?**
- We're not embedding documents
- We're not doing semantic search
- We're modeling operational structure, not knowledge

### 3. Decision Pack is Last

**Human-facing artifact generated from graph + governance.**

- Not stored (derived on demand)
- Template-based (deterministic formatting)
- Combines governance evaluation + graph context

**Why generate vs store?**
- Single source of truth (graph)
- Always current (re-compute with latest rules)
- No sync issues

---

## Repository Pattern

### Interface: `BaseGraphRepository`

Abstract methods:
```python
add_node(node)
add_edge(edge)
upsert_decision_graph(decision, governance)
get_governance_context(decision_id, depth)
```

### Implementations

**Day 1-2: `InMemoryGraphRepository`**
- Dict-based storage
- No dependencies
- Demo-stable
- Fast for hackathon

**Day 3+: `Neo4jGraphRepository`** (not yet built)
- Cypher queries
- Persistent storage
- Enterprise scale
- Drop-in replacement (same interface)

**Critical:** Service layer never imports concrete repository.
Always program against `BaseGraphRepository`.

---

## Ontology-lite Design

### Node Types (5)
- **Actor**: Who (people, roles, departments)
- **Action**: What (decisions, tasks)
- **Policy**: How (rules, constraints)
- **Risk**: Why not (threats, concerns)
- **Resource**: With what (budget, systems)

### Edge Predicates (6)
- **OWNS**: Actor owns Action/Resource
- **REQUIRES_APPROVAL_BY**: Action requires Actor approval
- **GOVERNED_BY**: Action governed by Policy
- **TRIGGERS**: Action triggers Policy/Risk
- **IMPACTS**: Action impacts Resource/Actor
- **MITIGATES**: Action mitigates Risk

### Why "Lite"?

Full ontology = hundreds of entity types + complex reasoning.

We use **just enough structure** to:
- Model decisions
- Enforce governance
- Enable queries
- Support audit

Without:
- Inference engines
- Semantic reasoning
- Complex taxonomies

---

## Data Flow

```
User Input (free text)
  ↓
[LLM] Extract → Decision object
  ↓
[Governance] Evaluate → Flags + Approval Chain + Risk Score
  ↓
[Graph] Store → Nodes + Edges
  ↓
[Decision Pack] Generate → Human-readable artifact
```

**Deterministic:** Governance evaluation, graph storage, pack generation
**LLM-powered:** Only decision extraction (Day 3+ scope)

---

## Evolution Path

**Hackathon (Day 1-2):**
- InMemory graph
- Mock rules
- Manual decision input

**Week 2:**
- Neo4j integration
- LLM extraction
- REST API

**Month 2:**
- Graph analytics (approval bottlenecks, risk clustering)
- Real-time policy updates
- Audit dashboards

**Month 3:**
- Multi-tenant
- Policy versioning
- Decision history/rollback

---

## Key Design Decisions

### ✅ Decisions We Made

1. **Graph-native from day 1** (even in-memory)
   - Forces correct abstractions
   - Prevents relational thinking
   - Easy backend swap later

2. **Repository pattern** (not ORM)
   - Cleaner abstractions
   - No framework lock-in
   - Testable

3. **Deterministic governance** (no LLM)
   - Reproducible
   - Auditable
   - Debuggable

4. **Template-based packs** (no generative text)
   - Consistent format
   - No hallucinations
   - Legal-safe

### ❌ Decisions We Avoided

1. **No GraphRAG**
   - We're not searching documents
   - We're modeling structure

2. **No distributed graph**
   - Hackathon scope
   - Single-node Neo4j is fine

3. **No real-time streaming**
   - REST API sufficient
   - Batch governance is acceptable

4. **No heavy ontology**
   - 5 node types enough
   - Extensible via properties

---

## Testing Strategy

**Unit tests:** Each helper function
**Integration tests:** Governance + graph together
**Demo stability:** InMemory repo = no external dependencies

---

## One-Line Summary

> **Graph-native decision governance with deterministic rules, swappable storage, and template-based human outputs — optimized for hackathon speed and enterprise evolution.**
