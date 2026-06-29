# Phase 1 Engine Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the Python Attractor engine around platform-facing contracts while preserving the existing local CLI and library execution path.

**Architecture:** Add a small `attractor_platform` package that sits beside the existing pipeline engine and owns repo-local workflow package discovery, config models, platform errors, and immutable run manifests. The current parser, validator, variable expansion, runner, and CLI remain the execution core; Phase 1 wraps them with typed contracts and regression coverage rather than replacing them.

**Tech Stack:** Python 3.12, pydantic v2, stdlib `tomllib`, pytest, existing Attractor parser/validator/runner APIs.

---

## Scope Boundary

This plan implements Phase 1 only:

- Stable platform-facing Python APIs, config objects, and error types.
- `RunSpec` as the immutable launch manifest.
- Repo-local `.attractor/workflows/<name>/workflow.dot` with optional `workflow.toml`.
- Repo-level `.attractor/project.toml` config parsing.
- Variable-expansion and validation parity audit fixtures that lock current Python behavior and document Fabro alignment decisions.
- Regression tests proving existing local CLI/library execution is still available without Docker.

This plan does not implement Postgres, durable queues, git worktrees, Docker policy wiring, FastAPI resources, the React console, git checkpoints, branch promotion, MCP, hooks, cron, PR automation, or control-plane governance. Those are separate Phase 1-to-2 and Phase 2+ plans.

## File Structure

- Create `src/attractor_platform/__init__.py`
  Public exports for Phase 1 platform contracts.
- Create `src/attractor_platform/errors.py`
  Shared platform exception hierarchy with stable machine-readable codes.
- Create `src/attractor_platform/config.py`
  Pydantic models for `ProjectConfig`, `WorkflowConfig`, environment policy, retention policy, and artifact policy.
- Create `src/attractor_platform/packages.py`
  Discovery and loading for repo-local workflow packages.
- Create `src/attractor_platform/runspec.py`
  Immutable `RunSpec` manifest and helper for building it from a loaded workflow package.
- Modify `pyproject.toml`
  Include `src/attractor_platform` in the hatch wheel packages.
- Modify `src/attractor_pipeline/__init__.py`
  Export validation helpers that are already part of the public engine surface.
- Create `tests/test_platform_errors.py`
  Error contract tests.
- Create `tests/test_platform_config.py`
  TOML config parsing and validation tests.
- Create `tests/test_workflow_packages.py`
  Repo-local workflow discovery tests.
- Create `tests/test_runspec.py`
  Immutable manifest and git metadata tests.
- Create `tests/test_phase1_regressions.py`
  CLI/library regression coverage preserving non-Docker local execution.
- Create `tests/test_phase1_variable_expansion_parity.py`
  Explicit audit fixtures for escaping, undefined values, dotted names, non-scalar values, and non-recursive expansion.
- Create `tests/test_phase1_validation_parity.py`
  Explicit audit fixtures for the current Python lint rule surface.
- Create `docs/superpowers/parity/2026-06-29-variable-expansion.md`
  Human-readable parity decisions for variable expansion.
- Create `docs/superpowers/parity/2026-06-29-validation-lint.md`
  Human-readable parity decisions for graph validation and lint rules.

---

### Task 1: Platform Package and Error Contracts

**Files:**
- Create: `src/attractor_platform/__init__.py`
- Create: `src/attractor_platform/errors.py`
- Create: `tests/test_platform_errors.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Write the failing error contract tests**

Create `tests/test_platform_errors.py`:

```python
from __future__ import annotations

from attractor_platform.errors import (
    AttractorPlatformError,
    ConfigLoadError,
    PlatformErrorCode,
    WorkflowPackageError,
)


def test_platform_error_has_stable_code_and_detail() -> None:
    err = WorkflowPackageError(
        "workflow.dot is required",
        detail={"workflow": "release-checks"},
    )

    assert err.code == PlatformErrorCode.WORKFLOW_PACKAGE_INVALID
    assert str(err) == "workflow.dot is required"
    assert err.detail == {"workflow": "release-checks"}
    assert err.to_dict() == {
        "code": "workflow_package_invalid",
        "message": "workflow.dot is required",
        "detail": {"workflow": "release-checks"},
    }


def test_specific_errors_are_platform_errors() -> None:
    assert issubclass(ConfigLoadError, AttractorPlatformError)
    assert issubclass(WorkflowPackageError, AttractorPlatformError)
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
pytest tests/test_platform_errors.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'attractor_platform'`.

- [ ] **Step 3: Add the platform error module**

Create `src/attractor_platform/errors.py`:

```python
"""Platform-facing error contracts for Attractor.

These exceptions are intentionally small and stable. They are safe to expose
through future API responses without binding the server to internal Python
exception types from parser, validation, or execution modules.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class PlatformErrorCode(StrEnum):
    """Stable machine-readable error codes for platform operations."""

    CONFIG_LOAD_FAILED = "config_load_failed"
    WORKFLOW_PACKAGE_INVALID = "workflow_package_invalid"
    RUN_SPEC_INVALID = "run_spec_invalid"
    GIT_METADATA_UNAVAILABLE = "git_metadata_unavailable"


class AttractorPlatformError(Exception):
    """Base class for platform contract failures."""

    code: PlatformErrorCode = PlatformErrorCode.CONFIG_LOAD_FAILED

    def __init__(self, message: str, *, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation suitable for API responses."""
        return {
            "code": self.code.value,
            "message": self.message,
            "detail": self.detail,
        }


class ConfigLoadError(AttractorPlatformError):
    """Raised when project or workflow TOML cannot be loaded."""

    code = PlatformErrorCode.CONFIG_LOAD_FAILED


