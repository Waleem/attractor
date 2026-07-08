from __future__ import annotations

import datetime as dt
import os
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio

import attractor_platform.indexing as indexing_module
import attractor_server.platform_app as platform_app_module
from attractor_platform.git import GitResult, GitRunner
from attractor_platform.storage.models import RunStatus
from attractor_server.platform_app import (
    _serialize_settings_timestamp,
    _serialize_timestamp,
    create_platform_app,
)

pytestmark = pytest.mark.asyncio


@dataclass
class _Repo:
    id: str
    name: str
    local_path: str
    default_branch: str
    current_commit: str
    dirty_state: str
    project_config_status: str
    created_at: dt.datetime
    updated_at: dt.datetime
    last_indexed_at: dt.datetime | None


@dataclass
class _Workflow:
    id: str
    repo_id: str
    name: str
    dot_path: str
    toml_path: str | None
    status: str
    diagnostics: dict[str, Any]
    indexed_at: dt.datetime


@dataclass
class _Run:
    id: str
    repo_id: str | None
    workflow_id: str | None
    run_spec: dict[str, Any]
    actor_label: str
    source_commit: str
    source_branch: str
    status: str
    worktree_path: str | None
    managed_branch: str | None
    error_category: str | None
    error_message: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None


@dataclass
class _Event:
    sequence: int
    event_type: str
    payload: dict[str, Any]
    actor_label: str
    created_at: dt.datetime


class _Repository:
    def __init__(self) -> None:
        self.repos: dict[str, _Repo] = {}
        self.workflows: dict[str, _Workflow] = {}
        self.runs: dict[str, _Run] = {}
        self.events: dict[str, list[_Event]] = {}
        self.artifacts: dict[str, list[Any]] = {}

    async def register_repo(
        self,
        repo_id: str,
        name: str,
        local_path: str,
        default_branch: str,
        current_commit: str,
        dirty_state: str,
        timestamp: dt.datetime,
        project_config_status: str = "valid",
    ) -> _Repo:
        repo = _Repo(
            id=repo_id,
            name=name,
            local_path=local_path,
            default_branch=default_branch,
            current_commit=current_commit,
            dirty_state=dirty_state,
            project_config_status=project_config_status,
            created_at=timestamp,
            updated_at=timestamp,
            last_indexed_at=timestamp,
        )
        self.repos[repo_id] = repo
        return repo

    async def list_repos(self) -> list[_Repo]:
        return list(self.repos.values())

    async def get_repo(self, repo_id: str) -> _Repo | None:
        return self.repos.get(repo_id)

    async def delete_repo(self, repo_id: str) -> bool:
        if repo_id not in self.repos:
            return False
        for run in self.runs.values():
            if run.repo_id == repo_id:
                run.repo_id = None
            if run.workflow_id in {
                workflow.id for workflow in self.workflows.values() if workflow.repo_id == repo_id
            }:
                run.workflow_id = None
        for workflow_id, workflow in list(self.workflows.items()):
            if workflow.repo_id == repo_id:
                del self.workflows[workflow_id]
        del self.repos[repo_id]
        return True

    async def update_repo_index_metadata(
        self,
        repo_id: str,
        *,
        default_branch: str,
        current_commit: str,
        dirty_state: str,
        timestamp: dt.datetime,
    ) -> _Repo:
        repo = self.repos[repo_id]
        repo.default_branch = default_branch
        repo.current_commit = current_commit
        repo.dirty_state = dirty_state
        repo.updated_at = timestamp
        repo.last_indexed_at = timestamp
        return repo

    async def upsert_workflow(
        self,
        workflow_id: str,
        repo_id: str,
        name: str,
        dot_path: str,
        toml_path: str | None,
        status: str,
        diagnostics: dict[str, Any],
        timestamp: dt.datetime,
    ) -> _Workflow:
        workflow = _Workflow(
            id=workflow_id,
            repo_id=repo_id,
            name=name,
            dot_path=dot_path,
            toml_path=toml_path,
            status=status,
            diagnostics=diagnostics,
            indexed_at=timestamp,
        )
        self.workflows[workflow_id] = workflow
        return workflow

    async def list_workflows(self, repo_id: str) -> list[_Workflow]:
        return [workflow for workflow in self.workflows.values() if workflow.repo_id == repo_id]

    async def get_workflow(self, workflow_id: str) -> _Workflow | None:
        return self.workflows.get(workflow_id)

    async def delete_workflows_not_in(self, repo_id: str, workflow_ids: set[str]) -> int:
        removed = 0
        for workflow_id, workflow in list(self.workflows.items()):
            if workflow.repo_id != repo_id or workflow_id in workflow_ids:
                continue
            if any(run.workflow_id == workflow_id for run in self.runs.values()):
                continue
            del self.workflows[workflow_id]
            removed += 1
        return removed

    async def create_run(
        self,
        *,
        run_id: str,
        repo_id: str,
        workflow_id: str,
        run_spec: dict[str, Any],
        actor_label: str,
        source_commit: str,
        source_branch: str,
        timestamp: dt.datetime,
    ) -> _Run:
        run = _Run(
            id=run_id,
            repo_id=repo_id,
            workflow_id=workflow_id,
            run_spec=run_spec,
            actor_label=actor_label,
            source_commit=source_commit,
            source_branch=source_branch,
            status=RunStatus.QUEUED.value,
            worktree_path=None,
            managed_branch=None,
            error_category=None,
            error_message=None,
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.runs[run_id] = run
        self.events[run_id] = []
        return run

    async def get_run(self, run_id: str) -> _Run | None:
        return self.runs.get(run_id)

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: dt.datetime | None = None,
    ) -> _Event:
        event = _Event(
            sequence=len(self.events[run_id]) + 1,
            event_type=event_type,
            payload=payload,
            actor_label=actor_label,
            created_at=timestamp or dt.datetime.now(dt.UTC),
        )
        self.events[run_id].append(event)
        return event

    async def list_events(self, run_id: str, after_sequence: int, limit: int) -> list[_Event]:
        return [
            event for event in self.events[run_id] if event.sequence > after_sequence
        ][:limit]


