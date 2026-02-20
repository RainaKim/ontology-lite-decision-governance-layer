# API Contract v1 — Decision Governance Layer

## Overview

REST + SSE API for submitting decisions into the governance pipeline and receiving
structured results for the Governance Console UI.

**Base URL:** `/v1`
**Auth:** None (hackathon scope)
**Content-Type:** `application/json` (except `/stream` which is `text/event-stream`)

---

## Versioning

URL prefix strategy: all endpoints live under `/v1`. No header-based versioning.

---

## Endpoints

### 1. `GET /v1/companies`

List all available company governance contexts.

**Response 200:**
```json
{
  "companies": [
    {
      "id": "nexus_dynamics",
      "name": "Nexus Dynamics",
      "industry": "Corporate Finance",
      "size": "2500+ employees",
      "governance_framework": "Corporate Finance"
    },
    {
      "id": "mayo_central",
      "name": "Mayo Central Hospital",
      "industry": "Healthcare & Data Privacy",
      "size": "3500+ employees",
      "governance_framework": "Healthcare & Data Privacy"
    },
    {
      "id": "delaware_gsa",
      "name": "State of Delaware (GSA)",
      "industry": "Public Sector & Procurement",
      "size": "12000+ employees",
      "governance_framework": "Public Sector & Procurement"
    }
  ],
  "total": 3
}
```

---

### 2. `GET /v1/companies/{company_id}`

Retrieve full company context including approval hierarchy and governance rules.

**Path params:** `company_id` — one of `nexus_dynamics`, `mayo_central`, `delaware_gsa`

**Response 200:**
```json
{
  "id": "nexus_dynamics",
  "name": "Nexus Dynamics",
  "industry": "Corporate Finance",
  "size": "2500+ employees",
  "governance_framework": "Corporate Finance",
  "description": "Global investment firm...",
  "approval_chain_summary": "Manager > CFO > Board",
  "total_governance_rules": 72,
  "strategic_goals": [
    {
      "goal_id": "G1",
      "name": "Revenue Growth",
      "owner_id": "cfo_001",
      "priority": "critical"
    }
  ],
  "approval_hierarchy": {
    "levels": ["..."],
    "personnel": ["..."]
  }
}
```

**Response 404:**
```json
{ "detail": "Company 'unknown_id' not found" }
```

---

### 3. `POST /v1/decisions`

Submit a decision text for governance pipeline evaluation. Returns immediately
(202 Accepted). The pipeline runs as a background task.

Connect to `GET /v1/decisions/{id}/stream` to receive real-time progress events.
Fetch `GET /v1/decisions/{id}` after the stream closes for the full console payload.

**Request body:**
```json
{
  "company_id": "nexus_dynamics",
  "input_text": "Acquire DataCorp for $3.5M to expand analytics capabilities",
  "use_o1_governance": false,
  "use_o1_graph": false
}
```

| Field | Type | Required | Default | Notes |
|-------|------|----------|---------|-------|
| `company_id` | string | ✅ | — | Must match an existing company ID |
| `input_text` | string | ✅ | — | 20–10,000 chars |
| `use_o1_governance` | bool | — | `false` | Use OpenAI o1 for governance (requires API key) |
| `use_o1_graph` | bool | — | `false` | Use OpenAI o1 for graph reasoning (requires API key) |

**Response 202:**
```json
{
  "decision_id": "dec_a1b2c3d4",
  "status": "pending",
  "message": "Decision submitted for governance evaluation",
  "stream_url": "/v1/decisions/dec_a1b2c3d4/stream"
}
```

**Response 422:** Validation error (missing fields, invalid company_id format)

---

### 4. `GET /v1/decisions/{decision_id}/stream`

**Server-Sent Events (SSE)** stream for real-time pipeline progress.

- `Content-Type: text/event-stream`
- Connection stays open until pipeline completes or fails
- UI should open this immediately after receiving `decision_id` from POST
- When `event: complete` or `event: error` is received, the connection closes

**SSE Event format:**

```
event: <event_type>
data: <JSON string>

```

**Event types:**