class WorkflowPackageError(AttractorPlatformError):
    """Raised when a repo-local workflow package is missing or invalid."""

    code = PlatformErrorCode.WORKFLOW_PACKAGE_INVALID


class RunSpecError(AttractorPlatformError):
    """Raised when an immutable run manifest cannot be built."""

    code = PlatformErrorCode.RUN_SPEC_INVALID


class GitMetadataError(AttractorPlatformError):
    """Raised when required git metadata cannot be read."""

    code = PlatformErrorCode.GIT_METADATA_UNAVAILABLE
```

Create `src/attractor_platform/__init__.py`:

```python
"""Platform contracts for the Python Attractor shared-runner direction."""

from attractor_platform.errors import (
    AttractorPlatformError,
    ConfigLoadError,
    GitMetadataError,
    PlatformErrorCode,
    RunSpecError,
    WorkflowPackageError,
)

__all__ = [
    "AttractorPlatformError",
    "ConfigLoadError",
    "GitMetadataError",
    "PlatformErrorCode",
    "RunSpecError",
    "WorkflowPackageError",
]
```

- [ ] **Step 4: Include the new package in the wheel**

In `pyproject.toml`, replace:

```toml
packages = ["src/attractor_llm", "src/attractor_agent", "src/attractor_pipeline", "src/attractor_server"]
```

with:

```toml
packages = ["src/attractor_llm", "src/attractor_agent", "src/attractor_pipeline", "src/attractor_server", "src/attractor_platform"]
```

- [ ] **Step 5: Run the error contract test**

Run:

```bash
pytest tests/test_platform_errors.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/attractor_platform/__init__.py src/attractor_platform/errors.py tests/test_platform_errors.py
git commit -m "feat: add platform error contracts"
```

---

### Task 2: Project and Workflow Config Models

**Files:**
- Create: `src/attractor_platform/config.py`
- Modify: `src/attractor_platform/__init__.py`
- Create: `tests/test_platform_config.py`

- [ ] **Step 1: Write the failing config tests**

Create `tests/test_platform_config.py`:

```python
from __future__ import annotations

import pytest

from attractor_platform.config import (
    ArtifactPolicy,
    EnvironmentConfig,
    ProjectConfig,
    RetentionPolicy,
    WorkflowConfig,
    load_project_config,
    load_workflow_config,
)
from attractor_platform.errors import ConfigLoadError


def test_default_project_config_is_safe_for_phase1() -> None:
    config = ProjectConfig()

    assert config.allowed_execution_modes == ["local"]
    assert config.default_environment == "local"
    assert config.retention.keep_events_days == 30
    assert config.artifacts.capture == ["logs", "patches", "summaries"]
    assert config.variables == {}
    assert config.secrets == []


def test_project_config_loads_from_toml(tmp_path) -> None:
    path = tmp_path / "project.toml"
    path.write_text(
        """
        default_environment = "docker"
        allowed_execution_modes = ["local", "docker"]

        [variables]
        service = "billing"

        [retention]
        keep_events_days = 14
        keep_artifacts_days = 7
        retain_workspace_on_failure = true

        [artifacts]
        capture = ["logs", "diffs"]
        max_bytes = 2048

        [environments.local]
        mode = "local"
        description = "trusted local execution"

        [environments.docker]
        mode = "docker"
        image = "python:3.12-slim"
        """,
        encoding="utf-8",
    )

    config = load_project_config(path)

    assert config.default_environment == "docker"
    assert config.allowed_execution_modes == ["local", "docker"]
    assert config.variables == {"service": "billing"}
    assert config.retention.keep_events_days == 14
    assert config.retention.keep_artifacts_days == 7
    assert config.retention.retain_workspace_on_failure is True
    assert config.artifacts.capture == ["logs", "diffs"]
    assert config.artifacts.max_bytes == 2048
    assert config.environments["docker"].image == "python:3.12-slim"


def test_missing_project_config_returns_defaults(tmp_path) -> None:
    assert load_project_config(tmp_path / "missing.toml") == ProjectConfig()


def test_invalid_project_toml_raises_config_error(tmp_path) -> None:
    path = tmp_path / "project.toml"
    path.write_text("default_environment = [", encoding="utf-8")

    with pytest.raises(ConfigLoadError) as excinfo:
        load_project_config(path)

    assert excinfo.value.code.value == "config_load_failed"
    assert excinfo.value.detail["path"] == str(path)


def test_workflow_config_loads_optional_values(tmp_path) -> None:
    path = tmp_path / "workflow.toml"
    path.write_text(
        """
        display_name = "Release Checks"
        description = "Run release readiness checks"
        tags = ["release", "quality"]
        default_environment = "docker"

        [inputs]
        release_version = "1.2.3"

        [approval]
        required = true
        prompt = "Promote branch?"

        [write_back]
        enabled = true
        target_branch = "release/generated"
        """,
        encoding="utf-8",
    )

    config = load_workflow_config(path)

    assert config.display_name == "Release Checks"
    assert config.tags == ["release", "quality"]
    assert config.default_environment == "docker"
    assert config.inputs == {"release_version": "1.2.3"}
    assert config.approval == {"required": True, "prompt": "Promote branch?"}
    assert config.write_back == {"enabled": True, "target_branch": "release/generated"}


def test_missing_workflow_config_returns_defaults(tmp_path) -> None:
    assert load_workflow_config(tmp_path / "workflow.toml") == WorkflowConfig()


def test_config_model_rejects_unknown_execution_mode() -> None:
    with pytest.raises(ValueError, match="default_environment must be allowed"):
        ProjectConfig(default_environment="remote", allowed_execution_modes=["local"])


def test_policy_models_accept_explicit_values() -> None:
    env = EnvironmentConfig(mode="docker", image="python:3.12-slim")
    retention = RetentionPolicy(keep_events_days=3, keep_artifacts_days=2)
    artifacts = ArtifactPolicy(capture=["logs"], max_bytes=10)

    assert env.mode == "docker"
    assert retention.keep_artifacts_days == 2
    assert artifacts.max_bytes == 10
