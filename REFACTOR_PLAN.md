# Refactor Plan

**Execution order:** highest impact × lowest effort first.
**Safety rule:** run `pytest tests/ -q` after every step. Stop on any failure.

---

## Phase 0 — Foundation (must run first, everything depends on this)

### P0-A: Create shared config and utils modules
**Problem:** Constants and utility functions are scattered or duplicated; no canonical home.
**Target pattern:** Thin modules in `app/config/` and `app/utils/` imported everywhere.
**Effort:** S (< 1 hr)
**Dependencies:** None — these are new files with no callers yet.
**Acceptance criteria:**
- `app/config/bedrock_config.py` exists with `NOVA_MODEL_ID`, `BEDROCK_REGION`, `BEDROCK_TIMEOUT`
- `app/config/company_config.py` exists with `PROFILE_ALIASES`
- `app/config/risk_config.py` exists with `RISK_BANDS`, `CONFIDENCE_PARAMS`
- `app/utils/formatters.py` exists with `format_krw(amount) -> str`
- `app/utils/llm_utils.py` exists with `extract_json(text) -> Optional[dict]`
- All 275 tests still pass (no callers changed yet)

---

## Phase 1 — High-Impact Duplicate Elimination

### P1-A: Eliminate duplicate `_fmt_krw()`
**Problem:** `_fmt_krw()` is copy-pasted identically in `nova_scenario_proposer.py` (line ~117) and `risk_response_simulation_service.py` (line ~56). Bug fixes must be applied twice.
**Target pattern:** Single `format_krw()` in `app/utils/formatters.py`; both services import it.
**Effort:** S
**Dependencies:** P0-A (formatters.py must exist)
**Acceptance criteria:**
- `_fmt_krw` no longer defined in either service file
- Both files import `from app.utils.formatters import format_krw`
- 275 tests pass

---

### P1-B: Consolidate `_PROFILE_ALIASES` to single source
**Problem:** `_PROFILE_ALIASES = {"mayo_central": "mayo_central_hospital"}` defined independently in `external_signal_service.py` and `curated_external_signal_provider.py`.
**Target pattern:** Single `PROFILE_ALIASES` in `app/config/company_config.py`; both files import it.
**Effort:** S
**Dependencies:** P0-A
**Acceptance criteria:**
- `_PROFILE_ALIASES` local definition removed from both service files
- Both import `from app.config.company_config import PROFILE_ALIASES`
- 275 tests pass

---

### P1-C: Consolidate Bedrock Model ID to config
**Problem:** `"us.amazon.nova-2-lite-v1:0"` appears as a literal string in 3 files.
**Target pattern:** All import `from app.config.bedrock_config import NOVA_MODEL_ID`.
**Effort:** S
**Dependencies:** P0-A
**Acceptance criteria:**
- String literal `"us.amazon.nova-2-lite-v1:0"` appears in exactly one file (`bedrock_config.py`)
- 275 tests pass

---

### P1-D: Consolidate JSON extraction to `llm_utils.py`
**Problem:** Ad-hoc JSON extraction from LLM responses (`find('{')...rfind('}')`) duplicated in `o1_reasoner.py`, `nova_scenario_proposer.py`, `nova_external_signal_summarizer.py`. `BedrockClient._strip_markdown()` does a related but narrower job.
**Target pattern:** `app/utils/llm_utils.py::extract_json(text) -> Optional[dict]`. Callers replace inline extraction.
**Effort:** M (1–3 hr — need to verify each call site produces equivalent output)
**Dependencies:** P0-A
**Acceptance criteria:**
- No inline `text.find('{')` JSON extraction in any service file
- `extract_json` handles markdown-fenced JSON and bare JSON equally
- 275 tests pass

---

## Phase 2 — Structural Simplification

### P2-A: Extract pure functions from `governance.py::load_rules()`
**Problem:** File I/O, path resolution, and language-overlay transformation are merged in one function. The transformation cannot be unit tested without disk I/O.
**Target pattern:** Extract `_apply_translation(raw: dict, lang: str) -> dict` as a pure function. `load_rules` calls it after loading JSON.
**Effort:** S
**Dependencies:** None (self-contained change)
**Acceptance criteria:**
- `_apply_translation` is a standalone function called from `load_rules`
- A unit test can call `_apply_translation({"translations": {...}}, "en")` without touching disk
- 275 tests pass

---

### P2-B: Convert if-chains in `external_signal_service.py` to config tables
**Problem:** `_infer_decision_type()` (4 `if` branches) and the theme-inference block (4 `if` blocks) are hardcoded priority chains.
**Target pattern:** Config lists/dicts in the same file (or `app/config/`); loop over config instead of if-chains.
**Effort:** M
**Dependencies:** None
**Acceptance criteria:**
- `_infer_decision_type` uses `_DECISION_TYPE_PRIORITY` list (or similar) instead of 4 `if` statements
- Theme inference uses `_FLAG_KEYWORD_THEMES` mapping table instead of 4 `if` blocks
- Adding a new decision type or theme requires only a config entry, not code change
- 275 tests pass

---

