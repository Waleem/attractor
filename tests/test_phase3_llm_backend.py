from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from attractor_agent.abort import AbortSignal
from attractor_pipeline.engine.runner import HandlerResult
from attractor_pipeline.graph import Node
from attractor_pipeline.handlers.codergen import CodergenHandler
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.llm_backend import build_platform_codergen_backend


_PROVIDER_ENV_VARS = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY")


def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _PROVIDER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize(
    ("env_name", "expected_provider", "expected_model"),
    [
        ("ANTHROPIC_API_KEY", "anthropic", "claude-sonnet-4-5"),
        ("OPENAI_API_KEY", "openai", "gpt-5.2"),
        ("GOOGLE_API_KEY", "gemini", "gemini-3-flash-preview"),
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
    assert backend_any._default_model == "claude-sonnet-4-5"


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
