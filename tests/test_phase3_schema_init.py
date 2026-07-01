from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from starlette.testclient import TestClient

from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import (
    DatabaseSettings,
    create_platform_engine,
    create_session_factory,
    default_test_database_url,
    initialize_platform_schema,
)
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
