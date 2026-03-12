# Architecture Decisions

This document explains each pattern being introduced in the refactor, why it was chosen, how to extend it correctly, and what to avoid. It doubles as technical documentation for external reviewers.

---

## AD-1: Shared Config Modules (`app/config/`)

### Decision
All magic values (model IDs, profile aliases, risk thresholds) move to dedicated config modules in `app/config/` instead of living as module-level constants inside service files.

### Why
Three copies of `"us.amazon.nova-2-lite-v1:0"` existed independently. When the Nova model version changes, every copy must be updated — and they can drift silently (no test catches a stale model ID). Centralised config makes the single source of truth explicit.

### How to extend
To configure a new Bedrock model or region:
1. Add the constant to `app/config/bedrock_config.py`
2. Import it in the service that needs it

To add a new company profile alias:
1. Add an entry to `PROFILE_ALIASES` in `app/config/company_config.py`
2. No other code changes needed

### What NOT to do
- Do not add business logic to config modules — they are pure data (constants and dicts).
- Do not add config that is already managed by environment variables (secrets, base URLs). Config modules are for structural/policy values, not secrets.
- Do not create one config file per service. Group by domain (`bedrock_config`, `risk_config`, `company_config`), not by consumer.

---

## AD-2: Utility Modules (`app/utils/`)

### Decision
Reusable, pure functions with no business-domain knowledge live in `app/utils/`. Currently: `formatters.py` (KRW formatting) and `llm_utils.py` (JSON extraction from LLM responses).

### Why
`_fmt_krw()` was copy-pasted identically into two service files. A bug fix in one would silently leave the other broken. Utility modules make the canonical implementation discoverable.

### How to extend
To add a new formatter (e.g., USD compact notation):
```python
# app/utils/formatters.py
def format_usd_compact(amount: Optional[float]) -> str:
    """Format USD as '$1.2B', '$450M', etc."""
    ...
```
Import wherever needed. No config changes required.

To add JSON extraction support for arrays (not just objects):
- Extend `extract_json` in `llm_utils.py` to handle list-rooted responses.
- All callers benefit automatically.

### What NOT to do
- Do not put domain logic in utils (no governance rules, no risk scoring).
- Do not put I/O in utils (no file reads, no HTTP calls).
- Do not let utils import from service modules — utils must have no upward dependencies.

---

## AD-3: Config Tables for if-chains (Data-Driven Dispatch)

### Decision
Multi-branch `if/elif` chains that switch on string values are replaced with config tables (lists or dicts) that a loop iterates over. The function body becomes a generic loop; extensions are config rows.

### Why
The dev rules for this codebase explicitly forbid keyword lists that encode semantic meaning. More broadly, adding a new decision type or theme previously required editing function bodies, which is error-prone and untestable at the individual-case level.

### How to extend
Example: adding a new decision type `"vendor_contract"`:

**Before (requires code edit):**
```python
def _infer_decision_type(decision: dict) -> str:
    if decision.get("involves_hiring"):
        return "hiring"
    # ... must add another if here
```

**After (add a config row):**
```python
_DECISION_TYPE_PRIORITY = [
    ("involves_hiring", "hiring"),
    ("uses_pii", "privacy"),
    ("new_product_development", "new_product"),
    ("involves_vendor_contract", "vendor_contract"),  # ← add here only
]
```

### What NOT to do
- Do not use keyword config tables for **semantic classification that affects scoring** — this violates dev rule #1. Config tables here are only for structural dispatch (field → enum value, flag prefix → severity level).
- Do not add scoring weights or evidence generation to config tables — use LLM structured output for semantic decisions.
- Do not silently drop unrecognised values — default to `"general"` or raise a warning; never silently return wrong data.

---

## AD-4: `BedrockStructuredExtractor` (Generic LLM Call + Validate Pattern)

### Decision
A single generic class replaces two near-identical thin service wrappers (`decision_context_service.py`, `risk_evidence_llm.py`). The class takes a prompt and a Pydantic output model and returns either a validated instance or `None`.

