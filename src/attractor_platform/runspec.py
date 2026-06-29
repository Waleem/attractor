"""Immutable run manifest for platform launches."""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

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


def _freeze_value(value: object) -> object:
    if isinstance(value, BaseModel):
        return _freeze_value(value.model_dump())
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_value(item) for item in value)
    return value


def _model_data(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump()
    return value


class FrozenRetentionPolicy(RetentionPolicy):
    """Immutable snapshot of retention policy values stored in a RunSpec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    keep_events_days: int = Field(default=30, ge=1)
    keep_artifacts_days: int = Field(default=30, ge=1)
    retain_workspace_on_failure: bool = False


class FrozenArtifactPolicy(ArtifactPolicy):
    """Immutable snapshot of artifact policy values stored in a RunSpec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    capture: tuple[str, ...] = ("logs", "patches", "summaries")
    max_bytes: int = Field(default=10_000_000, ge=1)


class FrozenWorkflowConfig(WorkflowConfig):
    """Immutable snapshot of workflow config values stored in a RunSpec."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    display_name: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    default_environment: str = ""
    inputs: Mapping[str, str] = Field(default_factory=dict)
    approval: Mapping[str, object] = Field(default_factory=dict)
    write_back: Mapping[str, object] = Field(default_factory=dict)
    retention: FrozenRetentionPolicy | None = None
    artifacts: FrozenArtifactPolicy | None = None

    @field_validator("retention", mode="before")
    @classmethod
    def _snapshot_retention(cls, value: object) -> object:
        return _model_data(value)

    @field_validator("artifacts", mode="before")
    @classmethod
    def _snapshot_artifacts(cls, value: object) -> object:
        return _model_data(value)

    @field_serializer("inputs", "approval", "write_back")
    def _serialize_mapping(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)

    @model_validator(mode="after")
    def _freeze_nested_values(self) -> FrozenWorkflowConfig:
        object.__setattr__(self, "inputs", cast(Mapping[str, str], _freeze_value(self.inputs)))
        object.__setattr__(
            self,
            "approval",
            cast(Mapping[str, object], _freeze_value(self.approval)),
        )
        object.__setattr__(
            self,
            "write_back",
            cast(Mapping[str, object], _freeze_value(self.write_back)),
        )
        return self


def _retention_snapshot(value: RetentionPolicy) -> FrozenRetentionPolicy:
    return FrozenRetentionPolicy.model_validate(value.model_dump())


def _artifact_policy_snapshot(value: ArtifactPolicy) -> FrozenArtifactPolicy:
    return FrozenArtifactPolicy.model_validate(value.model_dump())


def _workflow_config_snapshot(value: WorkflowConfig) -> FrozenWorkflowConfig:
    return FrozenWorkflowConfig.model_validate(value.model_dump())


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
    inputs: Mapping[str, str] = Field(default_factory=dict)
    actor_label: str = ""
    requested_environment: RunEnvironmentRequest = Field(default_factory=RunEnvironmentRequest)
    effective_environment: RunEnvironmentRequest = Field(default_factory=RunEnvironmentRequest)
    retention: RetentionPolicy
    artifact_policy: ArtifactPolicy
    approval_policy: Mapping[str, object] = Field(default_factory=dict)
    write_back_policy: Mapping[str, object] = Field(default_factory=dict)
    workflow_config: WorkflowConfig = Field(default_factory=WorkflowConfig)

    @field_serializer("inputs", "approval_policy", "write_back_policy")
    def _serialize_mapping(self, value: Mapping[str, object]) -> dict[str, object]:
        return dict(value)

    @model_validator(mode="after")
    def _freeze_nested_values(self) -> RunSpec:
        object.__setattr__(self, "retention", _retention_snapshot(self.retention))
        object.__setattr__(
            self,
            "artifact_policy",
            _artifact_policy_snapshot(self.artifact_policy),
        )
        object.__setattr__(
            self,
            "workflow_config",
            _workflow_config_snapshot(self.workflow_config),
        )
        object.__setattr__(self, "inputs", cast(Mapping[str, str], _freeze_value(self.inputs)))
        object.__setattr__(
            self,
            "approval_policy",
            cast(Mapping[str, object], _freeze_value(self.approval_policy)),
        )
        object.__setattr__(
            self,
            "write_back_policy",
            cast(Mapping[str, object], _freeze_value(self.write_back_policy)),
        )
        return self


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


def _requested_environment_record(
    package: WorkflowPackage,
    requested: str,
) -> RunEnvironmentRequest:
    raw = requested or "local"
    if raw == "local":
        return RunEnvironmentRequest(mode="local", name=raw)
    if raw == "docker":
        return RunEnvironmentRequest(mode="docker", name=raw)
    if raw == "remote":
        return RunEnvironmentRequest(mode="remote", name=raw)

    if raw in package.project_config.environments:
        env = package.project_config.environments[raw]
        return RunEnvironmentRequest(mode=env.mode, name=raw, image=env.image)

    return RunEnvironmentRequest(mode="local", name=raw)


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
    requested_environment_record = _requested_environment_record(package, requested_environment)

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
