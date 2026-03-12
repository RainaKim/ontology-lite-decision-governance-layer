# Agent Tasks — Autonomous Refactor Execution Guide

**For:** An autonomous agent executing the refactor while the developer is offline.
**Safety rule:** Run `source venv/bin/activate && python -m pytest tests/ -q` after every task.
**Baseline:** 275 tests pass. Any deviation is a STOP condition.
**Do NOT modify:** auth, migrations, `app/schemas/responses.py`, any file in `Out of Scope` section of `REFACTOR_SCOPE.md`.

---

## Task 0 — Foundation: Create Config and Utils Modules

**Branch:** `refactor/foundation`

### Pre-conditions
- [ ] `git status` is clean
- [ ] `pytest tests/ -q` shows 275 passed
- [ ] Files `app/config/bedrock_config.py`, `app/utils/formatters.py`, `app/utils/llm_utils.py` do NOT exist

### Steps

1. Create `app/config/__init__.py` if it doesn't exist (empty file).

2. Create `app/config/bedrock_config.py`:
```python
# Central Bedrock configuration — import from here, never hardcode elsewhere.
NOVA_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
BEDROCK_REGION = "us-east-1"
BEDROCK_TIMEOUT = 60.0
```

3. Create `app/config/company_config.py`:
```python
# Company profile aliases: canonical company_id → profile filename stem.
PROFILE_ALIASES: dict[str, str] = {
    "mayo_central": "mayo_central_hospital",
}
```

4. Create `app/config/risk_config.py` (values copied from `risk_scoring_service.py` — do NOT change the values):
```python
# Risk band boundaries and confidence parameters.
# These match the constants in risk_scoring_service.py until P4-A migrates them.
RISK_BANDS = {
    "default": {"low_max": 40, "medium_max": 70, "high_max": 85},
}
CONFIDENCE_PARAMS = {
    "base": 0.9,
    "decay": 0.1,
    "min": 0.4,
    "max": 0.95,
}
```

5. Create `app/utils/__init__.py` if it doesn't exist (empty file).

6. Create `app/utils/formatters.py`:
```python
from typing import Optional


def format_krw(amount: Optional[float]) -> str:
    """Format a KRW amount into Korean notation (억/만 원).

    Returns "미정" for None. This is the canonical implementation —
    do not define _fmt_krw in individual service files.
    """
    if amount is None:
        return "미정"
    v = int(amount)
    awk = v // 100_000_000
    man = (v % 100_000_000) // 10_000
    if awk > 0 and man > 0:
        return f"{awk}억 {man:,}만 원"
    if awk > 0:
        return f"{awk}억 원"
    if man > 0:
        return f"{man:,}만 원"
    return f"{v:,}원"
```

7. Create `app/utils/llm_utils.py`:
```python
import json
from typing import Optional


def extract_json(text: str) -> Optional[dict]:
    """Extract and parse JSON from an LLM response string.

    Handles:
    - Plain JSON
    - Markdown-fenced JSON (```json ... ```)
    - JSON embedded within surrounding prose
    """
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        end_of_first_line = text.find("\n")
        if end_of_first_line != -1:
            text = text[end_of_first_line + 1:]
    if text.endswith("```"):
        text = text[:text.rfind("```")]
    text = text.strip()

    # Try direct parse first
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Fall back: find outermost braces
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            result = json.loads(text[start:end])
            if isinstance(result, dict):
                return result
        except json.JSONDecodeError:
            pass

    return None
```

### Test command
```bash
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** 275 passed, 0 failed.

### Commit message
```
refactor: add shared config and utils modules (foundation)

- app/config/bedrock_config.py — NOVA_MODEL_ID, BEDROCK_REGION, BEDROCK_TIMEOUT
- app/config/company_config.py — PROFILE_ALIASES
- app/config/risk_config.py — RISK_BANDS, CONFIDENCE_PARAMS (mirrors existing constants)
- app/utils/formatters.py — canonical format_krw()
- app/utils/llm_utils.py — canonical extract_json()

No callers updated yet. Tests: 275 pass.
```

