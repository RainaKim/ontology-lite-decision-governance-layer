# Refactor Scope

**Branch at audit:** `refactor/prep`
**Companion docs:** `REFACTOR_AUDIT.md`, `REFACTOR_PLAN.md`, `AGENT_TASKS.md`

---

## In Scope

These files have clear, safe refactoring patterns and are covered by existing tests.

| File / Module | Problem | Pattern to Apply |
|---------------|---------|-----------------|
| `app/services/nova_scenario_proposer.py` | `_fmt_krw()` duplicated | Extract to `app/utils/formatters.py` |
| `app/services/risk_response_simulation_service.py` | `_fmt_krw()` duplicated | Import from `app/utils/formatters.py` |
| `app/services/decision_context_service.py` | Thin LLM wrapper (same skeleton as `risk_evidence_llm`) | Collapse into generic `BedrockStructuredExtractor` |
| `app/services/risk_evidence_llm.py` | Thin LLM wrapper | Collapse into `BedrockStructuredExtractor` |
| `app/bedrock_client.py` | Env + HTTP + parsing in one method | Extract `_build_payload`, `_parse_response`; inject api_key at `__init__` |
| `app/services/external_signal_service.py` | Decision type + theme inference if-chains; `_PROFILE_ALIASES` duplicated | Config tables; import shared alias from `app/config/company_config.py` |
| `app/providers/curated_external_signal_provider.py` | `_PROFILE_ALIASES` duplicated | Import shared alias |
| `app/routers/normalizers.py` | List-of-tuples severity lookup | Convert to `dict` |
| `app/governance.py` | `load_rules()` mixes I/O + translation | Extract `_apply_translation(raw, lang) -> dict` as pure function |
| `app/services/evidence_registry_service.py` | Operator if-chain; hardcoded budget thresholds | Operator dispatch table; surface thresholds as named constants with comments |

**New files to create (zero risk — additions only):**

| New File | Purpose |
|----------|---------|
| `app/utils/formatters.py` | `format_krw()`, `format_usd_compact()` |
| `app/utils/llm_utils.py` | `extract_json(text) -> Optional[dict]` |
| `app/config/bedrock_config.py` | `NOVA_MODEL_ID`, `BEDROCK_REGION`, `BEDROCK_TIMEOUT` |
| `app/config/company_config.py` | `PROFILE_ALIASES` |
| `app/config/risk_config.py` | `RISK_BANDS`, `CONFIDENCE_PARAMS` (move from `risk_scoring_service.py`) |

---

## Out of Scope — Do Not Touch

These files handle auth, migrations, or external integrations with high blast radius. Leave unchanged.

| File / Module | Reason |
|---------------|--------|
| `app/services/sso_service.py` | Auth logic — functional but tightly coupled by design; any breakage is a security surface. Refactor requires dedicated auth-aware testing. |
| `app/routers/sso.py` | HTTP entrypoints for OAuth flows; touching breaks the auth contract |
| `app/models/user.py`, `app/models/company.py` | ORM models tied to 3 migrations already applied to `dev.db`; schema changes need new Alembic migration |
| `alembic/versions/` | All migration files — never modify applied migrations |
| `app/repositories/user_repository.py`, `app/repositories/company_repository.py` | Repository pattern is correct; no issues found |
| `app/schemas/responses.py` | LOCKED shape — comment in memory explicitly marks this locked |
| `app/schemas/auth_responses.py` | Tied to auth contract |
| `app/services/risk_scoring_service.py` | Core scoring engine with 26 tests; constant extraction (2.3) is LOW risk but should be done carefully as a separate PR |
| `app/services/pipeline_service.py` | Async orchestrator; correct pattern; touching changes execution order |
| `tests/` | All test files — tests are the safety net, not the subject of refactoring |

---

## Delete Candidates

No files should be deleted outright. Both "thin wrapper" services (`decision_context_service.py`, `risk_evidence_llm.py`) should be **replaced** by a new generic abstraction — their callers in `pipeline_service.py` must be updated first before the old files are removed.

**Deletion order:**
1. Create `BedrockStructuredExtractor`
2. Update `pipeline_service.py` to use new class
3. Run tests → 275 pass
4. Delete `decision_context_service.py` and `risk_evidence_llm.py`

---

## Merge Candidates

| Files to Merge | Into | Rationale |
|----------------|------|-----------|
| `app/services/decision_context_service.py` + `app/services/risk_evidence_llm.py` | `app/services/bedrock_extractor.py` (new) | Same structure, different prompts/schemas |
| `_fmt_krw()` in `nova_scenario_proposer.py` and `risk_response_simulation_service.py` | `app/utils/formatters.py` (new) | Identical functions |
| JSON extraction in `o1_reasoner.py`, `nova_scenario_proposer.py`, `nova_external_signal_summarizer.py`, `bedrock_client.py` | `app/utils/llm_utils.py` (new) | Same ad-hoc pattern across 4 files |
| `_PROFILE_ALIASES` in `external_signal_service.py` + `curated_external_signal_provider.py` | `app/config/company_config.py` (new) | Single source of truth |
