# Graph Reasoning with o1 - Implementation Summary

## ✅ What We Built

### Complete Decision Pipeline with Graph-Based Intelligence

```
Decision Input
    ↓
Governance Evaluation (deterministic rules)
    ↓
Graph Storage (nodes + edges)
    ↓
**Graph Reasoning with o1** ← NEW!
    ├─ Find logical contradictions
    ├─ Validate ownership
    ├─ Detect risk gaps
    ├─ Identify policy conflicts
    └─ Generate evidence-based recommendations
    ↓
Decision Pack (enhanced with graph insights)
```

---

## 🧠 How o1 Analyzes the Graph

### Input to o1
```python
DECISION GRAPH STRUCTURE:
DECISION: Strategic acquisition of DataCorp for $3.5M

ACTORS (Owners & Approvers):
  - Maria Rodriguez (VP of Product)
  - David Chen (VP of M&A)
  - CEO (c_level)

POLICIES (Governance Rules Triggered):
  - Strategic Alignment Rule: Major initiatives must align with goals

RISKS:
  - [critical] Key data scientists may leave post-acquisition
    Mitigation: Retention packages and equity grants
  - [high] Integration complexity
  - [medium] Market demand uncertainty

RELATIONSHIPS:
  - decision_xxx_owner_0 --[OWNS]--> decision_xxx
  - decision_xxx --[REQUIRES_APPROVAL_BY]--> decision_xxx_approver_c_level_0
  - decision_xxx --[GOVERNED_BY]--> policy_R4
  - decision_xxx --[TRIGGERS]--> decision_xxx_risk_0
```

### o1 Analysis Tasks

**1. Logical Contradictions**
- Conflicting goals? (e.g., "reduce costs" vs "increase headcount")
- Incompatible KPIs? (e.g., "maximize quality" vs "minimize time")
- Risk-mitigation conflicts? (e.g., mitigation creates new risks)

**2. Ownership Validation**
- Do owners have the right authority level?
- Are critical stakeholders missing?
- Is ownership structure logical for this decision?

**3. Risk Coverage Gaps**
- Are obvious risks not identified?
- Do all critical risks have mitigation plans?
- Are mitigations realistic and sufficient?

**4. Policy Conflicts**
- Do multiple policies require contradictory actions?
- Are approval chains logically consistent?
- Are there circular dependencies?

**5. Graph Structure Issues**
- Orphaned nodes (no connections)
- Missing critical relationships
- Illogical relationship patterns

### o1 Output Example

```json
{
  "contradictions": [
    {
      "type": "goal_conflict",
      "severity": "high",
      "description": "Goal 1 (fast market entry) conflicts with Goal 2 (thorough integration)",
      "nodes_involved": ["goal_0", "goal_1"],
      "evidence": "Goal 1 implies speed, Goal 2 implies 9-month timeline",
      "impact": "Team will face contradictory priorities",
      "recommendation": "Prioritize integration quality; adjust market entry timeline"
    }
  ],
  "ownership_issues": [
    {
      "issue_type": "missing_stakeholder",
      "severity": "critical",
      "description": "CFO not involved despite $3.5M budget impact",
      "recommendation": "Add CFO to approval chain"
    }
  ],
  "risk_gaps": [
    {
      "gap_type": "missing_risk",
      "severity": "high",
      "description": "No regulatory approval risk identified for acquisition",
      "recommendation": "Add regulatory compliance assessment"
    }
  ],
  "recommendations": [
    {
      "priority": "critical",
      "action": "Add CFO to approval chain for financial oversight",
      "reasoning": "Missing financial governance for $3.5M decision",
      "expected_outcome": "Proper financial due diligence"
    }
  ],
  "confidence": 0.88
}
```

---

## 📊 Decision Pack Enhancement

### Before Graph Reasoning

```json
{
  "approval_chain": [...],
  "recommended_next_actions": [
    "Request approvals: CEO"
  ]
}
```

**Quality:** Generic, rule-based only

### After Graph Reasoning

```json
{
  "approval_chain": [...],
  "recommended_next_actions": [
    "Request approvals: CEO"
  ],
  "graph_reasoning": {
    "analysis_method": "o1-reasoning",
    "graph_context": {
      "nodes_analyzed": 16,
      "edges_analyzed": 18,
      "traversal_depth": 2,
      "subgraph_source": "mock_subgraph_extraction",
      "matched_personnel": ["Alice Chen (CEO)", "Bob Martinez (CTO)"],
      "selection_criteria": ["owner_name_match", "kpi_overlap", "reporting_chain"]
    },
    "logical_contradictions": [
      {
        "type": "goal_conflict",
        "severity": "high",
        "description": "Fast market entry vs thorough integration timeline",
        "recommendation": "Prioritize integration quality"
      }
    ],
    "ownership_issues": [
      {
        "issue_type": "missing_stakeholder",
        "severity": "critical",
        "description": "CFO not involved despite $3.5M budget"
      }
    ],
    "risk_gaps": [
      {
        "gap_type": "missing_risk",
        "severity": "high",
        "description": "No regulatory approval risk identified"
      }
    ],
    "policy_conflicts": [],
    "graph_recommendations": [
      {
        "priority": "critical",
        "action": "Add CFO to approval chain for financial oversight",
        "reasoning": "Missing financial governance for $3.5M decision"
      }
    ],
    "confidence": 0.88
  }
}
```