class _Executor:
    def __init__(self, repository: _Repository) -> None:
        self.repository = repository
        self.active_tasks: dict[str, Any] = {}
        self.max_concurrent_runs = 3
        self._run_number = 0
        self.git: GitRunner = GitRunner()
        self._artifact_root: Path | None = None

    async def register_and_launch(
        self,
        *,
        repo_path: str,
        workflow_name: str,
        actor_label: str,
        inputs: dict[str, str],
        requested_environment: str = "",
    ) -> str:
        repo = next(repo for repo in self.repository.repos.values() if repo.local_path == repo_path)
        now = dt.datetime.now(dt.UTC)
        await self.repository.register_repo(
            repo_id=repo.id,
            name=repo.name,
            local_path=repo.local_path,
            default_branch=repo.default_branch,
            current_commit=repo.current_commit,
            dirty_state=repo.dirty_state,
            timestamp=now,
            project_config_status=repo.project_config_status,
        )
        workflow = next(
            workflow
            for workflow in self.repository.workflows.values()
            if workflow.repo_id == repo.id and workflow.name == workflow_name
        )
        self._run_number += 1
        run_id = f"run_{self._run_number:04d}"
        await self.repository.create_run(
            run_id=run_id,
            repo_id=repo.id,
            workflow_id=workflow.id,
            run_spec={
                "run_id": run_id,
                "repo_path": repo_path,
                "workflow_name": workflow_name,
                "actor_label": actor_label,
                "inputs": inputs,
                "requested_environment": {
                    "mode": requested_environment or "local",
                    "name": requested_environment or "local",
                    "image": "",
                },
            },
            actor_label=actor_label,
            source_commit=repo.current_commit,
            source_branch=repo.default_branch,
            timestamp=now,
        )
        await self.repository.append_event(
            run_id,
            "run.queued",
            {"workflow_name": workflow_name, "repo_path": repo_path, "actor_label": actor_label},
            actor_label=actor_label,
            timestamp=now,
        )
        return run_id


