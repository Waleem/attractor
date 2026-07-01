"""LLM backend factory for the durable platform executor."""

from __future__ import annotations

import os
from collections.abc import Callable

from attractor_agent.profiles import get_profile
from attractor_llm.adapters.anthropic import AnthropicAdapter
from attractor_llm.adapters.base import ProviderConfig
from attractor_llm.adapters.gemini import GeminiAdapter
from attractor_llm.adapters.openai import OpenAIAdapter
from attractor_llm.client import Client
from attractor_pipeline.backends import AgentLoopBackend

_ProviderAdapterFactory = Callable[[ProviderConfig], object]

_PROVIDER_ENV_ORDER: tuple[tuple[str, str, _ProviderAdapterFactory], ...] = (
    ("anthropic", "ANTHROPIC_API_KEY", AnthropicAdapter),
    ("openai", "OPENAI_API_KEY", OpenAIAdapter),
    ("gemini", "GOOGLE_API_KEY", GeminiAdapter),
)


def build_platform_codergen_backend(
    *,
    default_provider: str | None = None,
    default_model: str | None = None,
) -> AgentLoopBackend | None:
    """Build the real codergen backend for platform runs.

    Returns ``None`` when no provider credentials are configured so callers keep
    the existing dry-run codergen behavior explicit.
    """
    client = Client()
    first_available_provider: str | None = None

    for provider, env_name, adapter_factory in _PROVIDER_ENV_ORDER:
        api_key = os.environ.get(env_name)
        if not api_key:
            continue
        client.register_adapter(
            provider,
            adapter_factory(
                ProviderConfig(
                    api_key=api_key,
                    timeout=120.0,
                )
            ),
        )
        first_available_provider = first_available_provider or provider

    if first_available_provider is None:
        return None

    provider = default_provider or first_available_provider
    model = default_model or get_profile(provider).default_model
    return AgentLoopBackend(
        client,
        default_provider=provider,
        default_model=model,
    )
