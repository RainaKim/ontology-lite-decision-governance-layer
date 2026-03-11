# Dev Rules — Decision Governance Layer

These rules are non-negotiable. Every PR, every function, every patch must comply.
Violations are **not** acceptable even for "quick fixes" or "demo convenience."

---

## Rule 1: No Scenario-Specific If-Else

**Hardcoding specific scenario text, company names, goal IDs, rule IDs, or semantic keywords inside logic is forbidden.**

### Forbidden patterns

```python
# ❌ String-matching a specific scenario keyword
if "북미 시장 점유율" in text:
    ...

# ❌ Branching on a company ID
if company_id == "nexus_dynamics":
    ...

# ❌ Hardcoding a goal ID
if goal_id == "G3":
    score += 20

# ❌ Hardcoding a rule ID
if rule.get("rule_id") == "R1":
    apply_financial_penalty()

# ❌ Keyword table for semantic classification — still hardcoding
COST_REDUCTION_KEYWORDS = {"cost", "절감", "efficiency", ...}
if set(goal_name.split()) & COST_REDUCTION_KEYWORDS:
    ...
# Why it's wrong: the keyword list encodes your assumption of what
# "cost reduction" means. Any language not in the list is silently missed.
# Semantic meaning belongs to the LLM, not a static set.
```

### Allowed patterns

All logic must be expressed through exactly one of these three mechanisms:

#### A. Config-driven rules
**Structural** company/industry parameters — weights, numeric thresholds, enum mappings.
These are OK as tables because they contain no semantic meaning; they are explicit business decisions.

```python
# ✅ Industry weight table — purely numeric policy, not semantic
INDUSTRY_COMPLIANCE_WEIGHTS = {
    "healthcare": 0.50,
    "헬스케어":    0.50,
    "finance":    0.35,
    "기업 금융":   0.35,
}
weight = INDUSTRY_COMPLIANCE_WEIGHTS.get(industry.lower(), 0.35)
```

The key distinction: if a human policy document says "compliance weight is 0.5 in healthcare,"
that belongs in a table. If a human would need to *read* text to decide, that belongs to the LLM.

#### B. Ontology/Graph-driven inference
Decisions are made by inspecting node type, edge relation type, and properties — never by matching literal identifiers or text.

```python
# ✅ Edge relation type drives logic — ontology-defined, not free text
if edge["relation"].lower() in CONFLICT_RELATIONS:   # CONFLICT_RELATIONS = ontology vocabulary
    conflict_score += priority_weight(goal["priority"])
```

#### C. LLM structured extraction
When the question requires understanding language or semantics, call the LLM **once**, receive a **validated Pydantic JSON response**, cache the result on `DecisionRecord`, and use that structured output in downstream deterministic logic.

```python
# ✅ LLM decides "what kind of goal is this?" — result is cached, not re-called
class GoalClassification(BaseModel):
    category: Literal["cost_reduction", "revenue_growth", "compliance", "safety", "other"]
    confidence: float = Field(ge=0.0, le=1.0)

classification = GoalClassification.model_validate(llm_response)
# Now deterministic logic uses classification.category — no keyword matching
if classification.category == "cost_reduction":
    ...
```

---

## Rule 2: LLM Is Allowed Only as a Classifier/Extractor

The LLM's role is **strictly limited** to producing structured inputs for deterministic formulas.

### What the LLM does

| Task | Allowed output shape |
|------|----------------------|
| (a) Evidence sentence generation | `{"summary": "한국어 1줄 요약"}` |
| (b) Conflict/support classification | `{"relation": "supports" \| "conflicts" \| "neutral", "confidence": 0.0-1.0}` |
| (c) KPI impact input extraction | `{"impact_direction": "positive"\|"negative", "magnitude_range": "low"\|"medium"\|"high", "confidence": 0.0-1.0}` |
| (d) Semantic category classification | `{"category": "<ontology_enum>", "confidence": 0.0-1.0}` |