@dataclass
class _Harness:
    client: httpx.AsyncClient
    repository: _Repository
    executor: _Executor


class _RecordingGitRunner(GitRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, repo_path: str | Path, *args: str) -> GitResult:
        self.calls.append(args)
        if args == ("rev-parse", "HEAD"):
            return GitResult(stdout="head-commit", stderr="")
        if args == ("rev-parse", "run-branch"):
            return GitResult(stdout="head-commit", stderr="")
        if args[:3] == ("diff", "--name-only", "--find-renames"):
            return GitResult(stdout="alpha.txt\nbeta.txt\ngamma.txt", stderr="")
        if args[:3] == ("diff", "--name-status", "--find-renames"):
            path = args[-1]
            return GitResult(stdout=f"A\t{path}", stderr="")
        if args[:3] == ("diff", "--numstat", "--find-renames"):
            path = args[-1]
            return GitResult(stdout=f"1\t0\t{path}", stderr="")
        raise AssertionError(f"Unexpected git args: {args!r}")


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)
    workflow_dir = repo_path / ".attractor" / "workflows" / "release"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          generate [shape=box, handler="noop"]
          done [shape=Msquare]
          start -> generate -> done
        }
        """,
        encoding="utf-8",
    )
    (repo_path / ".attractor" / "project.toml").write_text(
        'default_environment = "local"\nallowed_execution_modes = ["local"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


@pytest_asyncio.fixture
async def platform_harness() -> AsyncIterator[_Harness]:
    repository = _Repository()
    executor = _Executor(repository)
    app = create_platform_app(session_factory=cast(Any, None), executor=cast(Any, executor))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield _Harness(client=client, repository=repository, executor=executor)


async def _register_repo(harness: _Harness, repo_path: Path) -> None:
    response = await harness.client.post(
        "/api/repos",
        json={"name": "sample", "local_path": str(repo_path)},
    )
    assert response.status_code == 201


def _git_commit(repo_path: Path, message: str) -> str:
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


async def test_create_run_preserves_typed_launch_metadata_and_queues_event(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)

    response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
            "inputs": {"ticket": "TASK-3"},
            "requested_environment": "docker",
        },
    )

    assert response.status_code == 201
    run_id = response.json()["id"]
    run = platform_harness.repository.runs[run_id]
    assert run.run_spec["repo_path"] == str(sample_repo)
    assert run.run_spec["workflow_name"] == "release"
    assert run.run_spec["actor_label"] == "alice"
    assert run.run_spec["inputs"] == {"ticket": "TASK-3"}
    assert run.run_spec["requested_environment"] == {
        "mode": "docker",
        "name": "docker",
        "image": "",
    }
    events_response = await platform_harness.client.get(f"/api/runs/{run_id}/events")
    assert events_response.status_code == 200
    assert events_response.json()["items"][0]["event_type"] == "run.queued"


async def test_unregister_repo_removes_registration_and_workflow_index(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    repo_id = next(iter(platform_harness.repository.repos))

    response = await platform_harness.client.delete(f"/api/repos/{repo_id}")
    repos_response = await platform_harness.client.get("/api/repos")
    workflows_response = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")

    assert response.status_code == 200
    assert response.json() == {"id": repo_id, "deleted": True}
    assert repos_response.status_code == 200
    assert repos_response.json()["items"] == []
    assert workflows_response.status_code == 404
    assert platform_harness.repository.workflows == {}


async def test_unregister_repo_preserves_runs_by_clearing_repo_and_workflow_links(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    repo_id = next(iter(platform_harness.repository.repos))

    run_response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
            "inputs": {},
        },
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    delete_response = await platform_harness.client.delete(f"/api/repos/{repo_id}")
    run_detail_response = await platform_harness.client.get(f"/api/runs/{run_id}")

    assert delete_response.status_code == 200
    assert run_detail_response.status_code == 200
    assert run_detail_response.json()["repo_id"] is None
    assert run_detail_response.json()["workflow_id"] is None
    assert run_id in platform_harness.repository.runs


async def test_create_run_rejects_non_string_input_values(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)

    response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
            "inputs": {"ticket": 3},
        },
    )

    assert response.status_code == 400
    assert "inputs" in response.json()["error"]


async def test_create_run_rejects_non_object_json_body(
    platform_harness: _Harness,
) -> None:
    response = await platform_harness.client.post(
        "/api/runs",
        json=["not", "an", "object"],
    )

    assert response.status_code == 400
    assert "object" in response.json()["error"]


async def test_create_run_rejects_non_string_requested_environment(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)

    response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
            "inputs": {},
            "requested_environment": {"mode": "local"},
        },
    )

    assert response.status_code == 400
    assert "requested_environment" in response.json()["error"]


async def test_fs_browse_lists_directory_metadata_without_file_contents(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    nested_repo = sample_repo / "packages" / "tool"
    nested_repo.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=nested_repo, check=True, stdout=subprocess.DEVNULL)
    (sample_repo / "README.md").write_text("secret file content\n", encoding="utf-8")
    (sample_repo / ".venv").mkdir()
    (sample_repo / "node_modules").mkdir()
    await _register_repo(platform_harness, sample_repo)

    response = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(sample_repo)},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(sample_repo.resolve())
    assert body["truncated"] is False
    entries = body["items"]
    assert entries[:1] == [
        {
            "name": "packages",
            "path": str((sample_repo / "packages").resolve()),
            "kind": "directory",
            "is_git_repo": False,
        }
    ]
    assert {
        "name": "README.md",
        "path": str((sample_repo / "README.md").resolve()),
        "kind": "file",
        "is_git_repo": False,
    } in entries
    assert not any(
        entry["name"] in {".git", ".attractor", ".venv", "node_modules"} for entry in entries
    )
    assert "secret file content" not in response.text

    nested_response = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(sample_repo / "packages")},
    )
    assert nested_response.status_code == 200
    assert nested_response.json()["items"] == [
        {
            "name": "tool",
            "path": str(nested_repo.resolve()),
            "kind": "directory",
            "is_git_repo": True,
        }
    ]


async def test_fs_browse_default_root_rejects_non_directory_and_escape(
    platform_harness: _Harness,
    sample_repo: Path,
    tmp_path: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    symlink = sample_repo / "outside-link"
    symlink.symlink_to(outside, target_is_directory=True)

    missing = await platform_harness.client.get("/api/fs/browse")
    assert missing.status_code == 200
    assert missing.json()["path"] == str(sample_repo.resolve())
    assert missing.json()["roots"] == [str(sample_repo.resolve())]

    file_response = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(sample_repo / ".attractor" / "project.toml")},
    )
    assert file_response.status_code == 400
    assert "directory" in file_response.json()["error"]

    parent_response = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(sample_repo / "..")},
    )
    assert parent_response.status_code == 403
    assert "not allowed" in parent_response.json()["error"]

    symlink_response = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(symlink)},
    )
    assert symlink_response.status_code == 403
    assert "not allowed" in symlink_response.json()["error"]


async def test_fs_browse_uses_registration_roots_when_no_repo_or_run_roots_exist(
    platform_harness: _Harness,
) -> None:
    response = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(Path.home())},
    )

    assert response.status_code == 200
    assert response.json()["path"] == str(Path.home().resolve())
    assert str(Path.home().resolve()) in response.json()["roots"]


async def test_fs_browse_registration_mode_lists_configured_roots_without_registered_repos(
    platform_harness: _Harness,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registration_root = tmp_path / "registration-root"
    registration_root.mkdir()
    (registration_root / "alpha").mkdir()
    (registration_root / ".hidden").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (registration_root / "escape-link").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("ATTRACTOR_BROWSE_ROOTS", str(registration_root))

    response = await platform_harness.client.get(
        "/api/fs/browse",
        params={"mode": "registration"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["path"] == str(registration_root.resolve())
    assert body["roots"][0] == str(registration_root.resolve())
    assert {
        "name": "alpha",
        "path": str((registration_root / "alpha").resolve()),
        "kind": "directory",
        "is_git_repo": False,
    } in body["items"]
    assert not any(entry["name"] in {".hidden", "escape-link"} for entry in body["items"])


async def test_fs_browse_registration_mode_allows_unregistered_roots_even_when_repos_exist(
    platform_harness: _Harness,
    sample_repo: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    registration_root = tmp_path / "registration-root"
    registration_root.mkdir()
    (registration_root / "alpha").mkdir()
    monkeypatch.setenv("ATTRACTOR_BROWSE_ROOTS", str(registration_root))

    rejected = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(registration_root)},
    )
    assert rejected.status_code == 403

    allowed = await platform_harness.client.get(
        "/api/fs/browse",
        params={"path": str(registration_root), "mode": "registration"},
    )
    assert allowed.status_code == 200
    assert allowed.json()["items"] == [
        {
            "name": "alpha",
            "path": str((registration_root / "alpha").resolve()),
            "kind": "directory",
            "is_git_repo": False,
        }
    ]


async def test_register_repo_preserves_custom_name_after_refresh_and_launch(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    register_response = await platform_harness.client.post(
        "/api/repos",
        json={"name": "Custom Name", "local_path": str(sample_repo)},
    )
    assert register_response.status_code == 201
    repo_id = register_response.json()["id"]

    refresh_response = await platform_harness.client.post(f"/api/repos/{repo_id}/refresh")
    assert refresh_response.status_code == 200
    assert refresh_response.json()["repo"]["name"] == "Custom Name"

    create_run_response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
        },
    )
    assert create_run_response.status_code == 201

    list_response = await platform_harness.client.get("/api/repos")
    assert list_response.status_code == 200
    assert [repo["name"] for repo in list_response.json()["items"]] == ["Custom Name"]

    detail_response = await platform_harness.client.get(f"/api/repos/{repo_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["name"] == "Custom Name"


async def test_run_responses_include_run_spec_for_re_run(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    create_response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
            "inputs": {"ticket": "TASK-9"},
            "requested_environment": "local",
        },
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]

    response = await platform_harness.client.get(f"/api/runs/{run_id}")

    assert response.status_code == 200
    assert response.json()["run_spec"] == {
        "run_id": run_id,
        "repo_path": str(sample_repo),
        "workflow_name": "release",
        "actor_label": "alice",
        "inputs": {"ticket": "TASK-9"},
        "requested_environment": {
            "mode": "local",
            "name": "local",
            "image": "",
        },
    }


async def test_timestamp_serializers_emit_explicit_utc_z_suffix() -> None:
    naive = dt.datetime(2026, 7, 3, 12, 0, 0)
    aware = dt.datetime(2026, 7, 3, 5, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=-7)))

    assert _serialize_timestamp(naive) == "2026-07-03T12:00:00Z"
    assert _serialize_timestamp(aware) == "2026-07-03T12:00:00Z"
    assert _serialize_settings_timestamp(naive) == "2026-07-03T12:00:00Z"
    assert _serialize_settings_timestamp(aware) == "2026-07-03T12:00:00Z"


async def test_list_runs_filters_by_status_and_repo_id(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    first = await platform_harness.client.post(
        "/api/runs",
        json={"repo_path": str(sample_repo), "workflow_name": "release", "actor_label": "alice"},
    )
    second = await platform_harness.client.post(
        "/api/runs",
        json={"repo_path": str(sample_repo), "workflow_name": "release", "actor_label": "bob"},
    )
    assert first.status_code == 201
    assert second.status_code == 201
    platform_harness.repository.runs[first.json()["id"]].status = RunStatus.COMPLETED.value
    platform_harness.repository.runs[second.json()["id"]].status = RunStatus.FAILED.value

    response = await platform_harness.client.get(
        "/api/runs",
        params={
            "status": RunStatus.FAILED.value,
            "repo_id": next(iter(platform_harness.repository.repos)),
        },
    )

    assert response.status_code == 200
    assert [run["id"] for run in response.json()["items"]] == [second.json()["id"]]


async def test_get_run_diff_returns_bounded_file_metadata(
    platform_harness: _Harness,
    sample_repo: Path,
    tmp_path: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    create_response = await platform_harness.client.post(
        "/api/runs",
        json={"repo_path": str(sample_repo), "workflow_name": "release", "actor_label": "alice"},
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]
    source_commit = platform_harness.repository.runs[run_id].source_commit
    worktree_path = tmp_path / "run-worktree"
    subprocess.run(
        ["git", "worktree", "add", "-b", "run-branch", str(worktree_path), source_commit],
        cwd=sample_repo,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    (worktree_path / "generated.txt").write_text("new line\n", encoding="utf-8")
    head_commit = _git_commit(worktree_path, "generated")
    platform_harness.repository.runs[run_id].status = RunStatus.COMPLETED.value
    platform_harness.repository.runs[run_id].worktree_path = str(worktree_path)
    platform_harness.repository.runs[run_id].managed_branch = "run-branch"

    response = await platform_harness.client.get(f"/api/runs/{run_id}/diff")

    assert response.status_code == 200
    assert response.json() == {
        "run_id": run_id,
        "base_commit": source_commit,
        "head_commit": head_commit,
        "truncated": False,
        "files": [
            {
                "path": "generated.txt",
                "status": "added",
                "additions": 1,
                "deletions": 0,
            }
        ],
    }


async def test_get_run_diff_rejects_run_without_owned_worktree(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    create_response = await platform_harness.client.post(
        "/api/runs",
        json={"repo_path": str(sample_repo), "workflow_name": "release", "actor_label": "alice"},
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]
    (sample_repo / "unrelated.txt").write_text("unrelated\n", encoding="utf-8")
    _git_commit(sample_repo, "unrelated repo advance")
    platform_harness.repository.runs[run_id].status = RunStatus.FAILED.value

    response = await platform_harness.client.get(f"/api/runs/{run_id}/diff")

    assert response.status_code == 409
    assert "worktree" in response.json()["error"]


async def test_get_run_diff_limits_git_diff_work_to_requested_files(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    create_response = await platform_harness.client.post(
        "/api/runs",
        json={"repo_path": str(sample_repo), "workflow_name": "release", "actor_label": "alice"},
    )
    assert create_response.status_code == 201
    run_id = create_response.json()["id"]
    run = platform_harness.repository.runs[run_id]
    run.status = RunStatus.COMPLETED.value
    fake_worktree = sample_repo / "run-owned-worktree"
    fake_worktree.mkdir()
    run.worktree_path = str(fake_worktree)
    run.managed_branch = "run-branch"
    git = _RecordingGitRunner()
    platform_harness.executor.git = git

    response = await platform_harness.client.get(
        f"/api/runs/{run_id}/diff",
        params={"limit": "1"},
    )

    assert response.status_code == 200
    assert response.json()["truncated"] is True
    assert [file["path"] for file in response.json()["files"]] == ["alpha.txt"]
    assert (
        "diff",
        "--name-only",
        "--find-renames",
        run.source_commit,
        "head-commit",
        "--",
    ) in git.calls
    assert not any(
        call[:3] == ("diff", "--name-status", "--find-renames") and call[-1] == "--"
        for call in git.calls
    )
    assert not any(
        call[:3] == ("diff", "--numstat", "--find-renames") and call[-1] == "--"
        for call in git.calls
    )
    assert sum(1 for call in git.calls if call[-1] in {"alpha.txt", "beta.txt"}) == 2


async def test_refresh_repo_indexes_new_workflow_added_after_registration(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    release_workflow_dir = sample_repo / ".attractor" / "workflows" / "hotfix"
    release_workflow_dir.mkdir(parents=True)
    (release_workflow_dir / "workflow.dot").write_text(
        """
        digraph Hotfix {
          graph [goal="ship hotfix"]
          start [shape=Mdiamond]
          apply [shape=box, handler="noop"]
          done [shape=Msquare]
          start -> apply -> done
        }
        """,
        encoding="utf-8",
    )

    repo_id = next(iter(platform_harness.repository.repos))
    response = await platform_harness.client.post(f"/api/repos/{repo_id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_count"] == 2
    assert body["removed_workflow_count"] == 0
    assert body["changed"] is True
    workflows_response = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    assert workflows_response.status_code == 200
    assert {workflow["name"] for workflow in workflows_response.json()} == {"release", "hotfix"}


async def test_refresh_repo_accepts_force_false_and_keeps_manual_force_default(
    platform_harness: _Harness,
    sample_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    repo_id = next(iter(platform_harness.repository.repos))

    def fail_discovery(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise AssertionError("unchanged refresh/list should not parse workflow packages")

    monkeypatch.setattr(indexing_module, "discover_workflow_packages", fail_discovery)
    monkeypatch.setattr(platform_app_module, "discover_workflow_packages", fail_discovery)
    gated_response = await platform_harness.client.post(
        f"/api/repos/{repo_id}/refresh",
        json={"force": False},
    )

    assert gated_response.status_code == 200
    assert gated_response.json()["workflow_count"] == 1
    assert gated_response.json()["removed_workflow_count"] == 0
    assert gated_response.json()["changed"] is False
    assert len(gated_response.json()["active_workflow_ids"]) == 1
    workflows_response = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    assert workflows_response.status_code == 200
    assert [workflow["name"] for workflow in workflows_response.json()] == ["release"]

    monkeypatch.undo()
    forced_response = await platform_harness.client.post(
        f"/api/repos/{repo_id}/refresh",
        json={"force": True},
    )
    default_response = await platform_harness.client.post(f"/api/repos/{repo_id}/refresh")

    assert forced_response.status_code == 200
    assert forced_response.json()["changed"] is True
    assert default_response.status_code == 200
    assert default_response.json()["changed"] is True


async def test_refresh_repo_force_false_reindexes_when_workflow_tree_changes(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    repo_id = next(iter(platform_harness.repository.repos))
    hotfix_workflow_dir = sample_repo / ".attractor" / "workflows" / "hotfix"
    hotfix_workflow_dir.mkdir(parents=True)
    hotfix_dot = hotfix_workflow_dir / "workflow.dot"
    hotfix_dot.write_text(
        """
        digraph Hotfix {
          graph [goal="ship hotfix"]
          start [shape=Mdiamond]
          apply [shape=box, handler="noop"]
          done [shape=Msquare]
          start -> apply -> done
        }
        """,
        encoding="utf-8",
    )
    future_ns = int((dt.datetime.now(dt.UTC) + dt.timedelta(seconds=5)).timestamp() * 1_000_000_000)
    os.utime(sample_repo / ".attractor" / "workflows", ns=(future_ns, future_ns))
    os.utime(hotfix_workflow_dir, ns=(future_ns, future_ns))
    os.utime(hotfix_dot, ns=(future_ns, future_ns))

    response = await platform_harness.client.post(
        f"/api/repos/{repo_id}/refresh",
        json={"force": False},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changed"] is True
    assert body["workflow_count"] == 2
    workflows_response = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    assert workflows_response.status_code == 200
    assert {workflow["name"] for workflow in workflows_response.json()} == {"release", "hotfix"}


async def test_refresh_repo_clears_stale_diagnostics_after_invalid_workflow_is_fixed(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    workflow_dot = sample_repo / ".attractor" / "workflows" / "release" / "workflow.dot"
    workflow_dot.write_text("not a digraph", encoding="utf-8")

    repo_id = next(iter(platform_harness.repository.repos))
    broken_response = await platform_harness.client.post(f"/api/repos/{repo_id}/refresh")
    assert broken_response.status_code == 200
    broken_workflows = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    assert broken_workflows.status_code == 200
    broken_release = next(
        workflow for workflow in broken_workflows.json() if workflow["name"] == "release"
    )
    assert broken_release["status"] == "invalid"
    assert broken_release["diagnostics"]["error"]["message"] == "Unable to parse workflow.dot"

    workflow_dot.write_text(
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          generate [shape=box, handler="noop"]
          done [shape=Msquare]
          start -> generate -> done
        }
        """,
        encoding="utf-8",
    )

    fixed_response = await platform_harness.client.post(f"/api/repos/{repo_id}/refresh")
    assert fixed_response.status_code == 200
    fixed_workflows = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    assert fixed_workflows.status_code == 200
    fixed_release = next(
        workflow for workflow in fixed_workflows.json() if workflow["name"] == "release"
    )
    assert fixed_release["status"] == "valid"
    assert "error" not in fixed_release["diagnostics"]
    assert all(
        "Unable to parse workflow.dot" not in item["message"]
        for item in fixed_release["diagnostics"]["items"]
    )


