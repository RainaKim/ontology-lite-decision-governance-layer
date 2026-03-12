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
