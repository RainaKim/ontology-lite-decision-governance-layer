COMPANY_RULES_FILES: dict[str, dict[str, str]] = {
}

# API/DB company_id -> configs/{config_id}.json stem (CompanyConfig, Tier 1 governance config).
# Add one row per company; the pipeline itself stays company-agnostic.
COMPANY_CONFIG_IDS: dict[str, str] = {
    "nexus_dynamics": "nexus_analytics",
}


def resolve_config_id(company_id: str) -> str:
    """Return the configs/ file stem for a company_id (identity when no alias is registered)."""
    return COMPANY_CONFIG_IDS.get(company_id, company_id)


PROFILE_ALIASES: dict[str, str] = {
    "mayo_central": "mayo_central_hospital",
    "nexus_dynamics": "nexus_dynamics",
}
