# Central Bedrock configuration — import from here, never hardcode elsewhere.
# Extension: add a constant here and import it in the service that needs it.
# Rules: no business logic, no secrets (those stay in .env), group by domain not by consumer.
NOVA_MODEL_ID = "us.amazon.nova-2-lite-v1:0"
BEDROCK_REGION = "us-east-1"
BEDROCK_TIMEOUT = 60.0
