from __future__ import annotations

import datetime as dt
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio

from attractor_platform.git import GitRunner
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
class _WriteBack:
    id: str
    run_id: str
    source_branch: str
    target_branch: str
    actor_label: str
    status: str
    commit_sha: str | None
    error_message: str | None
    created_at: dt.datetime
    applied_at: dt.datetime | None = None


class _InMemoryWriteBackRepository:
    def __init__(self) -> None:
        self.repos: dict[str, _Repo] = {}
        self.runs: dict[str, _Run] = {}
        self.events: dict[str, list[_Event]] = {}
        self.writebacks: list[_WriteBack] = []
        self.atomic_writeback_calls = 0

    async def get_repo(self, repo_id: str) -> _Repo | None:
        return self.repos.get(repo_id)

    async def get_run(self, run_id: str) -> _Run | None:
        return self.runs.get(run_id)

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus | str,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> _Run:
        run = self.runs[run_id]
        run.status = status.value if isinstance(status, RunStatus) else status
        run.error_category = error_category
        run.error_message = error_message
        run.updated_at = dt.datetime.now(dt.UTC)
        return run

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: dt.datetime | None = None,
    ) -> _Event:
        events = self.events.setdefault(run_id, [])
        event = _Event(
            sequence=len(events) + 1,
            event_type=event_type,
            payload=payload,
            actor_label=actor_label,
            created_at=timestamp or dt.datetime.now(dt.UTC),
        )
        events.append(event)
        return event

    async def create_writeback(
        self,
        writeback_id: str,
        run_id: str,
        source_branch: str,
        target_branch: str,
        actor_label: str,
        status: str,
        commit_sha: str | None,
        error_message: str | None,
        timestamp: dt.datetime,
    ) -> _WriteBack:
        writeback = _WriteBack(
            id=writeback_id,
            run_id=run_id,
            source_branch=source_branch,
            target_branch=target_branch,
            actor_label=actor_label,
            status=status,
            commit_sha=commit_sha,
            error_message=error_message,
            created_at=timestamp,
            applied_at=timestamp if status == "applied" else None,
        )
        self.writebacks.append(writeback)
        return writeback

    async def record_writeback_result(
        self,
        writeback_id: str,
        run_id: str,
        source_branch: str,
        target_branch: str,
        actor_label: str,
        status: str,
        commit_sha: str | None,
        error_message: str | None,
        timestamp: dt.datetime,
    ) -> _WriteBack:
        self.atomic_writeback_calls += 1
        writeback = await self.create_writeback(
            writeback_id=writeback_id,
            run_id=run_id,
            source_branch=source_branch,
            target_branch=target_branch,
            actor_label=actor_label,
            status=status,
            commit_sha=commit_sha,
            error_message=error_message,
            timestamp=timestamp,
        )
        event_type = "writeback.applied" if status == "applied" else "writeback.failed"
        await self.append_event(
            run_id=run_id,
            event_type=event_type,
            payload={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "commit_sha": commit_sha,
                "error_message": error_message,
            },
            actor_label=actor_label,
            timestamp=timestamp,
        )
        await self.update_run_status(
            run_id,
            RunStatus.WRITEBACK_APPLIED if status == "applied" else RunStatus.WRITEBACK_FAILED,
            error_category=None if status == "applied" else "writeback_failed",
            error_message=error_message if status != "applied" else None,
        )
        return writeback


class _FakeExecutor:
    def __init__(self, repository: _InMemoryWriteBackRepository) -> None:
        self.repository = repository
        self.active_tasks: dict[str, Any] = {}
        self.max_concurrent_runs = 1
        self.git = GitRunner()


class _FailingAtomicWriteBackRepository(_InMemoryWriteBackRepository):
    async def record_writeback_result(
        self,
        writeback_id: str,
        run_id: str,
        source_branch: str,
        target_branch: str,
        actor_label: str,
        status: str,
        commit_sha: str | None,
        error_message: str | None,
        timestamp: dt.datetime,
    ) -> _WriteBack:
        self.atomic_writeback_calls += 1
        raise RuntimeError("atomic persistence failed")


@dataclass
class _Harness:
    client: httpx.AsyncClient
    repository: _InMemoryWriteBackRepository


