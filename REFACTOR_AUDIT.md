# Refactor Audit — Decision Governance Layer

**Date:** 2026-03-12
**Branch at audit time:** `refactor/prep`
**Test baseline:** 275 passed, 0 failed

---

## Category 1: Dead / Redundant Services

### 1.1 `decision_context_service.py` — Thin LLM Wrapper
**Severity:** MEDIUM
**File:** `app/services/decision_context_service.py`

This service has a single responsibility: format a prompt, call Bedrock, validate with Pydantic, and filter the result. All "business logic" is either trivial string matching or delegated to the LLM. The filtering table (`_JUDGMENT_KEY_PREFIXES`) is the only real logic:

```python
# decision_context_service.py ~line 84
def is_left_panel_safe(entity: ExtractedEntity) -> bool:
    key_lower = entity.key.lower()
    return (
        entity.kind in _ALLOWED_PANEL_KINDS
        and entity.confidence >= _MIN_CONFIDENCE
        and not any(key_lower.startswith(p) for p in _JUDGMENT_KEY_PREFIXES)
        and entity.category.lower() not in _EXCLUDED_CATEGORIES
    )
```

The service wraps exactly one Bedrock call and returns a Pydantic-validated model. This is the same structure as `risk_evidence_llm.py` (see 1.2).

**Recommended pattern:** Merge into a generic `BedrockStructuredExtractor` (see Architecture Decisions). Keep `is_left_panel_safe` as a standalone predicate in a utils module.

---

### 1.2 `risk_evidence_llm.py` — Duplicate of 1.1's Pattern
**Severity:** MEDIUM
**File:** `app/services/risk_evidence_llm.py`

Identical structure to `decision_context_service.py`: build prompt → call Bedrock → Pydantic validate → return `None` on failure. The two services share no code but follow the same template verbatim.

```python
# risk_evidence_llm.py (representative pattern)
async def infer_risk_semantics(
    decision: dict,
    company_profile: dict,
    rules: dict,
    _client=None,
) -> Optional[RiskSemantics]:
    client = _client or BedrockClient()
    try:
        raw = client.invoke(prompt, system_prompt=SYSTEM_PROMPT)
        data = json.loads(raw)
        return RiskSemantics(**data)
    except Exception:
        return None
```

**Recommended pattern:** Same as 1.1 — both collapse into `BedrockStructuredExtractor.extract(prompt, output_model)`.

---

## Category 2: Hardcoded Values

### 2.1 Bedrock Model ID Duplicated Across Three Files
**Severity:** HIGH
**Files:**
- `app/bedrock_client.py` line ~20
- `app/services/nova_scenario_proposer.py` line ~32
- `app/services/nova_external_signal_summarizer.py` line ~41

```python
# bedrock_client.py
_DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"

# nova_scenario_proposer.py
_MODEL_ID = "us.amazon.nova-2-lite-v1:0"

# nova_external_signal_summarizer.py
_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
```

Three independent string literals for the same value. Changing models requires touching three files and these can drift silently.

**Recommended pattern:**
```python
# app/config/bedrock_config.py (new)
NOVA_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
BEDROCK_REGION = "us-east-1"
BEDROCK_TIMEOUT = 60.0
```

---

### 2.2 Budget Thresholds Hardcoded in Evidence Registry
**Severity:** MEDIUM
**File:** `app/services/evidence_registry_service.py` lines ~33–34

```python
_CAPEX_THRESHOLD = 50_000_000
_BOARD_THRESHOLD = 1_000_000_000
```

These constants drive governance trigger conditions but are not company-configurable. If a company has a different financial policy, the code must change.

**Recommended pattern:** Load from company profile JSON (`mock_company.json` already has a `financial_policy` section — wire it up) or add to the rules config.

---

### 2.3 Risk Band Thresholds and Confidence Constants
**Severity:** MEDIUM
**File:** `app/services/risk_scoring_service.py` lines ~37–44

```python
_BAND_LOW_MAX    = 40
_BAND_MEDIUM_MAX = 70
_BAND_HIGH_MAX   = 85

_CONF_BASE  = 0.9
_CONF_DECAY = 0.1
_CONF_MIN   = 0.4
_CONF_MAX   = 0.95
```

Industry-specific thresholds would ideally vary (healthcare already overrides `aggregate_weights` — why not bands?).

**Recommended pattern:** Move to `app/config/risk_config.py`, keyed by industry. Existing `INDUSTRY_WEIGHTS` dict in this file is the right model to copy.

---

### 2.4 OAuth URLs Hardcoded in SSO Service
**Severity:** LOW
**File:** `app/services/sso_service.py` lines ~35–44

