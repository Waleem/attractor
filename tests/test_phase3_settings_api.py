from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import attractor_server.platform_app as platform_app_module
from attractor_agent.profiles import get_profile
from attractor_pipeline.backends import DirectLLMBackend
from attractor_pipeline.handlers import CodergenHandler
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import (
    DatabaseSettings,
    create_platform_engine,
    create_session_factory,
    default_test_database_url,
    initialize_platform_schema,
    session_scope,
)
from attractor_platform.storage.models import SettingSecretModel, SettingVariableModel
from attractor_server.platform_app import create_platform_app

pytestmark = pytest.mark.asyncio

_LLM_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "ATTRACTOR_DEFAULT_PROVIDER",
    "ATTRACTOR_DEFAULT_MODEL",
)


async def _client_with_executor(
    tmp_path: Path,
    *,
    default_provider: str | None = None,
    default_model: str | None = None,
) -> tuple[httpx.AsyncClient, Any, DurableRunExecutor]:
    app, engine, executor = await _app_with_executor(
        tmp_path,
        default_provider=default_provider,
        default_model=default_model,
    )
    transport = httpx.ASGITransport(app=app)
    return (
        httpx.AsyncClient(transport=transport, base_url="http://testserver"),
        engine,
        executor,
    )


async def _app_with_executor(
    tmp_path: Path,
    *,
    default_provider: str | None = None,
    default_model: str | None = None,
) -> tuple[Any, Any, DurableRunExecutor]:
    engine = create_platform_engine(
        DatabaseSettings(url=default_test_database_url(tmp_path / "settings.sqlite3")),
    )
    await initialize_platform_schema(engine)
    session_factory = create_session_factory(engine)
    executor = DurableRunExecutor.for_tests(
        session_factory=session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    runtime_default_kwargs = {}
    if default_provider is not None:
        runtime_default_kwargs["default_provider"] = default_provider
    if default_model is not None:
        runtime_default_kwargs["default_model"] = default_model
    app = create_platform_app(
        session_factory=session_factory,
        executor=executor,
        engine=engine,
        secret_key_path=tmp_path / "platform-secret.key",
        **runtime_default_kwargs,
    )
    return app, engine, executor


async def _client(tmp_path: Path) -> tuple[httpx.AsyncClient, Any]:
    client, engine, _executor = await _client_with_executor(tmp_path)
    return client, engine


def _assert_raw_secret_absent(payload: Any, raw_secret: str) -> None:
    assert raw_secret not in json.dumps(payload, sort_keys=True)


def _clear_llm_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_name in _LLM_ENV_NAMES:
        monkeypatch.delenv(env_name, raising=False)


async def test_secret_api_is_write_only_and_lists_metadata(tmp_path: Path) -> None:
    client, engine = await _client(tmp_path)
    try:
        raw_secret = "sk-task-4-openai-secret"

        put_response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": raw_secret},
        )
        assert put_response.status_code == 200
        put_payload = put_response.json()
        assert put_payload["name"] == "openai"
        assert put_payload["configured"] is True
        assert put_payload["updated_at"]
        assert set(put_payload) == {"name", "configured", "updated_at"}
        _assert_raw_secret_absent(put_payload, raw_secret)

        get_response = await client.get("/api/settings/secrets")
        assert get_response.status_code == 200
        get_payload = get_response.json()
        assert get_payload == {"items": [put_payload]}
        _assert_raw_secret_absent(get_payload, raw_secret)
    finally:
        await client.aclose()
        await engine.dispose()


async def test_secret_api_stores_ciphertext_without_raw_secret(tmp_path: Path) -> None:
    client, engine = await _client(tmp_path)
    try:
        raw_secret = "sk-task-4-ciphertext"

        response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": raw_secret},
        )

        assert response.status_code == 200
        session_factory = create_session_factory(engine)
        async with session_scope(session_factory) as session:
            secret = await session.scalar(
                select(SettingSecretModel).where(SettingSecretModel.name == "openai")
            )
        assert secret is not None
        assert secret.encrypted_value != raw_secret
        assert raw_secret not in secret.encrypted_value
    finally:
        await client.aclose()
        await engine.dispose()