async def test_refresh_repo_deletes_stale_workflow_rows_for_removed_workflow(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    repo_id = next(iter(platform_harness.repository.repos))
    removed_workflow_dir = sample_repo / ".attractor" / "workflows" / "release"
    for path in sorted(removed_workflow_dir.rglob("*"), reverse=True):
        if path.is_file():
            path.unlink()
    removed_workflow_dir.rmdir()

    response = await platform_harness.client.post(f"/api/repos/{repo_id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_count"] == 0
    assert body["removed_workflow_count"] == 1
    assert body["changed"] is True
    workflows_response = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    assert workflows_response.status_code == 200
    assert workflows_response.json() == []


async def test_refresh_repo_keeps_referenced_stale_workflow_for_run_history(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness, sample_repo)
    repo_id = next(iter(platform_harness.repository.repos))
    historical_workflow_id = "wf_historical"
    orphan_workflow_id = "wf_orphan"
    now = dt.datetime.now(dt.UTC)

    await platform_harness.repository.upsert_workflow(
        workflow_id=historical_workflow_id,
        repo_id=repo_id,
        name="historical",
        dot_path=str(sample_repo / ".attractor" / "workflows" / "historical" / "workflow.dot"),
        toml_path=None,
        status="valid",
        diagnostics={},
        timestamp=now,
    )
    await platform_harness.repository.upsert_workflow(
        workflow_id=orphan_workflow_id,
        repo_id=repo_id,
        name="orphan",
        dot_path=str(sample_repo / ".attractor" / "workflows" / "orphan" / "workflow.dot"),
        toml_path=None,
        status="valid",
        diagnostics={},
        timestamp=now,
    )
    run = await platform_harness.repository.create_run(
        run_id="run_historical",
        repo_id=repo_id,
        workflow_id=historical_workflow_id,
        run_spec={},
        actor_label="alice",
        source_commit="1" * 40,
        source_branch="main",
        timestamp=now,
    )

    response = await platform_harness.client.post(f"/api/repos/{repo_id}/refresh")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_count"] == 1
    assert body["removed_workflow_count"] == 1
    assert body["changed"] is True
    assert historical_workflow_id not in body["active_workflow_ids"]
    workflows_response = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    assert workflows_response.status_code == 200
    assert {workflow["name"] for workflow in workflows_response.json()} == {"release"}
    assert historical_workflow_id in platform_harness.repository.workflows
    assert orphan_workflow_id not in platform_harness.repository.workflows
    run_response = await platform_harness.client.get(f"/api/runs/{run.id}")
    assert run_response.status_code == 200
    assert run_response.json()["workflow_id"] == historical_workflow_id
