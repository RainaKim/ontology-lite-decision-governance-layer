# Central Bedrock configuration — import from here, never hardcode elsewhere.
# Extension: add a constant here and import it in the service that needs it.
# Rules: no business logic, no secrets (those stay in .env), group by domain not by consumer.

# ── Model tier selection ──────────────────────────────────────────────────────
# Lite: fast extraction, entity classification, translation (low-complexity I/O)
# Pro:  multi-step reasoning, graph contradiction analysis, governance conflict
#       resolution (high-complexity reasoning that benefits from stronger model)
NOVA_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
NOVA_PRO_MODEL_ID = "us.amazon.nova-pro-v1:0"
BEDROCK_REGION = "us-east-1"
BEDROCK_TIMEOUT = 60.0
