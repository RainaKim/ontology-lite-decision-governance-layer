# Decision Governance Layer

Enterprise AI system that transforms free-form decision text into structured, validated JSON objects.

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

## Usage

### Extract Decision

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{
    "decision_text": "We should launch a new mobile app to increase user engagement by 30% over the next quarter. The marketing team will lead this initiative with support from engineering. Key risks include technical debt and market timing. We need CEO approval before proceeding."
  }'
```

### Response

```json
{
  "decision": {
    "decision_statement": "Launch a new mobile app to increase user engagement",
    "goals": [...],
    "kpis": [...],
    "risks": [...],
    "owners": [...],
    "required_approvals": ["CEO"],
    "assumptions": [...],
    "confidence": 0.85
  },
  "extraction_metadata": {
    "request_id": "...",
    "retry_count": 0,
    "success": true
  }
}
```

## Features

- LLM-based structured extraction (OpenAI GPT-4o)
- Pydantic validation
- Automatic retry (max 2 attempts)
- Graceful fallback (never crashes)
- Request tracking and logging
