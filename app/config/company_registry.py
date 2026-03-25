# Single source of truth for company ID → rules file and profile aliases.
# Add a new row here when onboarding a new company — no other code changes needed.
#
# NOTE: Legacy mock JSON files (mock_company_nexus.json, mock_company_healthcare_merged.json)
# have been removed. Rules files will be populated when Neo4j-backed CompanyConfig is implemented.

COMPANY_RULES_FILES: dict[str, dict[str, str]] = {
    # "nexus_dynamics": {
    #     "merged": "nexus_dynamics_config.json",
    # },
    # "mayo_central": {
    #     "merged": "mayo_central_config.json",
    # },
}

PROFILE_ALIASES: dict[str, str] = {
    "mayo_central": "mayo_central_hospital",
    "nexus_dynamics": "nexus_dynamics",
}
