"""
Neo4j connection configuration for DecisionGovernance AI.

Each company gets its own Neo4j database (multi-tenant isolation).
Connection is shared; database is switched per request via `database` param.

Local Docker:
    docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/password neo4j:5.11

Env vars (set in .env):
    NEO4J_URI       — bolt://localhost:7687  (or neo4j+s:// for AuraDB)
    NEO4J_USERNAME  — neo4j
    NEO4J_PASSWORD  — password
    NEO4J_DATABASE  — neo4j  (default database; per-company DB overrides this)
"""

import os

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# Per-company database name pattern: {company_id}_governance
# e.g. nexus_governance, mayo_governance
# Override by setting NEO4J_DB_{COMPANY_ID_UPPER} env var.
def get_company_database(company_id: str) -> str:
    """
    Return the Neo4j database name for a given company.

    Default pattern: {company_id}_governance
    Override: NEO4J_DB_NEXUS=nexus_governance (env var)
    """
    env_key = f"NEO4J_DB_{company_id.upper()}"
    return os.getenv(env_key, f"{company_id}_governance")
