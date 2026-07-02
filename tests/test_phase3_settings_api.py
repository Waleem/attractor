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
from attractor_server.platform_app import create_platform_app

pytestmark = pytest.mark.asyncio


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
) -> None:
    client, engine = await _client(tmp_path)
    try:
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
        assert payload["models"]["default_provider"] == "openai"
        assert payload["models"]["default_model"]
        assert payload["models"]["provider_credentials"]["openai"]["configured"] is True
        assert "value" not in payload["models"]["provider_credentials"]["openai"]
        assert isinstance(payload["variables"]["items"], list)
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