```python
GOOGLE_AUTH_URL   = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL  = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
AZURE_AUTH_URL    = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize"
AZURE_TOKEN_URL   = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
```

These are stable public endpoints, so LOW severity. However, they should live in a config/constants file for clarity.

---

### 2.5 Profile Aliases Defined in Two Independent Places
**Severity:** MEDIUM
**Files:**
- `app/services/external_signal_service.py` (has `_PROFILE_ALIASES`)
- `app/providers/curated_external_signal_provider.py` (has its own copy of `_PROFILE_ALIASES`)

```python
# external_signal_service.py
_PROFILE_ALIASES = {"mayo_central": "mayo_central_hospital"}

# curated_external_signal_provider.py (same dict, second definition)
_PROFILE_ALIASES = {"mayo_central": "mayo_central_hospital"}
```

A single source of truth is needed. If a new alias is added, both must be updated.

**Recommended pattern:** Single `PROFILE_ALIASES` constant in `app/config/company_config.py`, imported by both.

---

## Category 3: Duplicate Logic

### 3.1 `_fmt_krw()` Defined Twice
**Severity:** HIGH
**Files:**
- `app/services/nova_scenario_proposer.py` lines ~117–130
- `app/services/risk_response_simulation_service.py` lines ~56–68

```python
# Identical in both files:
def _fmt_krw(amount) -> str:
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

Bug fix in one won't propagate to the other.

**Recommended pattern:** `app/utils/formatters.py::format_krw(amount)`. Both services import from there.

---

### 3.2 JSON-from-LLM Extraction Pattern Duplicated
**Severity:** MEDIUM
**Files:**
- `app/o1_reasoner.py` lines ~88–99
- `app/services/nova_scenario_proposer.py`
- `app/services/nova_external_signal_summarizer.py`
- `app/bedrock_client.py` (has `_strip_markdown` as a static method)

```python
# o1_reasoner.py
json_start = reasoning_text.find('{')
json_end = reasoning_text.rfind('}') + 1
if json_start >= 0 and json_end > json_start:
    json_str = reasoning_text[json_start:json_end]
    result = json.loads(json_str)
```

`BedrockClient._strip_markdown()` already exists but is only wired to the Bedrock client's own output. Other services re-implement extraction independently.

**Recommended pattern:** `app/utils/llm_utils.py::extract_json(text: str) -> Optional[dict]` — handles fence stripping + bracket extraction in one place.

---

### 3.3 LLM Call → Pydantic Validate → Return None Pattern
**Severity:** MEDIUM
**Files:** `decision_context_service.py`, `risk_evidence_llm.py` (same pattern, covered in 1.1 and 1.2)

```python
# Both files have this skeleton:
try:
    raw = client.invoke(prompt, system_prompt=SYSTEM_PROMPT)
    data = json.loads(raw)
    return OutputModel(**data)
except Exception:
    return None
```

**Recommended pattern:** Covered under Architecture Decisions — `BedrockStructuredExtractor.extract()`.

---

### 3.4 `_PROFILE_ALIASES` Lookup Logic Duplicated
**Severity:** MEDIUM
See Finding 2.5. Not just data but also the lookup code pattern is repeated.

---

## Category 4: if/else Chains (3+ Branches on Type/String)

### 4.1 Decision Type Inference — Priority-Ordered Field Check
**Severity:** MEDIUM
**File:** `app/services/external_signal_service.py` lines ~356–370

```python
def _infer_decision_type(decision: dict) -> str:
    if decision.get("involves_hiring"):
        return "hiring"
    if decision.get("uses_pii"):
        return "privacy"
    if decision.get("new_product_development"):
        return "new_product"
    cost = decision.get("cost")
    if cost and isinstance(cost, (int, float)) and cost > 0:
        return "procurement"
    return "general"
```

4 branches on boolean fields, hardcoded priority order. Adding a new type requires editing this function.

**Recommended pattern:**
```python
# app/config/decision_type_config.py
DECISION_TYPE_PRIORITY = [
    ("involves_hiring", "hiring"),
    ("uses_pii", "privacy"),
    ("new_product_development", "new_product"),
]

def infer_decision_type(decision: dict, priority=DECISION_TYPE_PRIORITY) -> str:
    for field, dtype in priority:
        if decision.get(field):
            return dtype
    cost = decision.get("cost")
    if cost and isinstance(cost, (int, float)) and cost > 0:
        return "procurement"
    return "general"
