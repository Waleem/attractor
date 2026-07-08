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
from attractor_platform.storage.models import RunRecordModel, SettingSecretModel
from attractor_platform.storage.repositories import PlatformRepository
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


@pytest.mark.asyncio
async def test_initialize_sqlite_schema_upgrades_run_repo_links_to_preserve_history(
    tmp_path: Path,
) -> None:
    engine = create_platform_engine(
        DatabaseSettings(url=default_test_database_url(tmp_path / "old-links.sqlite3")),
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    """
                    CREATE TABLE registered_repos (
                        id VARCHAR(64) NOT NULL PRIMARY KEY,
                        name VARCHAR(200) NOT NULL,
                        local_path TEXT NOT NULL UNIQUE,
                        default_branch VARCHAR(200) NOT NULL,
                        current_commit VARCHAR(40) NOT NULL,
                        dirty_state VARCHAR(20) NOT NULL,
                        project_config_status VARCHAR(40) NOT NULL,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        last_indexed_at DATETIME
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE workflow_packages (
                        id VARCHAR(64) NOT NULL PRIMARY KEY,
                        repo_id VARCHAR(64) NOT NULL,
                        name VARCHAR(200) NOT NULL,
                        dot_path TEXT NOT NULL,
                        toml_path TEXT,
                        status VARCHAR(40) NOT NULL,
                        diagnostics JSON NOT NULL,
                        indexed_at DATETIME NOT NULL,
                        FOREIGN KEY(repo_id) REFERENCES registered_repos (id) ON DELETE CASCADE,
                        UNIQUE (repo_id, name)
                    )
                    """
                )
            )
            await conn.execute(
                text(
                    """
                    CREATE TABLE run_records (
                        id VARCHAR(64) NOT NULL PRIMARY KEY,
                        repo_id VARCHAR(64) NOT NULL,
                        workflow_id VARCHAR(64) NOT NULL,
                        status VARCHAR(40) NOT NULL,
                        run_spec JSON NOT NULL,
                        actor_label VARCHAR(200) NOT NULL,
                        source_commit VARCHAR(40) NOT NULL,
                        source_branch VARCHAR(200) NOT NULL,
                        worktree_path TEXT,
                        managed_branch VARCHAR(300),
                        error_category VARCHAR(100),
                        error_message TEXT,
                        created_at DATETIME NOT NULL,
                        updated_at DATETIME NOT NULL,
                        started_at DATETIME,
                        completed_at DATETIME,
                        FOREIGN KEY(repo_id) REFERENCES registered_repos (id) ON DELETE RESTRICT,
                        FOREIGN KEY(workflow_id)
                            REFERENCES workflow_packages (id)
                            ON DELETE RESTRICT
                    )
                    """
                )
            )
            await conn.execute(text("CREATE INDEX ix_run_records_status ON run_records (status)"))
            timestamp = "2026-07-08 12:00:00"
            await conn.execute(
                text(
                    """
                    INSERT INTO registered_repos (
                        id,
                        name,
                        local_path,
                        default_branch,
                        current_commit,
                        dirty_state,
                        project_config_status,
                        created_at,
                        updated_at,
                        last_indexed_at
                    )
                    VALUES (
                        'repo_old',
                        'old',
                        '/tmp/old',
                        'main',
                        '0000000000000000000000000000000000000000',
                        'clean',
                        'valid',
                        :timestamp,
                        :timestamp,
                        :timestamp
                    )
                    """
                ),
                {"timestamp": timestamp},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO workflow_packages (
                        id,
                        repo_id,
                        name,
                        dot_path,
                        toml_path,
                        status,
                        diagnostics,
                        indexed_at
                    )
                    VALUES (
                        'wf_old',
                        'repo_old',
                        'release',
                        '/tmp/old/.attractor/workflows/release/workflow.dot',
                        NULL,
                        'valid',
                        '{}',
                        :timestamp
                    )
                    """
                ),
                {"timestamp": timestamp},
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO run_records (
                        id,
                        repo_id,
                        workflow_id,
                        status,
                        run_spec,
                        actor_label,
                        source_commit,
                        source_branch,
                        created_at,
                        updated_at
                    )
                    VALUES (
                        'run_old',
                        'repo_old',
                        'wf_old',
                        'completed',
                        '{}',
                        'alice',
                        '0000000000000000000000000000000000000000',
                        'main',
                        :timestamp,
                        :timestamp
                    )
                    """
                ),
                {"timestamp": timestamp},
            )

        await initialize_platform_schema(engine)

        async with engine.begin() as conn:
            columns = list(await conn.execute(text("PRAGMA table_info(run_records)")))
            foreign_keys = list(await conn.execute(text("PRAGMA foreign_key_list(run_records)")))
        not_null_by_column = {row[1]: row[3] for row in columns}
        on_delete_by_column = {row[3]: row[6] for row in foreign_keys}
        assert not_null_by_column["repo_id"] == 0
        assert not_null_by_column["workflow_id"] == 0
        assert on_delete_by_column["repo_id"] == "SET NULL"
        assert on_delete_by_column["workflow_id"] == "SET NULL"

        repository = PlatformRepository(create_session_factory(engine))
        assert await repository.delete_repo("repo_old") is True

        async with create_session_factory(engine)() as session:
            run = await session.get(RunRecordModel, "run_old")
        assert run is not None
        assert run.repo_id is None
        assert run.workflow_id is None
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
