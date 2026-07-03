from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from attractor_platform.storage.models import RunStatus
from tests.test_phase3_console_api_contracts import (
    _Harness,
    _git_commit,
    _register_repo,
    platform_harness,
    sample_repo,
)

pytestmark = pytest.mark.asyncio


async def test_run_diff_includes_bounded_patch_content(
    platform_harness: _Harness,
    sample_repo: Path,
    tmp_path: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    create_response = await platform_harness.client.post(
        "/api/runs",
        json={"repo_path": str(sample_repo), "workflow_name": "release", "actor_label": "alice"},
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]
    source_commit = platform_harness.repository.runs[run_id].source_commit
    worktree_path = tmp_path / "run-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "run-branch", str(worktree_path), source_commit],
        cwd=sample_repo,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    (worktree_path / "HELLO.md").write_text("hello\n", encoding="utf-8")
    _git_commit(worktree_path, "add hello")
    run = platform_harness.repository.runs[run_id]
    run.status = RunStatus.COMPLETED.value
    run.worktree_path = str(worktree_path)
    run.managed_branch = "run-branch"

    response = await platform_harness.client.get(
        f"/api/runs/{run_id}/diff",
        params={"include_patch": "true"},
    )

    assert response.status_code == 200
    file_row = response.json()["files"][0]
    assert file_row["path"] == "HELLO.md"
    assert file_row["patch"].startswith("diff --git")
    assert "+hello" in file_row["patch"]
    assert len(file_row["patch"]) <= 60_000
    assert file_row["patch_truncated"] is False
