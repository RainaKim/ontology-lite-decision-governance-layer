# Agent Refactor Log

---

## REFACTOR COMPLETE

Final test run: 275 passed, 0 failed (branch: refactor/prep)

| Task | Status | Commit |
|------|--------|--------|
| R7 — Delete Dead Seed Scripts | DONE | f56f2f0 |
| R8 — Delete Orphaned Test File | DONE | ff9c01d |
| R9 — Delete Unused Modules | DONE | e0720ce |
| R1 — Consolidate Company Registry | DONE | f9438b0 |
| R2 — Named Constants in governance.py | DONE | cf0d507 |
| R3 — Named Constants in risk_scoring_service.py | DONE | ff78dab |
| R4 — Decision Type Priority → JSON Config | DONE | b0cd251 |
| R5 — Industry Code Field | DONE | f687f71 |
| R6 — Router Dependency Extraction | DONE | 9f76255 |
| R10 — Consolidate Ko/En Company JSON Files | DONE | 71d9d95 |
| R11 — Create tests/conftest.py | DONE | 4f35fca |

---

## Task R11 — Create tests/conftest.py
**Status**: DONE
**Commits**: refactor/prep:4f35fca
**Notes**: Created tests/conftest.py with mock_user and mock_company fixtures. Existing test helpers (test_auth._make_user, test_rbac._make_user, test_sso._make_company) were left inline per STOP CONDITION — their attribute signatures differ from the conftest fixtures or require per-call role variation. 275 tests pass.
---

## Task R10 — Consolidate Ko/En Company JSON Files
**Status**: DONE
**Commits**: refactor/prep:71d9d95
**Notes**: All 3 company pairs had matching rule IDs. Created merged files: mock_company_nexus.json, mock_company_healthcare_merged.json, sool_sool_icecream_merged.json. Updated company_registry.py to use "merged" key. Updated company_service.py and governance.py to extract translations[lang]. Fixed tests/test_risk_response_simulation.py which directly opened mock_company.json. Deleted 6 original files. 275 tests pass.
---

## Task R6 — Router Dependency Extraction
**Status**: DONE
**Commits**: refactor/prep:9f76255
**Notes**: Created app/dependencies/__init__.py, company_deps.py, auth_deps.py. Replaced inline checks in decisions.py with validate_company_exists() and require_tenant_isolation(). No other routers had duplicate checks. 275 tests pass.
---

## Task R5 — Industry Code Field
**Status**: DONE
**Commits**: refactor/prep:f687f71
**Notes**: Added industry_code to all 6 company JSON files. Replaced substring-based industry detection in risk_scoring_service.py with industry_code check + legacy fallback. Healthcare weight (0.50) still applies. 275 tests pass.
---

## Task R4 — Decision Type Priority → JSON Config
**Status**: DONE
**Commits**: refactor/prep:b0cd251
**Notes**: Created 3 per-company priority JSON files under demo_fixtures/external_sources/. Added _load_priorities() loader function. Replaced _DECISION_TYPE_PRIORITY dict and its usage. 275 tests pass.
---

## Task R3 — Named Constants in risk_scoring_service.py
**Status**: DONE
**Commits**: refactor/prep:ff78dab
**Notes**: Added _BAND_LOW_MAX=40, _BAND_MEDIUM_MAX=70, _BAND_HIGH_MAX=85, _CONF_BASE=0.9, _CONF_DECAY=0.1, _CONF_MIN=0.4, _CONF_MAX=0.95. Also replaced confidence=0.4 fallback in empty dims case with _CONF_MIN. All 275 tests pass (32 risk scoring tests pass).
---

## Task R2 — Named Constants in governance.py
**Status**: DONE
**Commits**: refactor/prep:cf0d507
**Notes**: Extracted severity_weights and strategic_impact_bonus inline dicts to module-level _SEVERITY_WEIGHTS and _STRATEGIC_IMPACT_BONUS. No numeric changes. 275 tests pass.
---

## Task R1 — Consolidate Company Registry
**Status**: DONE
**Commits**: refactor/prep:f9438b0
**Notes**: Created app/config/company_registry.py. _REGISTRY in company_service.py was keyed lang→company_id, new COMPANY_RULES_FILES is company_id→lang; derived _REGISTRY dynamically. _PROFILE_ALIASES consolidated from 2 files. 275 tests pass.
---

## Task R9 — Delete Unused Modules
**Status**: DONE
**Commits**: refactor/prep:e0720ce
**Notes**: e2e_runner had one reference in demo_fixtures.py but it was a comment, not an import. ontology.py had zero references. Both deleted. 275 tests pass.
---

## Task R8 — Delete Orphaned Test File
**Status**: DONE
**Commits**: refactor/prep:ff9c01d
**Notes**: No code references found. Only .md documentation referenced test_request.json. Deleted from project root. 275 tests pass.
---

## Task R7 — Delete Dead Seed Scripts
**Status**: DONE
**Commits**: refactor/prep:f56f2f0
**Notes**: Migrations 0008/0009 exist. Only .md files referenced seed scripts (docs, not code). Deleted scripts/seed_companies.py and scripts/seed_decisions.py. 275 tests pass.
---

