from __future__ import annotations

import datetime as dt
import subprocess
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


class _Repository:
    def __init__(self) -> None:
        self.repos: dict[str, _Repo] = {}
        self.workflows: dict[str, _Workflow] = {}
        self.runs: dict[str, _Run] = {}
        self.events: dict[str, list[_Event]] = {}

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
async def platform_harness() -> _Harness:
    repository = _Repository()
    executor = _Executor(repository)
    app = create_platform_app(session_factory=cast(Any, None), executor=cast(Any, executor))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield _Harness(client=client, repository=repository)


async def _register_repo(harness: _Harness, repo_path: Path) -> None:
    response = await harness.client.post(
        "/api/repos",
        json={"name": "sample", "local_path": str(repo_path)},
    )
    assert response.status_code == 201


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
