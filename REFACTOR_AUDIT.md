# Refactor Audit — Decision Governance Layer
**Date**: 2026-03-12
**Branch**: governance-new-flow
**Scope**: All Python files under `app/` and `tests/`

---

## Executive Summary

16 issues found across 8 files in 5 categories:

| Severity | Count |
|----------|-------|
| HIGH     | 4     |
| MEDIUM   | 9     |
| LOW      | 3     |

---

## Category 1 — Scenario-Specific If/Else (dev_rules §1 violations)

### 1.1 Company → Rules File Registry (HIGH)
**File**: `app/governance.py` lines 74–78
**File**: `app/services/company_service.py` lines 22–33 (duplicate)

```python
# governance.py
_COMPANY_RULES_FILES: dict[str, dict[str, str]] = {
    "nexus_dynamics":     {"ko": "mock_company.json", "en": "mock_company_en.json"},
    "mayo_central":       {"ko": "mock_company_healthcare.json", "en": "mock_company_healthcare_en.json"},
    "sool_sool_icecream": {"ko": "sool_sool_icecream_company.json", "en": "sool_sool_icecream_company_en.json"},
}
```

Same mapping duplicated in `company_service.py` as `_REGISTRY`. Adding a company requires editing code in two places. Violates dev_rules §1 and §4.

**Fix**: Single `app/config/company_registry.py` module. Both files import from it.

---

### 1.2 External Signal Profile Aliases (MEDIUM)
**File**: `app/services/external_signal_service.py` lines 38–42
**File**: `app/providers/curated_external_signal_provider.py` lines 34–38

```python
_PROFILE_ALIASES: dict[str, str] = {
    "mayo_central": "mayo_central_hospital",
    ...
}
```

Duplicated in two files. Must change both when adding an alias.

**Fix**: Define once in `app/config/company_registry.py`, import in both.

---

### 1.3 Decision Type Priority per Company (MEDIUM)
**File**: `app/providers/curated_external_signal_provider.py` lines 50–73

```python
_DECISION_TYPE_PRIORITY: dict[str, dict[str, list[str]]] = {
    "sool_sool_icecream": {"procurement": ["SOOL_EXT_001", ...], ...},
    "mayo_central": {...},
    "nexus_dynamics": {...},
}
```

Per-company, per-decision-type signal priority embedded in code. New company = code edit.

**Fix**: Move to `app/demo_fixtures/external_sources/{company_id}_priorities.json`. Load at startup.

---

## Category 2 — Semantic Keyword Tables (dev_rules §1 violations)

### 2.1 `_COST_REDUCTION_KEYWORDS` (HIGH)
**File**: `app/services/risk_scoring_service.py` lines 1442–1445

```python
_COST_REDUCTION_KEYWORDS = {
    "cost", "비용", "efficiency", "절감", "reduction", "savings",
    "budget", "operating", "운영", "spend",
}
```

Used to classify goals as cost-reduction type (line 1453). Acknowledged in the file's own TODO (lines 1431–1435) as a dev_rules §1 violation. Misses semantic intent ("trim overhead", "reduce overhead").

**Fix**: Use `risk_semantics` LLM layer (`GoalCategory` Pydantic model). The scaffold already exists in `app/services/risk_evidence_llm.py`.

---

### 2.2 `_PRIVACY_KEYWORDS` (MEDIUM)
**File**: `app/governance.py` line 492

```python
_PRIVACY_KEYWORDS = {'pii', 'hipaa', 'gdpr', 'privacy', '프라이버시', '개인정보', 'phi', 'anonymi'}
```

Encodes what constitutes "privacy-related" compliance. New frameworks (CPRA, PIPEDA) need code edits.

**Fix**: Extend LLM extractor to classify rules by privacy relevance, or load keywords from per-company config.

---

### 2.3 `_TYPE_HINT_KEYWORDS` (MEDIUM)
**File**: `app/routers/normalizers.py` lines 99–104

```python
_TYPE_HINT_KEYWORDS: dict[str, set[str]] = {
    "compliance": {"규제", "준수", "COMPLIANCE", "HIPAA", "GDPR", ...},
    "financial":  {"비용", "예산", "효율", "절감", "COST", "BUDGET"},
    ...
}
```

Maps rule types → vocabulary to find relevant strategic goals. Encodes semantic associations in both Korean and English.

**Fix**: Use LLM semantic similarity between rule text and goal text, or load from company config.

---

## Category 3 — Magic Numbers & Hardcoded Thresholds

### 3.1 Risk Band Thresholds (MEDIUM)
**File**: `app/services/risk_scoring_service.py` lines 37–45

```python
def _band(score: int) -> str:
    if score < 40: return "LOW"
    if score < 70: return "MEDIUM"
    if score < 85: return "HIGH"
    return "CRITICAL"
```

