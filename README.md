# Decision Governance Layer

**Ontology-lite system for enterprise decision structuring and deterministic governance.**

## Architecture

```
Decision Text (free-form)
  ↓
GPT-4o Extraction → Structured Decision JSON
  ↓
Deterministic Governance Evaluation (NO LLMs)
  ├─ Completeness Checks
  ├─ Derived Attributes (budget, EU, PII detection)
  ├─ Rule Enforcement
  ├─ Approval Chain Generation
  └─ Status Calculation (approved/needs_approval/blocked)
  ↓
Decision Response
```

**Key Principle**: Governance is deterministic. Same input → same output. NO LLM calls in governance logic.

---

## Setup

### Prerequisites
- Python 3.11+
- OpenAI API key

### Installation

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Run Server

```bash
uvicorn app.main:app --reload --port 8000
```

Server runs at `http://localhost:8000`

---

## API Usage

### POST /extract

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "decision_text": "Invest $600k in cloud infrastructure to reduce operating costs by 20%. Bob Martinez (CFO) will manage budget while Charlie Kim (CTO) handles implementation. Risks: migration downtime, vendor lock-in."
  }'
```

### Response Structure

```json
{
  "decision": {
    "decision_statement": "Invest $600k in cloud infrastructure optimization",
    "goals": [...],
    "kpis": [...],
    "risks": [...],
    "owners": [...],
    "confidence": 0.8
  },
  "extraction_metadata": {
    "request_id": "uuid",
    "retry_count": 0,
    "model": "gpt-4o",
    "success": true
  },
  "governance_applied": true,
  "governance_status": "needs_approval",
  "approval_chain": [
    {
      "approver_id": "alice_001",
      "approver_name": "Alice Chen",
      "approver_role": "CEO",
      "level": 4,
      "reasons": ["Strategic alignment", "High-cost decision"],
      "triggered_rules": ["R4", "R5"]
    },
    {
      "approver_id": "bob_002",
      "approver_name": "Bob Martinez",
      "approver_role": "CFO",
      "level": 3,
      "reasons": ["Budget > $100k", "Financial approval"],
      "triggered_rules": ["R1", "R5"]
    }
  ],
  "triggered_rules": [
    {"rule_id": "R1", "rule_name": "Budget Approval Rule"},
    {"rule_id": "R4", "rule_name": "Strategic Alignment Rule"},
    {"rule_id": "R5", "rule_name": "Multi-Approval Rule"}
  ],
  "flags": ["HIGH_RISK"],
  "requires_human_review": true,
  "derived_attributes": {
    "normalized_budget": 600000,
    "has_eu_scope": false,
    "has_pii_usage": false,
    "is_strategic": true,
    "estimated_risk_level": "medium"
  },
  "completeness_issues": []
}
```

---

## Governance Pipeline

### 1️⃣ Completeness Checks
- ✓ Has decision statement
- ✓ Has at least one owner
- ⚠️ Has KPIs (recommended)
- ⚠️ Has risks (recommended)
- ⚠️ Risks have severity (recommended)

### 2️⃣ Derived Attributes (Deterministic)
- **normalized_budget**: Extract $ amounts (e.g., "$600k" → 600000)
- **has_eu_scope**: Detect EU/GDPR keywords
- **has_pii_usage**: Detect privacy/PII keywords
- **has_deployment**: Detect launch/deploy keywords
- **is_strategic**: Detect strategic initiative keywords
- **estimated_risk_level**: Calculate from risk severities

### 3️⃣ Rule Enforcement
Rules from `mock_company.json`:
- **R1**: Budget > $100k → CFO approval
- **R2**: EU or PII → CTO review
- **R3**: Deployment → conflict check
- **R4**: Strategic → CEO approval
- **R5**: Budget > $500k → CFO + CEO approval

### 4️⃣ Approval Chain Generation
- Deduplicates approvers (same person from multiple rules)
- Orders by level (highest first)
- Merges reasons from all triggered rules

### 5️⃣ Status Calculation
- **BLOCKED**: Missing critical fields (owner, decision statement)
- **NEEDS_APPROVAL**: Has approval chain or significant flags
- **APPROVED**: No approvals needed, all checks pass

---

## Features

✅ **LLM-based Extraction** (GPT-4o) - Fast, accurate JSON extraction
✅ **Deterministic Governance** - Same input → same output, NO LLMs
✅ **Rule-based Approval Chains** - Derived from company governance rules
✅ **Derived Attributes** - Budget normalization, EU/PII detection
✅ **Retry Logic** - Max 2 retries on extraction failure
✅ **Graceful Fallback** - Never crashes, returns blocked status
✅ **Request Tracking** - Unique IDs and retry counts

---

## Project Structure

```
decision-governance-layer/
├── app/
│   ├── main.py                      # FastAPI app
│   ├── schemas.py                   # Pydantic models
│   ├── llm_client.py               # GPT-4o client
│   ├── extractor.py                # Extraction + retry logic
│   ├── governance_deterministic.py  # Pure governance engine (NO LLMs)
│   └── __init__.py
├── mock_company.json               # Company governance rules
├── requirements.txt
├── .env.example
└── README.md
```
