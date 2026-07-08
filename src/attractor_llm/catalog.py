from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

_CAPABILITY_FIELDS: dict[str, str] = {
    "tools": "supports_tools",
    "vision": "supports_vision",
    "reasoning": "supports_reasoning",
}


@dataclass(frozen=True)
class ModelInfo:
    """Metadata for a known LLM model."""

    id: str
    provider: str
    display_name: str
    context_window: int
    max_output: int | None = None
    supports_tools: bool = False
    supports_vision: bool = False
    supports_reasoning: bool = False
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None
    aliases: tuple[str, ...] = ()
    knowledge_cutoff: str | None = None
    source: str = "curated"


MODEL_CATALOG: list[ModelInfo] = [
    ModelInfo(
        id="claude-fable-5",
        provider="anthropic",
        display_name="Claude Fable 5",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=10.0,
        output_cost_per_million=50.0,
        aliases=("fable", "claude-fable", "fable-5"),
        knowledge_cutoff="2026-01",
    ),
    ModelInfo(
        id="claude-opus-4-8",
        provider="anthropic",
        display_name="Claude Opus 4.8",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=5.0,
        output_cost_per_million=25.0,
        aliases=("opus", "claude-opus", "opus-4-8"),
        knowledge_cutoff="2026-01",
    ),
    ModelInfo(
        id="claude-sonnet-5",
        provider="anthropic",
        display_name="Claude Sonnet 5",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=3.0,
        output_cost_per_million=15.0,
        aliases=("sonnet", "claude-sonnet", "sonnet-5"),
        knowledge_cutoff="2026-01",
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        provider="anthropic",
        display_name="Claude Haiku 4.5",
        context_window=200_000,
        max_output=64_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=1.0,
        output_cost_per_million=5.0,
        aliases=("haiku", "claude-haiku", "claude-haiku-4-5", "haiku-4-5"),
        knowledge_cutoff="2025-02",
    ),
    ModelInfo(
        id="gpt-5.5",
        provider="openai",
        display_name="GPT-5.5",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=5.0,
        output_cost_per_million=30.0,
        aliases=("gpt-5", "5.5"),
        knowledge_cutoff="2025-12",
    ),
    ModelInfo(
        id="gpt-5.4",
        provider="openai",
        display_name="GPT-5.4",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=2.5,
        output_cost_per_million=15.0,
        aliases=("5.4",),
        knowledge_cutoff="2025-08",
    ),
    ModelInfo(
        id="gpt-5.4-mini",
        provider="openai",
        display_name="GPT-5.4 Mini",
        context_window=400_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        input_cost_per_million=0.75,
        output_cost_per_million=4.5,
        aliases=("gpt-mini", "5.4-mini"),
        knowledge_cutoff="2025-08",
    ),
    ModelInfo(
        id="gpt-5.4-nano",
        provider="openai",
        display_name="GPT-5.4 Nano",
        context_window=400_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gpt-nano", "5.4-nano"),
        knowledge_cutoff="2025-08",
    ),
    ModelInfo(
        id="gpt-5.4-codex",
        provider="openai",
        display_name="GPT-5.4 Codex",
        context_window=1_000_000,
        max_output=128_000,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gpt-codex", "5.4-codex"),
        knowledge_cutoff="2025-08",
    ),
    ModelInfo(
        id="gemini-3.5-flash",
        provider="gemini",
        display_name="Gemini 3.5 Flash",
        context_window=1_048_576,
        max_output=65_536,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=(
            "gemini-flash",
            "3.5-flash",
            "flash",
        ),
        knowledge_cutoff="2025-01",
    ),
    ModelInfo(
        id="gemini-3.1-pro-preview",
        provider="gemini",
        display_name="Gemini 3.1 Pro Preview",
        context_window=1_048_576,
        max_output=65_536,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("gemini-pro", "3.1-pro"),
        knowledge_cutoff="2025-01",
    ),
    ModelInfo(
        id="gemini-3.1-flash-lite",
        provider="gemini",
        display_name="Gemini 3.1 Flash-Lite",
        context_window=1_048_576,
        max_output=65_536,
        supports_tools=True,
        supports_vision=True,
        supports_reasoning=True,
        aliases=("flash-lite", "3.1-flash-lite"),
        knowledge_cutoff="2025-01",
    ),
]

_CATALOG_INDEX: dict[str, ModelInfo] = {m.id: m for m in MODEL_CATALOG}
_SYNCED_CATALOG_BY_PROVIDER: dict[str, tuple[ModelInfo, ...]] = {}

_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-5",
    "openai": "gpt-5.5",
    "gemini": "gemini-3.5-flash",
}