@dataclass(frozen=True)
class _GitScenario:
    repo_path: Path
    worktree_path: Path
    base_commit: str
    managed_commit: str
    managed_branch: str


def _git(repo_path: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _commit_all(repo_path: Path, message: str) -> str:
    _git(repo_path, "add", ".")
    _git(repo_path, "commit", "-m", message)
    return _git(repo_path, "rev-parse", "HEAD")


@pytest.fixture
def git_scenario(tmp_path: Path) -> _GitScenario:
    repo_path = tmp_path / "registered"
    worktree_path = tmp_path / "managed"
    repo_path.mkdir()
    _git(repo_path, "init", "-b", "main")
    _git(repo_path, "config", "user.email", "tests@example.com")
    _git(repo_path, "config", "user.name", "Tests")
    (repo_path / "app.txt").write_text("registered\n", encoding="utf-8")
    base_commit = _commit_all(repo_path, "base")

    managed_branch = "attractor/runs/run_1"
    _git(repo_path, "worktree", "add", "-b", managed_branch, str(worktree_path), base_commit)
    _git(worktree_path, "config", "user.email", "tests@example.com")
    _git(worktree_path, "config", "user.name", "Tests")
    (worktree_path / "app.txt").write_text("managed\n", encoding="utf-8")
    managed_commit = _commit_all(worktree_path, "managed change")

    return _GitScenario(
        repo_path=repo_path,
        worktree_path=worktree_path,
        base_commit=base_commit,
        managed_commit=managed_commit,
        managed_branch=managed_branch,
    )


@pytest_asyncio.fixture
async def harness(git_scenario: _GitScenario) -> AsyncIterator[_Harness]:
    repository = _InMemoryWriteBackRepository()
    now = dt.datetime.now(dt.UTC)
    repository.repos["repo_1"] = _Repo(
        id="repo_1",
        name="registered",
        local_path=str(git_scenario.repo_path),
        default_branch="main",
        current_commit=git_scenario.base_commit,
        dirty_state="clean",
        project_config_status="valid",
        created_at=now,
        updated_at=now,
        last_indexed_at=now,
    )
    repository.runs["run_1"] = _Run(
        id="run_1",
        repo_id="repo_1",
        workflow_id="workflow_1",
        run_spec={
            "run_id": "run_1",
            "source_commit": git_scenario.base_commit,
            "source_branch": "main",
        },
        actor_label="alice",
        source_commit=git_scenario.base_commit,
        source_branch="main",
        status=RunStatus.COMPLETED.value,
        worktree_path=str(git_scenario.worktree_path),
        managed_branch=git_scenario.managed_branch,
        error_category=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )
    app = create_platform_app(
        session_factory=cast(Any, None),
        executor=cast(Any, _FakeExecutor(repository)),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield _Harness(client=client, repository=repository)


async def test_successful_writeback_promotes_managed_branch(
    harness: _Harness,
    git_scenario: _GitScenario,
) -> None:
    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "feature/promoted", "actor_label": "alice"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "applied"
    assert payload["target_branch"] == "feature/promoted"
    assert payload["commit_sha"] == git_scenario.managed_commit
    assert payload["applied_at"] is not None
    assert harness.repository.writebacks[-1].applied_at is not None
    assert harness.repository.runs["run_1"].status == RunStatus.WRITEBACK_APPLIED.value
    assert harness.repository.events["run_1"][-1].event_type == "writeback.applied"
    assert harness.repository.atomic_writeback_calls == 1
    assert _git(git_scenario.repo_path, "rev-parse", "feature/promoted") == (
        git_scenario.managed_commit
    )


async def test_writeback_rejects_non_completed_run_without_mutation(
    harness: _Harness,
    git_scenario: _GitScenario,
) -> None:
    run = harness.repository.runs["run_1"]
    run.status = RunStatus.WAITING_FOR_APPROVAL.value
    before_status = run.status

    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "feature/promoted", "actor_label": "alice"},
    )

    assert response.status_code == 409
    assert "completed" in response.json()["error"]
    assert harness.repository.runs["run_1"].status == before_status
    assert harness.repository.writebacks == []
    assert harness.repository.events == {}
    assert harness.repository.atomic_writeback_calls == 0
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/feature/promoted"],
            cwd=git_scenario.repo_path,
            check=False,
        ).returncode
        == 1
    )


