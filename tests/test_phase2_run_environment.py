from __future__ import annotations

import asyncio

import pytest

from attractor_agent.environment import LocalEnvironment
from attractor_agent.tools.core import get_allowed_roots, get_environment
from attractor_platform.git import PreparedWorktree
from attractor_platform.run_environment import WorktreeLocalRunEnvironment


def prepared_worktree(tmp_path, run_id: str) -> PreparedWorktree:
    path = tmp_path / run_id
    path.mkdir(parents=True)
    return PreparedWorktree(
        repo_path=tmp_path / "repo",
        path=path,
        branch=f"attractor/runs/{run_id}",
        base_commit="1" * 40,
    )


@pytest.mark.asyncio
async def test_worktree_local_environment_installs_local_environment(tmp_path) -> None:
    prepared = prepared_worktree(tmp_path, "run-1")
    run_environment = WorktreeLocalRunEnvironment(prepared)

    async with run_environment.activate() as execution_env:
        assert isinstance(execution_env, LocalEnvironment)
        assert await execution_env.working_directory() == str(prepared.path)
        assert get_environment() is execution_env
        assert get_allowed_roots() == [prepared.path.resolve()]


@pytest.mark.asyncio
async def test_worktree_environment_is_task_local_for_concurrent_runs(tmp_path) -> None:
    prepared_one = prepared_worktree(tmp_path, "run-1")
    prepared_two = prepared_worktree(tmp_path, "run-2")

    async def capture(prepared: PreparedWorktree) -> tuple[str, list, object]:
        run_environment = WorktreeLocalRunEnvironment(prepared)
        async with run_environment.activate() as _:
            await asyncio.sleep(0)
            return (
                await get_environment().working_directory(),
                get_allowed_roots(),
                get_environment(),
            )

    first_result, second_result = await asyncio.gather(
        asyncio.create_task(capture(prepared_one)),
        asyncio.create_task(capture(prepared_two)),
    )

    assert first_result[0] == str(prepared_one.path)
    assert first_result[1] == [prepared_one.path.resolve()]
    assert first_result[2] is not second_result[2]

    assert second_result[0] == str(prepared_two.path)
    assert second_result[1] == [prepared_two.path.resolve()]