```

- [ ] **Step 2: Run the failing config tests**

Run:

```bash
pytest tests/test_platform_config.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'attractor_platform.config'`.

- [ ] **Step 3: Add the config models and TOML loaders**

Create `src/attractor_platform/config.py`:

```python
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
```

Update `src/attractor_platform/__init__.py`:

```python
"""Platform contracts for the Python Attractor shared-runner direction."""

from attractor_platform.config import (
    ArtifactPolicy,
    EnvironmentConfig,
    ProjectConfig,
    RetentionPolicy,
    WorkflowConfig,
    load_project_config,
    load_workflow_config,
)
from attractor_platform.errors import (
    AttractorPlatformError,
    ConfigLoadError,
    GitMetadataError,
    PlatformErrorCode,
    RunSpecError,
    WorkflowPackageError,
)

__all__ = [
    "ArtifactPolicy",
    "AttractorPlatformError",
    "ConfigLoadError",
    "EnvironmentConfig",
    "GitMetadataError",
    "PlatformErrorCode",
    "ProjectConfig",
    "RetentionPolicy",
    "RunSpecError",
    "WorkflowConfig",
    "WorkflowPackageError",
    "load_project_config",
    "load_workflow_config",
]
```

- [ ] **Step 4: Run the config tests**

Run:

```bash
pytest tests/test_platform_config.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the existing environment tests to check no contract collision**

Run:

```bash
pytest tests/test_environment.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_platform/__init__.py src/attractor_platform/config.py tests/test_platform_config.py
git commit -m "feat: add platform config models"
```

---

### Task 3: Repo-Local Workflow Package Loader

**Files:**
- Create: `src/attractor_platform/packages.py`
- Modify: `src/attractor_platform/__init__.py`
- Create: `tests/test_workflow_packages.py`

- [ ] **Step 1: Write failing workflow package tests**

Create `tests/test_workflow_packages.py`:

```python
from __future__ import annotations

import pytest

from attractor_platform.errors import WorkflowPackageError
from attractor_platform.packages import (
    WorkflowPackage,
    WorkflowValidationStatus,
    discover_workflow_packages,
    load_workflow_package,
)


VALID_DOT = """
digraph ReleaseChecks {
  graph [goal="Check release"]
  start [shape=Mdiamond]
  task [shape=box, prompt="Check $service"]
  done [shape=Msquare]
  start -> task -> done
}
"""


def write_workflow(root, name: str, dot: str = VALID_DOT, toml: str | None = None) -> None:
    workflow_dir = root / ".attractor" / "workflows" / name
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(dot, encoding="utf-8")
    if toml is not None:
        (workflow_dir / "workflow.toml").write_text(toml, encoding="utf-8")


def test_load_workflow_package_requires_workflow_dot(tmp_path) -> None:
    workflow_dir = tmp_path / ".attractor" / "workflows" / "missing-dot"
    workflow_dir.mkdir(parents=True)

    with pytest.raises(WorkflowPackageError) as excinfo:
        load_workflow_package(tmp_path, "missing-dot")

    assert excinfo.value.code.value == "workflow_package_invalid"
    assert "workflow.dot is required" in str(excinfo.value)


def test_load_workflow_package_with_optional_toml(tmp_path) -> None:
    (tmp_path / ".attractor").mkdir()
    (tmp_path / ".attractor" / "project.toml").write_text(
        """
        default_environment = "local"
        allowed_execution_modes = ["local"]

        [variables]
        service = "billing"
        """,
        encoding="utf-8",
    )
    write_workflow(
        tmp_path,
        "release-checks",
        toml='display_name = "Release Checks"\ntags = ["release"]\n',
    )

    package = load_workflow_package(tmp_path, "release-checks")

    assert isinstance(package, WorkflowPackage)
    assert package.name == "release-checks"
    assert package.repo_path == tmp_path
    assert package.dot_path.name == "workflow.dot"
    assert package.workflow_config.display_name == "Release Checks"
    assert package.project_config.variables == {"service": "billing"}
    assert package.status == WorkflowValidationStatus.VALID
    assert package.graph is not None
    assert package.graph.name == "ReleaseChecks"
    assert package.diagnostics == []


def test_workflow_toml_is_optional(tmp_path) -> None:
    write_workflow(tmp_path, "test-repair")

    package = load_workflow_package(tmp_path, "test-repair")

    assert package.workflow_config.display_name == ""
    assert package.toml_path is None


def test_invalid_dot_is_reported_as_package_error(tmp_path) -> None:
    write_workflow(tmp_path, "broken", dot="not a digraph")

    with pytest.raises(WorkflowPackageError) as excinfo:
        load_workflow_package(tmp_path, "broken")

    assert "Unable to parse workflow.dot" in str(excinfo.value)
    assert excinfo.value.detail["workflow"] == "broken"


def test_validation_errors_are_package_errors(tmp_path) -> None:
    write_workflow(
        tmp_path,
        "invalid",
        dot="""
        digraph Invalid {
          start [shape=Mdiamond]
          task [shape=box]
          start -> task
        }
        """,
    )

    with pytest.raises(WorkflowPackageError) as excinfo:
        load_workflow_package(tmp_path, "invalid")

    assert "Workflow validation failed" in str(excinfo.value)
    assert excinfo.value.detail["workflow"] == "invalid"
    assert "R02" in excinfo.value.detail["errors"]


def test_discover_workflow_packages_sorts_by_name(tmp_path) -> None:
    write_workflow(tmp_path, "zeta")
    write_workflow(tmp_path, "alpha")

    packages = discover_workflow_packages(tmp_path)

    assert [package.name for package in packages] == ["alpha", "zeta"]
    assert [package.status for package in packages] == [
        WorkflowValidationStatus.VALID,
        WorkflowValidationStatus.VALID,
    ]


def test_discover_records_invalid_workflow_without_raising(tmp_path) -> None:
    write_workflow(tmp_path, "good")
    write_workflow(tmp_path, "broken", dot="not a digraph")

    packages = {p.name: p for p in discover_workflow_packages(tmp_path)}

    assert packages["good"].status == WorkflowValidationStatus.VALID
    assert packages["broken"].status == WorkflowValidationStatus.INVALID
    assert packages["broken"].graph is None
    assert packages["broken"].error is not None


def test_discover_records_invalid_project_config_without_raising(tmp_path) -> None:
    (tmp_path / ".attractor").mkdir()
    (tmp_path / ".attractor" / "project.toml").write_text(
        "default_environment = [",
        encoding="utf-8",
    )
    write_workflow(tmp_path, "good")

    packages = discover_workflow_packages(tmp_path)

    assert len(packages) == 1
    assert packages[0].name == "good"
    assert packages[0].status == WorkflowValidationStatus.INVALID
    assert packages[0].graph is None
    assert packages[0].error is not None


def test_discover_returns_empty_when_attractor_dir_missing(tmp_path) -> None:
    assert discover_workflow_packages(tmp_path) == []
```

