from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from attractor_pipeline.engine.runner import HandlerResult, Outcome, PipelineResult, PipelineStatus
from attractor_platform.checkpoints import GitCheckpoint
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import create_session_factory
from attractor_platform.storage.models import Base, RunStatus

pytestmark = pytest.mark.asyncio


@dataclass
class _FakeEvent:
    sequence: int
    event_type: str
    payload: dict[str, Any]
    actor_label: str


@dataclass
class _FakeArtifact:
    kind: str
    name: str
    uri: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass
class _FakeCheckpoint:
    node_id: str
    stage_index: int
    commit_sha: str
    ref_name: str


class _InMemoryPlatformRepository:
    def __init__(self) -> None:
        self.runs: dict[str, SimpleNamespace] = {}
        self.events: dict[str, list[_FakeEvent]] = {}
        self.artifacts: dict[str, list[_FakeArtifact]] = {}
        self.checkpoints: dict[str, list[_FakeCheckpoint]] = {}
        self.register_repo_calls: list[dict[str, Any]] = []

    async def register_repo(self, **kwargs: Any) -> None:
        self.register_repo_calls.append(dict(kwargs))
        return None

    async def upsert_workflow(self, **_: Any) -> None:
        return None

    async def create_run(
        self,
        *,
        run_id: str,
        repo_id: str,
        workflow_id: str,
        run_spec: dict[str, Any],
        actor_label: str,
        source_commit: str,
        source_branch: str,
        timestamp: Any,
    ) -> SimpleNamespace:
        run = SimpleNamespace(
            id=run_id,
            repo_id=repo_id,
            workflow_id=workflow_id,
            run_spec=run_spec,
            actor_label=actor_label,
            source_commit=source_commit,
            source_branch=source_branch,
            status=RunStatus.QUEUED.value,
            worktree_path=None,
            managed_branch=None,
            started_at=None,
            completed_at=None,
            error_category=None,
            error_message=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.runs[run_id] = run
        self.events[run_id] = []
        self.artifacts[run_id] = []
        self.checkpoints[run_id] = []
        return run

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: Any | None = None,
    ) -> _FakeEvent:
        del timestamp
        event = _FakeEvent(
            sequence=len(self.events[run_id]) + 1,
            event_type=event_type,
            payload=dict(payload),
            actor_label=actor_label,
        )
        self.events[run_id].append(event)
        return event

    async def list_events(self, run_id: str, after_sequence: int, limit: int) -> list[_FakeEvent]:
        return [
            event
            for event in self.events[run_id]
            if event.sequence > after_sequence
        ][:limit]

    async def get_run(self, run_id: str) -> SimpleNamespace | None:
        return self.runs.get(run_id)

    async def create_artifact(
        self,
        *,
        artifact_id: str,
        run_id: str,
        kind: str,
        name: str,
        uri: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
        timestamp: Any,
    ) -> _FakeArtifact:
        del artifact_id, timestamp
        artifact = _FakeArtifact(
            kind=kind,
            name=name,
            uri=uri,
            media_type=media_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        self.artifacts[run_id].append(artifact)
        return artifact

    async def list_artifacts(self, run_id: str) -> list[_FakeArtifact]:
        return list(self.artifacts[run_id])

    async def create_checkpoint(
        self,
        *,
        checkpoint_id: str,
        run_id: str,
        node_id: str,
        stage_index: int,
        commit_sha: str,
        ref_name: str,
        timestamp: Any,
    ) -> _FakeCheckpoint:
        del checkpoint_id, timestamp
        checkpoint = _FakeCheckpoint(
            node_id=node_id,
            stage_index=stage_index,
            commit_sha=commit_sha,
            ref_name=ref_name,
        )
        self.checkpoints[run_id].append(checkpoint)
        return checkpoint

    async def list_checkpoints(self, run_id: str) -> list[_FakeCheckpoint]:
        return list(self.checkpoints[run_id])


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


def _init_repo_with_workflow(tmp_path: Path, workflow_name: str, workflow_dot: str) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)
    workflow_dir = repo_path / ".attractor" / "workflows" / workflow_name
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(workflow_dot, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


def _make_executor(tmp_path: Path) -> tuple[DurableRunExecutor, _InMemoryPlatformRepository]:
    executor = DurableRunExecutor.for_tests(
        session_factory=cast(Any, None),
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    repository = _InMemoryPlatformRepository()
    executor_any: Any = executor
    executor_any.repository = repository

    async def _update_run_record(
        run_id: str,
        *,
        status: RunStatus | None = None,
        worktree_path: str | None = None,
        managed_branch: str | None = None,
        started_at: Any | None = None,
        completed_at: Any | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        run = repository.runs[run_id]
        if status is not None:
            run.status = status.value
        if worktree_path is not None:
            run.worktree_path = worktree_path
        if managed_branch is not None:
            run.managed_branch = managed_branch
        if started_at is not None:
            run.started_at = started_at
        if completed_at is not None:
            run.completed_at = completed_at
        run.error_category = error_category
        run.error_message = error_message

    executor_any._update_run_record = _update_run_record
    return executor, repository


async def test_register_and_launch_tracks_active_task_and_removes_it_after_completion(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="hold", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)
    started = asyncio.Event()
    released = asyncio.Event()

    class _HoldHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "hold.txt").write_text("holding", encoding="utf-8")
            started.set()
            await released.wait()
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    executor._handlers.register("hold", _HoldHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )

    await asyncio.wait_for(started.wait(), timeout=2.0)
    assert run_id in executor.active_tasks
    assert not executor.active_tasks[run_id].done()

    released.set()
    result = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    checkpoints = await repository.list_checkpoints(run_id)

    assert result.status == PipelineStatus.COMPLETED
    assert run is not None
    assert run.status == RunStatus.COMPLETED.value
    assert run_id not in executor.active_tasks
    assert checkpoints


async def test_register_and_launch_preserves_valid_project_config_status(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="noop", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    await executor.wait(run_id)

    assert repository.register_repo_calls
    assert repository.register_repo_calls[0]["project_config_status"] == "valid"


async def test_failed_run_captures_runtime_artifacts_and_clears_active_task(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          missing [shape=box, handler="nonexistent_handler", prompt="run"]
          done [shape=Msquare]
          start -> task -> missing -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "failure.txt").write_text("failure trace", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    executor._handlers.register("writer", _WritingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    result = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    artifacts = repository.artifacts[run_id]
    event_types = [event.event_type for event in repository.events[run_id]]

    assert result.status == PipelineStatus.FAILED
    assert run is not None
    assert run.status == RunStatus.FAILED.value
    assert run_id not in executor.active_tasks
    assert "pipeline.failed" in event_types
    assert "run.failed" in event_types
    failure_artifact = next(artifact for artifact in artifacts if artifact.name == "failure.txt")
    assert executor._artifact_store.read_bytes(failure_artifact.uri) == b"failure trace"


async def test_terminal_append_cancellation_recovers_and_records_terminal_event(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          missing [shape=box, handler="nonexistent_handler", prompt="run"]
          done [shape=Msquare]
          start -> task -> missing -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "failure.txt").write_text("failure trace", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    original_append_event = repository.append_event
    terminal_append_cancellations = 0

    async def _cancelling_append_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: Any | None = None,
    ) -> _FakeEvent:
        nonlocal terminal_append_cancellations
        if event_type == "run.failed" and terminal_append_cancellations < 2:
            terminal_append_cancellations += 1
            raise asyncio.CancelledError("terminal event persistence cancelled")
        return await original_append_event(
            run_id,
            event_type,
            payload,
            actor_label=actor_label,
            timestamp=timestamp,
        )

    repository_any = cast(Any, repository)
    repository_any.append_event = _cancelling_append_event
    executor._handlers.register("writer", _WritingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )

    # Internal terminal persistence cancellation should surface as a failed wait,
    # but it must not livelock the executor.
    result = await asyncio.wait_for(executor.wait(run_id), timeout=2.0)
    second_wait = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    event_types = [event.event_type for event in repository.events[run_id]]
    failure_artifacts = [
        artifact for artifact in repository.artifacts[run_id] if artifact.name == "failure.txt"
    ]

    assert result.status == PipelineStatus.FAILED
    assert result.error is not None
    assert "Terminal finalization cancelled" in result.error
    assert second_wait == result
    assert run is not None
    assert run.status == RunStatus.FAILED.value
    assert "pipeline.failed" in event_types
    assert "run.failed" in event_types
    assert len(failure_artifacts) == 1
    assert run_id not in executor.active_tasks


async def test_terminal_append_cancellation_exhaustion_raises_without_terminal_result(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          missing [shape=box, handler="nonexistent_handler", prompt="run"]
          done [shape=Msquare]
          start -> task -> missing -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "failure.txt").write_text("failure trace", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    original_append_event = repository.append_event
    terminal_append_attempts = 0

    async def _always_cancelling_append_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: Any | None = None,
    ) -> _FakeEvent:
        nonlocal terminal_append_attempts
        if event_type == "run.failed":
            terminal_append_attempts += 1
            raise asyncio.CancelledError("terminal event persistence cancelled")
        return await original_append_event(
            run_id,
            event_type,
            payload,
            actor_label=actor_label,
            timestamp=timestamp,
        )

    repository_any = cast(Any, repository)
    repository_any.append_event = _always_cancelling_append_event
    executor._handlers.register("writer", _WritingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )

    with pytest.raises(RuntimeError, match="terminal event persistence"):
        await asyncio.wait_for(executor.wait(run_id), timeout=2.0)
    with pytest.raises(RuntimeError, match="terminal event persistence"):
        await executor.wait(run_id)

    run = await repository.get_run(run_id)
    event_types = [event.event_type for event in repository.events[run_id]]

    assert run is not None
    assert run.status == RunStatus.RUNNING.value
    assert "pipeline.failed" in event_types
    assert "run.failed" not in event_types
    assert terminal_append_attempts >= 3
    assert run_id not in executor.active_tasks


async def test_terminal_append_post_commit_cancellation_reconciles_without_duplicate_event(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          missing [shape=box, handler="nonexistent_handler", prompt="run"]
          done [shape=Msquare]
          start -> task -> missing -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "failure.txt").write_text("failure trace", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    original_append_event = repository.append_event
    terminal_append_attempts = 0

    async def _post_commit_cancelling_append_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: Any | None = None,
    ) -> _FakeEvent:
        nonlocal terminal_append_attempts
        event = await original_append_event(
            run_id,
            event_type,
            payload,
            actor_label=actor_label,
            timestamp=timestamp,
        )
        if event_type == "run.failed":
            terminal_append_attempts += 1
            if terminal_append_attempts == 1:
                raise asyncio.CancelledError("terminal event persistence cancelled after commit")
        return event

    repository_any = cast(Any, repository)
    repository_any.append_event = _post_commit_cancelling_append_event
    executor._handlers.register("writer", _WritingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )

    result = await asyncio.wait_for(executor.wait(run_id), timeout=2.0)
    second_wait = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    terminal_events = [
        event for event in repository.events[run_id] if event.event_type == "run.failed"
    ]

    assert result.status == PipelineStatus.FAILED
    assert result.error is not None
    assert "nonexistent_handler" in result.error
    assert second_wait == result
    assert run is not None
    assert run.status == RunStatus.FAILED.value
    assert run.completed_at is not None
    assert run.error_category == "pipeline"
    assert run.error_message is not None
    assert "nonexistent_handler" in run.error_message
    assert terminal_append_attempts == 1
    assert len(terminal_events) == 1
    assert run_id not in executor.active_tasks


async def test_terminal_artifact_persistence_failure_is_cached_for_repeated_waits(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          missing [shape=box, handler="nonexistent_handler", prompt="run"]
          done [shape=Msquare]
          start -> task -> missing -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "failure.txt").write_text("failure trace", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    original_create_artifact = repository.create_artifact
    artifact_attempts = 0

    async def _failing_create_artifact(**kwargs: Any) -> _FakeArtifact:
        nonlocal artifact_attempts
        artifact_attempts += 1
        raise RuntimeError("artifact boom")

    repository_any = cast(Any, repository)
    repository_any.create_artifact = _failing_create_artifact
    executor._handlers.register("writer", _WritingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )

    with pytest.raises(RuntimeError, match="artifact boom") as first_error:
        await executor.wait(run_id)
    with pytest.raises(RuntimeError, match="artifact boom") as second_error:
        await executor.wait(run_id)

    run = await repository.get_run(run_id)
    event_types = [event.event_type for event in repository.events[run_id]]

    assert type(second_error.value) is type(first_error.value)
    assert str(second_error.value) == str(first_error.value)
    assert run is not None
    assert run.status == RunStatus.RUNNING.value
    assert "run.failed" not in event_types
    assert artifact_attempts >= 2
    assert run_id not in executor.active_tasks

    repository_any.create_artifact = original_create_artifact


async def test_terminal_artifact_retry_via_finalization_skips_already_persisted_artifacts(
    tmp_path: Path,
) -> None:
    executor, repository = _make_executor(tmp_path)
    logs_root = tmp_path / "artifacts" / "_runtime" / "run_partial_artifacts"
    logs_root.mkdir(parents=True)
    (logs_root / "alpha.txt").write_text("alpha", encoding="utf-8")
    (logs_root / "beta.txt").write_text("beta", encoding="utf-8")

    run_id = "run_partial_artifacts"
    await repository.create_run(
        run_id=run_id,
        repo_id="repo_test",
        workflow_id="wf_test",
        run_spec={},
        actor_label="tester",
        source_commit="deadbeef",
        source_branch="main",
        timestamp=None,
    )

    original_create_artifact = repository.create_artifact
    artifact_attempts: list[str] = []
    fail_on_beta = True

    async def _partially_failing_create_artifact(**kwargs: Any) -> _FakeArtifact:
        nonlocal fail_on_beta
        artifact_attempts.append(str(kwargs["name"]))
        if fail_on_beta and kwargs["name"] == "beta.txt":
            fail_on_beta = False
            raise RuntimeError("artifact boom")
        return await original_create_artifact(**kwargs)

    repository_any = cast(Any, repository)
    repository_any.create_artifact = _partially_failing_create_artifact

    failed_result = PipelineResult(status=PipelineStatus.FAILED, error="boom")

    async def _finalize_failed_result() -> PipelineResult:
        return await executor._record_terminal_result(
            run_id=run_id,
            run_spec=cast(Any, SimpleNamespace(actor_label="tester")),
            prepared=None,
            logs_root=logs_root,
            result=failed_result,
            terminal_event_type="run.failed",
            terminal_payload={"error": "boom"},
            error_category="RuntimeError",
            error_message="boom",
        )

    with pytest.raises(RuntimeError, match="artifact boom"):
        await executor._await_terminal_finalization(
            run_id=run_id,
            finalizer=_finalize_failed_result(),
        )

    with pytest.raises(RuntimeError, match="artifact boom"):
        await executor.wait(run_id)

    result = await executor._await_terminal_finalization(
        run_id=run_id,
        finalizer=_finalize_failed_result(),
    )
    second_wait = await executor.wait(run_id)

    assert result is failed_result
    assert second_wait is failed_result
    assert artifact_attempts == ["alpha.txt", "beta.txt", "beta.txt"]
    assert [artifact.name for artifact in repository.artifacts[run_id]] == [
        "alpha.txt",
        "beta.txt",
    ]


async def test_terminal_row_retry_does_not_duplicate_terminal_event_after_persist(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          missing [shape=box, handler="nonexistent_handler", prompt="run"]
          done [shape=Msquare]
          start -> task -> missing -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "failure.txt").write_text("failure trace", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    original_append_event = repository.append_event
    terminal_append_attempts = 0

    async def _tracking_append_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: Any | None = None,
    ) -> _FakeEvent:
        nonlocal terminal_append_attempts
        if event_type == "run.failed":
            terminal_append_attempts += 1
        return await original_append_event(
            run_id,
            event_type,
            payload,
            actor_label=actor_label,
            timestamp=timestamp,
        )

    original_update_run_record = executor._update_run_record
    terminal_update_attempts = 0

    async def _cancelling_terminal_update(
        run_id: str,
        *,
        status: RunStatus | None = None,
        worktree_path: str | None = None,
        managed_branch: str | None = None,
        started_at: Any | None = None,
        completed_at: Any | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        nonlocal terminal_update_attempts
        if status == RunStatus.FAILED and completed_at is not None:
            terminal_update_attempts += 1
            if terminal_update_attempts == 1:
                raise asyncio.CancelledError("terminal row update cancelled")
        await original_update_run_record(
            run_id,
            status=status,
            worktree_path=worktree_path,
            managed_branch=managed_branch,
            started_at=started_at,
            completed_at=completed_at,
            error_category=error_category,
            error_message=error_message,
        )

    repository_any = cast(Any, repository)
    repository_any.append_event = _tracking_append_event
    executor_any = cast(Any, executor)
    executor_any._update_run_record = _cancelling_terminal_update
    executor._handlers.register("writer", _WritingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )

    result = await asyncio.wait_for(executor.wait(run_id), timeout=2.0)
    second_wait = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    terminal_events = [
        event for event in repository.events[run_id] if event.event_type == "run.failed"
    ]

    assert result.status == PipelineStatus.FAILED
    assert result.error is not None
    assert "nonexistent_handler" in result.error
    assert second_wait == result
    assert run is not None
    assert run.status == RunStatus.FAILED.value
    assert run.completed_at is not None
    assert run.error_category == "pipeline"
    assert run.error_message is not None
    assert "nonexistent_handler" in run.error_message
    assert terminal_append_attempts == 1
    assert terminal_update_attempts == 2
    assert len(terminal_events) == 1
    assert run_id not in executor.active_tasks


async def test_terminal_retry_does_not_duplicate_artifact_after_post_commit_create(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          missing [shape=box, handler="nonexistent_handler", prompt="run"]
          done [shape=Msquare]
          start -> task -> missing -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "alpha.txt").write_text("alpha", encoding="utf-8")
            (logs_root / "beta.txt").write_text("beta", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    original_create_artifact = repository.create_artifact
    artifact_attempts: list[str] = []
    post_commit_failure_emitted = False

    async def _post_commit_failing_create_artifact(**kwargs: Any) -> _FakeArtifact:
        nonlocal post_commit_failure_emitted
        artifact_attempts.append(str(kwargs["name"]))
        artifact = await original_create_artifact(**kwargs)
        if kwargs["name"] == "beta.txt" and not post_commit_failure_emitted:
            post_commit_failure_emitted = True
            raise RuntimeError("artifact boom after commit")
        return artifact

    original_update_run_record = executor._update_run_record
    terminal_update_attempts = 0

    async def _cancelling_terminal_update(
        run_id: str,
        *,
        status: RunStatus | None = None,
        worktree_path: str | None = None,
        managed_branch: str | None = None,
        started_at: Any | None = None,
        completed_at: Any | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        nonlocal terminal_update_attempts
        if status == RunStatus.FAILED and completed_at is not None:
            terminal_update_attempts += 1
            if terminal_update_attempts == 1:
                raise asyncio.CancelledError("terminal row update cancelled")
        await original_update_run_record(
            run_id,
            status=status,
            worktree_path=worktree_path,
            managed_branch=managed_branch,
            started_at=started_at,
            completed_at=completed_at,
            error_category=error_category,
            error_message=error_message,
        )

    repository_any = cast(Any, repository)
    repository_any.create_artifact = _post_commit_failing_create_artifact
    executor_any = cast(Any, executor)
    executor_any._update_run_record = _cancelling_terminal_update
    executor._handlers.register("writer", _WritingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )

    result = await asyncio.wait_for(executor.wait(run_id), timeout=2.0)
    second_wait = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    artifact_names = [artifact.name for artifact in repository.artifacts[run_id]]

    assert result.status == PipelineStatus.FAILED
    assert result.error is not None
    assert "nonexistent_handler" in result.error
    assert second_wait == result
    assert run is not None
    assert run.status == RunStatus.FAILED.value
    assert artifact_attempts.count("alpha.txt") == 1
    assert artifact_attempts.count("beta.txt") == 1
    assert artifact_names.count("alpha.txt") == 1
    assert artifact_names.count("beta.txt") == 1
    assert terminal_update_attempts == 2
    assert run_id not in executor.active_tasks


async def test_external_cancellation_reaches_terminal_cancelled_state(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="blocker", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)
    started = asyncio.Event()

    class _BlockingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, logs_root, abort_signal
            started.set()
            await asyncio.sleep(60)
            return HandlerResult(status=Outcome.SUCCESS, output="unreachable")

    executor._handlers.register("blocker", _BlockingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    await asyncio.wait_for(started.wait(), timeout=2.0)

    executor.active_tasks[run_id].cancel()
    result = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    event_types = [event.event_type for event in repository.events[run_id]]

    assert result.status == PipelineStatus.CANCELLED
    assert run is not None
    assert run.status == RunStatus.CANCELLED.value
    assert "run.cancelled" in event_types
    assert run_id not in executor.active_tasks

    second_wait = await executor.wait(run_id)
    assert second_wait.status == PipelineStatus.CANCELLED


async def test_repeated_external_cancellation_still_records_terminal_cancelled_result(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="blocker", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)
    started = asyncio.Event()
    terminal_recording_started = asyncio.Event()
    allow_terminal_recording = asyncio.Event()

    class _BlockingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, logs_root, abort_signal
            started.set()
            await asyncio.sleep(60)
            return HandlerResult(status=Outcome.SUCCESS, output="unreachable")

    original_append_event = repository.append_event

    async def _blocking_append_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: Any | None = None,
    ) -> _FakeEvent:
        if event_type == "run.cancelled":
            terminal_recording_started.set()
            await allow_terminal_recording.wait()
        return await original_append_event(
            run_id,
            event_type,
            payload,
            actor_label=actor_label,
            timestamp=timestamp,
        )

    repository_any = cast(Any, repository)
    repository_any.append_event = _blocking_append_event
    executor._handlers.register("blocker", _BlockingHandler())

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    await asyncio.wait_for(started.wait(), timeout=2.0)

    wait_task = asyncio.create_task(executor.wait(run_id))
    executor.active_tasks[run_id].cancel()

    await asyncio.wait_for(terminal_recording_started.wait(), timeout=2.0)
    executor.active_tasks[run_id].cancel()
    allow_terminal_recording.set()

    result = await asyncio.wait_for(wait_task, timeout=2.0)
    run = await repository.get_run(run_id)
    event_types = [event.event_type for event in repository.events[run_id]]

    assert result.status == PipelineStatus.CANCELLED
    assert run is not None
    assert run.status == RunStatus.CANCELLED.value
    assert "run.cancelled" in event_types
    assert run_id not in executor.active_tasks

    second_wait = await executor.wait(run_id)
    assert second_wait.status == PipelineStatus.CANCELLED


async def test_checkpoint_failure_does_not_persist_orphaned_event_and_marks_run_failed(
    tmp_path: Path,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="writer", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        """,
    )
    executor, repository = _make_executor(tmp_path)

    class _WritingHandler:
        async def execute(self, node, context, graph, logs_root, abort_signal=None):
            del node, context, graph, abort_signal
            assert logs_root is not None
            (logs_root / "checkpoint.txt").write_text("checkpoint candidate", encoding="utf-8")
            return HandlerResult(status=Outcome.SUCCESS, output="ok")

    class _FailingCheckpointService:
        def create_checkpoint(self, **_: Any) -> GitCheckpoint:
            raise RuntimeError("checkpoint boom")

    executor._handlers.register("writer", _WritingHandler())
    executor_any: Any = executor
    executor_any._checkpoint_service = _FailingCheckpointService()

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    result = await executor.wait(run_id)
    run = await repository.get_run(run_id)
    event_types = [event.event_type for event in repository.events[run_id]]

    assert result.status == PipelineStatus.FAILED
    assert result.error is not None
    assert "checkpoint boom" in result.error
    assert run is not None
    assert run.status == RunStatus.FAILED.value
    assert "checkpoint.saved" not in event_types
    assert "run.failed" in event_types
    assert repository.checkpoints[run_id] == []
    assert run_id not in executor.active_tasks


async def test_executor_runs_workflow_in_worktree_and_persists_events(
    tmp_path: Path,
    platform_session_factory,
) -> None:
    repo_path = _init_repo_with_workflow(
        tmp_path,
        "release",
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="noop", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        """,
    )

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

    assert result.status == PipelineStatus.COMPLETED
    assert run is not None
    assert run.status == RunStatus.COMPLETED.value
    assert [event.event_type for event in events][0] == "run.queued"
    assert "pipeline.started" in [event.event_type for event in events]
    assert checkpoints
    assert run_id not in executor.active_tasks
