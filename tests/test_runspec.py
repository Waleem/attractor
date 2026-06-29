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
def test_build_run_spec_preserves_explicit_named_environment_request(tmp_path: Path) -> None:
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
    package = load_workflow_package(repo, "build")

    spec = build_run_spec(package, requested_environment="docker-ci")

    assert spec.requested_environment == RunEnvironmentRequest(
        mode="docker",
        name="docker-ci",
        image="python:3.12-slim",
    )
    assert spec.effective_environment == RunEnvironmentRequest(
        mode="docker",
        name="docker-ci",
        image="python:3.12-slim",
    )


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_build_run_spec_unknown_requested_environment_raises_run_spec_error(
    tmp_path: Path,
) -> None:
    repo = make_repo(tmp_path)
    package = load_workflow_package(repo, "build")

    with pytest.raises(RunSpecError, match="not allowed"):
        build_run_spec(package, requested_environment="staging")


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_run_spec_is_immutable(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    spec = build_run_spec(load_workflow_package(repo, "build"))

    with pytest.raises(ValidationError, match="frozen"):
        spec.workflow_name = "changed"  # type: ignore[misc]


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_run_spec_snapshots_inputs_as_immutable_mapping(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    launch_inputs = {"target": "wheel"}

    spec = build_run_spec(load_workflow_package(repo, "build"), inputs=launch_inputs)
    launch_inputs["target"] = "sdist"

    assert spec.inputs == {"target": "wheel"}
    with pytest.raises(TypeError):
        spec.inputs["target"] = "sdist"  # type: ignore[index]


@pytest.mark.skipif(not git_available(), reason="git is required")
@pytest.mark.parametrize("field_name", ["approval_policy", "write_back_policy"])
def test_run_spec_snapshots_policies_as_immutable_mappings(
    tmp_path: Path,
    field_name: str,
) -> None:
    repo = make_repo(tmp_path)
    (repo / ".attractor" / "workflows" / "build" / "workflow.toml").write_text(
        """
        [approval]
        required = true
        reviewers = ["ops"]

        [write_back]
        mode = "branch"
        metadata = { labels = ["automation"] }
        """,
        encoding="utf-8",
    )

    spec = build_run_spec(load_workflow_package(repo, "build"))
    policy = getattr(spec, field_name)

    with pytest.raises(TypeError):
        policy["new"] = "value"  # type: ignore[index]


@pytest.mark.skipif(not git_available(), reason="git is required")
def test_run_spec_snapshots_nested_config_as_immutable_values(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".attractor" / "workflows" / "build" / "workflow.toml").write_text(
        """
        tags = ["release"]

        [inputs]
        target = "wheel"

        [approval]
        reviewers = ["ops"]

        [retention]
        keep_events_days = 7
        keep_artifacts_days = 8

        [artifacts]
        capture = ["logs"]
        max_bytes = 100
        """,
        encoding="utf-8",
    )
    package = load_workflow_package(repo, "build")

    spec = build_run_spec(package)
    package.workflow_config.tags.append("mutated")
    package.workflow_config.inputs["target"] = "sdist"
    package.workflow_config.retention.keep_events_days = 99  # type: ignore[union-attr]
    package.workflow_config.artifacts.capture.append("patches")  # type: ignore[union-attr]

    assert spec.workflow_config.tags == ("release",)
    assert spec.workflow_config.inputs == {"target": "wheel"}
    assert spec.workflow_config.retention is not None
    assert spec.workflow_config.retention.keep_events_days == 7
    assert spec.workflow_config.artifacts is not None
    assert spec.workflow_config.artifacts.capture == ("logs",)

    with pytest.raises(ValidationError, match="frozen"):
        spec.retention.keep_events_days = 1  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        spec.artifact_policy.max_bytes = 1  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        spec.workflow_config.display_name = "changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        spec.workflow_config.inputs["target"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        spec.workflow_config.approval["reviewers"] = []  # type: ignore[index]


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
    assert spec.workflow_config.model_dump(mode="json") == WorkflowConfig().model_dump(mode="json")
