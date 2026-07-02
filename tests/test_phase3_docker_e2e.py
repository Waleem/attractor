from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from attractor_agent.tools.core import _read_file, _write_file, get_environment
from attractor_pipeline.engine.runner import HandlerResult, Outcome, PipelineStatus
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import create_session_factory, default_test_database_url
from attractor_platform.storage.models import Base, RunStatus

pytestmark = pytest.mark.asyncio

DOCKER_IMAGE = "python:3.12-slim"


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


class _DockerWorkspaceWriter:
    async def execute(
        self,
        node: Any,
        context: dict[str, Any],
        graph: Any,
        logs_root: Path | None,
        abort_signal: Any | None = None,
    ) -> HandlerResult:
        del node, context, graph, abort_signal

        workspace = await get_environment().working_directory()
        seed = await _read_file("seed.txt")
        await _write_file("generated/task7.txt", f"{workspace}\n{seed}")

        if logs_root is not None:
            logs_root.mkdir(parents=True, exist_ok=True)
            (logs_root / "docker-handler.txt").write_text(
                f"workspace={workspace}\nseed={seed}",
                encoding="utf-8",
            )

        return HandlerResult(
            status=Outcome.SUCCESS,
            output=f"wrote generated/task7.txt from {workspace}",
            context_updates={"docker_workspace": workspace, "docker_seed": seed},
        )


def _require_docker_image(image: str) -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker CLI unavailable; skipping Docker E2E")

    info = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    if info.returncode != 0:
        reason = (info.stderr or info.stdout).strip() or "docker info failed"
        pytest.skip(f"Docker daemon unavailable; skipping Docker E2E: {reason}")

    inspect = subprocess.run(
        ["docker", "image", "inspect", image],
        capture_output=True,
        text=True,
        check=False,
    )
    if inspect.returncode != 0:
        pytest.skip(f"Docker image {image!r} unavailable locally; skipping Docker E2E")


def _init_docker_workflow_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)

    attractor_dir = repo_path / ".attractor"
    workflow_dir = attractor_dir / "workflows" / "docker-write"
    workflow_dir.mkdir(parents=True)
    (repo_path / "seed.txt").write_text("seed-from-registered-repo", encoding="utf-8")
    (attractor_dir / "project.toml").write_text(
        "\n".join(
            [
                'default_environment = "docker"',
                'allowed_execution_modes = ["local", "docker"]',
                "",
                "[environments.docker]",
                'mode = "docker"',
                f'image = "{DOCKER_IMAGE}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (workflow_dir / "workflow.dot").write_text(
        """
        digraph DockerWrite {
          graph [goal="write in docker workspace"]
          start [shape=Mdiamond]
          write [shape=parallelogram, handler="docker_workspace_writer"]
          done [shape=Msquare]
          start -> write -> done
        }
        """,
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


async def test_docker_run_uses_prepared_worktree_and_persists_outputs(
    tmp_path: Path,
    platform_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _require_docker_image(DOCKER_IMAGE)
    repo_path = _init_docker_workflow_repo(tmp_path)

    executor = DurableRunExecutor.for_tests(
        session_factory=platform_session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    executor._handlers.register("docker_workspace_writer", _DockerWorkspaceWriter())

    before_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="docker-write",
        actor_label="docker-e2e",
        inputs={},
        requested_environment="docker",
    )
    result = await executor.wait(run_id)

    run = await executor.repository.get_run(run_id)
    events = await executor.repository.list_events(run_id, after_sequence=0, limit=100)
    artifacts = await executor.repository.list_artifacts(run_id)
    checkpoints = await executor.repository.list_checkpoints(run_id)
    after_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    assert result.status == PipelineStatus.COMPLETED
    assert run is not None
    assert run.status == RunStatus.COMPLETED.value
    assert run.run_spec["effective_environment"] == {
        "mode": "docker",
        "name": "docker",
        "image": DOCKER_IMAGE,
    }
    assert [event.event_type for event in events][0] == "run.queued"
    assert "run.started" in [event.event_type for event in events]
    assert "pipeline.completed" in [event.event_type for event in events]
    assert checkpoints
    assert artifacts
    assert any(artifact.name == "docker-handler.txt" for artifact in artifacts)

    managed_output = Path(run.worktree_path) / "generated" / "task7.txt"
    assert managed_output.read_text(encoding="utf-8") == (
        "/workspace\nseed-from-registered-repo"
    )
    assert (repo_path / "generated" / "task7.txt").exists() is False
    assert before_status == ""
    assert after_status == ""