def merge_model_catalog(
    curated: Sequence[ModelInfo],
    synced: Sequence[ModelInfo],
) -> list[ModelInfo]:
    """Merge provider-synced rows onto curated catalog metadata.

    Curated entries remain authoritative for overlapping model ids. Synced
    entries only append previously unknown models.
    """
    curated_by_key = {(model.provider, model.id): model for model in curated}
    merged = list(curated)
    for model in synced:
        if (model.provider, model.id) not in curated_by_key:
            merged.append(model)
    return merged


def replace_synced_catalog(rows_by_provider: Mapping[str, Iterable[ModelInfo]]) -> None:
    """Replace the in-memory provider-sync overlay."""
    global _SYNCED_CATALOG_BY_PROVIDER
    normalized: dict[str, tuple[ModelInfo, ...]] = {}
    for provider, rows in rows_by_provider.items():
        provider_rows = tuple(rows)
        curated_rows = [model for model in MODEL_CATALOG if model.provider == provider]
        curated_ids = {curated.id for curated in curated_rows}
        normalized[provider] = tuple(
            model
            for model in merge_model_catalog(curated_rows, list(provider_rows))
            if model.provider == provider and model.id not in curated_ids
        )
    _SYNCED_CATALOG_BY_PROVIDER = normalized


def update_synced_catalog(rows_by_provider: Mapping[str, Iterable[ModelInfo]]) -> None:
    """Replace synced rows for the provided providers, preserving other overlays."""
    normalized = dict(_SYNCED_CATALOG_BY_PROVIDER)
    replace_synced_catalog({**normalized, **rows_by_provider})


def _catalog_rows(provider: str | None = None) -> list[ModelInfo]:
    if provider is None:
        merged = list(MODEL_CATALOG)
        for provider_name in _DEFAULT_MODELS:
            merged.extend(_SYNCED_CATALOG_BY_PROVIDER.get(provider_name, ()))
        for provider_name in sorted(set(_SYNCED_CATALOG_BY_PROVIDER) - set(_DEFAULT_MODELS)):
            merged.extend(_SYNCED_CATALOG_BY_PROVIDER.get(provider_name, ()))
        return merged

    curated_rows = [m for m in MODEL_CATALOG if m.provider == provider]
    synced_rows = list(_SYNCED_CATALOG_BY_PROVIDER.get(provider, ()))
    return merge_model_catalog(curated_rows, synced_rows)


def get_model_info(model_id: str) -> ModelInfo | None:
    """Look up model metadata by ID or alias.

    Exact ID match takes precedence; falls back to alias search.

    Returns:
        ModelInfo if found, None otherwise.
    """
    # Exact ID match first (existing behaviour, O(1))
    info = _CATALOG_INDEX.get(model_id)
    if info is not None:
        return info

    for entry in _catalog_rows():
        if entry.id == model_id:
            return entry

    # Alias search — return first entry whose aliases contain model_id
    for entry in _catalog_rows():
        if model_id in entry.aliases:
            return entry

    return None


def list_models(provider: str | None = None) -> list[ModelInfo]:
    """List all known models, optionally filtered by provider."""
    return _catalog_rows(provider)


def get_default_model(provider: str) -> ModelInfo:
    """Get the default model for a provider.

    Raises:
        KeyError: If provider is unknown.
    """
    model_id = _DEFAULT_MODELS.get(provider)
    if model_id is None:
        raise KeyError(f"Unknown provider: {provider!r}")
    info = _CATALOG_INDEX.get(model_id)
    if info is None:
        raise KeyError(f"Default model {model_id!r} not found in catalog")
    return info


def get_latest_model(provider: str, capability: str | None = None) -> ModelInfo | None:
    """Return the newest/best model for a provider, optionally filtered by capability.

    Catalog order acts as rank: the first entry per provider is the latest/best.

    Args:
        provider:   Provider name, e.g. ``"anthropic"``, ``"openai"``, ``"gemini"``.
        capability: Optional capability filter — one of ``"tools"``, ``"vision"``,
                    or ``"reasoning"``.  An unknown capability string will always
                    return ``None``.

    Returns:
        The first matching :class:`ModelInfo`, or ``None`` if no entry satisfies
        both the provider and (optional) capability filter.
    """
    if capability is not None and capability not in _CAPABILITY_FIELDS:
        # Unknown capability — no model can satisfy it
        return None

    for entry in MODEL_CATALOG:
        if entry.provider != provider:
            continue
        if capability is not None:
            field_name = _CAPABILITY_FIELDS[capability]
            if not getattr(entry, field_name):
                continue
        return entry

    return None
