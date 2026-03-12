# Agent Refactor Log

**Baseline:** 275 tests pass on `refactor/prep`
**Date:** 2026-03-12
**Agent model:** claude-sonnet-4-6

---

## Status Legend
- ✅ DONE — committed, PR open
- 🔄 IN_PROGRESS
- ⏳ PENDING
- ❌ BLOCKED — see note
- ⚠️ SKIPPED — see note

---

## Pre-flight Observations

1. **P1-B already done**: Both `external_signal_service.py` and `curated_external_signal_provider.py`
   already import `PROFILE_ALIASES` from `app.config.company_registry`. No change needed.

2. **P0-A company_config.py** not needed: `app/config/company_registry.py` already exists and
   contains `PROFILE_ALIASES`. Tasks that reference `company_config.py` use `company_registry.py`.

3. **P3-A pipeline_service.py update BLOCKED**: `tests/test_decision_context_extraction.py` imports
   directly from `decision_context_service` (tests `is_left_panel_safe`, `filter_left_panel_entities`,
   prompt builders). `tests/test_risk_semantics.py` imports `infer_risk_semantics` from
   `risk_evidence_llm`. Both services have non-trivial domain logic tested separately from the
   LLM call pattern. Per STOP condition: old service files NOT deleted, pipeline_service.py NOT
   updated. BedrockStructuredExtractor created as a standalone addition only.
   Resolution: migrate test_decision_context_extraction.py and test_risk_semantics.py to test
   their domain logic independently of the LLM call path, then complete the pipeline_service.py
   migration.

---

## Task Log

### Task 0 — Foundation: Config and Utils Modules
**Branch:** `refactor/foundation`
**PR:** #18
**Status:** ✅ DONE
**Files created:**
- `app/config/bedrock_config.py` — NOVA_MODEL_ID, BEDROCK_REGION, BEDROCK_TIMEOUT
- `app/config/risk_config.py` — RISK_BANDS, CONFIDENCE_PARAMS
- `app/utils/__init__.py`
- `app/utils/formatters.py` — canonical format_krw()
- `app/utils/llm_utils.py` — canonical extract_json()

---

### Task 1A — Dedupe `_fmt_krw`
**Branch:** `refactor/dedupe-formatters`
**PR:** #19
**Status:** ✅ DONE
- Removed `_fmt_krw` from `nova_scenario_proposer.py` and `risk_response_simulation_service.py`
- Both import `format_krw` from `app.utils.formatters`

---

### Task 1B — Dedupe `PROFILE_ALIASES`
**Branch:** N/A
**Status:** ✅ ALREADY DONE (pre-existing import from company_registry.py in both files)

---

### Task 1C — Dedupe Bedrock Model ID
**Branch:** `refactor/dedupe-model-id`
**PR:** #20
**Status:** ✅ DONE
- Removed literal from: `bedrock_client.py`, `nova_scenario_proposer.py`,
  `nova_external_signal_summarizer.py`, `llm_client.py`
- All import `NOVA_MODEL_ID` from `app.config.bedrock_config`

---

### Task 1D — Consolidate JSON extraction
**Branch:** `refactor/consolidate-json-extraction`
**PR:** #21
**Status:** ✅ DONE
- Replaced inline markdown-fence + `json.loads` in `nova_scenario_proposer.py`
  and `nova_external_signal_summarizer.py` with `extract_json()` from `app.utils.llm_utils`
- Removed unused `import json` from both files
- Note: `o1_reasoner.py` still has inline extraction — it is not in the
  REFACTOR_SCOPE.md "In Scope" list; left unchanged

---

### Task 2A — Extract `_apply_translation` from governance.py
**Branch:** `refactor/governance-pure-translation`
**PR:** #22
**Status:** ✅ DONE
- Extracted `_apply_translation(raw, lang) -> dict` as a pure function
- `load_rules()` now calls `_apply_translation` after loading JSON