- [ ] **Step 2: Run the failing package tests**

Run:

```bash
pytest tests/test_workflow_packages.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'attractor_platform.packages'`.

- [ ] **Step 3: Add the workflow package loader**

Create `src/attractor_platform/packages.py`:

```python
"""Repo-local workflow package discovery."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from attractor_pipeline.graph import Graph
from attractor_pipeline.parser import parse_dot
from attractor_pipeline.parser.parser import ParseError
from attractor_pipeline.validation import Diagnostic, Severity, validate
from attractor_platform.config import (
    ProjectConfig,
    WorkflowConfig,
    load_project_config,
    load_workflow_config,
)
from attractor_platform.errors import AttractorPlatformError, WorkflowPackageError


class WorkflowValidationStatus(StrEnum):
    """Validation status for repo-local workflow packages."""

    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class WorkflowPackage:
    """Loaded repo-local workflow package."""

    repo_path: Path
    name: str
    package_path: Path
    dot_path: Path
    toml_path: Path | None
    project_config: ProjectConfig
    workflow_config: WorkflowConfig
    graph: Graph | None
    diagnostics: list[Diagnostic]
    status: WorkflowValidationStatus = WorkflowValidationStatus.VALID
    error: dict[str, object] | None = None


def _workflow_dir(repo_path: Path, name: str) -> Path:
    return repo_path / ".attractor" / "workflows" / name


def load_workflow_package(repo_path: str | Path, name: str) -> WorkflowPackage:
    """Load and validate `.attractor/workflows/<name>/workflow.dot`."""
    repo = Path(repo_path).expanduser().resolve()
    package_path = _workflow_dir(repo, name)
    dot_path = package_path / "workflow.dot"
    toml_path = package_path / "workflow.toml"

    if not dot_path.exists():
        raise WorkflowPackageError(
            "workflow.dot is required",
            detail={"repo_path": str(repo), "workflow": name, "path": str(dot_path)},
        )

    try:
        graph = parse_dot(dot_path.read_text(encoding="utf-8"))
    except (OSError, ParseError) as exc:
        raise WorkflowPackageError(
            "Unable to parse workflow.dot",
            detail={"repo_path": str(repo), "workflow": name, "error": str(exc)},
        ) from exc

    diagnostics = validate(graph)
    errors = [d for d in diagnostics if d.severity == Severity.ERROR]
    if errors:
        raise WorkflowPackageError(
            "Workflow validation failed",
            detail={
                "repo_path": str(repo),
                "workflow": name,
                "errors": "; ".join(f"{d.rule}: {d.message}" for d in errors),
            },
        )

    project_config = load_project_config(repo / ".attractor" / "project.toml")
    workflow_config = load_workflow_config(toml_path)

    return WorkflowPackage(
        repo_path=repo,
        name=name,
        package_path=package_path,
        dot_path=dot_path,
        toml_path=toml_path if toml_path.exists() else None,
        project_config=project_config,
        workflow_config=workflow_config,
        graph=graph,
        diagnostics=diagnostics,
        status=WorkflowValidationStatus.VALID,
        error=None,
    )


def inspect_workflow_package(repo_path: str | Path, name: str) -> WorkflowPackage:
    """Load a package without raising; record invalid packages instead."""
    try:
        return load_workflow_package(repo_path, name)
    except AttractorPlatformError as exc:
        repo = Path(repo_path).expanduser().resolve()
        package_path = _workflow_dir(repo, name)
        toml_path = package_path / "workflow.toml"
        try:
            project_config = load_project_config(repo / ".attractor" / "project.toml")
        except AttractorPlatformError:
            project_config = ProjectConfig()
        return WorkflowPackage(
            repo_path=repo,
            name=name,
            package_path=package_path,
            dot_path=package_path / "workflow.dot",
            toml_path=toml_path if toml_path.exists() else None,
            project_config=project_config,
            workflow_config=WorkflowConfig(),
            graph=None,
            diagnostics=[],
            status=WorkflowValidationStatus.INVALID,
            error=exc.to_dict(),
        )


def discover_workflow_packages(repo_path: str | Path) -> list[WorkflowPackage]:
    """Discover all workflow packages, recording invalid ones rather than failing."""
    repo = Path(repo_path).expanduser().resolve()
    workflows_dir = repo / ".attractor" / "workflows"
    if not workflows_dir.exists():
        return []

    return [
        inspect_workflow_package(repo, child.name)
        for child in sorted(workflows_dir.iterdir(), key=lambda path: path.name)
        if child.is_dir()
    ]
```

