from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import (
    DatabaseSettings,
    create_platform_engine,
    create_session_factory,
    default_test_database_url,
    initialize_platform_schema,
)
from attractor_server.platform_app import PlatformModelTestResult, create_platform_app

pytestmark = pytest.mark.asyncio

_LLM_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "ATTRACTOR_DEFAULT_PROVIDER",
    "ATTRACTOR_DEFAULT_MODEL",
)


class FakeModelTester:
    def __init__(self, *, failures: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str, str]] = []
        self.failures = failures or set()

    async def test_model(
        self,
        *,
        provider: str,
        model: str,
        api_key: str,
    ) -> PlatformModelTestResult:
        self.calls.append((provider, model, api_key))
        if model in self.failures:
            return PlatformModelTestResult(
                ok=False,
                latency_ms=7.5,
                error=f"{api_key} failed for {model}",
            )
        return PlatformModelTestResult(ok=True, latency_ms=12.25, error=None)


async def _client(
    tmp_path: Path,
    *,
    model_tester: Any | None = None,
) -> tuple[httpx.AsyncClient, Any, FakeModelTester | None]:
    engine = create_platform_engine(
        DatabaseSettings(url=default_test_database_url(tmp_path / "model-testing.sqlite3")),
    )
    await initialize_platform_schema(engine)
    session_factory = create_session_factory(engine)
    executor = DurableRunExecutor.for_tests(
        session_factory=session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    app = create_platform_app(
        session_factory=session_factory,
        executor=executor,
        engine=engine,
        secret_key_path=tmp_path / "platform-secret.key",
        model_tester=model_tester,
    )
    transport = httpx.ASGITransport(app=app)
    return (
        httpx.AsyncClient(transport=transport, base_url="http://testserver"),
        engine,
        model_tester,
    )


def _clear_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in _LLM_ENV_NAMES:
        monkeypatch.delenv(env_name, raising=False)


def _assert_raw_secret_absent(payload: Any, raw_secret: str) -> None:
    assert raw_secret not in json.dumps(payload, sort_keys=True)


async def test_model_catalog_returns_operator_metadata(tmp_path: Path) -> None:
    client, engine, _tester = await _client(tmp_path)
    try:
        response = await client.get("/api/settings/models/catalog")

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {"items"}
        by_id = {row["model"]: row for row in payload["items"]}

        assert by_id["gpt-5.5"] == {
            "provider": "openai",
            "model": "gpt-5.5",
            "display_name": "GPT-5.5",
            "context": 1_000_000,
            "max_output": 128_000,
            "capabilities": ["tools", "vision", "reasoning"],
            "badges": {"default": True, "small": False},
        }
        assert by_id["gpt-5.4-mini"]["badges"] == {"default": False, "small": True}
        assert by_id["claude-sonnet-5"]["badges"] == {"default": True, "small": False}
        assert by_id["gemini-3.5-flash"]["provider"] == "gemini"
    finally:
        await client.aclose()
        await engine.dispose()


async def test_model_test_endpoint_uses_fake_tester_with_vault_keys_and_redacts_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm_environment(monkeypatch)
    raw_secret = "sk-model-test-openai-secret"
    fake_tester = FakeModelTester(failures={"gpt-5.4-mini"})
    client, engine, _tester = await _client(tmp_path, model_tester=fake_tester)
    try:
        put_response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": raw_secret},
        )
        response = await client.post("/api/settings/models/test", json={})

        assert put_response.status_code == 200
        assert response.status_code == 200
        payload = response.json()
        _assert_raw_secret_absent(payload, raw_secret)

        summary = payload["summary"]
        assert summary["ok"] == 4
        assert summary["failed"] == 1
        assert summary["skipped"] == 7
        assert summary["tested_at"]

        openai_items = [item for item in payload["items"] if item["provider"] == "openai"]
        assert [call[:2] for call in fake_tester.calls] == [
            ("openai", item["model"]) for item in openai_items
        ]
        assert {call[2] for call in fake_tester.calls} == {raw_secret}
        assert any(
            item["model"] == "gpt-5.4-mini"
            and item["ok"] is False
            and item["latency_ms"] == 7.5
            and "failed for gpt-5.4-mini" in item["error"]
            for item in openai_items
        )
    finally:
        await client.aclose()
        await engine.dispose()


async def test_model_test_endpoint_skips_missing_provider_keys_without_live_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm_environment(monkeypatch)
    fake_tester = FakeModelTester()
    client, engine, _tester = await _client(tmp_path, model_tester=fake_tester)
    try:
        response = await client.post("/api/settings/models/test", json={})

        assert response.status_code == 200
        payload = response.json()
        assert payload["summary"]["ok"] == 0
        assert payload["summary"]["failed"] == 0
        assert payload["summary"]["skipped"] == len(payload["items"])
        assert fake_tester.calls == []
        assert {
            "provider",
            "model",
            "display_name",
            "ok",
            "latency_ms",
            "error",
        } <= set(payload["items"][0])
        assert all(item["ok"] is False for item in payload["items"])
        assert all(item["latency_ms"] is None for item in payload["items"])
        assert all(item["error"] == "Missing provider API key" for item in payload["items"])
    finally:
        await client.aclose()
        await engine.dispose()