### STOP conditions
- Any import error when loading the new modules → fix import before committing
- Tests drop below 275 → revert and investigate

---

## Task 1A — Dedupe `_fmt_krw`

**Branch:** `refactor/dedupe-formatters`
**Requires:** Task 0 complete and merged.

### Pre-conditions
- [ ] `app/utils/formatters.py` exists and contains `format_krw`
- [ ] 275 tests pass

### Steps

1. In `app/services/nova_scenario_proposer.py`:
   - Add import: `from app.utils.formatters import format_krw`
   - Delete the local `_fmt_krw` function definition
   - Replace all calls to `_fmt_krw(...)` with `format_krw(...)`

2. In `app/services/risk_response_simulation_service.py`:
   - Add import: `from app.utils.formatters import format_krw`
   - Delete the local `_fmt_krw` function definition
   - Replace all calls to `_fmt_krw(...)` with `format_krw(...)`

3. Verify with grep: `grep -r "_fmt_krw" app/` should return zero results.

### Test command
```bash
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** 275 passed.

### Commit message
```
refactor: deduplicate _fmt_krw — import from app.utils.formatters

Removes _fmt_krw() from nova_scenario_proposer and
risk_response_simulation_service; both now import format_krw
from the canonical app/utils/formatters module.
```

### STOP conditions
- `grep -r "_fmt_krw" app/` returns results in any file other than formatters.py → do not commit until resolved

---

## Task 1B — Dedupe `PROFILE_ALIASES`

**Branch:** `refactor/dedupe-profile-aliases`
**Requires:** Task 0 complete.

### Pre-conditions
- [ ] `app/config/company_config.py` exists with `PROFILE_ALIASES`
- [ ] 275 tests pass

### Steps

1. In `app/services/external_signal_service.py`:
   - Add import: `from app.config.company_config import PROFILE_ALIASES`
   - Delete local `_PROFILE_ALIASES = {...}` definition
   - Replace all references to `_PROFILE_ALIASES` with `PROFILE_ALIASES`

2. In `app/providers/curated_external_signal_provider.py`:
   - Same: add import, delete local definition, update references.

3. Verify: `grep -r "_PROFILE_ALIASES" app/` returns zero results.

### Test command
```bash
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** 275 passed.

### Commit message
```
refactor: single source of truth for PROFILE_ALIASES

Removes duplicate _PROFILE_ALIASES dicts from external_signal_service
and curated_external_signal_provider; both now import from
app/config/company_config.
```

---

## Task 1C — Dedupe Bedrock Model ID

**Branch:** `refactor/dedupe-model-id`
**Requires:** Task 0 complete.

### Pre-conditions
- [ ] `app/config/bedrock_config.py` exists with `NOVA_MODEL_ID`
- [ ] 275 tests pass

### Steps

1. In `app/bedrock_client.py`:
   - Add import: `from app.config.bedrock_config import NOVA_MODEL_ID, BEDROCK_REGION, BEDROCK_TIMEOUT`
   - Replace `_DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"` with `_DEFAULT_MODEL = NOVA_MODEL_ID`
   - Replace hardcoded region and timeout if present

2. In `app/services/nova_scenario_proposer.py`:
   - Add import, replace `_MODEL_ID = "us.amazon.nova-2-lite-v1:0"` with `_MODEL_ID = NOVA_MODEL_ID`

3. In `app/services/nova_external_signal_summarizer.py`:
   - Same pattern.

4. Verify: `grep -r '"us.amazon.nova' app/` returns only `bedrock_config.py`.

### Test command
```bash
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** 275 passed.

### Commit message
```
refactor: centralize Bedrock model ID in app/config/bedrock_config