```

---

### 4.2 Theme Inference from Governance Flags — Keyword Table
**Severity:** MEDIUM
**File:** `app/services/external_signal_service.py` lines ~235–244

```python
for flag in flags:
    if any(kw in flag for kw in ("FINANCIAL", "BUDGET", "COST")):
        themes.append("risk_financial")
    if any(kw in flag for kw in ("PRIVACY", "PII", "PHI")):
        themes.append("privacy_compliance")
    if any(kw in flag for kw in ("COMPLIANCE", "REGULATORY", "VIOLATION")):
        themes.append("regulatory_compliance")
    if any(kw in flag for kw in ("STRATEGIC", "CONFLICT", "MISALIGNMENT")):
        themes.append("strategic_benchmark")
```

> **Ambiguity note:** Dev rules forbid keyword lists for *semantic classification that affects scoring*. This is UI-only theming (no scores change). However, it's still a maintenance liability — the mapping should be a config table.

**Recommended pattern:**
```python
# app/config/theme_config.py
FLAG_KEYWORD_THEMES: list[tuple[tuple[str, ...], str]] = [
    (("FINANCIAL", "BUDGET", "COST"),         "risk_financial"),
    (("PRIVACY", "PII", "PHI"),               "privacy_compliance"),
    (("COMPLIANCE", "REGULATORY", "VIOLATION"), "regulatory_compliance"),
    (("STRATEGIC", "CONFLICT", "MISALIGNMENT"), "strategic_benchmark"),
]
```

---

### 4.3 Strategic Impact Inference — Keyword Matching on Flags
**Severity:** LOW
**File:** `app/services/external_signal_service.py` lines ~373–381

```python
def _infer_strategic_impact(governance_result: Optional[dict]) -> str:
    if not governance_result:
        return "N/A"
    for flag in governance_result.get("flags", []):
        flag_upper = flag.upper()
        if "STRATEGIC" in flag_upper or "CONFLICT" in flag_upper or "MISALIGNMENT" in flag_upper:
            return "Potential strategic conflict"
    return "N/A"
```

Only two return values; the keywords are a subset of Finding 4.2. Should share the same config table.

---

### 4.4 Flag Severity Pattern List vs. Dict
**Severity:** LOW
**File:** `app/routers/normalizers.py` lines ~64–68

```python
_FLAG_SEVERITY_PATTERNS = [
    ("CRITICAL", FlagSeverity.critical),
    ("HIGH",     FlagSeverity.high),
    ("MEDIUM",   FlagSeverity.medium),
]
```

Using a list of tuples where a dict lookup would be O(1) and self-documenting.

**Recommended pattern:**
```python
_FLAG_SEVERITY_MAP: dict[str, FlagSeverity] = {
    "CRITICAL": FlagSeverity.critical,
    "HIGH":     FlagSeverity.high,
    "MEDIUM":   FlagSeverity.medium,
}
```

---

## Category 5: Untestable Code (I/O Mixed with Logic)

### 5.1 `BedrockClient.invoke()` — Env Var + HTTP + Parsing in One Method
**Severity:** MEDIUM
**File:** `app/bedrock_client.py` lines ~46–106

```python
def invoke(self, user_message: str, *, system_prompt=None, max_tokens=2048) -> str:
    api_key = os.environ.get("BEDROCK_API_KEY")   # I/O: env
    if not api_key:
        raise RuntimeError("BEDROCK_API_KEY not set")
    payload = { ... }                             # logic: payload build
    response = httpx.post(                        # I/O: HTTP
        self._endpoint, headers={...}, json=payload, timeout=_TIMEOUT
    )
    response.raise_for_status()
    text = response.json()["output"]["message"]["content"][0]["text"]  # parsing
    return self._strip_markdown(text)             # transformation
```

Currently tests pass a `_client` mock that bypasses the whole method. But the internal structure cannot be unit tested piecemeal — payload building, response parsing, and markdown stripping are not independently callable.

**Recommended pattern:** Extract `_build_payload(...)` and `_parse_response(...)` as pure methods. Read `api_key` in `__init__` (or inject it). Keep HTTP call isolated in `_http_post(...)`.

---

### 5.2 `governance.py::load_rules()` — File I/O + Translation Logic Mixed
**Severity:** MEDIUM
**File:** `app/governance.py` lines ~93–130

```python
def load_rules(rules_path=None, company_id=None, lang="ko") -> dict:
    # path resolution
    if rules_path is None:
        files = _COMPANY_RULES_FILES.get(company_id, {})
        filename = files.get("merged") or _DEFAULT_RULES_FILE
        rules_path = Path(__file__).parent.parent / filename
    # I/O
    with open(rules_path, 'r') as f:
        raw = json.load(f)
    # transformation: language overlay
    if "translations" in raw:
        translation = raw.get("translations", {}).get(lang_key, {})
        data = {**raw, **translation}
        ...
    return data
