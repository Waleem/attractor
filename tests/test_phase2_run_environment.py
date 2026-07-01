from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from attractor_agent.environment import LocalEnvironment, ShellResult
from attractor_agent.tools.core import (
    _read_file,
    _shell,
    _write_file,
    get_allowed_roots,
    get_environment,
    reset_allowed_roots,
    reset_environment,
    set_allowed_roots,
    set_environment,
)
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


class StubContainerEnvironment:
    def __init__(self, working_dir: str = "/workspace/run-1") -> None:
        self._working_dir = working_dir
        self.writes: dict[str, str] = {}
        self.shell_working_dirs: list[str | None] = []

    async def read_file(self, path: str) -> str:
        return self.writes[path]

    async def write_file(self, path: str, content: str) -> None:
        self.writes[path] = content

    async def file_exists(self, path: str) -> bool:
        return path in self.writes

    async def is_file(self, path: str) -> bool:
        return path in self.writes

    async def mkdir(self, path: str) -> None:
        return None

    async def exec_shell(
        self,
        command: str,
        timeout: int = 120,
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ShellResult:
        del command, timeout, env
        self.shell_working_dirs.append(working_dir)
        return ShellResult(stdout=f"{working_dir}\n", stderr="", returncode=0)

    async def glob(self, pattern: str, path: str = ".") -> list[str]:
        del pattern, path
        return []

    async def list_dir(self, path: str) -> list[str]:
        del path
        return []

    async def working_directory(self) -> str:
        return self._working_dir

    def platform(self) -> str:
        return "docker"

    def os_version(self) -> str:
        return "docker"

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


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
async def test_worktree_local_environment_tools_use_worktree_cwd(tmp_path) -> None:
    prepared = prepared_worktree(tmp_path, "run-1")
    run_environment = WorktreeLocalRunEnvironment(prepared)

    async with run_environment.activate():
        await _write_file("note.txt", "hello")

        assert (prepared.path / "note.txt").read_text() == "hello"
        assert "hello" in await _read_file("note.txt")
        assert (await _shell("pwd")).strip() == str(prepared.path)


@pytest.mark.asyncio
async def test_non_local_environment_preserves_container_relative_paths() -> None:
    environment = StubContainerEnvironment()
    environment_token = set_environment(environment)
    roots_token = set_allowed_roots(["/workspace", "/tmp"])
    try:
        await _write_file("note.txt", "hello")

        assert environment.writes["/workspace/run-1/note.txt"] == "hello"
        assert "hello" in await _read_file("note.txt")
        assert (await _shell("pwd")).strip() == "/workspace/run-1"
        assert environment.shell_working_dirs == ["/workspace/run-1"]
    finally:
        reset_allowed_roots(roots_token)
        reset_environment(environment_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed_roots", [["/workspace"], ["/workspace/run-1"]])
async def test_non_local_environment_rejects_parent_traversal_for_file_paths(
    allowed_roots: list[str | Path],
) -> None:
    environment = StubContainerEnvironment()
    environment_token = set_environment(environment)
    roots_token = set_allowed_roots(allowed_roots)
    try:
        with pytest.raises(PermissionError, match="outside allowed directories"):
            await _write_file("../../etc/passwd", "x")

        assert environment.writes == {}
    finally:
        reset_allowed_roots(roots_token)
        reset_environment(environment_token)


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed_roots", [["/workspace"], ["/workspace/run-1"]])
async def test_non_local_environment_rejects_parent_traversal_for_shell_working_dir(
    allowed_roots: list[str | Path],
) -> None:
    environment = StubContainerEnvironment()
    environment_token = set_environment(environment)
    roots_token = set_allowed_roots(allowed_roots)
    try:
        with pytest.raises(PermissionError, match="Shell working_dir outside allowed roots"):
            await _shell("pwd", working_dir="../../etc")

        assert environment.shell_working_dirs == []
    finally:
        reset_allowed_roots(roots_token)
        reset_environment(environment_token)


@pytest.mark.asyncio
async def test_worktree_local_environment_restores_previous_state_after_exit(tmp_path) -> None:
    prepared = prepared_worktree(tmp_path, "run-1")
    custom_root = tmp_path / "custom-root"
    custom_root.mkdir()
    custom_env = LocalEnvironment(working_dir=str(custom_root))

    environment_token = set_environment(custom_env)
    roots_token = set_allowed_roots([custom_root])
    try:
        async with WorktreeLocalRunEnvironment(prepared).activate() as execution_env:
            assert get_environment() is execution_env
            assert get_allowed_roots() == [prepared.path.resolve()]

        assert get_environment() is custom_env
        assert get_allowed_roots() == [custom_root.resolve()]
    finally:
        reset_allowed_roots(roots_token)
        reset_environment(environment_token)


@pytest.mark.asyncio
async def test_worktree_environment_is_task_local_for_concurrent_runs(tmp_path) -> None:
    prepared_one = prepared_worktree(tmp_path, "run-1")
    prepared_two = prepared_worktree(tmp_path, "run-2")
    ready_count = 0
    ready_lock = asyncio.Lock()
    both_ready = asyncio.Event()
    release = asyncio.Event()

    async def capture(prepared: PreparedWorktree) -> tuple[str, list, object, object]:
        nonlocal ready_count
        run_environment = WorktreeLocalRunEnvironment(prepared)
        async with run_environment.activate() as execution_env:
            async with ready_lock:
                ready_count += 1
                if ready_count == 2:
                    both_ready.set()
            await both_ready.wait()
            await release.wait()
            return (
                await get_environment().working_directory(),
                get_allowed_roots(),
                get_environment(),
                execution_env,
            )

    first_task = asyncio.create_task(capture(prepared_one))
    second_task = asyncio.create_task(capture(prepared_two))

    await both_ready.wait()
    release.set()

    first_result, second_result = await asyncio.gather(first_task, second_task)

    assert first_result[0] == str(prepared_one.path)
    assert first_result[1] == [prepared_one.path.resolve()]
    assert first_result[2] is first_result[3]
    assert first_result[2] is not second_result[2]

    assert second_result[0] == str(prepared_two.path)
    assert second_result[1] == [prepared_two.path.resolve()]
    assert second_result[2] is second_result[3]