---

### Task 2B — Config tables in external_signal_service.py
**Branch:** `refactor/external-signal-config-tables`
**PR:** #23
**Status:** ✅ DONE
- Added `_DECISION_TYPE_PRIORITY`, `_FLAG_KEYWORD_THEMES`, `_STRATEGIC_IMPACT_KEYWORDS`
- `_infer_decision_type`, `_infer_strategic_impact`, and theme-inference loop
  now iterate config tables

---

### Task 2C — Severity list → dict in normalizers.py
**Branch:** `refactor/normalizers-severity-dict`
**PR:** #24
**Status:** ✅ DONE
- Replaced `_FLAG_SEVERITY_PATTERNS` list with `_FLAG_SEVERITY_MAP` dict
- Lookup uses `dict.items()` iteration

---

### Task 2D — Operator dispatch table in evidence_registry_service.py
**Branch:** `refactor/trigger-operator-dispatch`
**PR:** #25
**Status:** ✅ DONE
- Added `_TRIGGER_OPS: dict[str, Callable]` with ==, !=, >, <, >=, <=
- `_eval_trigger_condition` replaced if-chain with dict dispatch

---

### Task 3A — BedrockStructuredExtractor
**Branch:** `refactor/bedrock-structured-extractor`
**PR:** #26
**Status:** ✅ DONE (partial — see NEEDS_HUMAN_REVIEW below)
**Created:** `app/services/bedrock_extractor.py` with `BedrockStructuredExtractor`

**NEEDS_HUMAN_REVIEW: Full pipeline_service.py migration blocked**
- `decision_context_service.py` cannot be deleted: `test_decision_context_extraction.py`
  tests domain-specific functions (`is_left_panel_safe`, `filter_left_panel_entities`,
  `_JUDGMENT_KEY_PREFIXES`). These are not the LLM-call pattern — they're extraction
  domain logic that lives correctly in the service file.
- `risk_evidence_llm.py` cannot be deleted: `test_risk_semantics.py` imports
  `infer_risk_semantics` directly, and the test injects mock clients via `_client=`.
- To complete P3-A: refactor tests to import domain logic independently from the
  LLM wiring, then replace `pipeline_service.py` call sites with `BedrockStructuredExtractor`.

---

### Task 4A — Risk band config externalization
**Branch:** (not started)
**Status:** ⏳ PENDING
**Note:** `risk_scoring_service.py` is listed as Out of Scope in REFACTOR_SCOPE.md
("Core scoring engine with 26 tests; constant extraction is LOW risk but should be
done carefully as a separate PR"). Foundation exists: `app/config/risk_config.py`
already has the matching constants. Migration is a safe, isolated change when ready.

---

### Task 4B — Budget threshold comments
**Branch:** `refactor/budget-threshold-comments`
**PR:** #27
**Status:** ✅ DONE
- Added governance rule ID comments to `_CAPEX_THRESHOLD` and `_BOARD_THRESHOLD`

---

## Summary

| Task | Status | PR |
|------|--------|----|
| P0-A Foundation | ✅ | #18 |
| P1-A Dedupe _fmt_krw | ✅ | #19 |
| P1-B Dedupe PROFILE_ALIASES | ✅ Pre-existing | — |
| P1-C Dedupe model ID | ✅ | #20 |
| P1-D Consolidate JSON extraction | ✅ | #21 |
| P2-A _apply_translation | ✅ | #22 |
| P2-B Config tables | ✅ | #23 |
| P2-C Severity dict | ✅ | #24 |
| P2-D Operator dispatch | ✅ | #25 |
| P3-A BedrockStructuredExtractor | ✅ partial | #26 |
| P4-A Risk band externalization | ⏳ (Out of scope per REFACTOR_SCOPE.md) | — |
| P4-B Budget threshold comments | ✅ | #27 |

**Tests throughout:** 275 pass on every commit. No regressions.
