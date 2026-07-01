from __future__ import annotations

import asyncio
import datetime as dt
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio

from attractor_platform.storage.models import RunStatus
from attractor_server.platform_app import create_platform_app

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
    repo_id: str
    workflow_id: str
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


@dataclass
class _Artifact:
    id: str
    run_id: str
    kind: str
    name: str
    uri: str
    media_type: str
    size_bytes: int
    sha256: str
    created_at: dt.datetime


@dataclass
class _Checkpoint:
    id: str
    run_id: str
    node_id: str
    stage_index: int
    commit_sha: str
    ref_name: str
    created_at: dt.datetime


class _InMemoryPlatformRepository:
    def __init__(self) -> None:
        self.repos: dict[str, _Repo] = {}
        self.workflows: dict[str, _Workflow] = {}
        self.runs: dict[str, _Run] = {}
        self.events: dict[str, list[_Event]] = {}
        self.artifacts: dict[str, list[_Artifact]] = {}
        self.checkpoints: dict[str, list[_Checkpoint]] = {}

    async def register_repo(
        self,
        repo_id: str,
        name: str,
        local_path: str,
        default_branch: str,
        current_commit: str,
        dirty_state: str,
        timestamp: dt.datetime,
    ) -> _Repo:
        existing = self.repos.get(repo_id)
        repo = _Repo(
            id=repo_id,
            name=name,
            local_path=local_path,
            default_branch=default_branch,
            current_commit=current_commit,
            dirty_state=dirty_state,
            project_config_status="valid",
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
            last_indexed_at=timestamp,
        )
        self.repos[repo_id] = repo
        return repo

    async def list_repos(self) -> list[_Repo]:
        return sorted(self.repos.values(), key=lambda repo: repo.name)

    async def get_repo(self, repo_id: str) -> _Repo | None:
        return self.repos.get(repo_id)

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
        return sorted(
            [workflow for workflow in self.workflows.values() if workflow.repo_id == repo_id],
            key=lambda workflow: workflow.name,
        )

    async def get_workflow(self, workflow_id: str) -> _Workflow | None:
        return self.workflows.get(workflow_id)

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
        self.artifacts[run_id] = []
        self.checkpoints[run_id] = []
        return run

    async def list_runs(self) -> list[_Run]:
        return sorted(self.runs.values(), key=lambda run: run.created_at)

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

    async def list_artifacts(self, run_id: str) -> list[_Artifact]:
        return list(self.artifacts[run_id])

    async def list_checkpoints(self, run_id: str) -> list[_Checkpoint]:
        return list(self.checkpoints[run_id])


class _FakeExecutor:
    def __init__(self, repository: _InMemoryPlatformRepository) -> None:
        self.repository = repository
        self.active_tasks: dict[str, asyncio.Task[Any]] = {}
        self.max_concurrent_runs = 3
        self._run_number = 0

    async def register_and_launch(
        self,
        *,
        repo_path: str,
        workflow_name: str,
        actor_label: str,
        inputs: dict[str, str],
    ) -> str:
        repo = next(repo for repo in self.repository.repos.values() if repo.local_path == repo_path)
        workflow = next(
            workflow
            for workflow in self.repository.workflows.values()
            if workflow.repo_id == repo.id and workflow.name == workflow_name
        )
        self._run_number += 1
        run_id = f"run_{self._run_number:04d}"
        now = dt.datetime.now(dt.UTC)
        await self.repository.create_run(
            run_id=run_id,
            repo_id=repo.id,
            workflow_id=workflow.id,
            run_spec={
                "run_id": run_id,
                "repo_path": repo_path,
                "workflow_name": workflow_name,
                "inputs": inputs,
            },
            actor_label=actor_label,
            source_commit=repo.current_commit,
            source_branch=repo.default_branch,
            timestamp=now,
        )
        await self.repository.append_event(
            run_id,
            "run.queued",
            {"workflow_name": workflow_name, "repo_path": repo_path},
            actor_label=actor_label,
            timestamp=now,
        )
        return run_id


@dataclass
class _Harness:
    client: httpx.AsyncClient
    repository: _InMemoryPlatformRepository
    executor: _FakeExecutor


@pytest.fixture
def sample_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, stdout=subprocess.DEVNULL)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=repo_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)

    workflows = repo_path / ".attractor" / "workflows" / "release"
    workflows.mkdir(parents=True)
    (workflows / "workflow.dot").write_text(
        """
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          build [shape=box, handler="noop"]
          done [shape=Msquare]
          start -> build -> done
        }
        """,
        encoding="utf-8",
    )
    (repo_path / ".attractor" / "project.toml").write_text(
        'default_environment = "local"\nallowed_execution_modes = ["local"]\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        stdout=subprocess.DEVNULL,
    )
    return repo_path


@pytest_asyncio.fixture
async def platform_harness() -> AsyncIterator[_Harness]:
    repository = _InMemoryPlatformRepository()
    executor = _FakeExecutor(repository)
    app = create_platform_app(session_factory=cast(Any, None), executor=cast(Any, executor))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield _Harness(client=client, repository=repository, executor=executor)


