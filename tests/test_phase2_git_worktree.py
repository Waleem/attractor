from __future__ import annotations

import subprocess
from pathlib import Path

from attractor_platform.git import GitRunner, WorktreeManager


def make_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=path, check=True)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True)
    return path


def test_worktree_manager_creates_managed_branch_without_mutating_repo(tmp_path) -> None:
    repo_path = make_repo(tmp_path / "repo")
    root = tmp_path / "worktrees"
    manager = WorktreeManager(GitRunner(), root)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path, text=True).strip()

    prepared = manager.prepare(repo_path, run_id="run_abc", base_commit=base)
    (prepared.path / "generated.txt").write_text("created in worktree\n", encoding="utf-8")

    assert prepared.branch == "attractor/runs/run_abc"
    assert prepared.path.exists()
    assert not (repo_path / "generated.txt").exists()


def test_worktree_manager_refuses_dirty_registered_repo(tmp_path) -> None:
    repo_path = make_repo(tmp_path / "repo")
    (repo_path / "README.md").write_text("# dirty\n", encoding="utf-8")
    manager = WorktreeManager(GitRunner(), tmp_path / "worktrees")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path, text=True).strip()

    try:
        manager.prepare(repo_path, run_id="run_dirty", base_commit=base)
    except RuntimeError as exc:
        assert "dirty" in str(exc).lower()
    else:
        raise AssertionError("expected dirty repo failure")
