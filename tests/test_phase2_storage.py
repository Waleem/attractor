from __future__ import annotations

import datetime as dt
import os
from asyncio import gather
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from attractor_platform.storage.db import create_session_factory
from attractor_platform.storage.models import Base, RunStatus
from attractor_platform.storage.repositories import PlatformRepository, _select_run_for_append_lock


@pytest_asyncio.fixture
async def platform_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("ATTRACTOR_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("ATTRACTOR_TEST_DATABASE_URL is not configured")

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


async def _create_minimal_run_for_test(repo: PlatformRepository, run_id: str) -> None:
    now = dt.datetime.now(dt.UTC)
    repo_id = f"{run_id}_repo"
    workflow_id = f"{run_id}_workflow"
    await repo.register_repo(
        repo_id=repo_id,
        name="test",
        local_path=f"/tmp/{run_id}",
        default_branch="main",
        current_commit="0" * 40,
        dirty_state="clean",
        timestamp=now,
    )
    await repo.upsert_workflow(
        workflow_id=workflow_id,
        repo_id=repo_id,
        name="test",
        dot_path=f"/tmp/{run_id}/workflow.dot",
        toml_path=None,
        status="valid",
        diagnostics={},
        timestamp=now,
    )
    await repo.create_run(
        run_id=run_id,
        repo_id=repo_id,
        workflow_id=workflow_id,
        run_spec={},
        actor_label="",
        source_commit="0" * 40,
        source_branch="main",
        timestamp=now,
    )


def test_append_event_lock_statement_targets_parent_run_for_update() -> None:
    statement = _select_run_for_append_lock("run_1")

    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "FROM run_records" in sql
    assert "WHERE run_records.id = 'run_1'" in sql
    assert "FOR UPDATE" in sql


async def test_run_events_are_append_only_and_ordered(platform_session_factory) -> None:
    repo = PlatformRepository(platform_session_factory)
    now = dt.datetime.now(dt.UTC)

    await repo.register_repo(
        repo_id="repo_1",
        name="demo",
        local_path="/tmp/demo",
        default_branch="main",
        current_commit="1" * 40,
        dirty_state="clean",
        timestamp=now,
    )
    await repo.upsert_workflow(
        workflow_id="wf_1",
        repo_id="repo_1",
        name="release",
        dot_path="/tmp/demo/.attractor/workflows/release/workflow.dot",
        toml_path=None,
        status="valid",
        diagnostics={},
        timestamp=now,
    )
    await repo.create_run(
        run_id="run_1",
        repo_id="repo_1",
        workflow_id="wf_1",
        run_spec={"actor_label": "alice"},
        actor_label="alice",
        source_commit="1" * 40,
        source_branch="main",
        timestamp=now,
    )

    first = await repo.append_event("run_1", "run.queued", {"secret": "value"}, timestamp=now)
    second = await repo.append_event("run_1", "run.started", {"node": "start"}, timestamp=now)

    events = await repo.list_events("run_1", after_sequence=0, limit=100)
    assert [event.sequence for event in events] == [first.sequence, second.sequence]
    assert events[0].payload == {"secret": "[REDACTED]"}


async def test_concurrent_run_events_receive_distinct_sequences(platform_session_factory) -> None:
    repo = PlatformRepository(platform_session_factory)
    now = dt.datetime.now(dt.UTC)
    await _create_minimal_run_for_test(repo, "run_concurrent")

    await gather(
        *[
            repo.append_event(
                "run_concurrent",
                f"run.event_{index}",
                {"index": index},
                timestamp=now,
            )
            for index in range(20)
        ]
    )

    events = await repo.list_events("run_concurrent", after_sequence=0, limit=100)

    assert [event.sequence for event in events] == list(range(1, 21))


async def test_run_status_updates(platform_session_factory) -> None:
    repo = PlatformRepository(platform_session_factory)
    await _create_minimal_run_for_test(repo, "run_status")

    await repo.update_run_status("run_status", RunStatus.RUNNING)
    record = await repo.get_run("run_status")

    assert record is not None
    assert record.status == RunStatus.RUNNING.value
