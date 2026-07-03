from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, cast

import pytest

from attractor_agent.abort import AbortSignal
from attractor_pipeline.engine.runner import HandlerResult
from attractor_pipeline.graph import Node
from attractor_pipeline.handlers.codergen import CodergenHandler
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.llm_backend import build_platform_codergen_backend
from attractor_platform.secrets import SecretVault, load_provider_secret_values
from attractor_platform.storage.db import (
    DatabaseSettings,
    create_platform_engine,
    create_session_factory,
    default_test_database_url,
    initialize_platform_schema,
    session_scope,
)
from attractor_platform.storage.models import SettingSecretModel

_PROVIDER_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY")


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("env_name", "expected_provider", "expected_model"),
    [
        ("ANTHROPIC_API_KEY", "anthropic", "claude-sonnet-5"),
        ("OPENAI_API_KEY", "openai", "gpt-5.5"),
        ("GOOGLE_API_KEY", "gemini", "gemini-3.5-flash"),
    ],
)
def test_build_platform_codergen_backend_detects_provider_env_keys(
    monkeypatch: pytest.MonkeyPatch,
    env_name: str,
    expected_provider: str,
    expected_model: str,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv(env_name, f"fake-{expected_provider}-key")

    backend = build_platform_codergen_backend(default_provider=None, default_model=None)

    assert backend is not None
    backend_any = cast(Any, backend)
    client = backend_any._client
    assert set(client._adapters) == {expected_provider}
    assert backend_any._default_provider == expected_provider
    assert backend_any._default_model == expected_model


def test_build_platform_codergen_backend_selects_first_available_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")
    monkeypatch.setenv("GOOGLE_API_KEY", "fake-google-key")

    backend = build_platform_codergen_backend(default_provider=None, default_model=None)

    assert backend is not None
    backend_any = cast(Any, backend)
    assert set(backend_any._client._adapters) == {"anthropic", "openai", "gemini"}
    assert backend_any._default_provider == "anthropic"
    assert backend_any._default_model == "claude-sonnet-5"


def test_build_platform_codergen_backend_honors_explicit_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "fake-openai-key")

    backend = build_platform_codergen_backend(
        default_provider="openai",
        default_model="gpt-custom",
    )

    assert backend is not None
    backend_any = cast(Any, backend)
    assert backend_any._default_provider == "openai"
    assert backend_any._default_model == "gpt-custom"


def test_build_platform_codergen_backend_returns_none_for_explicit_provider_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-anthropic-key")

    assert (
        build_platform_codergen_backend(
            default_provider="openai",
            default_model=None,
        )
        is None
    )


def test_build_platform_codergen_backend_returns_none_without_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)

    assert build_platform_codergen_backend(default_provider=None, default_model=None) is None


@pytest.mark.asyncio
async def test_build_platform_codergen_backend_uses_vault_provider_key_without_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    engine = create_platform_engine(
        DatabaseSettings(url=default_test_database_url(tmp_path / "settings.sqlite3"))
    )
    await initialize_platform_schema(engine)
    session_factory = create_session_factory(engine)
    vault = SecretVault(tmp_path / "platform-secret.key")
    raw_secret = "fake-vault-openai-key"
    try:
        async with session_scope(session_factory) as session:
            session.add(
                SettingSecretModel(
                    name="openai",
                    encrypted_value=vault.encrypt(raw_secret),
                    updated_at=dt.datetime.now(dt.UTC),
                )
            )

        provider_api_keys = await load_provider_secret_values(
            session_factory=session_factory,
            secret_vault=vault,
            provider_names=("openai", "anthropic", "gemini"),
        )
        backend = build_platform_codergen_backend(
            default_provider=None,
            default_model=None,
            provider_api_keys=provider_api_keys,
        )

        assert provider_api_keys == {"openai": raw_secret}
        assert backend is not None
        backend_any = cast(Any, backend)
        assert set(backend_any._client._adapters) == {"openai"}
        assert backend_any._default_provider == "openai"
        assert backend_any._default_model == "gpt-5.5"
    finally:
        await engine.dispose()


class _FakeCodergenBackend:
    async def run(
        self,
        node: Node,
        prompt: str,
        context: dict[str, Any],
        abort_signal: AbortSignal | None = None,
    ) -> str | HandlerResult:
        del node, prompt, context, abort_signal
        return "fake output"


def test_durable_run_executor_for_tests_registers_codergen_backend(tmp_path: Path) -> None:
    fake_backend = _FakeCodergenBackend()

    executor = DurableRunExecutor.for_tests(
        session_factory=cast(Any, None),
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
        codergen_backend=fake_backend,
    )

    handler = executor._handlers.get("codergen")
    assert isinstance(handler, CodergenHandler)
    assert handler._backend is fake_backend