### What the LLM must NOT do

- ❌ Output a numeric score or risk band directly
- ❌ Return free-form reasoning text that drives logic
- ❌ Make threshold comparisons or weighted sums

### Validation requirement

Every LLM call **must** validate its output through a Pydantic model before use.

```python
# ✅ Always validate LLM output
class LLMClassificationResult(BaseModel):
    relation: Literal["supports", "conflicts", "neutral"]
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str

result = LLMClassificationResult.model_validate(raw_llm_json)
```

---

## Rule 3: Every Computed Metric Must Have a Provenance

Every `score` and every `signal` must carry at least one `evidence` item.

### Evidence requirements

- **At least 1 evidence item** per dimension score
- Evidence must be **UI-friendly** — written for a human reviewer, not a developer
- **No internal field names, dict keys, or raw values** in the evidence text

```python
# ❌ Leaks internal field name and raw value
RiskEvidence(type="field", ref={"field": "remaining_budget", "raw_value": 50_000_000})

# ✅ UI-friendly, no raw values, no internal keys
RiskEvidence(type="field", ref={"used_for": "예산 초과 비율 계산", "field_present": True})
```

### Evidence types

| type | When to use |
|------|-------------|
| `"field"` | A decision/company field was read to compute the score |
| `"rule"` | A triggered governance rule contributed to the score |
| `"graph_edge"` | A graph relationship (supports/conflicts) was used |
| `"llm_classification"` | An LLM-derived structured label was used |
| `"note"` | Explanation for a fallback, missing data, or boundary condition |

---

## Rule 4: Add a Pattern Before Adding a Branch

Before writing any new `if/else`, ask in order:

```
Need new conditional logic?
         │
         ▼
Is it a structural/numeric policy (weight, threshold, enum mapping)?
    YES ──▶ Add a row to the config table. Done.
         │
        NO
         │
         ▼
Does it require understanding language or semantics?
    YES ──▶ Add an LLM structured call with a Pydantic output model.
         │   Cache result on DecisionRecord. Use the structured field
         │   in existing deterministic logic.
        NO
         │
         ▼
Is it an ontology / graph structural property?
    YES ──▶ Add a node type, edge relation, or property to the ontology.
         │   Drive logic from the graph, not from text.
        NO
         │
         ▼
Write the minimal deterministic branch.
Document WHY none of the above applied in a comment above the branch.
```

### Concrete example

Classifying whether a goal is "cost-reduction type":

```python
# ❌ Wrong — keyword table is semantic hardcoding
COST_REDUCTION_KEYWORDS = {"cost", "비용", "절감", ...}
is_cost_reduction = bool(set(goal_name.split()) & COST_REDUCTION_KEYWORDS)

# ✅ Right — LLM classifies semantics, deterministic logic uses the result
class GoalCategory(BaseModel):
    category: Literal["cost_reduction", "revenue_growth", "compliance", "safety", "other"]
    confidence: float = Field(ge=0.0, le=1.0)

goal_classification = GoalCategory.model_validate(
    llm_client.classify_goal(goal_name, goal_description)
)
# Deterministic formula uses the structured enum — no text matching
if goal_classification.category == "cost_reduction":
    kpi_impact = compute_cost_impact(cost, baseline)
```

---

## Summary Checklist

Before committing any code, verify:

- [ ] No string literal matches a company name, goal ID, rule ID, or semantic keyword in branching logic
- [ ] Keyword lists that encode *semantic meaning* have been replaced with LLM structured calls
- [ ] All company/industry-specific **numeric/structural** parameters live in a config table
- [ ] Every LLM output is validated by a Pydantic model before use
- [ ] LLM output is never a score — only a structured input to a deterministic formula
- [ ] Every dimension score and signal has `evidence[]` populated
- [ ] Evidence text is UI-readable with no raw internal field values or dict keys
- [ ] New conditional logic was evaluated against: table → LLM → ontology → minimal branch
