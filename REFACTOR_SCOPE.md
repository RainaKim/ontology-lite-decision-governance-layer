# Refactor Scope — Decision Governance Layer
**Date**: 2026-03-12
**Based on**: REFACTOR_AUDIT.md

---

## Modules Safe to Refactor

These modules have clear, mechanical fixes with no business-logic ambiguity. Each has existing test coverage that can verify correctness after the change.

### R1 — `app/config/company_registry.py` (NEW FILE)
**What**: Create a single source of truth for company ID → rules file mapping and profile aliases.
**Replaces**:
- `_COMPANY_RULES_FILES` in `app/governance.py`
- `_REGISTRY` in `app/services/company_service.py`
- `_PROFILE_ALIASES` in `app/services/external_signal_service.py`
- `_PROFILE_ALIASES` in `app/providers/curated_external_signal_provider.py`

**Risk**: LOW — pure consolidation, no logic change. All four files become importers.
**Test gate**: All existing company-resolution tests pass unchanged.

---

### R2 — `app/governance.py` — Magic number extraction
**What**: Replace severity/strategic-impact bonuses with named constants at module top.
```python
# Before
severity_weights = {"critical": 8.0, "high": 3.0, "medium": 1.5, "low": 0.5}

# After
_SEVERITY_WEIGHTS = {"critical": 8.0, "high": 3.0, "medium": 1.5, "low": 0.5}
```
**Risk**: LOW — rename only; values do not change.
**Test gate**: Governance evaluation tests produce identical scores.

---

### R3 — `app/services/risk_scoring_service.py` — Named constants for magic numbers
**What**:
- Extract band thresholds (40, 70, 85) to `_BAND_LOW`, `_BAND_MEDIUM`, `_BAND_HIGH`
- Extract confidence formula constants to `_CONF_BASE`, `_CONF_DECAY`, `_CONF_MIN`, `_CONF_MAX`
- Extract priority weights to `_PRIORITY_WEIGHTS` dict (already partially named — just document)

**Risk**: LOW — value-neutral rename.
**Test gate**: All 26 risk scoring unit tests pass with identical numeric output.

---

### R4 — `app/demo_fixtures/external_sources/{company_id}_priorities.json` (NEW FILES)
**What**: Extract `_DECISION_TYPE_PRIORITY` from `curated_external_signal_provider.py` into per-company JSON files. Provider loads at startup.
**Risk**: LOW-MEDIUM — logic stays the same; only storage changes. Must verify JSON loading and fallback when file absent.
**Test gate**: External signal tests produce same signal IDs for same inputs.

---

### R5 — `app/services/risk_scoring_service.py` — Industry code lookup
**What**: Add `industry_code` field (optional) to company JSON configs. If present, use it instead of substring matching. If absent, fall back to existing substring logic (no regression).
**Risk**: LOW — strictly additive; existing path unchanged when `industry_code` absent.
**Test gate**: Healthcare weight (0.50) still applied for mayo_central after change.

---

### R6 — `app/routers/decisions.py` — Extract dependencies
**What**: Move tenant isolation check and company existence validation out of route handler into reusable FastAPI dependencies.
**Risk**: LOW-MEDIUM — HTTP response codes/messages must stay identical to avoid breaking callers.
**Test gate**: Decision submission tests pass; 403 and 422 responses still returned correctly.

---

### R7 — Delete Dead Seed Scripts
**What**: Delete `scripts/seed_companies.py` and `scripts/seed_decisions.py`. Alembic migrations 0008 and 0009 are authoritative.
**Risk**: NONE — files are unused during normal app lifecycle.
**Test gate**: Test suite passes identically before and after deletion.

---

### R8 — Delete Orphaned Test Fixture File
**What**: Delete `test_request.json` from project root.
**Risk**: NONE.
**Test gate**: All tests pass.

---

### R9 — Verify and Delete Unused Modules
**What**: Confirm `app/e2e_runner.py` and `app/ontology.py` have zero imports anywhere, then delete them.
**Risk**: LOW — must grep imports before deleting.
**Test gate**: All tests pass; no ImportError.

---

