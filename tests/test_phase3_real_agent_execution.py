from __future__ import annotations

import os
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import select

from attractor_agent.abort import AbortSignal
from attractor_agent.tools.core import get_environment
from attractor_pipeline.engine.runner import PipelineStatus
from attractor_pipeline.graph import Node
from attractor_platform.executor import CODERGEN_OUTPUT_PREVIEW_MAX_CHARS, DurableRunExecutor
from attractor_platform.storage.db import create_session_factory, default_test_database_url
from attractor_platform.storage.models import ArtifactModel, Base, RunStatus

pytestmark = pytest.mark.asyncio


class RecordingCodergenBackend:
    def __init__(self) -> None:
        self.invocations: list[str] = []

    async def run(
        self,
        node: Node,
        prompt: str,
        context: dict[str, Any],
        abort_signal: AbortSignal | None = None,
    ) -> str:
        del prompt, context, abort_signal
        self.invocations.append(node.id)
        working_directory = Path(await get_environment().working_directory())
        (working_directory / "agent-output.txt").write_text(
            "fake codergen wrote this\n",
            encoding="utf-8",
        )
        return "fake codergen completed"


class LongOutputCodergenBackend:
    async def run(
        self,
        node: Node,
        prompt: str,
        context: dict[str, Any],
        abort_signal: AbortSignal | None = None,
    ) -> str:
        del node, prompt, context, abort_signal
        return (
            "visible fake codergen output\n"
            + ("x" * CODERGEN_OUTPUT_PREVIEW_MAX_CHARS)
            + "tail that must not persist"
        )


@pytest_asyncio.fixture
async def platform_session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get(
        "ATTRACTOR_TEST_DATABASE_URL",
        default_test_database_url(tmp_path / "platform.sqlite3"),
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


def _init_codergen_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)
    workflow_dir = repo_path / ".attractor" / "workflows" / "real-agent"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(
        """
        digraph RealAgent {
          graph [goal="write a file using the real agent handler path"]
          start [shape=Mdiamond]
          generate [shape=box, handler="codergen", prompt="Write agent-output.txt"]
          done [shape=Msquare]
          start -> generate -> done
        }
        """,
        encoding="utf-8",
    )
    (repo_path / ".attractor" / "project.toml").write_text(
        'default_environment = "local"\nallowed_execution_modes = ["local"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


async def test_durable_executor_runs_codergen_backend_without_provider_keys(
    tmp_path: Path,
    platform_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    repo_path = _init_codergen_repo(tmp_path)
    backend = RecordingCodergenBackend()
    executor = DurableRunExecutor.for_tests(
        session_factory=platform_session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
        codergen_backend=backend,
    )

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="real-agent",
        actor_label="tester",
        inputs={},
    )
    result = await executor.wait(run_id)
    run = await executor.repository.get_run(run_id)
    events = await executor.repository.list_events(run_id, after_sequence=0, limit=100)
    async with platform_session_factory() as session:
        artifacts = list(
            await session.scalars(
                select(ArtifactModel)
                .where(ArtifactModel.run_id == run_id)
                .order_by(ArtifactModel.kind, ArtifactModel.name)
            )
        )

    assert result.status == PipelineStatus.COMPLETED
    assert backend.invocations == ["generate"]
    assert run is not None
    assert run.status == RunStatus.COMPLETED.value
    assert run.managed_branch
    assert [event.event_type for event in events][0] == "run.queued"
    assert "pipeline.completed" in {event.event_type for event in events}
    assert any(
        event.event_type == "run.completed"
        and event.payload.get("outputs", {}).get("codergen.generate.output")
        == "fake codergen completed"
        for event in events
    )
    response_artifact = next(
        artifact for artifact in artifacts if artifact.kind == "generate" and artifact.name == "response.md"
    )
    assert executor._artifact_store.read_bytes(response_artifact.uri) == b"fake codergen completed"

    promoted_content = subprocess.run(
        ["git", "show", f"{run.managed_branch}:agent-output.txt"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert promoted_content == "fake codergen wrote this\n"
    assert (repo_path / "agent-output.txt").exists() is False


async def test_run_completed_bounds_long_codergen_output_evidence(
    tmp_path: Path,
    platform_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    repo_path = _init_codergen_repo(tmp_path)
    executor = DurableRunExecutor.for_tests(
        session_factory=platform_session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
        codergen_backend=LongOutputCodergenBackend(),
    )

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="real-agent",
        actor_label="tester",
        inputs={},
    )
    result = await executor.wait(run_id)
    events = await executor.repository.list_events(run_id, after_sequence=0, limit=100)
    completed_payload = next(
        event.payload for event in events if event.event_type == "run.completed"
    )
    output_evidence = completed_payload["outputs"]["codergen.generate.output"]

    assert result.status == PipelineStatus.COMPLETED
    assert output_evidence.startswith("visible fake codergen output")
    assert "tail that must not persist" not in output_evidence
    assert "[truncated" in output_evidence
    assert len(output_evidence) <= CODERGEN_OUTPUT_PREVIEW_MAX_CHARS + 128
