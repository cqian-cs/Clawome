from __future__ import annotations

"""LLM provider — ChatLiteLLM with multi-provider routing via LiteLLM.

Supports 12 providers + Custom through a unified interface.
All providers return identical AIMessage format (.content, .response_metadata).

Each provider's routing, api_base requirement, and extra parameters are
defined in PROVIDER_CONFIG so adding/fixing a provider is a single-dict change.
"""

from langchain_litellm import ChatLiteLLM
from agent_config.settings import settings


# ── Per-provider configuration ────────────────────────────────────────
#
#   prefix          LiteLLM model prefix (e.g. "openai/model", "anthropic/model")
#   needs_api_base  True = OpenAI-compatible, requires user-supplied api_base
#                   False = LiteLLM routes automatically via API key
#   extra_body      Optional dict merged into extra_body (e.g. enable_thinking)

PROVIDER_CONFIG = {
    "dashscope": {
        "prefix": "openai",
        "needs_api_base": True,
        "extra_body": {"enable_thinking": False},
    },
    "openai": {
        "prefix": "openai",
        "needs_api_base": True,
        "extra_body": {"enable_thinking": False},
    },
    "anthropic": {
        "prefix": "anthropic",
        "needs_api_base": False,
    },
    "google": {
        "prefix": "gemini",
        "needs_api_base": False,
    },
    "deepseek": {
        "prefix": "deepseek",
        "needs_api_base": False,
        "extra_body": {"enable_thinking": False},
    },
    "moonshot": {
        "prefix": "openai",
        "needs_api_base": True,
    },
    "zhipu": {
        "prefix": "openai",
        "needs_api_base": True,
    },
    "volcengine": {
        "prefix": "openai",
        "needs_api_base": True,
        "extra_body": {"enable_thinking": False},
    },
    "minimax": {
        "prefix": "openai",
        "needs_api_base": True,
    },
    "mistral": {
        "prefix": "mistral",
        "needs_api_base": False,
    },
    "groq": {
        "prefix": "groq",
        "needs_api_base": False,
    },
    "xai": {
        "prefix": "xai",
        "needs_api_base": False,
    },
    "custom": {
        "prefix": "",
        "needs_api_base": True,
    },
}

# Convenience set used by runner._validate_config()
NO_API_BASE = {k for k, v in PROVIDER_CONFIG.items() if not v.get("needs_api_base")}


def get_llm(
    model_name: str | None = None,
    temperature: float | None = None,
    streaming: bool = False,
) -> ChatLiteLLM:
    """Create an LLM instance routed through LiteLLM.

    The provider prefix is prepended automatically based on the configured
    provider (e.g. "openai/gpt-4o", "anthropic/claude-sonnet-4-20250514").
    """
    provider = settings.llm.provider or "dashscope"
    cfg = PROVIDER_CONFIG.get(provider, PROVIDER_CONFIG["custom"])
    raw_model = model_name or settings.llm.model_name

    # Strip any existing provider prefix (e.g. "dashscope/qwen-plus" → "qwen-plus")
    # so we can re-add the correct LiteLLM prefix below.
    model = raw_model.split("/", 1)[1] if "/" in raw_model else raw_model

    # Build the LiteLLM model string: "prefix/model"
    prefix = cfg.get("prefix", "")
    litellm_model = f"{prefix}/{model}" if prefix else model

    kwargs = dict(
        model=litellm_model,
        temperature=temperature if temperature is not None else settings.llm.temperature,
        max_tokens=settings.llm.max_tokens,
        timeout=60,           # 60s hard timeout — prevents 166s hangs
        streaming=streaming,
    )

    # API key
    if settings.llm.api_key:
        kwargs["api_key"] = settings.llm.api_key

    # API base — only for providers that need it
    if cfg.get("needs_api_base") and settings.llm.api_base:
        kwargs["api_base"] = settings.llm.api_base

    # Provider-specific extra_body (e.g. enable_thinking for Qwen3 / DeepSeek R1)
    extra_body = cfg.get("extra_body")
    if extra_body:
        kwargs["model_kwargs"] = {"extra_body": dict(extra_body)}

    return ChatLiteLLM(**kwargs)