#### `step` — pipeline progress update
```
event: step
data: {"decision_id": "dec_a1b2c3d4", "step": 1, "label": "extracting", "message": "Extracting decision structure from input text..."}

event: step
data: {"decision_id": "dec_a1b2c3d4", "step": 2, "label": "evaluating_governance", "message": "Evaluating governance rules against company context..."}

event: step
data: {"decision_id": "dec_a1b2c3d4", "step": 3, "label": "building_graph", "message": "Building knowledge graph..."}

event: step
data: {"decision_id": "dec_a1b2c3d4", "step": 4, "label": "reasoning", "message": "Performing graph reasoning and contradiction analysis..."}

event: step
data: {"decision_id": "dec_a1b2c3d4", "step": 5, "label": "building_decision_pack", "message": "Assembling decision pack..."}
```

#### `complete` — pipeline finished, full payload available
```
event: complete
data: {"decision_id": "dec_a1b2c3d4", "status": "complete", "result_url": "/v1/decisions/dec_a1b2c3d4"}
```

#### `error` — pipeline failed
```
event: error
data: {"decision_id": "dec_a1b2c3d4", "status": "failed", "message": "Extraction failed: LLM timeout"}
```

**Step label reference:**

| Step | Label |
|------|-------|
| 1 | `extracting` |
| 2 | `evaluating_governance` |
| 3 | `building_graph` |
| 4 | `reasoning` |
| 5 | `building_decision_pack` |

**Response 404:** `{ "detail": "Decision 'dec_xyz' not found" }`

---

### 5. `GET /v1/decisions/{decision_id}`

Full console payload. Fetch after receiving `event: complete` from the SSE stream.
Also valid to poll directly (for clients that cannot open SSE connections).

**Response 200 — Console Payload (LOCKED SHAPE):**
```json
{
  "decision_id": "dec_a1b2c3d4",
  "status": "complete",

  "company": {
    "id": "nexus_dynamics",
    "name": "Nexus Dynamics",
    "industry": "Corporate Finance",
    "size": "2500+ employees",
    "governance_framework": "Corporate Finance"
  },

  "decision": {
    "statement": "Acquire DataCorp for $3.5M...",
    "goals": [
      { "description": "Expand analytics", "metric": "New features" }
    ],
    "kpis": [
      { "name": "ARR", "target": "$8M within 24 months", "measurement_frequency": "Quarterly" }
    ],
    "risks": [
      { "description": "Integration complexity", "severity": "high", "mitigation": "Dedicated team" }
    ],
    "owners": [
      { "name": "Maria Rodriguez", "role": "VP of Product", "responsibility": "Strategy" }
    ],
    "assumptions": [
      { "description": "Valuation is accurate", "criticality": "high" }
    ],
    "required_approvals": ["CFO", "CEO", "Board"]
  },

  "derived_attributes": {
    "risk_level": "high",
    "confidence": 0.72,
    "strategic_impact": "high",
    "completeness_score": 0.88
  },

  "governance": {
    "status": "review_required",
    "requires_human_review": true,
    "risk_score": 7.5,
    "flags": [
      {
        "code": "HIGH_FINANCIAL_RISK",
        "category": "financial",
        "severity": "high",
        "message": "Decision involves expenditure above high-risk threshold ($1M)"
      },
      {
        "code": "BOARD_APPROVAL_REQUIRED",
        "category": "compliance",
        "severity": "critical",
        "message": "Acquisition value exceeds board approval threshold"
      }
    ],
    "triggered_rules": [
      {
        "rule_id": "R1",
        "name": "Major Financial Decision Rule",
        "type": "financial",
        "description": "Expenditures above $1M require CFO approval",
        "status": "TRIGGERED",
        "severity": "high",
        "consequence": { "action": "require_approval", "approver_role": "CFO" }
      }
    ],
    "all_rules": [
      {
        "rule_id": "R1",
        "name": "Major Financial Decision Rule",
        "type": "financial",
        "description": "Expenditures above $1M require CFO approval",
        "status": "TRIGGERED",
        "severity": "high",
        "consequence": { "action": "require_approval", "approver_role": "CFO" }
      },
      {
        "rule_id": "R2",
        "name": "Privacy Rule",
        "type": "compliance",
        "description": "PII usage requires privacy review",
        "status": "PASSED",
        "severity": "critical",
        "consequence": { "action": "require_review", "approver_role": "Privacy Officer" }
      }
    ],
    "approval_chain": [
      {
        "role": "CFO",
        "name": "Jennifer Walsh",
        "level": 3,
        "status": "pending",
        "reason": "Major financial decision — Rule R1"
      },
      {
        "role": "CEO",
        "name": "Michael Thompson",
        "level": 4,
        "status": "pending",
        "reason": "Board-level strategic decision — Rule R3"
      }
    ]
  },

  "graph_payload": {
    "nodes": 14,
    "edges": 18,
    "analysis_method": "deterministic_subgraph",
    "subgraph_summary": {
      "owner_nodes": ["owner_vp_product", "owner_vp_ma"],
      "goal_nodes": ["G1", "G3"],
      "rule_nodes": ["R1", "R3"],
      "reporting_chain": ["cfo_001", "ceo_001", "board_001"]
    }
  },

  "reasoning": {
    "analysis_method": "deterministic",
    "logical_contradictions": [
      "Risk 'Key scientists may leave' has critical severity but mitigation is limited to retention packages with no fallback"
    ],
    "graph_recommendations": [
      "Escalate to Board given acquisition size",
      "Require independent valuation review before CFO sign-off"
    ],
    "confidence": 0.72,
    "raw_analysis": null
  },

  "decision_pack": {
    "title": "Acquisition of DataCorp — Governance Decision Pack",
    "summary": {
      "decision_statement": "Acquire DataCorp for $3.5M...",
      "human_approval_required": true,
      "risk_level": "high",
      "governance_status": "review_required",
      "graph_analysis_enabled": true
    },
    "goals_kpis": { "goals": ["..."], "kpis": ["..."] },
    "risks": ["..."],
    "approval_chain": ["..."],
    "recommended_next_actions": [
      "Obtain independent valuation of DataCorp",
      "Schedule CFO review meeting",
      "Prepare Board presentation"
    ],
    "audit": {
      "evaluated_at": "2025-02-18T12:00:05Z",
      "rules_evaluated": 5,
      "rules_triggered": 2,
      "pipeline_version": "v1"
    },
    "graph_reasoning": {
      "analysis_method": "deterministic",
      "logical_contradictions": ["..."],
      "graph_recommendations": ["..."],
      "confidence": 0.72
    }
  },

  "extraction_metadata": {
    "completeness_score": 0.88,
    "completeness_issues": [],
    "extraction_method": "llm",
    "company_id": "nexus_dynamics",
    "processed_at": "2025-02-18T12:00:05Z"
  }
}
```

