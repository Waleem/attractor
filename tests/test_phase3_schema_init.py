from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path
from typing import Any, cast

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.testclient import TestClient

from attractor_pipeline.handlers import CodergenHandler
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.secrets import SecretVault
from attractor_platform.storage.db import (
    DatabaseSettings,
    create_platform_engine,
    create_session_factory,
    default_test_database_url,
    initialize_platform_schema,
    session_scope,
)
from attractor_platform.storage.models import SettingSecretModel
from attractor_server import __main__ as server_main
from attractor_server.platform_app import create_platform_app


@pytest.mark.asyncio
async def test_initialize_sqlite_schema_creates_platform_tables(tmp_path: Path) -> None:
    engine = create_platform_engine(
        DatabaseSettings(url=default_test_database_url(tmp_path / "fresh.sqlite3")),
    )
    try:
        with pytest.raises(OperationalError, match="registered_repos"):
            async with engine.begin() as conn:
                await conn.execute(text("select count(*) from registered_repos"))

        await initialize_platform_schema(engine)

        async with engine.begin() as conn:
            result = await conn.execute(text("select count(*) from registered_repos"))
        assert result.scalar_one() == 0
    finally:
        await engine.dispose()


def test_platform_app_lifespan_initializes_fresh_sqlite_schema(tmp_path: Path) -> None:
    engine = create_platform_engine(
        DatabaseSettings(url=default_test_database_url(tmp_path / "app.sqlite3")),
    )
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
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/repos")

        assert response.status_code == 200
        assert response.json() == {"items": []}
    finally:
        anyio.run(engine.dispose)


def test_platform_main_defers_schema_initialization_to_uvicorn_lifespan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "attractor_server",
            "--platform",
            "--database-url",
            default_test_database_url(tmp_path / "main.sqlite3"),
            "--worktree-root",
            str(tmp_path / "worktrees"),
            "--artifact-root",
            str(tmp_path / "artifacts"),
        ],
    )

    def fail_asyncio_run(coro: Any) -> None:
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        raise AssertionError("platform main must not initialize schema via asyncio.run")

    uvicorn_calls: list[Any] = []
    monkeypatch.setattr(asyncio, "run", fail_asyncio_run)
    monkeypatch.setattr(server_main.uvicorn, "run", lambda app, **kwargs: uvicorn_calls.append(app))

    server_main.main()

    assert len(uvicorn_calls) == 1


def test_platform_app_lifespan_refreshes_codergen_backend_from_saved_provider_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for env_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(env_name, raising=False)

    engine = create_platform_engine(
        DatabaseSettings(url=default_test_database_url(tmp_path / "secret.sqlite3")),
    )
    session_factory = create_session_factory(engine)
    key_path = tmp_path / "platform-secret.key"

    async def seed_secret() -> None:
        await initialize_platform_schema(engine)
        vault = SecretVault(key_path)
        async with session_scope(cast(async_sessionmaker, session_factory)) as session:
            session.add(
                SettingSecretModel(
                    name="openai",
                    encrypted_value=vault.encrypt("sk-test-openai-from-vault"),
                    updated_at=dt.datetime.now(dt.UTC),
                )
            )

    anyio.run(seed_secret)
    executor = DurableRunExecutor.for_tests(
        session_factory=session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    app = create_platform_app(
        session_factory=session_factory,
        executor=executor,
        engine=engine,
        secret_key_path=key_path,
    )

    try:
        handler = cast(CodergenHandler, executor._handlers.get("codergen"))
        assert handler._backend is None

        with TestClient(app) as client:
            response = client.get("/api/settings")

        assert response.status_code == 200
        assert handler._backend is not None
    finally:
        anyio.run(engine.dispose)
