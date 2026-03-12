# Single source of truth for company ID → rules file and profile aliases.
# Add a new row here when onboarding a new company — no other code changes needed.
# See bedrock_config.py for general config module rules.

COMPANY_RULES_FILES: dict[str, dict[str, str]] = {
    "nexus_dynamics": {
        "merged": "mock_company_nexus.json",
    },
    "mayo_central": {
        "merged": "mock_company_healthcare_merged.json",
    },
    "sool_sool_icecream": {
        "merged": "sool_sool_icecream_merged.json",
    },
}

PROFILE_ALIASES: dict[str, str] = {
    "mayo_central": "mayo_central_hospital",
    "nexus_dynamics": "nexus_dynamics",
    "sool_sool_icecream": "sool_sool_icecream",
}