Thresholds 40 / 70 / 85 unnamed and unconfigurable.

**Fix**: Named constants at module top, or load from `company.risk_tolerance.band_thresholds`.

---

### 3.2 Aggregate Dimension Weights (MEDIUM)
**File**: `app/services/risk_scoring_service.py` lines 1550–1559

```python
default_weights = {"financial": 0.40, "compliance": 0.35, "strategic": 0.25}
if is_healthcare:
    default_weights["compliance"] = 0.50
elif is_public:
    default_weights["compliance"] = 0.45
```

Weights + industry override hardcoded. Adding a new industry sector needs code edit.

**Fix**: Move weights to company JSON config under `risk_tolerance.dimension_weights`. Read `industry_code` enum instead of substring match.

---

### 3.3 Severity & Strategic Impact Bonuses (MEDIUM)
**File**: `app/governance.py` lines 114–119, 127–132

```python
severity_weights      = {"critical": 8.0, "high": 3.0, "medium": 1.5, "low": 0.5}
strategic_impact_bonus = {"critical": 3.5, "high": 1.5, "medium": 0.0, "low": 0.0}
```

**Fix**: Move to company JSON config under `governance.severity_weights` and `governance.strategic_impact_bonuses`.

---

### 3.4 Confidence Decay Formula (LOW)
**File**: `app/services/risk_scoring_service.py` line 1570

```python
confidence = _clamp(0.9 - confidence_deductions * 0.1, 0.4, 0.95)
```

Base (0.9), decay-per-deduction (0.1), range (0.4–0.95) all magic literals.

**Fix**: Named constants: `CONF_BASE = 0.9`, `CONF_DECAY = 0.1`, `CONF_MIN = 0.4`, `CONF_MAX = 0.95`.

---

### 3.5 Signal Priority Weights (LOW)
**File**: `app/services/risk_scoring_service.py` lines 248–252

```python
_PRIORITY_WEIGHTS: dict[str, int] = {"critical": 40, "high": 25, "medium": 10, "low": 3}
```

**Fix**: Named constants or config.

---

## Category 4 — Industry Detection Fragility

### 4.1 Substring Matching for Industry Classification (MEDIUM)
**File**: `app/services/risk_scoring_service.py` lines 1544–1548

```python
industry = (cp.get("company", {}).get("industry") or "").lower()
is_healthcare = any(kw in industry for kw in ("health", "hospital", "medical", "헬스", "의료"))
is_public     = any(kw in industry for kw in ("government", "public", "정부", "공공", "gsa"))
```

Freetext `industry` field substring-matched. Company named "Health Insurance Services LLC" could unexpectedly match. Acknowledged in code via TODO lines 1540–1543.

**Fix**: Add `industry_code: str` (normalized enum: `"HEALTHCARE"`, `"PUBLIC_SECTOR"`, `"FINANCE"`, etc.) to company JSON config. Code reads enum, no substring matching.

---

## Category 5 — Misplaced Business Logic in Routers

### 5.1 Tenant Isolation Check in Router (LOW)
**File**: `app/routers/decisions.py` lines 68–73

```python
if current_user.role != UserRole.ADMIN and current_user.company_id != request.company_id:
    raise HTTPException(status_code=403, detail="Cannot submit decisions for a different company.")
```

**Fix**: Extract to `require_tenant_isolation(current_user, company_id)` FastAPI dependency.

---

### 5.2 Company Existence Validation in Router (LOW)
**File**: `app/routers/decisions.py` lines 59–65

```python
if not company_service.get_company_v1(request.company_id, lang=request.lang):
    valid_ids = sorted(company_service.list_companies_v1(lang="en"), key=lambda c: c.id)
    ...
    raise HTTPException(status_code=422, detail=f"Unknown company_id ...")
```

**Fix**: Extract to a Pydantic validator or FastAPI dependency: `validate_company_id(company_id, lang)`.

---

---

## Category 6 — Dead Files & Redundant Assets (Safe to Delete)

### 6.1 Seed Scripts Superseded by Migrations (DELETE)
- `scripts/seed_companies.py` — duplicates Alembic migration 0008 (`0008_seed_mock_companies.py`). Both insert the same 3 companies. Script uses dynamic UUIDs vs fixed in migration.
- `scripts/seed_decisions.py` — duplicates migration 0009 (`0009_seed_mock_decisions.py`). Both seed 6 test decisions.

**Action**: Delete both scripts. Migrations are the authoritative seeding mechanism.

---

### 6.2 Orphaned Test Fixture Files (DELETE)
- `test_request.json` (285B, root) — minimal curl payload duplicated by Pydantic schema definitions and pytest fixtures.

**Action**: Delete. Any manual testing should use inline curl JSON.