Update `src/attractor_platform/__init__.py`:

```python
"""Platform contracts for the Python Attractor shared-runner direction."""

from attractor_platform.config import (
    ArtifactPolicy,
    EnvironmentConfig,
    ProjectConfig,
    RetentionPolicy,
    WorkflowConfig,
    load_project_config,
    load_workflow_config,
)
from attractor_platform.errors import (
    AttractorPlatformError,
    ConfigLoadError,
    GitMetadataError,
    PlatformErrorCode,
    RunSpecError,
    WorkflowPackageError,
)
from attractor_platform.packages import (
    WorkflowPackage,
    WorkflowValidationStatus,
    discover_workflow_packages,
    inspect_workflow_package,
    load_workflow_package,
)

__all__ = [
    "ArtifactPolicy",
    "AttractorPlatformError",
    "ConfigLoadError",
    "EnvironmentConfig",
    "GitMetadataError",
    "PlatformErrorCode",
    "ProjectConfig",
    "RetentionPolicy",
    "RunSpecError",
    "WorkflowConfig",
    "WorkflowPackage",
    "WorkflowPackageError",
    "WorkflowValidationStatus",
    "discover_workflow_packages",
    "inspect_workflow_package",
    "load_project_config",
    "load_workflow_config",
    "load_workflow_package",
]
```

- [ ] **Step 4: Run the package tests**

Run:

```bash
pytest tests/test_workflow_packages.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/attractor_platform/__init__.py src/attractor_platform/packages.py tests/test_workflow_packages.py
git commit -m "feat: load repo-local workflow packages"
```

---

### Task 4: Immutable RunSpec Manifest

**Files:**
- Create: `src/attractor_platform/runspec.py`
- Modify: `src/attractor_platform/__init__.py`
- Create: `tests/test_runspec.py`

- [ ] **Step 1: Write failing RunSpec tests**

Create `tests/test_runspec.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from attractor_platform.config import ProjectConfig, WorkflowConfig
from attractor_platform.errors import RunSpecError
from attractor_platform.packages import inspect_workflow_package, load_workflow_package
from attractor_platform.runspec import (
    DirtyState,
    RunEnvironmentRequest,
    RunSpec,
    build_run_spec,
    read_git_metadata,
)


VALID_DOT = """
digraph Build {
  graph [goal="Build the project"]
  start [shape=Mdiamond]
  task [shape=box, prompt="Build $target"]
  done [shape=Msquare]
  start -> task -> done
}
"""


def git_available() -> bool:
    try:
        subprocess.run(["git", "--version"], check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    workflow_dir = repo / ".attractor" / "workflows" / "build"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(VALID_DOT, encoding="utf-8")
    return repo


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_read_git_metadata_clean_repo(tmp_path) -> None:
    repo = make_repo(tmp_path)

    metadata = read_git_metadata(repo)

    assert len(metadata.commit) == 40
    assert metadata.branch in {"main", "master"}
    assert metadata.dirty_state == DirtyState.CLEAN


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_read_git_metadata_dirty_repo(tmp_path) -> None:
    repo = make_repo(tmp_path)
    (repo / "README.md").write_text("# changed\n", encoding="utf-8")

    metadata = read_git_metadata(repo)

    assert metadata.dirty_state == DirtyState.DIRTY


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_build_run_spec_from_workflow_package(tmp_path) -> None:
    repo = make_repo(tmp_path)
    package = load_workflow_package(repo, "build")

    spec = build_run_spec(
        package,
        inputs={"target": "wheel"},
        actor_label="bahbinton",
        requested_environment="local",
    )

    assert spec.repo_path == repo.resolve()
    assert spec.workflow_name == "build"
    assert spec.graph_name == "Build"
    assert spec.inputs == {"target": "wheel"}
    assert spec.actor_label == "bahbinton"
    assert spec.requested_environment.mode == "local"
    assert spec.effective_environment.mode == "local"
    assert len(spec.source_commit) == 40
    assert spec.dirty_state == DirtyState.CLEAN


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_run_spec_is_immutable(tmp_path) -> None:
    repo = make_repo(tmp_path)
    spec = build_run_spec(load_workflow_package(repo, "build"))

    with pytest.raises(ValidationError, match="frozen"):
        spec.workflow_name = "changed"


def test_run_environment_request_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        RunEnvironmentRequest(mode="kubernetes")


def test_build_run_spec_rejects_invalid_discovery_record(tmp_path) -> None:
    workflow_dir = tmp_path / ".attractor" / "workflows" / "broken"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text("not a digraph", encoding="utf-8")
    package = inspect_workflow_package(tmp_path, "broken")

    assert package.graph is None
    with pytest.raises(RunSpecError, match="invalid workflow package"):
        build_run_spec(package)


def test_run_spec_can_be_built_directly_for_unit_tests(tmp_path) -> None:
    spec = RunSpec(
        repo_id="local:test",
        repo_path=tmp_path,
        workflow_name="build",
        graph_name="Build",
        workflow_dot_path=tmp_path / "workflow.dot",
        workflow_toml_path=None,
        source_commit="0" * 40,
        source_branch="main",
        dirty_state=DirtyState.CLEAN,
        inputs={"target": "wheel"},
        actor_label="tester",
        requested_environment=RunEnvironmentRequest(mode="local"),
        effective_environment=RunEnvironmentRequest(mode="local"),
        retention=ProjectConfig().retention,
        artifact_policy=ProjectConfig().artifacts,
        approval_policy={},
        write_back_policy={},
    )

    assert spec.run_id.startswith("run_")
    assert spec.workflow_config == WorkflowConfig()
```