```

The language-overlay transformation is untestable without writing to disk. It should be a pure function `_apply_translation(raw: dict, lang: str) -> dict`.

---

### 5.3 `sso_service.py::handle_google_callback()` — DB + HTTP + Logic Interleaved
**Severity:** MEDIUM
**File:** `app/services/sso_service.py` lines ~88–180

Three I/O operations (DB lookup, HTTP token exchange, HTTP userinfo) are interleaved with data parsing in a single function. Any path through the function requires mocking all three I/O layers simultaneously.

```python
def handle_google_callback(code: str, state: str, db: Session) -> dict:
    company_id = _verify_state(state)
    company = company_repository.get_by_id(db, company_id)   # I/O: DB
    with httpx.Client(timeout=10) as client:
        response = client.post(GOOGLE_TOKEN_URL, ...)         # I/O: HTTP
    token_data = response.json()                              # logic
    with httpx.Client(timeout=10) as client:
        userinfo = client.get(GOOGLE_USERINFO_URL, ...)       # I/O: HTTP
    user = user_repository.find_or_create_sso_user(db, ...)  # I/O: DB
    ...
```

**Recommended pattern:** Extract `_exchange_code(company, code) -> str` and `_fetch_userinfo(token) -> dict` as injectable methods. `handle_callback` becomes a thin orchestrator. (See Architecture Decisions.)

---

### 5.4 `evidence_registry_service.py::_eval_trigger_condition()` — Ad-Hoc Operator Logic
**Severity:** LOW
**File:** `app/services/evidence_registry_service.py` lines ~387–410

```python
def _eval_trigger_condition(trigger: dict, decision_payload: dict) -> bool:
    operator = trigger.get("triggerOperator", "==")
    if operator == ">":
        try:
            return float(actual) > float(expected)
        except (TypeError, ValueError):
            return False
    return actual == expected  # default
```

Only handles `>` and `==`. Adding `<`, `>=`, `in` requires another `if` branch. No way to enumerate supported operators.

**Recommended pattern:** Operator dispatch table `_OPS: dict[str, Callable] = {">": operator.gt, ...}`.

---

## Summary Table

| # | Category | File | Lines | Severity | Issue |
|---|----------|------|-------|----------|-------|
| 1.1 | Dead service | `decision_context_service.py` | all | MEDIUM | Thin LLM wrapper, no real logic |
| 1.2 | Dead service | `risk_evidence_llm.py` | all | MEDIUM | Duplicate of 1.1 pattern |
| 2.1 | Hardcoded | `bedrock_client.py`, `nova_scenario_proposer.py`, `nova_external_signal_summarizer.py` | 20, 32, 41 | HIGH | Model ID string in 3 places |
| 2.2 | Hardcoded | `evidence_registry_service.py` | 33–34 | MEDIUM | Budget thresholds not per-company |
| 2.3 | Hardcoded | `risk_scoring_service.py` | 37–44 | MEDIUM | Risk bands + confidence constants |
| 2.4 | Hardcoded | `sso_service.py` | 35–44 | LOW | OAuth URLs in source |
| 2.5 | Hardcoded | `external_signal_service.py`, `curated_external_signal_provider.py` | various | MEDIUM | `_PROFILE_ALIASES` duplicated |
| 3.1 | Duplicate | `nova_scenario_proposer.py`, `risk_response_simulation_service.py` | 117–130, 56–68 | HIGH | `_fmt_krw()` identical in 2 files |
| 3.2 | Duplicate | `o1_reasoner.py`, `nova_scenario_proposer.py`, `nova_external_signal_summarizer.py` | various | MEDIUM | JSON extraction from LLM response |
| 3.3 | Duplicate | `decision_context_service.py`, `risk_evidence_llm.py` | all | MEDIUM | LLM→Pydantic call pattern |
| 4.1 | if/else | `external_signal_service.py` | 356–370 | MEDIUM | Decision type inference (4 branches) |
| 4.2 | if/else | `external_signal_service.py` | 235–244 | MEDIUM | Theme inference (keyword if-block) |
| 4.3 | if/else | `external_signal_service.py` | 373–381 | LOW | Strategic impact keyword check |
| 4.4 | if/else | `normalizers.py` | 64–68 | LOW | Severity list vs dict |
| 5.1 | Untestable | `bedrock_client.py` | 46–106 | MEDIUM | Env+HTTP+parse in one method |
| 5.2 | Untestable | `governance.py` | 93–130 | MEDIUM | File I/O + translation mixed |
| 5.3 | Untestable | `sso_service.py` | 88–180 | MEDIUM | DB+HTTP+logic interleaved |
| 5.4 | Untestable | `evidence_registry_service.py` | 387–410 | LOW | Ad-hoc operator if-chain |
