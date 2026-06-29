"""Repo-local platform configuration models."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from attractor_platform.errors import ConfigLoadError

ExecutionMode = Literal["local", "docker", "remote"]


class RetentionPolicy(BaseModel):
    """Retention choices for run traces, artifacts, and workspaces."""

    model_config = ConfigDict(extra="forbid")

    keep_events_days: int = Field(default=30, ge=1)
    keep_artifacts_days: int = Field(default=30, ge=1)
    retain_workspace_on_failure: bool = False


class ArtifactPolicy(BaseModel):
    """Artifact capture policy for a project or workflow."""

    model_config = ConfigDict(extra="forbid")

    capture: list[str] = Field(default_factory=lambda: ["logs", "patches", "summaries"])
    max_bytes: int = Field(default=10_000_000, ge=1)


class EnvironmentConfig(BaseModel):
    """Server-managed execution environment definition."""

    model_config = ConfigDict(extra="forbid")

    mode: ExecutionMode = "local"
    description: str = ""
    image: str = ""
    working_dir: str = ""


class ProjectConfig(BaseModel):
    """Configuration loaded from `.attractor/project.toml`."""

    model_config = ConfigDict(extra="forbid")

    default_environment: str = "local"
    allowed_execution_modes: list[ExecutionMode] = Field(default_factory=lambda: ["local"])
    variables: dict[str, str] = Field(default_factory=dict)
    secrets: list[str] = Field(default_factory=list)
    retention: RetentionPolicy = Field(default_factory=RetentionPolicy)
    artifacts: ArtifactPolicy = Field(default_factory=ArtifactPolicy)
    environments: dict[str, EnvironmentConfig] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _default_environment_must_be_allowed(self) -> ProjectConfig:
        allowed_names = set(self.environments)
        allowed_names.update(self.allowed_execution_modes)
        if self.default_environment not in allowed_names:
            raise ValueError("default_environment must be allowed")
        return self


class WorkflowConfig(BaseModel):
    """Configuration loaded from optional `workflow.toml`."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    default_environment: str = ""
    inputs: dict[str, str] = Field(default_factory=dict)
    approval: dict[str, Any] = Field(default_factory=dict)
    write_back: dict[str, Any] = Field(default_factory=dict)
    retention: RetentionPolicy | None = None
    artifacts: ArtifactPolicy | None = None


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigLoadError(
            f"Invalid TOML in {path}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc
    except OSError as exc:
        raise ConfigLoadError(
            f"Unable to read config file {path}",
            detail={"path": str(path), "error": str(exc)},
        ) from exc


def load_project_config(path: str | Path) -> ProjectConfig:
    """Load project config, returning defaults when the file is absent."""
    config_path = Path(path)
    if not config_path.exists():
        return ProjectConfig()
    try:
        return ProjectConfig.model_validate(_read_toml(config_path))
    except ValueError as exc:
        raise ConfigLoadError(
            f"Invalid project config {config_path}",
            detail={"path": str(config_path), "error": str(exc)},
        ) from exc


def load_workflow_config(path: str | Path) -> WorkflowConfig:
    """Load workflow config, returning defaults when the file is absent."""
    config_path = Path(path)
    if not config_path.exists():
        return WorkflowConfig()
    try:
        return WorkflowConfig.model_validate(_read_toml(config_path))
    except ValueError as exc:
        raise ConfigLoadError(
            f"Invalid workflow config {config_path}",
            detail={"path": str(config_path), "error": str(exc)},
        ) from exc
