from __future__ import annotations

from dataclasses import dataclass

from attractor_llm.adapters.base import ProviderConfig
from attractor_llm.catalog import ModelInfo

SYNCED_CONTEXT_WINDOW_FALLBACK = 128_000


@dataclass(frozen=True)
class SyncedModelInfo:
    provider: str
    id: str
    display_name: str


async def sync_provider_models(provider: str, api_key: str) -> list[ModelInfo]:
    from attractor_llm.adapters.anthropic import AnthropicAdapter
    from attractor_llm.adapters.gemini import GeminiAdapter
    from attractor_llm.adapters.openai import OpenAIAdapter

    adapter_factory = {
        "anthropic": AnthropicAdapter,
        "openai": OpenAIAdapter,
        "gemini": GeminiAdapter,
    }.get(provider)
    if adapter_factory is None:
        raise ValueError(f"Unsupported provider: {provider}")

    adapter = adapter_factory(ProviderConfig(api_key=api_key, timeout=30.0))
    try:
        rows = await adapter.list_models()
    finally:
        await adapter.close()

    return [
        ModelInfo(
            id=row.id,
            provider=row.provider,
            display_name=row.display_name,
            context_window=SYNCED_CONTEXT_WINDOW_FALLBACK,
            max_output=None,
            source="provider",
        )
        for row in rows
    ]