Removes 3 duplicate string literals for "us.amazon.nova-2-lite-v1:0";
bedrock_client, nova_scenario_proposer, and nova_external_signal_summarizer
all import NOVA_MODEL_ID from the config module.
```

---

## Task 2A — Extract Pure Translation Function from `governance.py`

**Branch:** `refactor/governance-pure-translation`
**Requires:** No dependencies.

### Pre-conditions
- [ ] 275 tests pass
- [ ] Read `app/governance.py` fully before touching it

### Steps

1. In `app/governance.py`, extract the translation overlay logic from `load_rules()` into a new function `_apply_translation(raw: dict, lang: str) -> dict` placed above `load_rules`.

2. The function must be a pure transformation (no file I/O, no side effects):
```python
def _apply_translation(raw: dict, lang: str) -> dict:
    """Apply language overlay from a rules dict's 'translations' section.
    Pure function — no I/O. Returns a merged dict with the translated fields."""
    lang_key = lang if lang in ("ko", "en") else "ko"
    if "translations" not in raw:
        return raw
    translation = raw.get("translations", {}).get(lang_key, {})
    data = {**raw, **translation}
    if "rules" in translation:
        data["governance_rules"] = translation["rules"]
    return data
```

3. In `load_rules()`, replace the inline translation block with a call to `_apply_translation(raw, lang)`.

4. Do NOT change the function signature of `load_rules()`.

### Test command
```bash
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** 275 passed.

### Commit message
```
refactor: extract _apply_translation() as pure function in governance.py

Separates file I/O (load_rules) from data transformation (_apply_translation).
_apply_translation is now independently testable without disk access.
```

---

## Task 2B — Config Tables in `external_signal_service.py`

**Branch:** `refactor/external-signal-config-tables`
**Requires:** No dependencies.

### Pre-conditions
- [ ] Read `app/services/external_signal_service.py` fully before touching it
- [ ] 275 tests pass

### Steps

1. Near the top of `external_signal_service.py` (after imports), add:
```python
# --- Configuration tables (edit here to extend, not in function bodies) ---

_DECISION_TYPE_PRIORITY: list[tuple[str, str]] = [
    ("involves_hiring", "hiring"),
    ("uses_pii", "privacy"),
    ("new_product_development", "new_product"),
]

_FLAG_KEYWORD_THEMES: list[tuple[tuple[str, ...], str]] = [
    (("FINANCIAL", "BUDGET", "COST"),              "risk_financial"),
    (("PRIVACY", "PII", "PHI"),                    "privacy_compliance"),
    (("COMPLIANCE", "REGULATORY", "VIOLATION"),    "regulatory_compliance"),
    (("STRATEGIC", "CONFLICT", "MISALIGNMENT"),    "strategic_benchmark"),
]

_STRATEGIC_IMPACT_KEYWORDS: tuple[str, ...] = ("STRATEGIC", "CONFLICT", "MISALIGNMENT")
```

2. Rewrite `_infer_decision_type()` to loop over `_DECISION_TYPE_PRIORITY`:
```python
def _infer_decision_type(decision: dict) -> str:
    for field, dtype in _DECISION_TYPE_PRIORITY:
        if decision.get(field):
            return dtype
    cost = decision.get("cost")
    if cost and isinstance(cost, (int, float)) and cost > 0:
        return "procurement"
    return "general"
```

3. Rewrite the theme-inference block to loop over `_FLAG_KEYWORD_THEMES`:
```python
for flag in flags:
    for keywords, theme in _FLAG_KEYWORD_THEMES:
        if any(kw in flag for kw in keywords):
            themes.append(theme)
```

4. Rewrite `_infer_strategic_impact()` to use `_STRATEGIC_IMPACT_KEYWORDS`:
```python
def _infer_strategic_impact(governance_result: Optional[dict]) -> str:
    if not governance_result:
        return "N/A"
    for flag in governance_result.get("flags", []):
        if any(kw in flag.upper() for kw in _STRATEGIC_IMPACT_KEYWORDS):
            return "Potential strategic conflict"
    return "N/A"
```

