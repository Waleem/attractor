from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")
QUALIFIED_REF = re.compile(r"(^|/)refs/(heads|tags|remotes|notes|replace|bisect)/")
PROTECTED_BRANCHES = {"main", "master", "develop"}


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

    def promote_branch(
        self,
        repo_path: str | Path,
        *,
        worktree_path: str | Path,
        managed_branch: str,
        source_commit: str,
        target_branch: str,
        overwrite: bool = False,
        allow_protected: bool = False,
    ) -> str:
        repo = Path(repo_path).expanduser().resolve()
        worktree = Path(worktree_path).expanduser().resolve()
        if not repo.is_dir():
            raise RuntimeError(f"registered repo path is missing: {repo}")
        if not worktree.is_dir():
            raise RuntimeError(f"managed worktree path is missing: {worktree}")
        self._ensure_valid_branch_name(repo, managed_branch, label="managed branch")
        self._ensure_valid_branch_name(repo, target_branch, label="target branch")
        if self._is_protected_branch(target_branch) and not allow_protected:
            raise RuntimeError(f"target branch {target_branch!r} is protected")

        managed_commit = self._resolve_branch_commit(repo, managed_branch)
        worktree_commit = self.run(worktree, "rev-parse", "HEAD").stdout
        if worktree_commit != managed_commit:
            raise RuntimeError(
                "managed worktree HEAD does not match managed branch commit "
                f"{managed_branch!r}"
            )
        if not self._is_ancestor(repo, source_commit, managed_commit):
            raise RuntimeError(
                "managed branch is not based on RunSpec.source_commit "
                f"{source_commit}"
            )
        if self._branch_exists(repo, target_branch) and not overwrite:
            raise RuntimeError(f"target branch {target_branch!r} already exists")

        args = ["branch"]
        if overwrite:
            args.append("-f")
        args.extend([target_branch, managed_commit])
        self.run(repo, *args)
        return managed_commit

    def _ensure_valid_branch_name(self, repo_path: Path, branch: str, *, label: str) -> None:
        if not branch or not SAFE_REF.match(branch):
            raise RuntimeError(f"unsafe {label} name")
        if branch.startswith("refs/") or QUALIFIED_REF.search(branch):
            raise RuntimeError(f"invalid {label} name: {branch!r}")
        result = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"invalid {label} name: {branch!r}")

    def _is_protected_branch(self, branch: str) -> bool:
        return branch in PROTECTED_BRANCHES or branch.startswith("release/")

    def _resolve_branch_commit(self, repo_path: Path, branch: str) -> str:
        try:
            return self.run(
                repo_path,
                "rev-parse",
                "--verify",
                f"refs/heads/{branch}^{{commit}}",
            ).stdout
        except RuntimeError as exc:
            raise RuntimeError(
                f"managed branch {branch!r} is missing or cannot be resolved"
            ) from exc

    def _branch_exists(self, repo_path: Path, branch: str) -> bool:
        result = subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def _is_ancestor(self, repo_path: Path, ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True
        if result.returncode == 1:
            return False
        message = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"registered repo cannot resolve managed branch base: {message}")


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
        path = (self._root / run_id).resolve()
        try:
            path.relative_to(self._root)
        except ValueError as exc:
            raise RuntimeError("unsafe managed worktree path") from exc
        if not SAFE_REF.match(branch) or not self._is_valid_branch_name(repo, branch):
            raise RuntimeError("unsafe managed branch name")
        self._git.run(repo, "worktree", "add", "-b", branch, str(path), base_commit)
        return PreparedWorktree(repo_path=repo, path=path, branch=branch, base_commit=base_commit)

    def _is_valid_branch_name(self, repo_path: Path, branch: str) -> bool:
        result = subprocess.run(
            ["git", "check-ref-format", "--branch", branch],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
