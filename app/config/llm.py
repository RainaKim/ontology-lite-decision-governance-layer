"""
LLM provider abstraction for DecisionGovernance AI.

Usage:
    from app.config.llm import get_llm

    fast_llm = get_llm("fast")       # extraction, classification, summarization
    capable_llm = get_llm("capable") # graph reasoning, contradiction analysis

Provider is selected via LLM_PROVIDER env var (default: anthropic).
Model IDs are overridable via LLM_MODEL_FAST / LLM_MODEL_CAPABLE env vars.
"""

import os

from langchain_core.language_models.chat_models import BaseChatModel

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": {
        "fast": "claude-haiku-4-5-20251001",
        "capable": "claude-sonnet-4-6",
    },
    "openai": {
        "fast": "gpt-5.4-mini",
        "capable": "gpt-5.4",
    },
    "bedrock": {
        "fast": "us.amazon.nova-2-lite-v1:0",
        "capable": "us.amazon.nova-pro-v1:0",
    },
}

LLM_MODEL_FAST = os.getenv("LLM_MODEL_FAST", _DEFAULTS.get(LLM_PROVIDER, _DEFAULTS["anthropic"])["fast"])
LLM_MODEL_CAPABLE = os.getenv("LLM_MODEL_CAPABLE", _DEFAULTS.get(LLM_PROVIDER, _DEFAULTS["anthropic"])["capable"])


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_llm(tier: str = "fast") -> BaseChatModel:
    """
    Return a LangChain chat model for the configured provider.

    Args:
        tier: "fast" for extraction/classification, "capable" for reasoning/synthesis

    Returns:
        A LangChain BaseChatModel instance for the configured provider.

    Raises:
        ValueError: If LLM_PROVIDER is not one of: anthropic, openai, bedrock
    """
    model_id = LLM_MODEL_FAST if tier == "fast" else LLM_MODEL_CAPABLE

    if LLM_PROVIDER == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_id, temperature=0)

    if LLM_PROVIDER == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_id, temperature=0)

    if LLM_PROVIDER == "bedrock":
        from langchain_aws import ChatBedrock
        return ChatBedrock(model_id=model_id)

    raise ValueError(
        f"Unknown LLM_PROVIDER={LLM_PROVIDER!r}. "
        "Set LLM_PROVIDER to one of: anthropic, openai, bedrock"
    )