### Test command
```bash
source venv/bin/activate && python -m pytest tests/test_external_signal_service.py -q
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** All 23 external signal tests pass; 275 total pass.

### Commit message
```
refactor: replace if-chains with config tables in external_signal_service

Decision type inference, theme mapping, and strategic impact inference
now driven by _DECISION_TYPE_PRIORITY, _FLAG_KEYWORD_THEMES, and
_STRATEGIC_IMPACT_KEYWORDS — extend by adding a config row, not code.
```

### STOP conditions
- Any of the 23 `test_external_signal_service.py` tests fail → revert and investigate the specific test

---

## Task 2C — Severity List to Dict in `normalizers.py`

**Branch:** `refactor/normalizers-severity-dict`
**Requires:** No dependencies.

### Pre-conditions
- [ ] Read `app/routers/normalizers.py` before touching it
- [ ] 275 tests pass

### Steps

1. In `app/routers/normalizers.py`, replace:
```python
_FLAG_SEVERITY_PATTERNS = [
    ("CRITICAL", FlagSeverity.critical),
    ("HIGH", FlagSeverity.high),
    ("MEDIUM", FlagSeverity.medium),
]
```
with:
```python
_FLAG_SEVERITY_MAP: dict[str, FlagSeverity] = {
    "CRITICAL": FlagSeverity.critical,
    "HIGH":     FlagSeverity.high,
    "MEDIUM":   FlagSeverity.medium,
}
```

2. Update the lookup code to use dict access. Before:
```python
for pattern, severity in _FLAG_SEVERITY_PATTERNS:
    if pattern in flag_str:
        return severity
```
After:
```python
for key, severity in _FLAG_SEVERITY_MAP.items():
    if key in flag_str:
        return severity
```
(Order matters here — if critical must be checked before high, iterate in insertion order, which Python 3.7+ dicts preserve.)

### Test command
```bash
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** 275 passed.

### Commit message
```
refactor: convert _FLAG_SEVERITY_PATTERNS list to dict in normalizers.py
```

---

## Task 2D — Operator Dispatch Table in `evidence_registry_service.py`

**Branch:** `refactor/trigger-operator-dispatch`
**Requires:** No dependencies.

### Pre-conditions
- [ ] Read `app/services/evidence_registry_service.py` before touching it
- [ ] 275 tests pass

### Steps

1. Add `import operator` at the top of the file.

2. Define the dispatch table near `_eval_trigger_condition`:
```python
_TRIGGER_OPS: dict[str, Callable] = {
    "==":  operator.eq,
    "!=":  operator.ne,
    ">":   operator.gt,
    "<":   operator.lt,
    ">=":  operator.ge,
    "<=":  operator.le,
}
```

3. Rewrite `_eval_trigger_condition`:
```python
def _eval_trigger_condition(trigger: dict, decision_payload: dict) -> bool:
    field = trigger.get("triggerField")
    if not field:
        return False
    expected = trigger.get("triggerValue")
    op_key = trigger.get("triggerOperator", "==")
    actual = decision_payload.get(field)
    if actual is None:
        return False
    op_fn = _TRIGGER_OPS.get(op_key)
    if op_fn is None:
        return False  # unknown operator: safe default
    try:
        return op_fn(float(actual) if op_key != "==" else actual,
                     float(expected) if op_key != "==" else expected)
    except (TypeError, ValueError):
        return False
```

**Ambiguity note:** The `==` case should compare values as-is (strings, bools); numeric operators cast to float. Verify this matches existing test expectations before committing.

### Test command
```bash
source venv/bin/activate && python -m pytest tests/test_evidence_registry_service.py -v
source venv/bin/activate && python -m pytest tests/ -q
```
**Pass condition:** All evidence registry tests pass; 275 total pass.