### P2-C: Convert `_FLAG_SEVERITY_PATTERNS` list to dict in `normalizers.py`
**Problem:** Severity lookup uses a list of tuples instead of a dict. O(n) lookup, verbose.
**Target pattern:** `_FLAG_SEVERITY_MAP: dict[str, FlagSeverity]` with O(1) lookup.
**Effort:** S
**Dependencies:** None
**Acceptance criteria:**
- `_FLAG_SEVERITY_PATTERNS` list removed
- `_FLAG_SEVERITY_MAP` dict used instead
- 275 tests pass

---

### P2-D: Extract operator dispatch in `evidence_registry_service.py`
**Problem:** `_eval_trigger_condition` handles only `>` and `==` via an `if` chain. Adding operators requires code changes.
**Target pattern:** `_OPS: dict[str, Callable]` with `operator.gt`, `operator.eq`, etc.
**Effort:** S
**Dependencies:** None
**Acceptance criteria:**
- Operator logic is a dict dispatch; no `if operator == "..."` chain
- At minimum `==`, `>`, `<`, `>=`, `<=` supported
- Existing tests pass; add 3 new test cases for new operators if time permits

---

## Phase 3 — Service Consolidation (L effort, higher risk)

### P3-A: Create `BedrockStructuredExtractor` and collapse thin LLM wrappers
**Problem:** `decision_context_service.py` and `risk_evidence_llm.py` are structurally identical (prompt → Bedrock → Pydantic → None-on-fail). Two services for one pattern.
**Target pattern:** `app/services/bedrock_extractor.py::BedrockStructuredExtractor.extract(prompt, output_model, system_prompt) -> Optional[BaseModel]`
**Effort:** L (3 hr+ — must update pipeline_service.py callers and verify end-to-end)
**Dependencies:** P1-D (llm_utils.py must exist), P1-C (model ID from config)
**Acceptance criteria:**
- `BedrockStructuredExtractor` handles the call-validate-return-none pattern
- `pipeline_service.py` updated to use it for both extraction steps
- `decision_context_service.py` and `risk_evidence_llm.py` deleted
- 275 tests pass
- `test_decision_context_extraction.py` and `test_risk_semantics.py` still pass (via updated import paths or in-place mocks)

---

### P3-B: Refactor `BedrockClient` for testability
**Problem:** `invoke()` mixes env-var reading, HTTP call, response parsing, and markdown stripping. Not independently testable.
**Target pattern:** Pure `_build_payload(...)` and `_parse_response(...)` methods. `api_key` read at `__init__`. `http_client` injectable for tests.
**Effort:** L
**Dependencies:** P3-A (extractor will call client; client interface must be stable before extractor)
**STOP condition:** If changing `BedrockClient.__init__` signature breaks any existing mock in tests, halt and log. The existing `_client=` injection pattern in tests must be preserved or migrated carefully.
**Acceptance criteria:**
- `BedrockClient(api_key=..., http_client=...)` works with injected dependencies
- `_build_payload` and `_parse_response` are callable in isolation (pure)
- `invoke()` still works end-to-end with no injection (uses env var + real httpx)
- 275 tests pass

---

## Phase 4 — Configuration Externalization (optional / follow-up)

### P4-A: Move risk band thresholds to `risk_config.py`
**Problem:** `_BAND_*` and `_CONF_*` constants in `risk_scoring_service.py` are not company-configurable.
**Target pattern:** Import from `app/config/risk_config.py`. Healthcare profile already overrides weights; bands should follow the same pattern.
**Effort:** M
**Dependencies:** P0-A
**CAUTION:** `risk_scoring_service.py` has 26 tests. Change only the constant source, not the logic.
**Acceptance criteria:**
- Constants in `risk_config.py`, not hardcoded in service
- 26 risk scoring tests + all 275 tests pass

---

### P4-B: Surface budget thresholds as named, documented constants
**Severity:** Downgraded to LOW — `_CAPEX_THRESHOLD` and `_BOARD_THRESHOLD` serve current requirements and are not causing active bugs.
**Action:** Add a comment linking them to governance rule IDs so future engineers know where to change them.
**Effort:** S
**Dependencies:** None
**Acceptance criteria:** Comment added; no logic changes.

---

## Execution Summary

| Priority | Item | Effort | Risk |
|----------|------|--------|------|
| P0-A | Create config/utils modules | S | None |
| P1-A | Dedupe `_fmt_krw` | S | Low |
| P1-B | Dedupe `PROFILE_ALIASES` | S | Low |
| P1-C | Dedupe model ID | S | Low |
| P1-D | Consolidate JSON extraction | M | Low |
| P2-A | Extract `_apply_translation` | S | Low |
| P2-B | Config tables in external_signal_service | M | Low |
| P2-C | Severity list → dict | S | Low |
| P2-D | Operator dispatch table | S | Low |
| P3-A | `BedrockStructuredExtractor` | L | Medium |
| P3-B | `BedrockClient` testability | L | Medium |
| P4-A | Risk band config externalization | M | Low |
| P4-B | Budget threshold comments | S | None |
