from __future__ import annotations

import datetime as dt
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from attractor_platform.git import GitResult, GitRunner
from attractor_platform.storage.models import RunStatus
from tests.test_phase3_console_api_contracts import (
    _Harness,
    _git_commit,
    _register_repo,
    platform_harness,
    sample_repo,
)

pytestmark = pytest.mark.asyncio


@dataclass
class _Artifact:
    id: str
    run_id: str
    kind: str
    name: str
    uri: str
    media_type: str
    size_bytes: int
    sha256: str
    created_at: dt.datetime


class _PatchLimitGitRunner(GitRunner):
    def __init__(self, changed_file_count: int) -> None:
        self.changed_file_count = changed_file_count
        self.patch_calls: list[str] = []

    def run(self, repo_path: str | Path, *args: str) -> GitResult:
        if args == ("rev-parse", "HEAD"):
            return GitResult(stdout="head-commit", stderr="")
        if args == ("rev-parse", "run-branch"):
            return GitResult(stdout="head-commit", stderr="")
        if args[:3] == ("diff", "--name-only", "--find-renames"):
            return GitResult(
                stdout="\n".join(
                    f"file_{index:03d}.txt" for index in range(self.changed_file_count)
                ),
                stderr="",
            )
        if args[:3] == ("diff", "--name-status", "--find-renames"):
            path = args[-1]
            return GitResult(stdout=f"M\t{path}", stderr="")
        if args[:3] == ("diff", "--numstat", "--find-renames"):
            path = args[-1]
            return GitResult(stdout=f"1\t0\t{path}", stderr="")
        if args[:3] == ("diff", "--find-renames", "--unified=80"):
            path = args[-1]
            self.patch_calls.append(path)
            return GitResult(stdout=f"diff --git a/{path} b/{path}\n+hello\n", stderr="")
        raise AssertionError(f"Unexpected git args: {args!r}")


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


async def test_run_diff_include_patch_caps_file_count(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    create_response = await platform_harness.client.post(
        "/api/runs",
        json={"repo_path": str(sample_repo), "workflow_name": "release", "actor_label": "alice"},
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]
    run = platform_harness.repository.runs[run_id]
    run.status = RunStatus.COMPLETED.value
    fake_worktree = sample_repo / "run-owned-worktree"
    fake_worktree.mkdir()
    run.worktree_path = str(fake_worktree)
    run.managed_branch = "run-branch"
    git = _PatchLimitGitRunner(changed_file_count=75)
    platform_harness.executor.git = git

    response = await platform_harness.client.get(
        f"/api/runs/{run_id}/diff",
        params={"include_patch": "true", "limit": "500"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is True
    assert len(body["files"]) == 50
    assert len(git.patch_calls) == 50
    assert all("patch" in file_row for file_row in body["files"])


async def test_artifact_download_rejects_file_uri_outside_artifact_root(
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
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("secret\n", encoding="utf-8")
    platform_harness.executor._artifact_root = artifact_root
    platform_harness.repository.artifacts = {
        run_id: [
            _Artifact(
                id="artifact_outside",
                run_id=run_id,
                kind="logs",
                name="outside.txt",
                uri=outside_file.as_uri(),
                media_type="text/plain",
                size_bytes=7,
                sha256="a" * 64,
                created_at=dt.datetime.now(dt.UTC),
            )
        ]
    }

    response = await platform_harness.client.get(
        f"/api/runs/{run_id}/artifacts/artifact_outside"
    )

    assert response.status_code == 403


async def test_artifact_download_rejects_nonlocal_file_uri(
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
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    platform_harness.executor._artifact_root = artifact_root
    platform_harness.repository.artifacts = {
        run_id: [
            _Artifact(
                id="artifact_etc",
                run_id=run_id,
                kind="logs",
                name="passwd",
                uri="file://evil.example/etc/passwd",
                media_type="text/plain",
                size_bytes=12,
                sha256="b" * 64,
                created_at=dt.datetime.now(dt.UTC),
            )
        ]
    }

    response = await platform_harness.client.get(f"/api/runs/{run_id}/artifacts/artifact_etc")

    assert response.status_code == 403