### R10 — Consolidate Ko/En Company JSON Files
**What**: Merge each Ko/En pair into a single file with `"translations": {"ko": {...}, "en": {...}}` structure. Update `_COMPANY_RULES_FILES` (or its replacement from R1) to point to the merged file.
**Risk**: MEDIUM — both `governance.py` and `company_service.py` load these files; must update all call sites and verify governance evaluation produces identical output.
**Test gate**: Governance evaluation tests pass with identical triggered rules for all three companies.

---

### R11 — Create `tests/conftest.py` with Shared Fixtures
**What**: Extract `_make_user()` helper and inline mock-user/mock-company creation from `test_auth.py`, `test_rbac.py`, `test_sso.py` into `tests/conftest.py` as `@pytest.fixture` functions.
**Risk**: LOW — functional equivalence; just moves where setup code lives.
**Test gate**: All 275+ tests pass.

---

## Out of Scope (Do Not Touch)

### OOS-1 — `_COST_REDUCTION_KEYWORDS` replacement
**Why**: Replacing with LLM classification requires new `GoalCategory` Pydantic model, changes to `risk_evidence_llm.py`, and significant test surface. The risk_semantics scaffolding exists but is not fully wired. This is a feature change, not a refactor. The existing TODO comment is sufficient documentation for now.

### OOS-2 — `_PRIVACY_KEYWORDS` replacement
**Why**: Would require extending the LLM extractor prompt and adding a new Pydantic output field. Touches `governance.py`, `app/schemas/`, and LLM call paths. Not a mechanical fix.

### OOS-3 — `_TYPE_HINT_KEYWORDS` replacement
**Why**: Semantic similarity between rule text and goal text is a non-trivial LLM integration. Out of scope for a structural refactor.

### OOS-4 — Moving weights to company JSON config (risk_tolerance)
**Why**: Requires schema changes to company JSON files, parsing changes in `risk_scoring_service.py`, and risk of breaking the existing 26 risk scoring tests with wrong weight lookups. Should be tackled as a separate "config-driven weights" feature with its own test suite.

### OOS-5 — Neo4j migration (`app/o1_reasoner.py`)
**Why**: Infrastructure change, not a code refactor. Requires a new graph DB service.

### OOS-6 — Any file under `tests/`
**Why**: Test files should only be updated to match refactored signatures. Do not restructure tests during refactoring.

### OOS-7 — `app/services/pipeline_service.py`
**Why**: Async orchestrator with 5 interdependent steps and complex error handling. Any change risks pipeline failures that are hard to debug. No audit finding targets this file directly.

### OOS-8 — `app/schemas/responses.py`
**Why**: Pydantic response contracts are marked LOCKED in project memory. Do not touch.

### OOS-9 — `app/routers/sso.py` and `app/services/sso_service.py`
**Why**: OAuth2/OIDC flow. Security-critical; no findings target these files.

---

## Scope Summary

| Task | File(s) | Risk | In Scope |
|------|---------|------|----------|
| R1 — Company registry consolidation | governance.py, company_service.py, external_signal_service.py, curated_external_signal_provider.py | LOW | YES |
| R2 — Governance magic numbers → named constants | governance.py | LOW | YES |
| R3 — Risk scoring magic numbers → named constants | risk_scoring_service.py | LOW | YES |
| R4 — Decision type priority → JSON config | curated_external_signal_provider.py + new JSON files | LOW-MEDIUM | YES |
| R5 — Industry code field (additive) | risk_scoring_service.py + company JSON files | LOW | YES |
| R6 — Router dependency extraction | decisions.py | LOW-MEDIUM | YES |
| R7 — Delete dead seed scripts | scripts/ | NONE | YES |
| R8 — Delete orphaned test file | test_request.json | NONE | YES |
| R9 — Delete unused modules | app/e2e_runner.py, app/ontology.py | LOW | YES |
| R10 — Consolidate Ko/En JSON files | 6× mock company JSON + loaders | MEDIUM | YES |
| R11 — Create tests/conftest.py | tests/ | LOW | YES |
| Cost keyword → LLM classification | risk_scoring_service.py, risk_evidence_llm.py | HIGH | NO |
| Privacy keyword → LLM | governance.py | HIGH | NO |
| Type hint keywords → LLM | normalizers.py | HIGH | NO |
| Config-driven weights | risk_scoring_service.py + JSON | MEDIUM | NO |
| Neo4j migration | o1_reasoner.py | HIGH | NO |
| Alembic migration squashing | alembic/versions/ | HIGH | NO (breaks applied DBs) |