async def _register_repo(client: httpx.AsyncClient, sample_repo: Path) -> dict[str, Any]:
    response = await client.post(
        "/api/repos",
        json={"name": "sample", "local_path": str(sample_repo)},
    )
    assert response.status_code == 201
    return response.json()


async def _launch_run(client: httpx.AsyncClient, sample_repo: Path) -> dict[str, Any]:
    response = await client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
            "inputs": {},
        },
    )
    assert response.status_code == 201
    return response.json()


async def test_platform_health(platform_harness: _Harness) -> None:
    response = await platform_harness.client.get("/api/system/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_register_repo_and_list_workflows(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    repo = await _register_repo(platform_harness.client, sample_repo)
    repo_id = repo["id"]

    workflows = await platform_harness.client.get(f"/api/repos/{repo_id}/workflows")
    repos = await platform_harness.client.get("/api/repos")
    repo_detail = await platform_harness.client.get(f"/api/repos/{repo_id}")
    project_config = await platform_harness.client.get(f"/api/repos/{repo_id}/project-config")

    assert workflows.status_code == 200
    assert workflows.json()[0]["name"] == "release"
    assert workflows.json()[0]["status"] == "valid"
    assert repos.status_code == 200
    assert repos.json()["items"][0]["id"] == repo_id
    assert repo_detail.status_code == 200
    assert repo_detail.json()["local_path"] == str(sample_repo.resolve())
    assert project_config.status_code == 200
    assert project_config.json()["config"]["default_environment"] == "local"


async def test_launch_run_returns_durable_id(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness.client, sample_repo)

    run = await _launch_run(platform_harness.client, sample_repo)
    run_detail = await platform_harness.client.get(f"/api/runs/{run['id']}")
    runs = await platform_harness.client.get("/api/runs")

    assert run["id"].startswith("run_")
    assert run["workflow_id"].startswith("wf_")
    assert run_detail.status_code == 200
    assert run_detail.json()["id"] == run["id"]
    assert runs.status_code == 200
    assert [item["id"] for item in runs.json()["items"]] == [run["id"]]


async def test_launch_run_accepts_legacy_workflow_field(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness.client, sample_repo)

    response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow": "release",
            "actor_label": "alice",
            "inputs": {},
        },
    )

    assert response.status_code == 201
    assert response.json()["id"].startswith("run_")


async def test_validate_workflow_and_run_collections(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    repo = await _register_repo(platform_harness.client, sample_repo)
    workflow = (await platform_harness.client.get(f"/api/repos/{repo['id']}/workflows")).json()[0]
    run = await _launch_run(platform_harness.client, sample_repo)
    run_id = run["id"]
    now = dt.datetime.now(dt.UTC)
    platform_harness.repository.artifacts[run_id].append(
        _Artifact(
            id="artifact_1",
            run_id=run_id,
            kind="logs",
            name="run.log",
            uri="file:///tmp/run.log",
            media_type="text/plain",
            size_bytes=12,
            sha256="a" * 64,
            created_at=now,
        )
    )
    platform_harness.repository.checkpoints[run_id].append(
        _Checkpoint(
            id="ckpt_1",
            run_id=run_id,
            node_id="build",
            stage_index=1,
            commit_sha="b" * 40,
            ref_name="refs/attractor/runs/run_0001/checkpoints/0001-build",
            created_at=now,
        )
    )

    validation = await platform_harness.client.post(f"/api/workflows/{workflow['id']}/validate")
    events = await platform_harness.client.get(f"/api/runs/{run_id}/events")
    artifacts = await platform_harness.client.get(f"/api/runs/{run_id}/artifacts")
    checkpoints = await platform_harness.client.get(f"/api/runs/{run_id}/checkpoints")

    assert validation.status_code == 200
    assert validation.json()["status"] == "valid"
    assert events.status_code == 200
    assert events.json()["items"][0]["event_type"] == "run.queued"
    assert artifacts.status_code == 200
    assert artifacts.json()["items"][0]["name"] == "run.log"
    assert checkpoints.status_code == 200
    assert checkpoints.json()["items"][0]["node_id"] == "build"


async def test_cancel_writeback_and_capacity_surfaces(
    platform_harness: _Harness,
    sample_repo: Path,
) -> None:
    await _register_repo(platform_harness.client, sample_repo)
    run = await _launch_run(platform_harness.client, sample_repo)

    missing_cancel = await platform_harness.client.post("/api/runs/missing/cancel")
    missing_writeback = await platform_harness.client.post(
        "/api/runs/missing/writeback",
        json={"actor_label": "alice"},
    )
    writeback_missing_actor = await platform_harness.client.post(
        f"/api/runs/{run['id']}/writeback",
        json={},
    )
    writeback = await platform_harness.client.post(
        f"/api/runs/{run['id']}/writeback",
        json={"actor_label": "alice"},
    )
    capacity = await platform_harness.client.get("/api/system/capacity")

    assert missing_cancel.status_code == 404
    assert missing_writeback.status_code == 404
    assert writeback_missing_actor.status_code == 400
    assert writeback.status_code == 501
    assert "Task 12" in writeback.json()["error"]
    assert capacity.status_code == 200
    assert capacity.json()["active_runs"] == 0
