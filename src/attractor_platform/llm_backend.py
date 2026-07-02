"""LLM backend factory for the durable platform executor."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

from attractor_agent.profiles import get_profile
from attractor_llm.adapters.anthropic import AnthropicAdapter
from attractor_llm.adapters.base import ProviderAdapter, ProviderConfig
from attractor_llm.adapters.gemini import GeminiAdapter
from attractor_llm.adapters.openai import OpenAIAdapter
from attractor_llm.client import Client
from attractor_pipeline.backends import AgentLoopBackend

_ProviderAdapterFactory = Callable[[ProviderConfig], ProviderAdapter]

_PROVIDER_ENV_ORDER: tuple[tuple[str, str, _ProviderAdapterFactory], ...] = (
    ("anthropic", "ANTHROPIC_API_KEY", AnthropicAdapter),
    ("openai", "OPENAI_API_KEY", OpenAIAdapter),
    ("gemini", "GOOGLE_API_KEY", GeminiAdapter),
)


def resolve_platform_llm_defaults(
    *,
    default_provider: str | None = None,
    default_model: str | None = None,
    provider_api_keys: Mapping[str, str] | None = None,
) -> tuple[str, str] | None:
    """Resolve the provider/model pair the platform backend would use."""
    registered_providers: set[str] = set()
    first_env_provider: str | None = None
    first_vault_provider: str | None = None
    provider_api_keys = provider_api_keys or {}

    for provider, env_name, _adapter_factory in _PROVIDER_ENV_ORDER:
        if os.environ.get(env_name):
            registered_providers.add(provider)
            first_env_provider = first_env_provider or provider
            continue
        if provider_api_keys.get(provider):
            registered_providers.add(provider)
            first_vault_provider = first_vault_provider or provider

    first_available_provider = first_env_provider or first_vault_provider
    if first_available_provider is None:
        return None

    if default_provider is not None and default_provider not in registered_providers:
        return None

    provider = default_provider or first_available_provider
    model = default_model or get_profile(provider).default_model
    return provider, model


def build_platform_codergen_backend(
    *,
    default_provider: str | None = None,
    default_model: str | None = None,
    provider_api_keys: Mapping[str, str] | None = None,
) -> AgentLoopBackend | None:
    """Build the real codergen backend for platform runs.

    Returns ``None`` when no provider credentials are configured so callers keep
    the existing dry-run codergen behavior explicit.
    """
    client = Client()
    provider_api_keys = provider_api_keys or {}

    for provider, env_name, adapter_factory in _PROVIDER_ENV_ORDER:
        api_key = os.environ.get(env_name) or provider_api_keys.get(provider)
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

    resolved_defaults = resolve_platform_llm_defaults(
        default_provider=default_provider,
        default_model=default_model,
        provider_api_keys=provider_api_keys,
    )
    if resolved_defaults is None:
        return None
    provider, model = resolved_defaults
    return AgentLoopBackend(
        client,
        default_provider=provider,
        default_model=model,
    )
