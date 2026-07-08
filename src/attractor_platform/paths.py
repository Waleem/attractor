from __future__ import annotations

import os
from pathlib import Path


def default_platform_data_dir() -> Path:
    if os.environ.get("ATTRACTOR_RUNNING_IN_DOCKER") or Path("/data").is_dir():
        return Path("/data/attractor")
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    return (Path(xdg) if xdg else Path.home() / ".local" / "share") / "attractor"


def default_worktree_root() -> Path:
    return default_platform_data_dir() / "worktrees"


def default_artifact_root() -> Path:
    return default_platform_data_dir() / "artifacts"


def resolve_platform_roots(
    worktree_arg: str | None, artifact_arg: str | None
) -> tuple[Path, Path]:
    worktree_root = worktree_arg or os.environ.get("ATTRACTOR_WORKTREE_ROOT", "").strip()
    artifact_root = artifact_arg or os.environ.get("ATTRACTOR_ARTIFACT_ROOT", "").strip()

    return (
        Path(worktree_root) if worktree_root else default_worktree_root(),
        Path(artifact_root) if artifact_root else default_artifact_root(),
    )
