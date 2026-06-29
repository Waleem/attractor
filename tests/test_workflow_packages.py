from __future__ import annotations

import pytest

from attractor_platform.errors import WorkflowPackageError
from attractor_platform.packages import (
    WorkflowPackage,
    WorkflowValidationStatus,
    discover_workflow_packages,
    inspect_workflow_package,
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


@pytest.mark.parametrize("name", ["", "/absolute", "../escape", "nested/name", "nested\\name"])
def test_load_workflow_package_rejects_unsafe_workflow_names(tmp_path, name: str) -> None:
    escape_dir = tmp_path / ".attractor" / "escape"
    escape_dir.mkdir(parents=True)
    (escape_dir / "workflow.dot").write_text(VALID_DOT, encoding="utf-8")

    with pytest.raises(WorkflowPackageError) as excinfo:
        load_workflow_package(tmp_path, name)

    assert "Invalid workflow name" in str(excinfo.value)


def test_inspect_workflow_package_rejects_unsafe_workflow_names(tmp_path) -> None:
    with pytest.raises(WorkflowPackageError) as excinfo:
        inspect_workflow_package(tmp_path, "../escape")

    assert "Invalid workflow name" in str(excinfo.value)


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


def test_discover_workflow_packages_sorts_by_name_and_status(tmp_path) -> None:
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
    assert packages["broken"].diagnostics == []
    assert packages["broken"].error is not None
    assert packages["broken"].error["code"] == "workflow_package_invalid"


def test_discover_records_unsafe_workflow_name_without_raising(tmp_path) -> None:
    write_workflow(tmp_path, "good")
    unsafe_dir = tmp_path / ".attractor" / "workflows" / "bad\\name"
    unsafe_dir.mkdir(parents=True)
    (unsafe_dir / "workflow.dot").write_text(VALID_DOT, encoding="utf-8")

    packages = {p.name: p for p in discover_workflow_packages(tmp_path)}

    assert packages["good"].status == WorkflowValidationStatus.VALID
    assert packages["bad\\name"].status == WorkflowValidationStatus.INVALID
    assert packages["bad\\name"].graph is None
    assert packages["bad\\name"].diagnostics == []
    assert packages["bad\\name"].error is not None
    assert packages["bad\\name"].error["code"] == "workflow_package_invalid"
    assert packages["bad\\name"].error["message"] == "Invalid workflow name"


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
    assert packages[0].diagnostics == []
    assert packages[0].project_config.variables == {}
    assert packages[0].error is not None
    assert packages[0].error["code"] == "config_load_failed"


def test_discover_returns_empty_when_workflows_dir_missing(tmp_path) -> None:
    assert discover_workflow_packages(tmp_path) == []