**Note:** When running with `use_o1_graph=False` (deterministic fallback), `analysis_method`
will be `"deterministic"`, `graph_context.subgraph_source` will be `"repository_only"`,
and `confidence` will be `0.6`. The o1 path enriches with subgraph extraction
(`matched_personnel`, `selection_criteria`) and deeper analysis.

**Quality:** Evidence-based, catches issues humans miss

---

## 🚀 Usage

### Basic (Deterministic Only)

```python
from app.decision_pipeline import process_decision_with_graph_reasoning
from app.demo_fixtures import get_demo_fixture, get_company_context

decision = get_demo_fixture("budget_violation")
company = get_company_context()  # loads mock_company.json

result = await process_decision_with_graph_reasoning(
    decision=decision,
    company_context=company,
    use_o1_governance=False,
    use_o1_graph=False  # Deterministic fallback
)
```

### Enhanced (With o1 Graph Reasoning)

```python
result = await process_decision_with_graph_reasoning(
    decision=decision,
    company_context=company,     # needed for subgraph extraction
    use_o1_governance=False,     # Keep governance deterministic
    use_o1_graph=True            # Enable o1 for graph analysis
)

pack = result["decision_pack"]

# Check for contradictions
if pack["graph_reasoning"]["logical_contradictions"]:
    print("⚠️ Contradictions found:")
    for c in pack["graph_reasoning"]["logical_contradictions"]:
        print(f"  - [{c['severity']}] {c['description']}")
```

---

## 💡 Key Benefits

### 1. Catches Logical Contradictions
**Example:** Decision says "launch in 2 weeks" but also "complete full QA testing"
- **Without graph:** Both requirements accepted
- **With o1:** Detects time-quality conflict, recommends resolution

### 2. Validates Ownership
**Example:** Junior manager owns $5M decision
- **Without graph:** Rule doesn't catch authority mismatch
- **With o1:** Flags insufficient authority level

### 3. Detects Missing Risks
**Example:** Acquisition decision missing regulatory risk
- **Without graph:** Only sees risks explicitly stated
- **With o1:** Reasons about common risks for acquisition type

### 4. Identifies Policy Conflicts
**Example:** Rule A requires CFO approval, Rule B blocks financial approvals
- **Without graph:** Both rules apply independently
- **With o1:** Detects circular dependency

---

## 🔧 Implementation Files

- **`app/graph_reasoning.py`**: o1 graph analysis orchestration, deterministic fallback, insight formatting
- **`app/decision_pipeline.py`**: End-to-end orchestration (5-step pipeline)
- **`app/decision_pack.py`**: Enhanced with `graph_reasoning` section
- **`app/o1_reasoner.py`**: o1 API integration + `_extract_mock_subgraph` (owner matching, KPI overlap, reporting chain) + `_build_contradiction_prompt` (subgraph serialization)
- **`app/demo_fixtures.py`**: Test scenarios + `get_company_context()` for loading `mock_company.json`
- **`app/e2e_runner.py`**: Full pipeline validation (24 checks across 4 scenarios)

---

## 🎯 Design Decisions

### Why o1 for Graph Analysis (Not Governance)?

**Governance:** Deterministic, rule-based
- Needs to be reproducible
- Legal/compliance requirement
- Same input → same output

**Graph Analysis:** Pattern recognition, logical reasoning
- Find contradictions humans miss
- Reason about implicit relationships
- Context-aware recommendations

### Fallback Strategy

```python
if use_o1:
    try:
        insights = o1.analyze_graph(...)
    except:
        insights = deterministic_fallback(...)
else:
    insights = deterministic_fallback(...)
```

**Result:** System always works, o1 is optional enhancement

---

## 📈 Value Proposition

### Before (Rules Only)
"This decision needs CEO approval" 
→ Generic, template-based

### After (Rules + Graph + o1)
"This decision has 3 contradictory goals, is missing CFO oversight for $3.5M spend, and lacks regulatory risk assessment. Recommend: (1) Add CFO approval, (2) Prioritize integration quality, (3) Add compliance risk"
→ Specific, evidence-based, catches real issues

---

## 🔮 Future Enhancements

1. **Historical Pattern Analysis**
   - "Last 3 similar acquisitions were blocked due to missing ROI"
   - "CFO typically takes 2.1 days for financial reviews"

2. **Graph Algorithms**
   - PageRank: Find critical approvers
   - Community detection: Identify decision clusters
   - Path analysis: Find approval bottlenecks

3. **Multi-Decision Reasoning**
   - "This decision conflicts with decision_123 from last month"
   - "Similar decision pattern led to 80% rejection rate"

---

## 🎬 Demo Commands

```bash
# Single decision through full pipeline (deterministic)
python -m app.decision_pipeline

# E2E validation - all 4 scenarios through full pipeline (24 checks)
python -m app.e2e_runner
```

**Output:** Complete decision pack with `graph_reasoning` section including
`analysis_method`, `graph_context`, `logical_contradictions`, `ownership_issues`,
`risk_gaps`, `policy_conflicts`, `graph_recommendations`, and `confidence`.
