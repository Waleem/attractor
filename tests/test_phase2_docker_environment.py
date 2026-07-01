from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from attractor_agent.environment import DockerEnvironment
from attractor_agent.tools.core import get_allowed_roots
from attractor_pipeline.engine.runner import PipelineStatus
from attractor_platform.git import PreparedWorktree
from attractor_platform.run_environment import (
    DockerRunEnvironment,
    WorktreeLocalRunEnvironment,
    select_run_environment,
)
from attractor_platform.runspec import RunEnvironmentRequest
from tests.test_phase2_executor import _init_repo_with_workflow, _make_executor


def prepared_worktree(tmp_path: Path, run_id: str) -> PreparedWorktree:
    path = tmp_path / run_id
    path.mkdir(parents=True)
    return PreparedWorktree(
        repo_path=tmp_path / "repo",
        path=path,
        branch=f"attractor/runs/{run_id}",
        base_commit="1" * 40,
    )


def test_select_docker_run_environment() -> None:
    env = select_run_environment(
        RunEnvironmentRequest(mode="docker", name="docker", image="python:3.12-slim"),
        prepared_worktree=None,
    )

    assert isinstance(env, DockerRunEnvironment)


def test_select_docker_run_environment_uses_default_image() -> None:
    env = select_run_environment(
        RunEnvironmentRequest(mode="docker", name="docker"),
        prepared_worktree=None,
    )

    assert isinstance(env, DockerRunEnvironment)
    assert env._image == "python:3.12-slim"


def test_select_local_run_environment_requires_prepared_worktree() -> None:
    with pytest.raises(ValueError, match="prepared worktree"):
        select_run_environment(
            RunEnvironmentRequest(mode="local", name="local"),
            prepared_worktree=None,
        )


def test_select_local_run_environment_returns_worktree_local_environment(tmp_path: Path) -> None:
    prepared = prepared_worktree(tmp_path, "run-1")

    env = select_run_environment(
        RunEnvironmentRequest(mode="local", name="local"),
        prepared_worktree=prepared,
    )

    assert isinstance(env, WorktreeLocalRunEnvironment)


def test_select_remote_run_environment_raises() -> None:
    with pytest.raises(ValueError, match="remote run environments are not implemented"):
        select_run_environment(
            RunEnvironmentRequest(mode="remote", name="remote"),
            prepared_worktree=None,
        )


@pytest.mark.asyncio
async def test_docker_run_environment_uses_container_allowed_roots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _start(self: DockerEnvironment) -> None:
        del self

    async def _stop(self: DockerEnvironment) -> None:
        del self

    monkeypatch.setattr(DockerEnvironment, "start", _start)
    monkeypatch.setattr(DockerEnvironment, "stop", _stop)

    async with DockerRunEnvironment("python:3.12-slim").activate():
        roots = [str(root) for root in get_allowed_roots()]

    assert roots == ["/workspace", "/tmp"]
    assert "/private/tmp" not in roots


@pytest.mark.asyncio
async def test_executor_prepares_worktree_for_docker_run_without_starting_docker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
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
    (repo_path / ".attractor" / "project.toml").write_text(
        'default_environment = "docker"\nallowed_execution_modes = ["local", "docker"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", ".attractor/project.toml"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "add docker config"], cwd=repo_path, check=True)
    executor, repository = _make_executor(tmp_path)
    selected_requests: list[RunEnvironmentRequest] = []
    selected_worktrees: list[PreparedWorktree | None] = []

    class _FakeRunEnvironment:
        @asynccontextmanager
        async def activate(self) -> AsyncIterator[Any]:
            yield object()

    def _select_run_environment(
        request: RunEnvironmentRequest,
        prepared_worktree: PreparedWorktree | None,
    ) -> _FakeRunEnvironment:
        selected_requests.append(request)
        selected_worktrees.append(prepared_worktree)
        return _FakeRunEnvironment()

    monkeypatch.setattr(
        "attractor_platform.executor.select_run_environment",
        _select_run_environment,
    )

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    result = await executor.wait(run_id)
    run = await repository.get_run(run_id)

    assert result.status == PipelineStatus.COMPLETED
    assert selected_requests == [RunEnvironmentRequest(mode="docker", name="docker")]
    assert selected_worktrees and selected_worktrees[0] is not None
    assert run is not None
    assert run.worktree_path == str(selected_worktrees[0].path)
    assert run.managed_branch == selected_worktrees[0].branch
