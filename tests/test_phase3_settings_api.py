from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from attractor_agent.profiles import get_profile
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import (
    DatabaseSettings,
    create_platform_engine,
    create_session_factory,
    default_test_database_url,
    initialize_platform_schema,
    session_scope,
)
from attractor_platform.storage.models import SettingSecretModel
from attractor_server.platform_app import create_platform_app

pytestmark = pytest.mark.asyncio

_LLM_ENV_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ATTRACTOR_DEFAULT_PROVIDER",
    "ATTRACTOR_DEFAULT_MODEL",
)


async def _client(tmp_path: Path) -> tuple[httpx.AsyncClient, Any]:
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
    app = create_platform_app(
        session_factory=session_factory,
        executor=executor,
        engine=engine,
        secret_key_path=tmp_path / "platform-secret.key",
    )
    transport = httpx.ASGITransport(app=app)
    return (
        httpx.AsyncClient(transport=transport, base_url="http://testserver"),
        engine,
    )


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


async def test_settings_default_model_honors_explicit_provider_and_model_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine = await _client(tmp_path)
    try:
        _clear_llm_environment(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-status-only")
        monkeypatch.setenv("OPENAI_API_KEY", "openai-status-only")
        monkeypatch.setenv("ATTRACTOR_DEFAULT_PROVIDER", "openai")
        monkeypatch.setenv("ATTRACTOR_DEFAULT_MODEL", "gpt-task-4")

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
