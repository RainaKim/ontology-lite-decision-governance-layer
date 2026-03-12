# Agent Tasks — Refactor Workflow
**Date**: 2026-03-12
**Prerequisites**: Read REFACTOR_AUDIT.md and REFACTOR_SCOPE.md in full before starting.
**Branch**: `refactor/prep` → work on `refactor/cleanup-{task-id}` sub-branches, PR into `refactor/prep`

---

## Global Rules (Apply to Every Task)

1. **Run tests before and after every task.** Command: `source venv/bin/activate && python -m pytest tests/ -v`
2. **STOP conditions** — halt immediately and report if:
   - Any previously passing test fails
   - You encounter business logic you don't understand (e.g., a formula, a rule weight)
   - A file you planned to delete is imported somewhere you didn't expect
   - An edit would change numeric output of the risk scoring or governance evaluation
3. **Never change numeric values** — only rename/move them. If moving a magic number to a named constant, the value must be identical.
4. **Never touch** files listed as Out of Scope in REFACTOR_SCOPE.md.
5. **Commit format**: `refactor(scope): short description` — e.g., `refactor(registry): consolidate company registry to config module`
6. **One commit per task.** Do not bundle multiple tasks in one commit.

---

## Task R1 — Consolidate Company Registry

**Goal**: Eliminate the duplicate company ID → rules file mapping that exists in both `governance.py` and `company_service.py`.

### Steps

1. Create `app/config/__init__.py` (empty).
2. Create `app/config/company_registry.py` with:
   ```python
   # Single source of truth for company ID → rules file and profile aliases.
   # Add a new row here when onboarding a new company — no other code changes needed.

   COMPANY_RULES_FILES: dict[str, dict[str, str]] = {
       "nexus_dynamics": {
           "ko": "mock_company.json",
           "en": "mock_company_en.json",
       },
       "mayo_central": {
           "ko": "mock_company_healthcare.json",
           "en": "mock_company_healthcare_en.json",
       },
       "sool_sool_icecream": {
           "ko": "sool_sool_icecream_company.json",
           "en": "sool_sool_icecream_company_en.json",
       },
   }

   PROFILE_ALIASES: dict[str, str] = {
       "mayo_central": "mayo_central_hospital",
       "nexus_dynamics": "nexus_dynamics",
       "sool_sool_icecream": "sool_sool_icecream",
   }
   ```
3. In `app/governance.py`: remove `_COMPANY_RULES_FILES` dict. Add import: `from app.config.company_registry import COMPANY_RULES_FILES as _COMPANY_RULES_FILES`
4. In `app/services/company_service.py`: remove `_REGISTRY` dict. Import from registry and remap to match existing `_REGISTRY["ko"]`/`_REGISTRY["en"]` access pattern, or update all call sites.
5. In `app/services/external_signal_service.py`: remove `_PROFILE_ALIASES` dict. Import from registry.
6. In `app/providers/curated_external_signal_provider.py`: remove `_PROFILE_ALIASES` dict. Import from registry.
7. Run tests.

### STOP Conditions
- If `company_service.py`'s `_REGISTRY` is accessed in a way that `COMPANY_RULES_FILES` doesn't match structurally — stop and report the discrepancy.
- If any test involving company loading fails — stop immediately.

### Commit Message
```
refactor(registry): consolidate company registry to app/config/company_registry.py

Removes _COMPANY_RULES_FILES (governance.py) and _REGISTRY (company_service.py)
duplicates. Both now import from the single config module. Profile aliases also
consolidated from external_signal_service.py and curated_external_signal_provider.py.
```

---

## Task R2 — Named Constants in governance.py

**Goal**: Replace magic numbers in `app/governance.py` with named module-level constants.

### Steps

1. Read `app/governance.py` lines 110–140 (severity_weights and strategic_impact_bonus dicts).
2. These are already in dict form — they are already partially named. Verify they are not inline literals scattered elsewhere in the file.
3. If the dicts are defined inline inside a function body rather than at module level, move them to module level with uppercase names: `_SEVERITY_WEIGHTS`, `_STRATEGIC_IMPACT_BONUS`.
4. Replace any in-function reassignments with references to the module-level constants.
5. Verify no numeric value changes.
6. Run tests.