- [ ] **Step 2: Run the failing RunSpec tests**

Run:

```bash
pytest tests/test_runspec.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'attractor_platform.runspec'`.

- [ ] **Step 3: Add the immutable RunSpec model**

Create `src/attractor_platform/runspec.py`:

```python
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


def _resolve_environment(package: WorkflowPackage, requested: str) -> RunEnvironmentRequest:
    project = package.project_config
    workflow = package.workflow_config
    selected = requested or workflow.default_environment or project.default_environment

    if selected in project.environments:
        env = project.environments[selected]
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
        requested_environment=RunEnvironmentRequest(
            mode=requested_environment or "local",
            name=requested_environment or "local",
        ),
        effective_environment=effective_environment,
        retention=package.workflow_config.retention or package.project_config.retention,
        artifact_policy=package.workflow_config.artifacts or package.project_config.artifacts,
        approval_policy=package.workflow_config.approval,
        write_back_policy=package.workflow_config.write_back,
        workflow_config=package.workflow_config,
    )
```

Update `src/attractor_platform/__init__.py`:

```python
"""Platform contracts for the Python Attractor shared-runner direction."""

from attractor_platform.config import (
    ArtifactPolicy,
    EnvironmentConfig,
    ProjectConfig,
    RetentionPolicy,
    WorkflowConfig,
    load_project_config,
    load_workflow_config,
)
from attractor_platform.errors import (
    AttractorPlatformError,
    ConfigLoadError,
    GitMetadataError,
    PlatformErrorCode,
    RunSpecError,
    WorkflowPackageError,
)
from attractor_platform.packages import (
    WorkflowPackage,
    WorkflowValidationStatus,
    discover_workflow_packages,
    inspect_workflow_package,
    load_workflow_package,
)
from attractor_platform.runspec import (
    DirtyState,
    GitMetadata,
    RunEnvironmentRequest,
    RunSpec,
    build_run_spec,
    read_git_metadata,
)

__all__ = [
    "ArtifactPolicy",
    "AttractorPlatformError",
    "ConfigLoadError",
    "DirtyState",
    "EnvironmentConfig",
    "GitMetadata",
    "GitMetadataError",
    "PlatformErrorCode",
    "ProjectConfig",
    "RetentionPolicy",
    "RunEnvironmentRequest",
    "RunSpec",
    "RunSpecError",
    "WorkflowConfig",
    "WorkflowPackage",
    "WorkflowPackageError",
    "WorkflowValidationStatus",
    "build_run_spec",
    "discover_workflow_packages",
    "inspect_workflow_package",
    "load_project_config",
    "load_workflow_config",
    "load_workflow_package",
    "read_git_metadata",
]
```

- [ ] **Step 4: Run the RunSpec tests**

Run:

```bash
pytest tests/test_runspec.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/attractor_platform/__init__.py src/attractor_platform/runspec.py tests/test_runspec.py
git commit -m "feat: add immutable run specs"
```

---

### Task 5: Preserve Existing Local CLI and Library Execution

**Files:**
- Modify: `src/attractor_pipeline/__init__.py`
- Create: `tests/test_phase1_regressions.py`

- [ ] **Step 1: Write failing or locking regression tests**

Create `tests/test_phase1_regressions.py`:

```python
from __future__ import annotations

import asyncio
import subprocess
import sys

from attractor_pipeline import (
    HandlerRegistry,
    HandlerResult,
    Outcome,
    PipelineStatus,
    run_pipeline,
    validate,
    validate_or_raise,
)
from attractor_pipeline.engine.runner import Handler
from attractor_pipeline.graph import Graph, Node
from attractor_pipeline.parser import parse_dot


class LocalTestHandler(Handler):
    async def execute(
        self,
        node: Node,
        context: dict[str, object],
        graph: Graph,
        logs_root,
        abort_signal=None,
    ) -> HandlerResult:
        return HandlerResult(
            status=Outcome.SUCCESS,
            context_updates={"ran_without_docker": True},
            output="local execution ok",
        )


DOT = """
digraph LocalPath {
  graph [goal="Prove local path still works"]
  start [shape=Mdiamond]
  task [shape=box, handler="local.test", prompt="Run locally"]
  done [shape=Msquare]
  start -> task -> done
}
"""


def test_validate_exports_are_available_from_public_pipeline_api() -> None:
    graph = parse_dot(DOT)

    assert validate(graph) == []
    validate_or_raise(graph)


def test_library_run_pipeline_still_executes_without_docker(tmp_path) -> None:
    graph = parse_dot(DOT)
    registry = HandlerRegistry()
    registry.register("local.test", LocalTestHandler())

    result = asyncio.run(run_pipeline(graph, registry, logs_root=tmp_path))

    assert result.status == PipelineStatus.COMPLETED
    assert result.context["ran_without_docker"] is True


def test_cli_validate_still_accepts_plain_dot_file(tmp_path) -> None:
    dot_path = tmp_path / "workflow.dot"
    dot_path.write_text(DOT, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "attractor_pipeline.cli", "validate", str(dot_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Validation: PASS" in result.stdout
```

- [ ] **Step 2: Run the regression tests**

Run:

```bash
pytest tests/test_phase1_regressions.py -v
```

Expected: The `validate`/`validate_or_raise` export test FAILs until Step 3; the library and CLI path tests PASS.

- [ ] **Step 3: Export validation helpers from the public pipeline package**

Modify `src/attractor_pipeline/__init__.py`.

Add this import beside the existing parser and stylesheet imports:

```python
from attractor_pipeline.validation import Diagnostic, Severity, validate, validate_or_raise
```

Add these entries to `__all__`:

```python
    # Validation
    "Diagnostic",
    "Severity",
    "validate",
    "validate_or_raise",
```

- [ ] **Step 4: Run the regression tests**

