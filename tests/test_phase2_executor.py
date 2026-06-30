from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import create_session_factory
from attractor_platform.storage.models import Base, RunStatus

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def platform_session_factory(
    request: pytest.FixtureRequest,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("ATTRACTOR_TEST_DATABASE_URL")
    if not database_url:
        if shutil.which("pg_config") is None or shutil.which("pg_ctl") is None:
            pytest.skip(
                "Neither ATTRACTOR_TEST_DATABASE_URL nor local PostgreSQL tooling is available"
            )
        postgresql = request.getfixturevalue("postgresql")
        database_url = (
            "postgresql+asyncpg://"
            f"{postgresql.info.user}:{postgresql.info.password}@"
            f"{postgresql.info.host}:{postgresql.info.port}/{postgresql.info.dbname}"
        )

    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        yield create_session_factory(engine)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


async def test_executor_runs_workflow_in_worktree_and_persists_events(
    tmp_path,
    platform_session_factory,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)
    workflow_dir = repo_path / ".attractor" / "workflows" / "release"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="noop", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        """,
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)

    executor = DurableRunExecutor.for_tests(
        session_factory=platform_session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    assert run_id in executor.active_tasks
    result = await executor.wait(run_id)

    run = await executor.repository.get_run(run_id)
    events = await executor.repository.list_events(run_id, after_sequence=0, limit=100)
    checkpoints = await executor.repository.list_checkpoints(run_id)

    assert result.status.value == "success"
    assert run is not None
    assert run.status == RunStatus.COMPLETED.value
    assert [event.event_type for event in events][0] == "run.queued"
    assert "pipeline.started" in [event.event_type for event in events]
    assert checkpoints
