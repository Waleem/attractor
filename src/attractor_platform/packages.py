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

_PATH_SEPARATORS = ("/", "\\")


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


def _repo_path(repo_path: str | Path) -> Path:
    return Path(repo_path).expanduser().resolve()


def _validate_workflow_name(name: str) -> None:
    path = Path(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or any(separator in name for separator in _PATH_SEPARATORS)
    ):
        raise WorkflowPackageError(
            "Invalid workflow name",
            detail={"workflow": name},
        )


def _workflow_dir(repo_path: Path, name: str) -> Path:
    _validate_workflow_name(name)
    return repo_path / ".attractor" / "workflows" / name


def load_workflow_package(repo_path: str | Path, name: str) -> WorkflowPackage:
    """Load and validate `.attractor/workflows/<name>/workflow.dot`."""
    repo = _repo_path(repo_path)
    package_path = _workflow_dir(repo, name)
    dot_path = package_path / "workflow.dot"
    workflow_toml_path = package_path / "workflow.toml"

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
    errors = [diagnostic for diagnostic in diagnostics if diagnostic.severity == Severity.ERROR]
    if errors:
        raise WorkflowPackageError(
            "Workflow validation failed",
            detail={
                "repo_path": str(repo),
                "workflow": name,
                "errors": "; ".join(
                    f"{diagnostic.rule}: {diagnostic.message}" for diagnostic in errors
                ),
            },
        )

    project_config = load_project_config(repo / ".attractor" / "project.toml")
    workflow_config = load_workflow_config(workflow_toml_path)

    return WorkflowPackage(
        repo_path=repo,
        name=name,
        package_path=package_path,
        dot_path=dot_path,
        toml_path=workflow_toml_path if workflow_toml_path.exists() else None,
        project_config=project_config,
        workflow_config=workflow_config,
        graph=graph,
        diagnostics=diagnostics,
        status=WorkflowValidationStatus.VALID,
        error=None,
    )


def inspect_workflow_package(repo_path: str | Path, name: str) -> WorkflowPackage:
    """Load a package without raising platform errors."""
    _validate_workflow_name(name)
    try:
        return load_workflow_package(repo_path, name)
    except AttractorPlatformError as exc:
        repo = _repo_path(repo_path)
        package_path = _workflow_dir(repo, name)
        workflow_toml_path = package_path / "workflow.toml"
        try:
            project_config = load_project_config(repo / ".attractor" / "project.toml")
        except AttractorPlatformError:
            project_config = ProjectConfig()

        return WorkflowPackage(
            repo_path=repo,
            name=name,
            package_path=package_path,
            dot_path=package_path / "workflow.dot",
            toml_path=workflow_toml_path if workflow_toml_path.exists() else None,
            project_config=project_config,
            workflow_config=WorkflowConfig(),
            graph=None,
            diagnostics=[],
            status=WorkflowValidationStatus.INVALID,
            error=exc.to_dict(),
        )


def discover_workflow_packages(repo_path: str | Path) -> list[WorkflowPackage]:
    """Discover workflow packages, recording invalid packages without raising."""
    repo = _repo_path(repo_path)
    workflows_dir = repo / ".attractor" / "workflows"
    if not workflows_dir.is_dir():
        return []

    return [
        inspect_workflow_package(repo, child.name)
        for child in sorted(workflows_dir.iterdir(), key=lambda path: path.name)
        if child.is_dir()
    ]
