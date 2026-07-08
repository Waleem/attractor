from __future__ import annotations

import attractor_pipeline.backends as backend_module
import attractor_pipeline.cli as pipeline_cli
from attractor_agent.profiles import get_profile
from attractor_llm.catalog import (
    ModelInfo,
    get_default_model,
    get_latest_model,
    get_model_info,
    list_models,
    merge_model_catalog,
    replace_synced_catalog,
)
from attractor_llm.client import Client
from attractor_llm.types import Message, Response
from attractor_pipeline.backends import AgentLoopBackend, DirectLLMBackend
from attractor_pipeline.graph import Node


class _CapturingClient:
    def __init__(self) -> None:
        self.request = None

    async def complete(self, request, *, abort_signal=None):  # noqa: ANN001
        del abort_signal
        self.request = request
        return Response(
            model=request.model,
            provider=request.provider or "",
            message=Message.assistant("ok"),
        )


def test_catalog_contains_verified_current_model_ids() -> None:
    expected = {
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5.4-codex",
        "gemini-3.5-flash",
        "gemini-3.1-pro-preview",
        "gemini-3.1-flash-lite",
    }
    ids = {model.id for model in list_models()}
    assert expected <= ids


def test_catalog_removed_stale_defaults() -> None:
    ids = {model.id for model in list_models()}
    assert "claude-sonnet-4-5" not in ids
    assert "gpt-4.1-mini" not in ids
    assert "gemini-3-flash-preview" not in ids


def test_stale_full_model_ids_do_not_resolve_to_current_metadata() -> None:
    stale_ids = {
        "claude-opus-4-6",
        "claude-sonnet-4-5",
        "gpt-5.2",
        "gpt-5.2-mini",
        "gpt-4.1-mini",
        "gpt-5.2-codex",
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-pro",
        "gemini-2.5-flash",
    }
    assert {model.id for model in list_models()}.isdisjoint(stale_ids)
    for stale_id in stale_ids:
        assert get_model_info(stale_id) is None


def test_default_models_resolve_to_verified_ids() -> None:
    assert get_default_model("anthropic").id == "claude-sonnet-5"
    assert get_default_model("openai").id == "gpt-5.5"
    assert get_default_model("gemini").id == "gemini-3.5-flash"


def test_provider_profiles_match_catalog_defaults() -> None:
    for provider in ("anthropic", "openai", "gemini"):
        assert get_profile(provider).default_model == get_default_model(provider).id


def test_aliases_keep_operator_shortcuts_current() -> None:
    assert get_model_info("sonnet").id == "claude-sonnet-5"  # type: ignore[union-attr]
    assert get_model_info("haiku").id == "claude-haiku-4-5-20251001"  # type: ignore[union-attr]
    assert get_model_info("flash").id == "gemini-3.5-flash"  # type: ignore[union-attr]
    latest = get_latest_model("openai")
    assert latest is not None
    assert latest.id == "gpt-5.5"


def test_synced_catalog_overlay_adds_new_rows_without_overwriting_curated_metadata() -> None:
    replace_synced_catalog({})
    synced = [
        ModelInfo(
            id="gpt-live-new",
            provider="openai",
            display_name="GPT Live New",
            context_window=256_000,
            max_output=None,
        ),
        ModelInfo(
            id="gpt-5.5",
            provider="openai",
            display_name="Incorrect Synced Name",
            context_window=123,
            max_output=456,
        ),
    ]

    merged = merge_model_catalog(list_models(), synced)
    by_id = {model.id: model for model in merged}

    assert by_id["gpt-live-new"].display_name == "GPT Live New"
    assert by_id["gpt-live-new"].context_window == 256_000
    assert by_id["gpt-5.5"].display_name == "GPT-5.5"
    assert by_id["gpt-5.5"].context_window == 1_000_000

    replace_synced_catalog({"openai": synced})
    openai_models = list_models("openai")
    assert [model.id for model in openai_models[:2]] == ["gpt-5.5", "gpt-5.4"]
    assert openai_models[-1].id == "gpt-live-new"
    replace_synced_catalog({})


def test_backend_constructor_defaults_are_catalog_current() -> None:
    client = Client()
    assert AgentLoopBackend(client)._default_model == "claude-sonnet-5"
    assert DirectLLMBackend(client)._default_model == "claude-sonnet-5"


def test_backend_constructor_defaults_follow_explicit_provider() -> None:
    client = Client()
    assert AgentLoopBackend(client, default_provider="openai")._default_model == "gpt-5.5"
    assert (
        DirectLLMBackend(client, default_provider="gemini")._default_model
        == "gemini-3.5-flash"
    )


async def test_direct_backend_node_provider_override_uses_provider_default_model() -> None:
    client = _CapturingClient()
    backend = DirectLLMBackend(client)  # type: ignore[arg-type]
    node = Node(id="node", llm_provider="openai")

    result = await backend.run(node, "prompt", {"goal": "test"})

    assert result == "ok"
    assert client.request is not None
    assert client.request.provider == "openai"
    assert client.request.model == "gpt-5.5"


async def test_agent_loop_backend_node_provider_override_uses_provider_default_model(
    monkeypatch,
) -> None:  # noqa: ANN001
    captured_config = None

    class FakeSession:
        def __init__(
            self,
            *,
            client,
            config,
            tools,
            abort_signal,
        ) -> None:  # noqa: ANN001
            del client, tools, abort_signal
            nonlocal captured_config
            captured_config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001
            del exc_type, exc, tb
            return False

        async def submit(self, prompt):  # noqa: ANN001
            del prompt
            return "ok"

    monkeypatch.setattr(backend_module, "Session", FakeSession)
    backend = AgentLoopBackend(Client())
    node = Node(id="node", llm_provider="gemini")

    result = await backend.run(node, "prompt", {"goal": "test"})

    assert result == "ok"
    assert captured_config is not None
    assert captured_config.provider == "gemini"
    assert captured_config.model == "gemini-3.5-flash"


def test_cli_gemini_api_key_resolution_accepts_google_or_gemini(
    monkeypatch,
) -> None:  # noqa: ANN001
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    assert hasattr(pipeline_cli, "_provider_api_key")
    assert hasattr(pipeline_cli, "_available_provider_api_keys")
    assert pipeline_cli._provider_api_key("gemini") == ("GEMINI_API_KEY", "gemini-key")
    assert pipeline_cli._available_provider_api_keys()["gemini"] == "gemini-key"

    monkeypatch.setenv("GOOGLE_API_KEY", "google-key")
    assert pipeline_cli._provider_api_key("gemini") == ("GEMINI_API_KEY", "gemini-key")
    assert pipeline_cli._available_provider_api_keys()["gemini"] == "gemini-key"

    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert pipeline_cli._provider_api_key("gemini") == ("GOOGLE_API_KEY", "google-key")
    assert pipeline_cli._available_provider_api_keys()["gemini"] == "google-key"