async def test_secret_replace_and_delete_update_metadata_without_exposing_values(
    tmp_path: Path,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        first_secret = "sk-first"
        second_secret = "sk-second"

        first_response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": first_secret},
        )
        second_response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": second_secret},
        )
        delete_response = await client.delete("/api/settings/secrets/openai")
        list_response = await client.get("/api/settings/secrets")

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert delete_response.status_code == 200
        assert delete_response.json() == {
            "name": "openai",
            "configured": False,
            "updated_at": None,
        }
        assert list_response.json() == {"items": []}
        _assert_raw_secret_absent(second_response.json(), first_secret)
        _assert_raw_secret_absent(second_response.json(), second_secret)
    finally:
        await client.aclose()
        await engine.dispose()


async def test_concurrent_first_secret_writes_replace_instead_of_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, engine, _executor = await _app_with_executor(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    original_get = AsyncSession.get
    name = "race-openai"
    values = {"sk-race-first", "sk-race-second"}
    both_readers_arrived = asyncio.Event()
    reader_count = 0

    async def force_both_first_writers_to_observe_missing(
        self: AsyncSession,
        entity: Any,
        ident: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal reader_count
        if entity is SettingSecretModel and ident == name:
            reader_count += 1
            if reader_count == 2:
                both_readers_arrived.set()
            else:
                await both_readers_arrived.wait()
            return None
        return await original_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(
        AsyncSession,
        "get",
        force_both_first_writers_to_observe_missing,
    )
    try:
        responses = await asyncio.gather(
            client.put(f"/api/settings/secrets/{name}", json={"value": "sk-race-first"}),
            client.put(f"/api/settings/secrets/{name}", json={"value": "sk-race-second"}),
        )

        assert [response.status_code for response in responses] == [200, 200]
        assert {response.json()["name"] for response in responses} == {name}
        session_factory = create_session_factory(engine)
        async with session_scope(session_factory) as session:
            secret = await session.scalar(
                select(SettingSecretModel).where(SettingSecretModel.name == name)
            )
        assert secret is not None
        decrypted_value = app.state.platform_services.secret_vault.decrypt(
            secret.encrypted_value
        )
        assert decrypted_value in values
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_overview_includes_required_sections_and_secret_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        monkeypatch.setenv("GOOGLE_API_KEY", "google-status-only")
        await client.put("/api/settings/secrets/openai", json={"value": "sk-status-only"})

        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload = response.json()
        assert set(payload) == {
            "models",
            "environments",
            "variables",
            "server",
            "storage",
            "monitoring",
        }
        assert payload["models"]["default_provider"] == "gemini"
        assert payload["models"]["default_model"] == get_profile("gemini").default_model
        assert payload["models"]["provider_credentials"]["openai"]["configured"] is True
        assert payload["models"]["provider_credentials"]["gemini"] == {
            "name": "gemini",
            "env_var": "GOOGLE_API_KEY",
            "configured": True,
            "updated_at": None,
            "source": "environment",
        }
        assert "value" not in payload["models"]["provider_credentials"]["openai"]
        assert isinstance(payload["variables"]["items"], list)
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_default_model_uses_anthropic_when_only_anthropic_key_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-status-only")

        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["models"]["default_provider"] == "anthropic"
        assert payload["models"]["default_model"] == get_profile("anthropic").default_model
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_default_model_uses_gemini_when_only_google_key_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        monkeypatch.setenv("GOOGLE_API_KEY", "google-status-only")

        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["models"]["default_provider"] == "gemini"
        assert payload["models"]["default_model"] == get_profile("gemini").default_model
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_default_model_uses_gemini_when_only_gemini_key_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-status-only")

        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["models"]["default_provider"] == "gemini"
        assert payload["models"]["default_model"] == get_profile("gemini").default_model
        assert payload["models"]["provider_credentials"]["gemini"] == {
            "name": "gemini",
            "env_var": "GEMINI_API_KEY",
            "configured": True,
            "updated_at": None,
            "source": "environment",
        }
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_default_model_uses_saved_vault_key_without_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        raw_secret = "sk-task-4-openai-runtime"
        put_response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": raw_secret},
        )

        response = await client.get("/api/settings")

        assert put_response.status_code == 200
        assert response.status_code == 200
        payload = response.json()
        assert payload["models"]["default_provider"] == "openai"
        assert payload["models"]["default_model"] == get_profile("openai").default_model
        assert payload["models"]["provider_credentials"]["openai"]["source"] == "vault"
        _assert_raw_secret_absent(payload, raw_secret)
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_provider_credential_source_prefers_env_over_saved_vault_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "openai-env-runtime")
        raw_secret = "sk-task-4-openai-vault-fallback"
        put_response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": raw_secret},
        )

        response = await client.get("/api/settings")

        assert put_response.status_code == 200
        assert response.status_code == 200
        payload = response.json()
        assert payload["models"]["provider_credentials"]["openai"]["source"] == "environment"
        _assert_raw_secret_absent(payload, raw_secret)
    finally:
        await client.aclose()
        await engine.dispose()


