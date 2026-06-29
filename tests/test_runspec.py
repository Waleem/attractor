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
    workflow_dir = repo / ".attractor" / "workflows" / "build"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(VALID_DOT, encoding="utf-8")
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_read_git_metadata_clean_repo(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    metadata = read_git_metadata(repo)

    assert len(metadata.commit) == 40
    assert metadata.branch in {"main", "master"}
    assert metadata.dirty_state == DirtyState.CLEAN


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_read_git_metadata_dirty_repo(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / "README.md").write_text("# changed\n", encoding="utf-8")

    metadata = read_git_metadata(repo)

    assert metadata.dirty_state == DirtyState.DIRTY


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_build_run_spec_from_workflow_package(tmp_path: Path) -> None:
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
def test_build_run_spec_preserves_requested_and_effective_environment(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".attractor" / "project.toml").write_text(
        """
        default_environment = "local"
        allowed_execution_modes = ["local", "docker"]

        [environments.docker-ci]
        mode = "docker"
        image = "python:3.12-slim"
        """,
        encoding="utf-8",
    )
    (repo / ".attractor" / "workflows" / "build" / "workflow.toml").write_text(
        'default_environment = "docker-ci"\n',
        encoding="utf-8",
    )
    package = load_workflow_package(repo, "build")

    spec = build_run_spec(package)

    assert spec.requested_environment == RunEnvironmentRequest(mode="local", name="local")
    assert spec.effective_environment == RunEnvironmentRequest(
        mode="docker",
        name="docker-ci",
        image="python:3.12-slim",
    )


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_build_run_spec_does_not_policy_check_implicit_requested_environment(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    (repo / ".attractor" / "project.toml").write_text(
        """
        default_environment = "docker-ci"
        allowed_execution_modes = ["docker"]

        [environments.docker-ci]
        mode = "docker"
        image = "python:3.12-slim"
        """,
        encoding="utf-8",
    )
    package = load_workflow_package(repo, "build")

    spec = build_run_spec(package)

    assert spec.requested_environment == RunEnvironmentRequest(mode="local", name="local")
    assert spec.effective_environment == RunEnvironmentRequest(
        mode="docker",
        name="docker-ci",
        image="python:3.12-slim",
    )


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_run_spec_is_immutable(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    spec = build_run_spec(load_workflow_package(repo, "build"))

    with pytest.raises(ValidationError, match="frozen"):
        spec.workflow_name = "changed"  # type: ignore[misc]


def test_run_environment_request_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        RunEnvironmentRequest(mode="kubernetes")  # type: ignore[arg-type]


def test_build_run_spec_rejects_invalid_discovery_record(tmp_path: Path) -> None:
    workflow_dir = tmp_path / ".attractor" / "workflows" / "broken"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text("not a digraph", encoding="utf-8")
    package = inspect_workflow_package(tmp_path, "broken")

    assert package.graph is None
    with pytest.raises(RunSpecError, match="invalid workflow package"):
        build_run_spec(package)


def test_run_spec_can_be_built_directly_for_unit_tests(tmp_path: Path) -> None:
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
