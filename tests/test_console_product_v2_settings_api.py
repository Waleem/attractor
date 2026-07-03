from __future__ import annotations

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
from tests.test_phase3_settings_api import _client

pytestmark = pytest.mark.asyncio


async def _client_with_max_concurrent(
    tmp_path: Path,
    max_concurrent_runs: int,
) -> tuple[httpx.AsyncClient, Any]:
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
        max_concurrent_runs=max_concurrent_runs,
    )
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://testserver"), engine


def _rows_by_label(page: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["label"]: row
        for group in page["groups"]
        for row in group["rows"]
    }


async def test_deep_settings_overview_contains_operator_knobs(tmp_path) -> None:
    client, engine = await _client(tmp_path)
    try:
        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload: dict[str, Any] = response.json()
        pages = payload["pages"]
        page_ids = {page["id"] for page in pages}
        assert {
            "models",
            "integrations",
            "sandboxes",
            "environments",
            "variables",
            "secrets",
            "run-defaults",
            "server",
            "security",
            "storage",
            "monitoring",
            "live-events",
        } <= page_ids
        for page in pages:
            assert page["title"]
            assert page["description"]
            for group in page["groups"]:
                assert group["title"]
                for row in group["rows"]:
                    assert row["editability"] in {
                        "editable",
                        "restart-required",
                        "read-only",
                        "reserved",
                    }
                    assert {"label", "description", "value", "editability"} <= set(row)
    finally:
        await client.aclose()
        await engine.dispose()


async def test_settings_reports_configured_max_concurrent_runs(tmp_path: Path) -> None:
    client, engine = await _client_with_max_concurrent(tmp_path, 7)
    try:
        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload: dict[str, Any] = response.json()
        pages = {page["id"]: page for page in payload["pages"]}
        run_defaults = _rows_by_label(pages["run-defaults"])
        monitoring = _rows_by_label(pages["monitoring"])
        assert payload["server"]["max_concurrent_runs"] == 7
        assert run_defaults["--max-concurrent"]["value"] == 7
        assert monitoring["Run concurrency"]["value"] == "0/7"
    finally:
        await client.aclose()
        await engine.dispose()


async def test_system_capacity_reports_configured_max_concurrent_runs(
    tmp_path: Path,
) -> None:
    client, engine = await _client_with_max_concurrent(tmp_path, 7)
    try:
        response = await client.get("/api/system/capacity")

        assert response.status_code == 200
        assert response.json() == {
            "active_runs": 0,
            "max_concurrent_runs": 7,
            "available_slots": 7,
        }
    finally:
        await client.aclose()
        await engine.dispose()
