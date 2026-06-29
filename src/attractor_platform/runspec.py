"""Immutable run manifest for platform launches."""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from attractor_platform.config import ArtifactPolicy, RetentionPolicy, WorkflowConfig
from attractor_platform.errors import GitMetadataError, RunSpecError
from attractor_platform.packages import WorkflowPackage


class DirtyState(StrEnum):
    """Git dirty-state captured at launch time."""

    CLEAN = "clean"
    DIRTY = "dirty"
    UNKNOWN = "unknown"


class RunEnvironmentRequest(BaseModel):
    """Requested or effective execution environment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    mode: Literal["local", "docker", "remote"] = "local"
    name: str = "local"
    image: str = ""


@dataclass(frozen=True)
class GitMetadata:
    """Source git metadata pinned into a RunSpec."""

    commit: str
    branch: str
    dirty_state: DirtyState


class RunSpec(BaseModel):
    """Immutable launch manifest for one workflow run."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    run_id: str = Field(default_factory=lambda: f"run_{uuid.uuid4().hex}")
    repo_id: str
    repo_path: Path
    workflow_name: str
    graph_name: str
    workflow_dot_path: Path
    workflow_toml_path: Path | None = None
    source_commit: str
    source_branch: str
    dirty_state: DirtyState
    inputs: dict[str, str] = Field(default_factory=dict)
    actor_label: str = ""
    requested_environment: RunEnvironmentRequest = Field(default_factory=RunEnvironmentRequest)
    effective_environment: RunEnvironmentRequest = Field(default_factory=RunEnvironmentRequest)
    retention: RetentionPolicy
    artifact_policy: ArtifactPolicy
    approval_policy: dict[str, object] = Field(default_factory=dict)
    write_back_policy: dict[str, object] = Field(default_factory=dict)
    workflow_config: WorkflowConfig = Field(default_factory=WorkflowConfig)


def _git(repo_path: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GitMetadataError(
            "Unable to read git metadata",
            detail={"repo_path": str(repo_path), "command": "git " + " ".join(args)},
        ) from exc
    return result.stdout.strip()


def read_git_metadata(repo_path: str | Path) -> GitMetadata:
    """Read commit, branch, and dirty-state for a local git repo."""
    repo = Path(repo_path).expanduser().resolve()
    commit = _git(repo, "rev-parse", "HEAD")
    branch = _git(repo, "branch", "--show-current") or "HEAD"
    status = _git(repo, "status", "--porcelain")
    dirty_state = DirtyState.DIRTY if status else DirtyState.CLEAN
    return GitMetadata(commit=commit, branch=branch, dirty_state=dirty_state)


def _environment_request(package: WorkflowPackage, selected: str) -> RunEnvironmentRequest:
    project = package.project_config

    if selected in project.environments:
        env = project.environments[selected]
        if env.mode not in project.allowed_execution_modes:
            raise RunSpecError(
                "Requested environment is not allowed by project config",
                detail={
                    "workflow": package.name,
                    "requested_environment": selected,
                    "allowed_execution_modes": list(project.allowed_execution_modes),
                },
            )
        return RunEnvironmentRequest(mode=env.mode, name=selected, image=env.image)

    if selected not in project.allowed_execution_modes:
        raise RunSpecError(
            "Requested environment is not allowed by project config",
            detail={
                "workflow": package.name,
                "requested_environment": selected,
                "allowed_execution_modes": list(project.allowed_execution_modes),
            },
        )

    return RunEnvironmentRequest(mode=selected, name=selected)


def _resolve_environment(package: WorkflowPackage, requested: str) -> RunEnvironmentRequest:
    project = package.project_config
    workflow = package.workflow_config
    selected = requested or workflow.default_environment or project.default_environment
    return _environment_request(package, selected)


def build_run_spec(
    package: WorkflowPackage,
    *,
    inputs: dict[str, str] | None = None,
    actor_label: str = "",
    requested_environment: str = "",
) -> RunSpec:
    """Build an immutable `RunSpec` from a loaded workflow package."""
    if package.graph is None:
        raise RunSpecError(
            "Cannot build RunSpec for invalid workflow package",
            detail={"workflow": package.name},
        )

    metadata = read_git_metadata(package.repo_path)
    effective_environment = _resolve_environment(package, requested_environment)
    requested_environment_record = _environment_request(
        package,
        requested_environment or "local",
    )

    return RunSpec(
        repo_id=f"local:{package.repo_path}",
        repo_path=package.repo_path,
        workflow_name=package.name,
        graph_name=package.graph.name,
        workflow_dot_path=package.dot_path,
        workflow_toml_path=package.toml_path,
        source_commit=metadata.commit,
        source_branch=metadata.branch,
        dirty_state=metadata.dirty_state,
        inputs=inputs or {},
        actor_label=actor_label,
        requested_environment=requested_environment_record,
        effective_environment=effective_environment,
        retention=package.workflow_config.retention or package.project_config.retention,
        artifact_policy=package.workflow_config.artifacts or package.project_config.artifacts,
        approval_policy=package.workflow_config.approval,
        write_back_policy=package.workflow_config.write_back,
        workflow_config=package.workflow_config,
    )
