from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from attractor_llm.adapters.base import ProviderConfig
from attractor_llm.catalog import ModelInfo

SYNCED_CONTEXT_WINDOW_FALLBACK = 128_000
DEFAULT_PROVIDER_MODEL_SYNC_LIMIT = 10


@dataclass(frozen=True)
class SyncedModelInfo:
    provider: str
    id: str
    display_name: str
    created: int | float | None = None
    created_at: str | dt.datetime | None = None


async def sync_provider_models(
    provider: str,
    api_key: str,
    *,
    limit: int | None = DEFAULT_PROVIDER_MODEL_SYNC_LIMIT,
) -> list[ModelInfo]:
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

    ranked_rows = rank_synced_models(rows)
    if limit is not None:
        ranked_rows = ranked_rows[:limit]

    return [
        ModelInfo(
            id=row.id,
            provider=row.provider,
            display_name=row.display_name,
            context_window=SYNCED_CONTEXT_WINDOW_FALLBACK,
            max_output=None,
            source="provider",
        )
        for row in ranked_rows
    ]


def rank_synced_models(rows: list[SyncedModelInfo]) -> list[SyncedModelInfo]:
    """Order provider model rows from most recent to least recent."""
    return sorted(rows, key=_model_recency_key, reverse=True)


def _model_recency_key(row: SyncedModelInfo) -> tuple[int, float, tuple[int, ...], int, str]:
    timestamp = _created_timestamp(row)
    if timestamp is not None:
        return (1, timestamp, (), 0, row.id)
    version_parts = _version_parts(row.id)
    return (0, 0.0, version_parts, _variant_recency_score(row.id), _reverse_alpha_key(row.id))


def _created_timestamp(row: SyncedModelInfo) -> float | None:
    if isinstance(row.created, int | float):
        return float(row.created)
    if isinstance(row.created_at, dt.datetime):
        timestamp = row.created_at
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=dt.UTC)
        return timestamp.timestamp()
    if isinstance(row.created_at, str):
        value = row.created_at.strip()
        if not value:
            return None
        try:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _version_parts(model_id: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", model_id))


def _variant_recency_score(model_id: str) -> int:
    name = model_id.lower()
    if "flash" in name:
        return 40
    if "pro" in name:
        return 30
    if "sonnet" in name:
        return 25
    if "opus" in name:
        return 20
    if "mini" in name:
        return 10
    if "lite" in name or "nano" in name:
        return 5
    return 0


def _reverse_alpha_key(value: str) -> str:
    return "".join(chr(0x10FFFF - ord(character)) for character in value)