async def test_saving_provider_secret_updates_codergen_runtime_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, executor = await _client_with_executor(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        handler = cast(CodergenHandler, executor._handlers.get("codergen"))
        assert handler is not None
        assert handler._backend is None

        response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": "sk-task-4-openai-live-runtime"},
        )

        assert response.status_code == 200
        assert handler._backend is not None
        assert handler._backend._default_provider == "openai"
    finally:
        await client.aclose()
        await engine.dispose()


async def test_provider_secret_write_and_delete_preserve_runtime_llm_defaults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm_environment(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-env-runtime")
    client, engine, executor = await _client_with_executor(
        tmp_path,
        default_provider="openai",
        default_model="gpt-cli-task-4",
    )
    try:
        handler = cast(CodergenHandler, executor._handlers.get("codergen"))
        assert handler is not None

        put_response = await client.put(
            "/api/settings/secrets/openai",
            json={"value": "sk-task-4-openai-cli-default"},
        )
        settings_after_put = await client.get("/api/settings")

        assert put_response.status_code == 200
        assert handler._backend is not None
        backend = cast(DirectLLMBackend, handler._backend)
        assert backend._default_provider == "openai"
        assert backend._default_model == "gpt-cli-task-4"
        assert settings_after_put.status_code == 200
        assert settings_after_put.json()["models"]["default_provider"] == "openai"
        assert settings_after_put.json()["models"]["default_model"] == "gpt-cli-task-4"

        delete_response = await client.delete("/api/settings/secrets/openai")
        settings_after_delete = await client.get("/api/settings")

        assert delete_response.status_code == 200
        assert handler._backend is None
        assert settings_after_delete.status_code == 200
        assert settings_after_delete.json()["models"]["default_provider"] == ""
        assert settings_after_delete.json()["models"]["default_model"] == ""
    finally:
        await client.aclose()
        await engine.dispose()


async def test_codergen_backend_refreshes_are_serialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, engine, _executor = await _app_with_executor(tmp_path)
    services = app.state.platform_services
    entered_first_refresh = asyncio.Event()
    release_first_refresh = asyncio.Event()
    active_refreshes = 0
    max_active_refreshes = 0
    calls = 0

    async def fake_provider_api_keys_from_vault(
        _services: Any,
    ) -> dict[str, str]:
        nonlocal active_refreshes, calls, max_active_refreshes
        calls += 1
        active_refreshes += 1
        max_active_refreshes = max(max_active_refreshes, active_refreshes)
        try:
            if calls == 1:
                entered_first_refresh.set()
                await release_first_refresh.wait()
            else:
                await asyncio.sleep(0)
            return {"openai": "sk-refresh-serialized"}
        finally:
            active_refreshes -= 1

    monkeypatch.setattr(
        platform_app_module,
        "_provider_api_keys_from_vault",
        fake_provider_api_keys_from_vault,
    )
    try:
        first = asyncio.create_task(platform_app_module._refresh_codergen_backend(services))
        await entered_first_refresh.wait()
        second = asyncio.create_task(platform_app_module._refresh_codergen_backend(services))
        await asyncio.sleep(0)
        release_first_refresh.set()

        await asyncio.gather(first, second)

        assert calls == 2
        assert max_active_refreshes == 1
    finally:
        release_first_refresh.set()
        await engine.dispose()


async def test_settings_default_model_honors_explicit_provider_and_model_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_llm_environment(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-status-only")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-status-only")
    monkeypatch.setenv("ATTRACTOR_DEFAULT_PROVIDER", "openai")
    monkeypatch.setenv("ATTRACTOR_DEFAULT_MODEL", "gpt-task-4")
    client, engine = await _client(tmp_path)
    try:
        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["models"]["default_provider"] == "openai"
        assert payload["models"]["default_model"] == "gpt-task-4"
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_overview_redacts_storage_internals(tmp_path: Path) -> None:
    client, engine = await _client(tmp_path)
    try:
        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload = response.json()
        assert payload["storage"] == {"status": "configured"}
        serialized = json.dumps(payload, sort_keys=True)
        assert "database_url" not in serialized
        assert "secret_key_path" not in serialized
        assert "settings.sqlite3" not in serialized
        assert "platform-secret.key" not in serialized
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_variables_are_readable_non_secret_key_value_rows(
    tmp_path: Path,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        put_response = await client.put(
            "/api/settings/variables/DEFAULT_REGION",
            json={"value": "us-west-2"},
        )
        list_response = await client.get("/api/settings/variables")

        assert put_response.status_code == 200
        assert put_response.json()["key"] == "DEFAULT_REGION"
        assert put_response.json()["value"] == "us-west-2"
        assert list_response.json()["items"] == [put_response.json()]
    finally:
        await client.aclose()
        await engine.dispose()


async def test_concurrent_first_variable_writes_replace_instead_of_500(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, engine, _executor = await _app_with_executor(tmp_path)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    original_get = AsyncSession.get
    key = "RACE_REGION"
    values = {"us-west-1", "us-east-1"}
    both_readers_arrived = asyncio.Event()
    reader_count = 0

    async def force_both_first_writers_to_observe_missing(
        self: AsyncSession,
        entity: Any,
        ident: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        nonlocal reader_count
        if entity is SettingVariableModel and ident == key:
            reader_count += 1
            if reader_count == 2:
                both_readers_arrived.set()
            else:
                await both_readers_arrived.wait()
            return None
        return await original_get(self, entity, ident, *args, **kwargs)

    monkeypatch.setattr(
        AsyncSession,
        "get",
        force_both_first_writers_to_observe_missing,
    )
    try:
        responses = await asyncio.gather(
            client.put(f"/api/settings/variables/{key}", json={"value": "us-west-1"}),
            client.put(f"/api/settings/variables/{key}", json={"value": "us-east-1"}),
        )

        assert [response.status_code for response in responses] == [200, 200]
        assert {response.json()["key"] for response in responses} == {key}
        session_factory = create_session_factory(engine)
        async with session_scope(session_factory) as session:
            variable = await session.scalar(
                select(SettingVariableModel).where(SettingVariableModel.key == key)
            )
        assert variable is not None
        assert variable.value in values
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_names_are_ascii_only(tmp_path: Path) -> None:
    client, engine = await _client(tmp_path)
    try:
        variable_response = await client.put(
            "/api/settings/variables/UNICODE_é",
            json={"value": "unsafe"},
        )
        secret_response = await client.put(
            "/api/settings/secrets/gémini",
            json={"value": "unsafe"},
        )

        assert variable_response.status_code == 400
        assert secret_response.status_code == 400
    finally:
        await client.aclose()
        await engine.dispose()


async def test_setting_secret_name_rejects_database_max_length_plus_one(
    tmp_path: Path,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        overlong_name = "a" * 121

        response = await client.put(
            f"/api/settings/secrets/{overlong_name}",
            json={"value": "unsafe"},
        )

        assert response.status_code == 400
    finally:
        await client.aclose()
        await engine.dispose()


async def test_setting_variable_key_rejects_database_max_length_plus_one(
    tmp_path: Path,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        overlong_key = "a" * 161

        response = await client.put(
            f"/api/settings/variables/{overlong_key}",
            json={"value": "unsafe"},
        )

        assert response.status_code == 400
    finally:
        await client.aclose()
        await engine.dispose()


async def test_phase3_settings_tables_have_alembic_revision() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "src"
        / "attractor_platform"
        / "storage"
        / "alembic"
        / "versions"
        / "0002_phase3_settings_tables.py"
    )
    assert migration_path.exists()

    spec = importlib.util.spec_from_file_location("phase3_settings_migration", migration_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.down_revision == "0001_phase2_platform_spines"
    source = migration_path.read_text()
    assert '"setting_secrets"' in source
    assert '"setting_variables"' in source
    assert "op.create_table" in source
    assert "op.drop_table" in source