### Commit message
```
refactor: replace operator if-chain with dispatch table in evidence_registry_service

_eval_trigger_condition now uses _TRIGGER_OPS dict. Adds !=, <, >=, <=
support automatically. Unknown operators return False (safe default).
```

### STOP conditions
- Any evidence registry test changes result → halt, check if `==` equality semantics changed (string vs numeric comparison edge case)

---

## Task 3A — Create `BedrockStructuredExtractor` and Collapse Thin Wrappers

**Branch:** `refactor/bedrock-structured-extractor`
**Requires:** Tasks 0, 1C (model ID config), 1D (llm_utils) complete.
**Risk level:** MEDIUM — pipeline_service.py must be updated; test mocks may need updating.

### Pre-conditions
- [ ] `app/config/bedrock_config.py` exists
- [ ] `app/utils/llm_utils.py` exists with `extract_json`
- [ ] 275 tests pass
- [ ] Read `app/services/pipeline_service.py` and understand both extraction call sites before starting

### Steps

1. Create `app/services/bedrock_extractor.py`:
```python
"""Generic Bedrock → Pydantic extractor.

Replaces decision_context_service and risk_evidence_llm,
which share the same call-validate-return-None skeleton.
"""
import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel

from app.bedrock_client import BedrockClient
from app.utils.llm_utils import extract_json

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class BedrockStructuredExtractor:
    def __init__(self, _client: Optional[BedrockClient] = None):
        self._client = _client or BedrockClient()

    def extract(
        self,
        prompt: str,
        output_model: Type[T],
        system_prompt: Optional[str] = None,
    ) -> Optional[T]:
        """Call Bedrock, parse JSON, validate against output_model.

        Returns None on any failure (network, parse, validation).
        """
        try:
            raw = self._client.invoke(prompt, system_prompt=system_prompt)
            data = extract_json(raw)
            if data is None:
                logger.warning("BedrockStructuredExtractor: no JSON in response")
                return None
            return output_model(**data)
        except Exception as exc:
            logger.warning("BedrockStructuredExtractor: %s", exc)
            return None
```

2. Update `app/services/pipeline_service.py`:
   - Replace the `decision_context_service` import with `BedrockStructuredExtractor`
   - Replace the `risk_evidence_llm` import with `BedrockStructuredExtractor`
   - Wire up the same prompts and output models through `extractor.extract()`

3. Run tests. If any test file imports `decision_context_service` or `risk_evidence_llm` directly, update those imports to use `BedrockStructuredExtractor`.

4. Once all 275 tests pass, delete `app/services/decision_context_service.py` and `app/services/risk_evidence_llm.py`.

### STOP conditions
- Tests drop below 275 after step 2 → revert step 2, keep new file, log the blocker
- Any test references `decision_context_service` or `risk_evidence_llm` as a direct unit-under-test → do not delete; log as "requires test migration first"

### Commit message
```
refactor: introduce BedrockStructuredExtractor; remove thin LLM wrappers

decision_context_service.py and risk_evidence_llm.py deleted.
pipeline_service.py updated to use BedrockStructuredExtractor.extract().
Tests: 275 pass.
```

---

## Global STOP Conditions (apply to all tasks)

1. **Test count drops** below 275 → revert last change, log the failure, do not proceed.
2. **Import error** after editing any file → fix import before committing.
3. **Ambiguous business logic** (e.g., operator equality semantics, profile alias not in list) → log as "NEEDS_HUMAN_REVIEW: <description>" and skip that specific change.
4. **File not found** during refactor → the file may have been renamed; `git log --follow` to trace it, or log and skip.
5. **Any change to `app/schemas/responses.py`** → STOP immediately. This file is locked.
6. **Any change to `alembic/versions/`** → STOP immediately.
7. **Any change to `app/services/sso_service.py`** → STOP immediately (out of scope).