async def test_writeback_atomic_persistence_failure_does_not_partially_mutate(
    harness: _Harness,
) -> None:
    repository = _FailingAtomicWriteBackRepository()
    repository.repos.update(harness.repository.repos)
    repository.runs.update(harness.repository.runs)
    app = create_platform_app(
        session_factory=cast(Any, None),
        executor=cast(Any, _FakeExecutor(repository)),
    )
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/api/runs/run_1/writeback",
            json={"target_branch": "feature/promoted", "actor_label": "alice"},
        )

    assert response.status_code == 500
    assert "persistence failed" in response.json()["error"]
    assert repository.runs["run_1"].status == RunStatus.COMPLETED.value
    assert repository.writebacks == []
    assert repository.events == {}
    assert repository.atomic_writeback_calls == 1


async def test_writeback_rejects_protected_main(
    harness: _Harness,
) -> None:
    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "main", "actor_label": "alice"},
    )

    assert response.status_code == 409
    assert "protected" in response.json()["error"]
    assert harness.repository.runs["run_1"].status == RunStatus.WRITEBACK_FAILED.value
    assert harness.repository.writebacks[-1].status == "failed"


async def test_writeback_rejects_qualified_target_ref_without_creating_nested_ref(
    harness: _Harness,
    git_scenario: _GitScenario,
) -> None:
    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "refs/heads/main", "actor_label": "alice"},
    )

    assert response.status_code == 409
    assert "target branch" in response.json()["error"]
    assert harness.repository.runs["run_1"].status == RunStatus.WRITEBACK_FAILED.value
    assert harness.repository.writebacks[-1].status == "failed"
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/refs/heads/main"],
            cwd=git_scenario.repo_path,
            check=False,
        ).returncode
        == 1
    )


async def test_writeback_rejects_existing_target_without_overwrite(
    harness: _Harness,
    git_scenario: _GitScenario,
) -> None:
    _git(git_scenario.repo_path, "branch", "feature/existing", git_scenario.base_commit)

    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "feature/existing", "actor_label": "alice"},
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["error"]
    assert _git(git_scenario.repo_path, "rev-parse", "feature/existing") == (
        git_scenario.base_commit
    )


async def test_writeback_rejects_missing_managed_branch_even_when_tag_matches(
    harness: _Harness,
    git_scenario: _GitScenario,
) -> None:
    _git(git_scenario.worktree_path, "checkout", "--detach", git_scenario.managed_commit)
    _git(git_scenario.repo_path, "branch", "-D", git_scenario.managed_branch)
    _git(git_scenario.repo_path, "tag", git_scenario.managed_branch, git_scenario.managed_commit)

    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "feature/promoted", "actor_label": "alice"},
    )

    assert response.status_code == 409
    assert "managed branch" in response.json()["error"]
    assert harness.repository.runs["run_1"].status == RunStatus.WRITEBACK_FAILED.value
    assert harness.repository.writebacks[-1].status == "failed"
    assert (
        subprocess.run(
            ["git", "show-ref", "--verify", "--quiet", "refs/heads/feature/promoted"],
            cwd=git_scenario.repo_path,
            check=False,
        ).returncode
        == 1
    )


async def test_writeback_overwrite_updates_existing_target(
    harness: _Harness,
    git_scenario: _GitScenario,
) -> None:
    _git(git_scenario.repo_path, "branch", "feature/existing", git_scenario.base_commit)

    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "feature/existing", "actor_label": "alice", "overwrite": True},
    )

    assert response.status_code == 200
    assert _git(git_scenario.repo_path, "rev-parse", "feature/existing") == (
        git_scenario.managed_commit
    )


async def test_writeback_does_not_mutate_registered_working_tree(
    harness: _Harness,
    git_scenario: _GitScenario,
) -> None:
    before = (git_scenario.repo_path / "app.txt").read_text(encoding="utf-8")

    response = await harness.client.post(
        "/api/runs/run_1/writeback",
        json={"target_branch": "feature/promoted", "actor_label": "alice"},
    )

    assert response.status_code == 200
    assert (git_scenario.repo_path / "app.txt").read_text(encoding="utf-8") == before
    assert _git(git_scenario.repo_path, "status", "--porcelain") == ""
