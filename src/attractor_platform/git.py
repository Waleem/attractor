from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str


class GitRunner:
    def run(self, repo_path: str | Path, *args: str) -> GitResult:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return GitResult(stdout=result.stdout.strip(), stderr=result.stderr.strip())

    def commit(self, repo_path: str | Path) -> str:
        return self.run(repo_path, "rev-parse", "HEAD").stdout

    def status_porcelain(self, repo_path: str | Path) -> str:
        return self.run(repo_path, "status", "--porcelain").stdout


@dataclass(frozen=True)
class PreparedWorktree:
    repo_path: Path
    path: Path
    branch: str
    base_commit: str


class WorktreeManager:
    def __init__(self, git: GitRunner, root: str | Path) -> None:
        self._git = git
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def prepare(self, repo_path: str | Path, *, run_id: str, base_commit: str) -> PreparedWorktree:
        repo = Path(repo_path).expanduser().resolve()
        if self._git.status_porcelain(repo):
            raise RuntimeError("registered repo is dirty; must be clean before server worktree run")
        if self._git.commit(repo) != base_commit:
            raise RuntimeError(
                "base mismatch: registered repo HEAD does not match RunSpec source commit"
            )
        branch = f"attractor/runs/{run_id}"
        if (
            not SAFE_REF.match(branch)
            or ".." in branch
            or branch.startswith("/")
            or branch.endswith("/")
        ):
            raise RuntimeError("unsafe managed branch name")
        path = (self._root / run_id).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise RuntimeError("unsafe managed worktree path") from exc
        self._git.run(repo, "worktree", "add", "-b", branch, str(path), base_commit)
        return PreparedWorktree(repo_path=repo, path=path, branch=branch, base_commit=base_commit)