Run:

```bash
pytest tests/test_phase1_regressions.py -v
```

Expected: PASS.

- [ ] **Step 5: Run the existing pipeline engine tests**

Run:

```bash
pytest tests/test_pipeline_engine.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_pipeline/__init__.py tests/test_phase1_regressions.py
git commit -m "test: preserve local pipeline execution"
```

---

### Task 6: Variable Expansion Parity Audit

**Files:**
- Create: `tests/test_phase1_variable_expansion_parity.py`
- Create: `docs/superpowers/parity/2026-06-29-variable-expansion.md`

- [ ] **Step 1: Write parity tests for the current Python variable behavior**

Create `tests/test_phase1_variable_expansion_parity.py`:

```python
from __future__ import annotations

import pytest

from attractor_pipeline.variable_expansion import expand_variables


def test_bare_and_braced_variables_expand_scalars() -> None:
    result = expand_variables(
        "Build $service version ${version} approved=$approved",
        {"service": "billing", "version": "1.2.3", "approved": True},
    )

    assert result == "Build billing version 1.2.3 approved=True"


def test_escaped_dollar_is_preserved_as_literal_dollar() -> None:
    result = expand_variables(r"Cost is \$5 and service is $service", {"service": "billing"})

    assert result == "Cost is $5 and service is billing"


def test_undefined_variables_are_kept_by_default() -> None:
    assert expand_variables("Hello $name", {}) == "Hello $name"


def test_undefined_variables_can_be_emptied() -> None:
    assert expand_variables("Hello $name", {}, undefined="empty") == "Hello "


def test_undefined_variables_can_raise() -> None:
    with pytest.raises(KeyError, match="Undefined variable"):
        expand_variables("Hello $name", {}, undefined="error")


def test_dotted_variable_names_are_single_lookup_keys() -> None:
    result = expand_variables(
        "Deploy $service.name",
        {"service.name": "billing-api", "service": "billing"},
    )

    assert result == "Deploy billing-api"


def test_nested_expansion_is_not_recursive() -> None:
    result = expand_variables("$outer", {"outer": "$inner", "inner": "value"})

    assert result == "$inner"


def test_non_scalar_values_are_not_expanded() -> None:
    result = expand_variables("Items: $items", {"items": ["a", "b"]})

    assert result == "Items: $items"
```

- [ ] **Step 2: Run the variable expansion parity tests**

Run:

```bash
pytest tests/test_phase1_variable_expansion_parity.py -v
```

Expected: PASS. These tests lock the existing Python behavior before any MiniJinja compatibility decision.

- [ ] **Step 3: Record the parity decision**

Create the directory:

```bash
mkdir -p docs/superpowers/parity
```

Create `docs/superpowers/parity/2026-06-29-variable-expansion.md`:

```markdown
# Variable Expansion Parity Audit

## Decision

Phase 1 keeps the existing Python `$name` and `${name}` expansion semantics. The platform records the differences from Fabro's MiniJinja-style templating rather than changing prompt expansion during engine hardening.

## Locked Python Behavior

- `$name` expands when `name` exists in the context and the value is `str`, `int`, `float`, or `bool`.
- `${name}` expands with the same lookup behavior as `$name`.
- `\$name` emits a literal `$name`.
- Undefined variables are kept by default.
- Callers can request undefined variables to become an empty string.
- Callers can request undefined variables to raise `KeyError`.
- Dotted names such as `$service.name` are single context keys, not object traversal.
- Expansion is not recursive. If `$outer` maps to `$inner`, the output is `$inner`.
- Non-scalar values are not expanded.

## Phase 1 Rationale

Changing prompt interpolation semantics can alter existing workflows. Phase 1 is a hardening phase, so the safe behavior is to test and document the current Python semantics. A future templating change must be introduced behind an explicit config switch and migration notes.
```

- [ ] **Step 4: Run the parity tests again**

Run:

```bash
pytest tests/test_phase1_variable_expansion_parity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/parity/2026-06-29-variable-expansion.md tests/test_phase1_variable_expansion_parity.py
git commit -m "test: lock variable expansion parity"
```

---

### Task 7: Validation and Lint Parity Audit

**Files:**
- Create: `tests/test_phase1_validation_parity.py`
- Create: `docs/superpowers/parity/2026-06-29-validation-lint.md`

- [ ] **Step 1: Write parity tests for the current Python lint surface**

Create `tests/test_phase1_validation_parity.py`:

```python
from __future__ import annotations

from attractor_pipeline.parser import parse_dot
from attractor_pipeline.validation import Severity, validate


def rules_for(dot: str) -> dict[str, Severity]:
    graph = parse_dot(dot)
    return {diagnostic.rule: diagnostic.severity for diagnostic in validate(graph)}


def test_valid_graph_has_no_diagnostics() -> None:
    diagnostics = validate(
        parse_dot(
            """
            digraph Valid {
              graph [goal="Ship"]
              start [shape=Mdiamond]
              task [shape=box, prompt="Do work"]
              done [shape=Msquare]
              start -> task -> done
            }
            """
        )
    )

    assert diagnostics == []


def test_missing_start_and_exit_are_errors() -> None:
    rule_map = rules_for(
        """
        digraph Missing {
          task [shape=box, prompt="Do work"]
        }
        """
    )

    assert rule_map["R01"] == Severity.ERROR
    assert rule_map["R02"] == Severity.ERROR


def test_unreachable_node_and_missing_prompt_are_warnings() -> None:
    rule_map = rules_for(
        """
        digraph Warnings {
          graph [goal="Warn"]
          start [shape=Mdiamond]
          task [shape=box]
          orphan [shape=box]
          done [shape=Msquare]
          start -> task -> done
        }
        """
    )

    assert rule_map["R05"] == Severity.WARNING
    assert rule_map["R13"] == Severity.WARNING


def test_missing_goal_is_info() -> None:
    rule_map = rules_for(
        """
        digraph Info {
          start [shape=Mdiamond]
          done [shape=Msquare]
          start -> done
        }
        """
    )

    assert rule_map["R12"] == Severity.INFO


def test_invalid_condition_is_error() -> None:
    rule_map = rules_for(
        """
        digraph BadCondition {
          graph [goal="Check"]
          start [shape=Mdiamond]
          done [shape=Msquare]
          start -> done [condition="outcome === success"]
        }
        """
    )

    assert rule_map["R14"] == Severity.ERROR


def test_manager_without_child_graph_is_error() -> None:
    rule_map = rules_for(
        """
        digraph Manager {
          graph [goal="Check"]
          start [shape=Mdiamond]
          manager [shape=hexagon]
          done [shape=Msquare]
          start -> manager -> done
        }
        """
    )

    assert rule_map["R15"] == Severity.ERROR
```