---

### 6.3 Potentially Unused Modules (VERIFY THEN DELETE)
- `app/e2e_runner.py` (15.4K) — not imported anywhere in app/ or tests/. May be a standalone dev utility.
- `app/ontology.py` (22.1K) — not imported anywhere in app/ or tests/. Likely legacy from an earlier architecture.

**Action**: Verify with `grep -r "e2e_runner\|ontology" app/ tests/`. If no imports, delete both.

---

### 6.4 Duplicate Ko/En Company JSON Files (CONSOLIDATE)
Six files exist as Korean/English pairs for three companies. Structure is identical; only text is translated.

| Ko file | En file |
|---------|---------|
| `mock_company.json` | `mock_company_en.json` |
| `mock_company_healthcare.json` | `mock_company_healthcare_en.json` |
| `sool_sool_icecream_company.json` | `sool_sool_icecream_company_en.json` |

**Action**: Consolidate each pair into one file with a top-level `"translations": {"ko": {...}, "en": {...}}` structure, or move locale-specific text to a separate i18n file. Update `_COMPANY_RULES_FILES` accordingly.

---

### 6.5 Test Boilerplate Without conftest.py (CONSOLIDATE)
`_make_user()` helper defined in `test_auth.py` line 33 and inline mock-user creation duplicated across `test_rbac.py`, `test_sso.py`. No `conftest.py` exists.

**Action**: Create `tests/conftest.py` with shared `@pytest.fixture` for `mock_user`, `mock_company`, etc. Remove inline duplicates.

---

### 6.6 Manual Smoke Test Scripts (DOCUMENT OR DELETE)
- `test_decision_pack.sh` (2.6K) — curl-based smoke test with two hardcoded JSON scenarios. Overlaps with `demo_cases.json`.
- `demo_cases.json` (10.7K) — 3 scenarios also partially covered by `demo_fixtures.py::_FIXTURES_BY_COMPANY`.

**Action**: Keep `test_decision_pack.sh` as a manual integration smoke test but add a comment at the top explaining it is not part of the pytest suite. Delete or merge `demo_cases.json` into the fixture if scenarios are duplicated.

---

### 6.7 Alembic Migrations — Squashing Candidates (OPTIONAL)
Migrations 0005, 0006, 0007 are tiny single-column additions that could be folded into their parent schema migrations:
- `0005_decisions_add_en_fields.py` → fold into 0004
- `0006_decisions_add_impact_label_en.py` → fold into 0004/0005
- `0007_companies_add_name_en.py` → fold into 0002

**Action**: Low priority. Only squash if `dev.db` is reset from scratch for hackathon demo (squashing applied migrations breaks existing DBs).

---

## Summary Table

| ID  | File | Lines | Category | Severity |
|-----|------|-------|----------|----------|
| 1.1 | governance.py + company_service.py | 74–78, 22–33 | Scenario if-else / Duplication | HIGH |
| 1.2 | external_signal_service.py + curated_external_signal_provider.py | 38–42, 34–38 | Scenario if-else / Duplication | MEDIUM |
| 1.3 | curated_external_signal_provider.py | 50–73 | Scenario if-else | MEDIUM |
| 2.1 | risk_scoring_service.py | 1442–1445 | Keyword-table | HIGH |
| 2.2 | governance.py | 492 | Keyword-table | MEDIUM |
| 2.3 | normalizers.py | 99–104 | Keyword-table | MEDIUM |
| 3.1 | risk_scoring_service.py | 37–45 | Magic-value | MEDIUM |
| 3.2 | risk_scoring_service.py | 1550–1559 | Magic-value | MEDIUM |
| 3.3 | governance.py | 114–119, 127–132 | Magic-value | MEDIUM |
| 3.4 | risk_scoring_service.py | 1570 | Magic-value | LOW |
| 3.5 | risk_scoring_service.py | 248–252 | Magic-value | LOW |
| 4.1 | risk_scoring_service.py | 1544–1548 | Industry detection fragility | MEDIUM |
| 5.1 | decisions.py | 68–73 | Misplaced logic | LOW |
| 5.2 | decisions.py | 59–65 | Misplaced logic | LOW |
| 6.1 | scripts/seed_companies.py, scripts/seed_decisions.py | — | Dead file / Duplication | HIGH |
| 6.2 | test_request.json | — | Dead file | LOW |
| 6.3 | app/e2e_runner.py, app/ontology.py | — | Potentially dead module | MEDIUM |
| 6.4 | 6× mock company JSON files | — | Duplication (Ko/En pairs) | MEDIUM |
| 6.5 | tests/ (no conftest.py) | — | Boilerplate duplication | LOW |
| 6.6 | test_decision_pack.sh, demo_cases.json | — | Undocumented / overlapping test data | LOW |
