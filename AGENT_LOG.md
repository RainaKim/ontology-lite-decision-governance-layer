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
   contains `PROFILE_ALIASES`. Tasks that reference `company_config.py` will use `company_registry.py`.

3. **P3-A deletion BLOCKED**: `tests/test_decision_context_extraction.py` imports directly from
   `decision_context_service` and `tests/test_risk_semantics.py` imports directly from
   `risk_evidence_llm`. Per STOP condition: "Any test references [these] as a direct unit-under-test →
   do not delete; log as 'requires test migration first'". Will create BedrockStructuredExtractor
   and update pipeline_service.py but NOT delete the old service files.

---

## Task Log

### Task 0 — Foundation: Config and Utils Modules
**Branch:** `refactor/foundation`
**Status:** 🔄 IN_PROGRESS

Files to create:
- `app/config/bedrock_config.py`
- `app/config/risk_config.py`
- `app/utils/__init__.py`
- `app/utils/formatters.py`
- `app/utils/llm_utils.py`

---

### Task 1A — Dedupe `_fmt_krw`
**Branch:** `refactor/dedupe-formatters`
**Status:** ⏳ PENDING

---

### Task 1B — Dedupe `PROFILE_ALIASES`
**Branch:** N/A
**Status:** ✅ ALREADY DONE (pre-existing import from company_registry.py)

---

### Task 1C — Dedupe Bedrock Model ID
**Branch:** `refactor/dedupe-model-id`
**Status:** ⏳ PENDING

---

### Task 1D — Consolidate JSON extraction
**Branch:** `refactor/consolidate-json-extraction`
**Status:** ⏳ PENDING

---

### Task 2A — Extract `_apply_translation` from governance.py
**Branch:** `refactor/governance-pure-translation`
**Status:** ⏳ PENDING

---

### Task 2B — Config tables in external_signal_service.py
**Branch:** `refactor/external-signal-config-tables`
**Status:** ⏳ PENDING

---

### Task 2C — Severity list → dict in normalizers.py
**Branch:** `refactor/normalizers-severity-dict`
**Status:** ⏳ PENDING

---

### Task 2D — Operator dispatch table in evidence_registry_service.py
**Branch:** `refactor/trigger-operator-dispatch`
**Status:** ⏳ PENDING

---

### Task 3A — BedrockStructuredExtractor
**Branch:** `refactor/bedrock-structured-extractor`
**Status:** ⏳ PENDING
**Note:** Will create extractor and update pipeline_service.py. Old service files
(`decision_context_service.py`, `risk_evidence_llm.py`) will NOT be deleted until
test files are migrated (STOP condition triggered).

---

### Task 4A — Risk band config externalization
**Branch:** `refactor/risk-config-externalize`
**Status:** ⏳ PENDING

---

### Task 4B — Budget threshold comments
**Branch:** `refactor/budget-threshold-comments`
**Status:** ⏳ PENDING