**Partial response during `processing`:** `governance`, `graph_payload`, `reasoning`,
`decision_pack` will be `null` until their respective pipeline steps complete.

**Response 404:** `{ "detail": "Decision 'dec_xyz' not found" }`

---

## Normalization Rules

All normalization is applied at the **response layer** — the governance engine output
is transformed before serialization. The engine itself is not modified.

### Flags

Raw engine flags (strings like `"HIGH_RISK"`, `"PRIVACY_REVIEW_REQUIRED"`) are
transformed to structured objects:

```
ENGINE OUTPUT:  ["HIGH_FINANCIAL_RISK", "BOARD_APPROVAL_REQUIRED"]
API OUTPUT:     [
  { "code": "HIGH_FINANCIAL_RISK", "category": "financial", "severity": "high", "message": "..." },
  { "code": "BOARD_APPROVAL_REQUIRED", "category": "compliance", "severity": "critical", "message": "..." }
]
```

**Category mapping:**
| Flag prefix / pattern | Category |
|-----------------------|----------|
| `HIGH_FINANCIAL`, `BUDGET`, `COST` | `financial` |
| `PRIVACY`, `GDPR`, `HIPAA`, `PII` | `privacy` |
| `CRITICAL_CONFLICT`, `BLOCK` | `conflict` |
| `STRATEGIC`, `BOARD` | `strategic` |
| everything else | `governance` |

**Severity mapping:**
| Flag pattern | Severity |
|--------------|----------|
| Contains `CRITICAL` | `critical` |
| Contains `HIGH` | `high` |
| Contains `MEDIUM` | `medium` |
| default | `low` |

### Governance Rules

The engine returns only triggered rules. The API response adds:
1. `status: "TRIGGERED"` to all rules returned by the engine
2. `status: "PASSED"` for rules evaluated but not triggered (derived from `all_rules - triggered_rules`)