### Why
The pattern `invoke → extract_json → Model(**data) → None on fail` appeared verbatim in both services. The only variation is the prompt and the output model — both of which are already parameters at the call site. Collapsing them into one class removes ~150 lines of duplicate code and gives a single place to improve error logging, retry logic, or timeout behaviour.

### How to extend
To add a new LLM extraction step to the pipeline:
1. Define a Pydantic output schema in `app/schemas/`
2. Write the prompt (as a string or a prompt-builder function)
3. In `pipeline_service.py`:
```python
result = extractor.extract(
    prompt=build_my_prompt(context),
    output_model=MyOutputSchema,
    system_prompt=MY_SYSTEM_PROMPT,
)
```
No new service file needed.

### What NOT to do
- Do not put scoring or governance logic inside `BedrockStructuredExtractor`. It is an I/O adapter only.
- Do not add retries with exponential backoff without testing for idempotency first — LLM calls are not always safe to retry (costs, non-determinism).
- Do not catch `Exception` and silently return `None` for errors that indicate misconfiguration (missing API key, wrong model ID). Only suppress transient/expected failures (parse errors, validation errors). Consider re-raising `RuntimeError` for auth failures.

---

## AD-5: Pure Function Extraction (Testability)

### Decision
Functions that mix I/O with transformation logic are split: I/O stays in an outer function; the transformation becomes a pure inner function. Example: `governance.py::load_rules()` → `_apply_translation()` is now pure and callable without disk.

### Why
Pure functions are trivially unit-testable — no mocks, no fixtures, no filesystem. When `_apply_translation` was embedded in `load_rules`, testing the language-overlay logic required either writing JSON to a temp file or patching `open()`. Extracting it makes testing direct and fast.

### How to extend
This pattern applies whenever you need to add a new transformation to a function that already does I/O:
1. Write the transformation as a pure function.
2. Call it from the I/O function.
3. Test the pure function directly with in-memory data.

### What NOT to do
- Do not extract pure functions into a separate service module just to make them "reusable" if there is only one caller — keep them as module-level private functions (`_apply_translation`, not a new service class).
- Do not let the pure function call `os.environ`, open files, or make HTTP requests. If it does, it is not pure.
- Do not remove the I/O outer function — callers rely on it; only the internals change.

---

## AD-6: Dependency Injection for Testability (BedrockClient)

### Decision
`BedrockClient` is refactored so that the API key and HTTP client can be injected at construction time. This is already partially done (`_client=` parameter in services) — the goal is to make the existing pattern more consistent.

### Why
The current pattern requires mocking `os.environ` or the `httpx.post` global to test `BedrockClient` in isolation. Injecting the HTTP client as a constructor parameter lets tests pass a `httpx.MockTransport` or a pre-configured test client without global mocking.

### How to extend
```python
# In tests:
import httpx
from unittest.mock import Mock

mock_transport = httpx.MockTransport(handler=my_handler)
client = BedrockClient(
    api_key="test-key",
    http_client=httpx.Client(transport=mock_transport),
)
```

### What NOT to do
- Do not make the API key a required constructor argument — it must still default to `os.environ.get("BEDROCK_API_KEY")` for production use.
- Do not inject the HTTP client in every method call — inject once at construction. Method-level injection is a code smell for "this should be a constructor argument".
- Do not expose the HTTP client as a public attribute — it is an implementation detail.

---

## Cross-Cutting: Dev Rules Enforcement

This codebase enforces four rules. Every refactoring decision was made with these in mind:

1. **No scenario-specific if-else** — config tables (AD-3) replace string-matching branches.
2. **LLM = classifier/extractor only** — `BedrockStructuredExtractor` (AD-4) keeps LLM calls pure I/O; all scoring happens in deterministic code.
3. **Every metric needs provenance** — risk scoring evidence chains are not touched in this refactor; they remain intact.
4. **Table → LLM → ontology → branch** — when a new semantic classification is needed, it goes into an LLM call with a Pydantic schema, not an if-chain. This refactor adds config tables only for **structural dispatch** (field existence → type string), not for semantic meaning.

Any future engineer extending this codebase should ask: *"Is this a structural rule (config table OK) or a semantic rule (needs LLM classification)?"* before adding any new mapping.