- [ ] **Step 2: Run validation parity tests**

Run:

```bash
pytest tests/test_phase1_validation_parity.py -v
```

Expected: PASS.

- [ ] **Step 3: Record the lint parity decision**

Create the directory if Task 6 has not already created it:

```bash
mkdir -p docs/superpowers/parity
```

Create `docs/superpowers/parity/2026-06-29-validation-lint.md`:

```markdown
# Validation and Lint Parity Audit

## Decision

Phase 1 keeps the existing Python validation rule surface and adds explicit tests for the rules most important to platform launch safety. The platform package treats validation errors as workflow package load failures, so invalid repo-local workflows cannot produce `RunSpec` manifests.

## Locked Python Behavior

- `R01` missing or duplicate start nodes are errors.
- `R02` missing or duplicate exit nodes are errors.
- `R03` incoming edges to the start node are errors.
- `R04` outgoing edges from exit nodes are errors.
- `R05` unreachable nodes are warnings.
- `R06` edges referencing missing nodes are errors.
- `R07` no reachable exit is an error.
- `R08` conditional nodes with fewer than two outgoing edges are warnings.
- `R09` goal gates without retry targets are warnings.
- `R10` missing retry targets are errors.
- `R11` self-loops are warnings.
- `R12` missing graph goal is info.
- `R13` box nodes without prompts are warnings.
- `R14` invalid edge condition syntax is an error.
- `R15` manager nodes without `child_graph` are errors.

## Phase 1 Rationale

The current Python validator already enforces the core StrongDM Attractor graph constraints and several hardening rules added during prior spec-compliance work. Phase 1 should make those rules visible and stable at the platform boundary before adding server-side workflow indexing and launch APIs.
```

- [ ] **Step 4: Run validation parity tests again**

Run:

```bash
pytest tests/test_phase1_validation_parity.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/parity/2026-06-29-validation-lint.md tests/test_phase1_validation_parity.py
git commit -m "test: lock validation parity"
```

---

### Task 8: Phase 1 Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run the focused Phase 1 suite**

Run:

```bash
pytest \
  tests/test_platform_errors.py \
  tests/test_platform_config.py \
  tests/test_workflow_packages.py \
  tests/test_runspec.py \
  tests/test_phase1_regressions.py \
  tests/test_phase1_variable_expansion_parity.py \
  tests/test_phase1_validation_parity.py \
  -v
```

Expected: PASS.

- [ ] **Step 2: Run representative existing regression suites**

Run:

```bash
pytest tests/test_pipeline_engine.py tests/test_environment.py tests/test_server.py -v
```

Expected: PASS.

- [ ] **Step 3: Run lint and type checks**

Run:

```bash
ruff check src/attractor_platform src/attractor_pipeline/__init__.py tests/test_platform_errors.py tests/test_platform_config.py tests/test_workflow_packages.py tests/test_runspec.py tests/test_phase1_regressions.py tests/test_phase1_variable_expansion_parity.py tests/test_phase1_validation_parity.py
```

Expected: PASS.

Run:

```bash
pyright src/attractor_platform
```

Expected: PASS.

- [ ] **Step 4: Commit verification-only fixes if required**

If lint or type checks require mechanical fixes, make only the reported changes and commit them:

```bash
git add src/attractor_platform src/attractor_pipeline/__init__.py tests/test_platform_errors.py tests/test_platform_config.py tests/test_workflow_packages.py tests/test_runspec.py tests/test_phase1_regressions.py tests/test_phase1_variable_expansion_parity.py tests/test_phase1_validation_parity.py
git commit -m "chore: clean phase 1 contract checks"
```

- [ ] **Step 5: Record final status**

Run:

```bash
git status --short
```

Expected: no tracked files modified. Existing untracked brainstorming artifacts may remain untracked if they predate this plan.

---

## Self-Review

**Spec coverage**

- Stable public APIs, config objects, and error types: Tasks 1, 2, 3, 4, and 5.
- `RunSpec` as immutable run manifest: Task 4.
- Variable-expansion parity audit: Task 6.
- Validation/lint parity audit: Task 7.
- Existing local CLI/library path remains non-Docker: Task 5.
- Repo-local `.attractor/workflows/<name>/workflow.dot` with optional `workflow.toml`: Task 3.
- Repo-level `.attractor/project.toml`: Task 2.

**Known phase boundary**

- Worktree isolation, Docker run policy, durable events, artifact records, git checkpoints, branch promotion, and FastAPI resources are intentionally excluded from this Phase 1 plan because they belong to the Phase 1-to-2 and Phase 2 spines in the approved spec.

**Execution notes**

- Use small commits exactly as listed. Each task is independently reviewable.
- Keep the existing `attractor_pipeline` runner behavior intact.
- Do not require Docker for any Phase 1 verification command.