```
ENGINE:  triggered_rules: [{ rule_id, name, type, ... }]
API:     triggered_rules: [{ ..., status: "TRIGGERED" }]
         all_rules:       [{ ..., status: "TRIGGERED" }, { ..., status: "PASSED" }]
```

### Approval Chain

Each approval chain step receives an explicit `status: "pending"` field
(decisions arrive unreviewed):

```
ENGINE:  [{ "role": "CFO", "name": "Jennifer Walsh", "level": 3 }]
API:     [{ "role": "CFO", "name": "Jennifer Walsh", "level": 3, "status": "pending", "reason": "..." }]
```

---

## Error Response Format

All errors follow RFC 7807 (simplified):

```json
{ "detail": "Human-readable error message" }
```

| HTTP Status | When |
|-------------|------|
| 404 | Company or decision not found |
| 422 | Request validation failure (Pydantic) |
| 500 | Unhandled server error |

---

## Company ID Reference

| `company_id` | Company | Framework | JSON file |
|---|---|---|---|
| `nexus_dynamics` | Nexus Dynamics | Corporate Finance | `mock_company.json` |
| `mayo_central` | Mayo Central Hospital | Healthcare & Data Privacy | `mock_company_healthcare.json` |
| `delaware_gsa` | State of Delaware (GSA) | Public Sector & Procurement | `mock_company_public.json` |

---

## Backend Must Implement Checklist

For Agent 2 / implementing engineer:

### Router setup
- [ ] Create `app/routers/companies.py` with `GET /v1/companies` and `GET /v1/companies/{id}`
- [ ] Create `app/routers/decisions.py` with `POST /v1/decisions`, `GET /v1/decisions/{id}/stream`, `GET /v1/decisions/{id}`
- [ ] Register both routers in `app/main.py` under `/v1` prefix

### Company service
- [ ] `company_service.list_companies()` — load all 3 mock JSON files, return `CompanyListResponse`
- [ ] `company_service.get_company(company_id)` — return `CompanyDetailResponse` or raise 404
- [ ] Map filenames to IDs: `nexus_dynamics` → `mock_company.json`, `mayo_central` → `mock_company_healthcare.json`, `delaware_gsa` → `mock_company_public.json`

### Decision lifecycle
- [ ] `POST /v1/decisions` creates a `DecisionRecord` in `decision_store`, enqueues `BackgroundTask` via `run_pipeline()`
- [ ] `GET /v1/decisions/{id}/stream` uses `fastapi.responses.StreamingResponse` with `text/event-stream`; generator yields `step`, `complete`, or `error` SSE events
- [ ] `GET /v1/decisions/{id}` assembles `ConsolePayloadResponse` from stored `DecisionRecord`; returns partial payload (nulls) during `processing`

### SSE stream implementation
- [ ] Use `asyncio.sleep(0.5)` polling loop inside the SSE generator — checks `decision_store.get(id).current_step` and emits `step` events for each new step
- [ ] Emit `complete` event and break when `status == "complete"`
- [ ] Emit `error` event and break when `status == "failed"`
- [ ] Set response headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`

### Normalization (at response assembly, NOT in engine)
- [ ] `_normalize_flags(raw_flags: list[str]) -> list[NormalizedFlag]` — convert string flags to structured objects using category/severity mapping tables above
- [ ] `_normalize_rules(triggered: list[dict], all_rules: list[dict]) -> tuple[list[NormalizedRule], list[NormalizedRule]]` — add `status: "TRIGGERED"` or `"PASSED"`
- [ ] `_normalize_approval_chain(raw_chain: list[dict]) -> list[NormalizedApprovalStep]` — add `status: "pending"`

### Schema package migration (prerequisite — already done)
- [x] `app/schemas.py` → `app/schemas/domain.py`
- [x] `app/schemas/__init__.py` re-exports all symbols from `domain.py`
- [x] `app/schemas/requests.py` and `app/schemas/responses.py` created

### Wiring
- [ ] Existing `app/extractor.py`, `app/governance.py`, `app/graph_repository.py` are imported as singletons in `main.py` and passed to `run_pipeline()`
- [ ] `pipeline_service.run_pipeline()` already exists — call it via `BackgroundTasks.add_task(run_pipeline, decision_id, extractor, graph_repo)`
- [ ] Do NOT call OpenAI by default (`use_o1_governance=False`, `use_o1_graph=False`)