### STOP Conditions
- If a test asserts a specific governance score that would change — stop. The values must not change.
- If severity weights are overridden per-company anywhere in the file — stop and report (that's OOS business logic).

### Commit Message
```
refactor(governance): extract severity weights to named module-level constants
```

---

## Task R3 — Named Constants in risk_scoring_service.py

**Goal**: Give names to magic literals in `app/services/risk_scoring_service.py`.

### Steps

1. Read lines 37–45 (`_band()` function). Extract thresholds:
   ```python
   _BAND_LOW_MAX    = 40
   _BAND_MEDIUM_MAX = 70
   _BAND_HIGH_MAX   = 85
   ```
   Replace inline literals in `_band()` with these names.

2. Read line 1570 (confidence formula). Extract:
   ```python
   _CONF_BASE  = 0.9
   _CONF_DECAY = 0.1
   _CONF_MIN   = 0.4
   _CONF_MAX   = 0.95
   ```
   Replace the inline expression with `_clamp(_CONF_BASE - confidence_deductions * _CONF_DECAY, _CONF_MIN, _CONF_MAX)`.

3. `_PRIORITY_WEIGHTS` at lines 248–252 is already named — no change needed. Add a brief docstring explaining what it controls.

4. Do NOT change any numeric values.
5. Run tests. All 26 risk scoring tests must pass with identical output.

### STOP Conditions
- If extracting a constant would change how it's computed (e.g., it was computed dynamically) — stop and report.

### Commit Message
```
refactor(risk-scoring): extract band thresholds and confidence constants to named module constants
```

---

## Task R4 — Decision Type Priority → JSON Config

**Goal**: Move `_DECISION_TYPE_PRIORITY` in `app/providers/curated_external_signal_provider.py` to per-company JSON files.

### Steps

1. Read `app/providers/curated_external_signal_provider.py` lines 50–73 to understand the full structure.
2. For each company key (`sool_sool_icecream`, `mayo_central`, `nexus_dynamics`), create:
   - `app/demo_fixtures/external_sources/nexus_dynamics_priorities.json`
   - `app/demo_fixtures/external_sources/mayo_central_priorities.json`
   - `app/demo_fixtures/external_sources/sool_sool_icecream_priorities.json`
   Each file contains only that company's sub-dict (the `{"procurement": [...], "hiring": [...], ...}` part).
3. In `curated_external_signal_provider.py`, add a loader function:
   ```python
   def _load_priorities(company_id: str) -> dict[str, list[str]]:
       path = Path(__file__).parent.parent / "demo_fixtures" / "external_sources" / f"{company_id}_priorities.json"
       if path.exists():
           with open(path) as f:
               return json.load(f)
       return {}
   ```
4. Replace usages of `_DECISION_TYPE_PRIORITY[company_id]` with `_load_priorities(company_id)`.
5. Remove `_DECISION_TYPE_PRIORITY` dict entirely.
6. Run tests.

### STOP Conditions
- If `_DECISION_TYPE_PRIORITY` is accessed in any other file — stop and update that file too before removing the dict.
- If external signal tests return different signal IDs for the same input — stop.

### Commit Message
```
refactor(external-signals): move decision type priority to per-company JSON config files
```

---

## Task R5 — Industry Code Field (Additive)

**Goal**: Add optional `industry_code` field to company JSON configs so that industry detection in `risk_scoring_service.py` is deterministic rather than substring-matched.

### Steps

1. Add `"industry_code": "HEALTHCARE"` to `mock_company_healthcare.json` (and `_en.json`) under the top-level `company` object.
2. Add `"industry_code": "FINANCE"` to `mock_company.json` and `_en.json`.
3. Add `"industry_code": "FOOD_SERVICE"` to `sool_sool_icecream_company.json` and `_en.json`.
4. In `app/services/risk_scoring_service.py` lines 1544–1548, update the industry detection block:
   ```python
   industry_code = (cp.get("company", {}).get("industry_code") or "").upper()
   industry_text = (cp.get("company", {}).get("industry") or "").lower()

   if industry_code:
       is_healthcare = industry_code == "HEALTHCARE"
       is_public = industry_code in ("PUBLIC_SECTOR", "GOVERNMENT")
   else:
       # Legacy fallback: substring matching when industry_code absent
       is_healthcare = any(kw in industry_text for kw in ("health", "hospital", "medical", "헬스", "의료"))
       is_public = any(kw in industry_text for kw in ("government", "public", "정부", "공공", "gsa"))
   ```
5. Run tests. Healthcare compliance weight (0.50) must still apply for mayo_central.

### STOP Conditions
- If any risk scoring test produces a different weight or score — stop.

### Commit Message
```
refactor(industry): add industry_code field to company configs; use it in risk scoring when present
```

---

## Task R6 — Router Dependency Extraction

**Goal**: Move tenant isolation and company existence checks out of the route handler in `app/routers/decisions.py` into reusable dependencies.

### Steps

1. Read `app/routers/decisions.py` lines 55–75.
2. Create `app/dependencies/company_deps.py`:
   ```python
   from fastapi import HTTPException
   from app.services import company_service

   def validate_company_exists(company_id: str, lang: str = "ko") -> None:
       """Raises 422 if company_id is unknown."""
       if not company_service.get_company_v1(company_id, lang=lang):
           valid_ids = sorted(company_service.list_companies_v1(lang="en"), key=lambda c: c.id)
           valid_str = ", ".join(c.id for c in valid_ids)
           raise HTTPException(
               status_code=422,
               detail=f"Unknown company_id '{company_id}'. Valid: {valid_str}",
           )
   ```
3. Create `app/dependencies/auth_deps.py`:
   ```python
   from fastapi import HTTPException
   from app.services.rbac_service import UserRole

   def require_tenant_isolation(current_user, company_id: str) -> None:
       """Raises 403 if non-admin user targets another company."""
       if current_user.role != UserRole.ADMIN and current_user.company_id != company_id:
           raise HTTPException(
               status_code=403,
               detail="Cannot submit decisions for a different company.",
           )
   ```
4. Create `app/dependencies/__init__.py` (empty).
5. In `decisions.py`, replace the inline checks with calls to these functions.
6. Run tests. HTTP response codes (403, 422) and detail messages must be identical.

### STOP Conditions
- If these checks appear in other routers too — update them all in the same commit (don't leave half-migrated state).
- If any auth or decision test fails — stop.

### Commit Message
```
refactor(routers): extract tenant isolation and company validation to reusable dependencies
```

---

## Task R7 — Delete Dead Seed Scripts

**Goal**: Remove `scripts/seed_companies.py` and `scripts/seed_decisions.py`.

### Steps

1. Confirm Alembic migrations 0008 and 0009 exist and cover the same data.
2. Grep for any imports or shell invocations: `grep -r "seed_companies\|seed_decisions" .`
3. Delete both files.
4. Run tests.

### STOP Conditions
- If grep finds any reference to these scripts — stop and investigate before deleting.

### Commit Message
```
chore: delete redundant seed scripts superseded by Alembic migrations 0008 and 0009
```

---

## Task R8 — Delete Orphaned Test File

**Goal**: Remove `test_request.json` from project root.

### Steps

1. Grep for references: `grep -r "test_request.json" .`
2. If no references found, delete the file.
3. Run tests.

### Commit Message
```
chore: delete orphaned test_request.json (duplicated by pytest payloads)
```

---

## Task R9 — Verify and Delete Unused Modules

**Goal**: Remove `app/e2e_runner.py` and `app/ontology.py` if they are truly unused.

### Steps

1. `grep -r "e2e_runner" app/ tests/ --include="*.py"` — should return zero matches outside the file itself.
2. `grep -r "from app.ontology\|import ontology" app/ tests/ --include="*.py"` — should return zero matches.
3. If both grep results are empty, delete both files.
4. Run tests. If any ImportError surfaces — stop immediately and restore the deleted file.

### STOP Conditions
- Any grep match for either module — stop, do not delete.
- Any ImportError after deletion — restore and stop.

### Commit Message
```
chore: delete unused app/e2e_runner.py and app/ontology.py (zero imports found)
```

---

## Task R10 — Consolidate Ko/En Company JSON Files

**Goal**: Merge each Ko/En pair into a single file with a `translations` section.

### Steps

1. For each company, read both the Ko and En JSON files.
2. Verify they have the same top-level structure (same keys, same number of rules, etc.).
3. Create a merged file schema:
   ```json
   {
     "company": { "...": "..." },
     "industry_code": "...",
     "translations": {
       "ko": { "company": { "...": "..." }, "rules": [ ... ] },
       "en": { "company": { "...": "..." }, "rules": [ ... ] }
     }
   }
   ```
   The `translations.ko` and `translations.en` sections contain the locale-specific versions of all text fields.
4. Update `app/config/company_registry.py` (from R1) — `COMPANY_RULES_FILES` now points to a single file per company (no `ko`/`en` split in the key).
5. Update any file that loads company JSON and branches on `lang` parameter to read from `translations[lang]` instead.
6. Verify the merged file loads correctly and governance evaluation produces same triggered rules.
7. Delete the six original files only after all loaders are updated and tests pass.

### STOP Conditions
- If the Ko and En files have structurally different rule sets (different rule IDs) — stop. Cannot safely merge; flag for manual review.
- If governance test produces different triggered rules — stop and restore.

### Commit Message
```
refactor(fixtures): consolidate Ko/En company JSON pairs into single translated files
```

---

## Task R11 — Create tests/conftest.py

**Goal**: Eliminate `_make_user()` duplication and inline mock-object creation in test files.

### Steps

1. Read `tests/test_auth.py` (look for `_make_user()` around line 33).
2. Read `tests/test_rbac.py` and `tests/test_sso.py` to identify all mock object creation patterns.
3. Create `tests/conftest.py` with:
   - `@pytest.fixture def mock_user()` — returns a mock user with configurable role and company_id.
   - `@pytest.fixture def mock_company()` — returns a MagicMock Company object (matching pattern in test_sso.py).
4. Update `test_auth.py`, `test_rbac.py`, `test_sso.py` to use these fixtures instead of inline creation.
5. Run tests. All tests must pass identically.

### STOP Conditions
- If a test depends on a very specific user attribute that can't be captured by the fixture — leave that test inline and note it.
- If any test fails after fixture extraction — restore and stop.

### Commit Message
```
refactor(tests): extract shared mock fixtures to tests/conftest.py
```

---

## Execution Order

Run tasks in this order to minimize merge conflicts:

```
R7  → R8  → R9           (deletions — no dependencies)
R1                        (registry consolidation — prerequisite for R10)
R2  → R3                  (named constants — independent, can run in parallel)
R4                        (after R1, since it touches same provider file)
R5                        (after R10 if R10 done, otherwise standalone)
R6                        (independent)
R10                       (after R1 — depends on registry structure)
R11                       (last — touches tests)
```

---

## Final Validation Checklist

Before marking refactor complete, verify:
- [ ] `python -m pytest tests/ -v` → same pass count as baseline_test_results.txt
- [ ] No company name string literals in `app/` code (except registry config file)
- [ ] No duplicate dict between governance.py and company_service.py
- [ ] `app/e2e_runner.py` and `app/ontology.py` absent (or justified in a comment)
- [ ] `scripts/` directory either empty or contains only non-redundant scripts
- [ ] Six company JSON files reduced to three merged files
- [ ] `tests/conftest.py` exists and has at least `mock_user` and `mock_company` fixtures
- [ ] All commits follow `refactor(scope): description` format
