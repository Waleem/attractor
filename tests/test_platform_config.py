from __future__ import annotations

from pathlib import Path

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
from attractor_platform.paths import (
    default_artifact_root,
    default_platform_data_dir,
    default_worktree_root,
    resolve_platform_roots,
)


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


def test_platform_defaults_use_user_data_dir_outside_cwd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATTRACTOR_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("ATTRACTOR_WORKTREE_ROOT", raising=False)
    monkeypatch.delenv("ATTRACTOR_ARTIFACT_ROOT", raising=False)

    original_is_dir = Path.is_dir

    def fake_is_dir(path: Path) -> bool:
        if path == Path("/data"):
            return False
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)

    assert default_platform_data_dir() == Path.home() / ".local" / "share" / "attractor"
    assert default_worktree_root() == Path.home() / ".local" / "share" / "attractor" / "worktrees"
    assert default_artifact_root() == Path.home() / ".local" / "share" / "attractor" / "artifacts"


def test_platform_defaults_honor_xdg_data_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("ATTRACTOR_RUNNING_IN_DOCKER", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    original_is_dir = Path.is_dir

    def fake_is_dir(path: Path) -> bool:
        if path == Path("/data"):
            return False
        return original_is_dir(path)

    monkeypatch.setattr(Path, "is_dir", fake_is_dir)

    expected = tmp_path / "xdg" / "attractor"
    assert default_platform_data_dir() == expected
    assert default_worktree_root() == expected / "worktrees"
    assert default_artifact_root() == expected / "artifacts"


def test_platform_defaults_use_docker_data_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATTRACTOR_RUNNING_IN_DOCKER", "1")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    assert default_platform_data_dir() == Path("/data/attractor")
    assert default_worktree_root() == Path("/data/attractor/worktrees")
    assert default_artifact_root() == Path("/data/attractor/artifacts")


def test_resolve_platform_roots_honors_explicit_args_and_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    explicit_worktree = tmp_path / "explicit-worktrees"
    explicit_artifact = tmp_path / "explicit-artifacts"
    env_worktree = tmp_path / "env-worktrees"
    env_artifact = tmp_path / "env-artifacts"
    monkeypatch.setenv("ATTRACTOR_WORKTREE_ROOT", str(env_worktree))
    monkeypatch.setenv("ATTRACTOR_ARTIFACT_ROOT", str(env_artifact))

    worktree_root, artifact_root = resolve_platform_roots(
        str(explicit_worktree),
        str(explicit_artifact),
    )

    assert worktree_root == explicit_worktree
    assert artifact_root == explicit_artifact

    env_worktree_root, env_artifact_root = resolve_platform_roots(None, None)

    assert env_worktree_root == env_worktree
    assert env_artifact_root == env_artifact
