from __future__ import annotations

from attractor_agent.profiles import get_profile
from attractor_llm.catalog import get_default_model, get_latest_model, get_model_info, list_models
from attractor_llm.client import Client
from attractor_pipeline.backends import AgentLoopBackend, DirectLLMBackend


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
