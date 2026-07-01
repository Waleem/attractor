from __future__ import annotations

import asyncio
import os
import subprocess
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import create_session_factory, default_test_database_url
from attractor_platform.storage.models import Base, RunStatus
from attractor_server.platform_app import create_app

pytestmark = pytest.mark.asyncio


@dataclass
class _InMemoryRun:
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
    created_at: Any
    updated_at: Any
    started_at: Any | None = None
    completed_at: Any | None = None


@dataclass
class _InMemoryApproval:
    id: str
    run_id: str
    node_id: str | None
    question: str
    answer: str | None
    actor_label: str
    status: str
    created_at: Any
    decided_at: Any | None = None


@dataclass
class _InMemoryEvent:
    sequence: int
    event_type: str
    payload: dict[str, Any]
    actor_label: str


@dataclass
class _InMemoryArtifact:
    kind: str
    name: str
    uri: str
    media_type: str
    size_bytes: int
    sha256: str


@dataclass
class _InMemoryCheckpoint:
    node_id: str
    stage_index: int
    commit_sha: str
    ref_name: str


class _InMemoryApprovalRepository:
    def __init__(self) -> None:
        self.runs: dict[str, _InMemoryRun] = {}
        self.events: dict[str, list[_InMemoryEvent]] = {}
        self.approvals: dict[str, _InMemoryApproval] = {}
        self.artifacts: dict[str, list[_InMemoryArtifact]] = {}
        self.checkpoints: dict[str, list[_InMemoryCheckpoint]] = {}

    async def register_repo(self, **_: Any) -> None:
        return None

    async def upsert_workflow(self, **_: Any) -> None:
        return None

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
        timestamp: Any,
    ) -> _InMemoryRun:
        run = _InMemoryRun(
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

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: Any | None = None,
    ) -> _InMemoryEvent:
        del timestamp
        event = _InMemoryEvent(
            sequence=len(self.events[run_id]) + 1,
            event_type=event_type,
            payload=dict(payload),
            actor_label=actor_label,
        )
        self.events[run_id].append(event)
        return event

    async def get_run(self, run_id: str) -> _InMemoryRun | None:
        return self.runs.get(run_id)

    async def list_events(
        self,
        run_id: str,
        after_sequence: int,
        limit: int,
    ) -> list[_InMemoryEvent]:
        return [
            event
            for event in self.events[run_id]
            if event.sequence > after_sequence
        ][:limit]

    async def create_approval(
        self,
        approval_id: str,
        run_id: str,
        node_id: str | None,
        question: str,
        timestamp: Any,
    ) -> _InMemoryApproval:
        approval = _InMemoryApproval(
            id=approval_id,
            run_id=run_id,
            node_id=node_id,
            question=question,
            answer=None,
            actor_label="",
            status="pending",
            created_at=timestamp,
        )
        self.approvals[approval_id] = approval
        return approval

    async def get_approval(self, approval_id: str) -> _InMemoryApproval | None:
        return self.approvals.get(approval_id)

    async def list_approvals(self, run_id: str) -> list[_InMemoryApproval]:
        return sorted(
            [approval for approval in self.approvals.values() if approval.run_id == run_id],
            key=lambda approval: (approval.created_at, approval.id),
        )

    async def decide_pending_approval(
        self,
        *,
        approval_id: str,
        run_id: str,
        answer: str,
        actor_label: str,
        timestamp: Any,
    ) -> _InMemoryApproval | None:
        approval = self.approvals.get(approval_id)
        if approval is None or approval.run_id != run_id or approval.status != "pending":
            return None
        approval.answer = answer
        approval.actor_label = actor_label
        approval.status = "decided"
        approval.decided_at = timestamp
        return approval

    async def revert_decided_approval(
        self,
        *,
        approval_id: str,
        run_id: str,
        answer: str,
        actor_label: str,
        decided_at: Any,
    ) -> bool:
        approval = self.approvals.get(approval_id)
        if (
            approval is None
            or approval.run_id != run_id
            or approval.status != "decided"
            or approval.answer != answer
            or approval.actor_label != actor_label
            or approval.decided_at != decided_at
        ):
            return False
        approval.answer = None
        approval.actor_label = ""
        approval.status = "pending"
        approval.decided_at = None
        return True

    async def create_artifact(
        self,
        *,
        artifact_id: str,
        run_id: str,
        kind: str,
        name: str,
        uri: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
        timestamp: Any,
    ) -> _InMemoryArtifact:
        del artifact_id, timestamp
        artifact = _InMemoryArtifact(
            kind=kind,
            name=name,
            uri=uri,
            media_type=media_type,
            size_bytes=size_bytes,
            sha256=sha256,
        )
        self.artifacts[run_id].append(artifact)
        return artifact

    async def list_artifacts(self, run_id: str) -> list[_InMemoryArtifact]:
        return list(self.artifacts[run_id])

    async def create_checkpoint(
        self,
        *,
        checkpoint_id: str,
        run_id: str,
        node_id: str,
        stage_index: int,
        commit_sha: str,
        ref_name: str,
        timestamp: Any,
    ) -> _InMemoryCheckpoint:
        del checkpoint_id, timestamp
        checkpoint = _InMemoryCheckpoint(
            node_id=node_id,
            stage_index=stage_index,
            commit_sha=commit_sha,
            ref_name=ref_name,
        )
        self.checkpoints[run_id].append(checkpoint)
        return checkpoint

    async def list_checkpoints(self, run_id: str) -> list[_InMemoryCheckpoint]:
        return list(self.checkpoints[run_id])


@dataclass
class _InMemoryPlatformHarness:
    client: httpx.AsyncClient
    executor: DurableRunExecutor
    repository: _InMemoryApprovalRepository


@pytest_asyncio.fixture
async def platform_session_factory(
    tmp_path: Path,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get(
        "ATTRACTOR_TEST_DATABASE_URL",
        default_test_database_url(tmp_path / "platform.sqlite3"),
    )

    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        yield create_session_factory(engine)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def sample_repo_with_human_gate(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)

    workflow_dir = repo_path / ".attractor" / "workflows" / "approval"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(
        """
        digraph Approval {
          graph [goal="approval"]
          start [shape=Mdiamond]
          review [shape=house, prompt="Approve release?"]
          done [shape=Msquare]
          start -> review
          review -> done [label="approve"]
        }
        """,
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


@pytest_asyncio.fixture
async def in_memory_platform_harness(tmp_path: Path) -> AsyncIterator[_InMemoryPlatformHarness]:
    executor = DurableRunExecutor.for_tests(
        session_factory=cast(Any, None),
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    repository = _InMemoryApprovalRepository()
    executor_any = cast(Any, executor)
    executor_any.repository = repository

    async def _update_run_record(
        run_id: str,
        *,
        status: RunStatus | None = None,
        worktree_path: str | None = None,
        managed_branch: str | None = None,
        started_at: Any | None = None,
        completed_at: Any | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> None:
        run = repository.runs[run_id]
        if status is not None:
            run.status = status.value
        if worktree_path is not None:
            run.worktree_path = worktree_path
        if managed_branch is not None:
            run.managed_branch = managed_branch
        if started_at is not None:
            run.started_at = started_at
        if completed_at is not None:
            run.completed_at = completed_at
        run.error_category = error_category
        run.error_message = error_message

    async def _get_approval_decision(approval_id: str) -> _InMemoryApproval | None:
        return await repository.get_approval(approval_id)

    executor_any._update_run_record = _update_run_record
    executor_any._get_approval_decision = _get_approval_decision

    app = create_app(
        session_factory=cast(Any, None),
        executor=executor,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield _InMemoryPlatformHarness(client=client, executor=executor, repository=repository)

    tasks = [task for task in executor.active_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest_asyncio.fixture
async def platform_client(
    tmp_path: Path,
    platform_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    executor = DurableRunExecutor(
        session_factory=platform_session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    app = create_app(
        session_factory=platform_session_factory,
        executor=executor,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _wait_for_status(
    client: httpx.AsyncClient,
    run_id: str,
    status: str,
    *,
    attempts: int = 80,
) -> dict[str, object]:
    for _ in range(attempts):
        response = await client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    pytest.fail(f"Run {run_id} did not reach status {status!r}")


async def _launch_waiting_run(
    harness: _InMemoryPlatformHarness,
    repo_path: Path,
) -> tuple[str, dict[str, object]]:
    launch_response = await harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(repo_path),
            "workflow": "approval",
            "actor_label": "alice",
            "inputs": {},
        },
    )
    assert launch_response.status_code == 201
    run_id = launch_response.json()["id"]

    await _wait_for_status(
        harness.client,
        run_id,
        RunStatus.WAITING_FOR_APPROVAL.value,
    )

    approvals_response = await harness.client.get(f"/api/runs/{run_id}/approvals")
    assert approvals_response.status_code == 200
    pending_approvals = [
        approval
        for approval in approvals_response.json()["items"]
        if approval["status"] == "pending"
    ]
    assert len(pending_approvals) == 1
    return run_id, pending_approvals[0]


def _approval_summary(approvals: list[dict[str, object]]) -> list[tuple[object, object, object]]:
    return [
        (approval["status"], approval["answer"], approval["actor_label"])
        for approval in approvals
    ]


async def test_human_gate_lifecycle_in_memory(
    in_memory_platform_harness: _InMemoryPlatformHarness,
    sample_repo_with_human_gate: Path,
) -> None:
    run_id, pending_approval = await _launch_waiting_run(
        in_memory_platform_harness,
        sample_repo_with_human_gate,
    )

    assert pending_approval["question"] == "Approve release?"
    assert pending_approval["answer"] is None
    assert pending_approval["actor_label"] == ""

    decision_response = await in_memory_platform_harness.client.post(
        f"/api/runs/{run_id}/approvals/{pending_approval['id']}",
        json={"answer": "approve", "actor_label": "bob"},
    )

    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "decided"

    await _wait_for_status(
        in_memory_platform_harness.client,
        run_id,
        RunStatus.COMPLETED.value,
    )

    approvals_response = await in_memory_platform_harness.client.get(
        f"/api/runs/{run_id}/approvals"
    )
    approvals = approvals_response.json()["items"]
    assert len(approvals) == 1
    decided_approval = approvals[0]
    assert decided_approval["status"] == "decided"
    assert decided_approval["answer"] == "approve"
    assert decided_approval["actor_label"] in {"bob", "carol"}

    event_types = [
        event.event_type
        for event in in_memory_platform_harness.repository.events[run_id]
    ]
    assert "approval.requested" in event_types
    assert "approval.decided" in event_types
    assert event_types.index("approval.requested") < event_types.index("approval.decided")


async def test_duplicate_approval_decision_returns_conflict_in_memory(
    in_memory_platform_harness: _InMemoryPlatformHarness,
    sample_repo_with_human_gate: Path,
) -> None:
    run_id, pending_approval = await _launch_waiting_run(
        in_memory_platform_harness,
        sample_repo_with_human_gate,
    )

    first_response = await in_memory_platform_harness.client.post(
        f"/api/runs/{run_id}/approvals/{pending_approval['id']}",
        json={"answer": "approve", "actor_label": "bob"},
    )
    assert first_response.status_code == 200

    duplicate_response = await in_memory_platform_harness.client.post(
        f"/api/runs/{run_id}/approvals/{pending_approval['id']}",
        json={"answer": "approve", "actor_label": "carol"},
    )
    assert duplicate_response.status_code == 409

    approvals_response = await in_memory_platform_harness.client.get(
        f"/api/runs/{run_id}/approvals"
    )
    approvals = approvals_response.json()["items"]
    assert _approval_summary(approvals) == [("decided", "approve", "bob")]

    await _wait_for_status(
        in_memory_platform_harness.client,
        run_id,
        RunStatus.COMPLETED.value,
    )


async def test_concurrent_approval_decisions_only_decide_once_in_memory(
    in_memory_platform_harness: _InMemoryPlatformHarness,
    sample_repo_with_human_gate: Path,
) -> None:
    run_id, pending_approval = await _launch_waiting_run(
        in_memory_platform_harness,
        sample_repo_with_human_gate,
    )

    approval_id = pending_approval["id"]
    first_response, second_response = await asyncio.gather(
        in_memory_platform_harness.client.post(
            f"/api/runs/{run_id}/approvals/{approval_id}",
            json={"answer": "approve", "actor_label": "bob"},
        ),
        in_memory_platform_harness.client.post(
            f"/api/runs/{run_id}/approvals/{approval_id}",
            json={"answer": "approve", "actor_label": "carol"},
        ),
    )
    assert sorted(
        [first_response.status_code, second_response.status_code],
    ) == [200, 409]

    approvals_response = await in_memory_platform_harness.client.get(
        f"/api/runs/{run_id}/approvals"
    )
    approvals = approvals_response.json()["items"]
    assert _approval_summary(approvals) == [("decided", "approve", "bob")]

    await _wait_for_status(
        in_memory_platform_harness.client,
        run_id,
        RunStatus.COMPLETED.value,
    )


async def test_invalid_approval_answer_returns_bad_request_in_memory(
    in_memory_platform_harness: _InMemoryPlatformHarness,
    sample_repo_with_human_gate: Path,
) -> None:
    run_id, pending_approval = await _launch_waiting_run(
        in_memory_platform_harness,
        sample_repo_with_human_gate,
    )

    invalid_response = await in_memory_platform_harness.client.post(
        f"/api/runs/{run_id}/approvals/{pending_approval['id']}",
        json={"answer": "deny", "actor_label": "bob"},
    )
    assert invalid_response.status_code == 400

    run_response = await in_memory_platform_harness.client.get(f"/api/runs/{run_id}")
    assert run_response.status_code == 200
    assert run_response.json()["status"] == RunStatus.WAITING_FOR_APPROVAL.value

    approvals_response = await in_memory_platform_harness.client.get(
        f"/api/runs/{run_id}/approvals"
    )
    approvals = approvals_response.json()["items"]
    assert _approval_summary(approvals) == [("pending", None, "")]


async def test_missing_waiter_returns_conflict_in_memory(
    in_memory_platform_harness: _InMemoryPlatformHarness,
    sample_repo_with_human_gate: Path,
) -> None:
    run_id, pending_approval = await _launch_waiting_run(
        in_memory_platform_harness,
        sample_repo_with_human_gate,
    )

    approval_id = cast(str, pending_approval["id"])
    in_memory_platform_harness.executor._approval_waiters.pop(approval_id, None)

    missing_waiter_response = await in_memory_platform_harness.client.post(
        f"/api/runs/{run_id}/approvals/{approval_id}",
        json={"answer": "approve", "actor_label": "bob"},
    )
    assert missing_waiter_response.status_code == 409

    approvals_response = await in_memory_platform_harness.client.get(
        f"/api/runs/{run_id}/approvals"
    )
    approvals = approvals_response.json()["items"]
    assert _approval_summary(approvals) == [("pending", None, "")]


async def test_resume_race_returns_conflict_without_deciding_in_memory(
    in_memory_platform_harness: _InMemoryPlatformHarness,
    sample_repo_with_human_gate: Path,
) -> None:
    run_id, pending_approval = await _launch_waiting_run(
        in_memory_platform_harness,
        sample_repo_with_human_gate,
    )
    approval_id = cast(str, pending_approval["id"])
    decide_pending_approval = in_memory_platform_harness.repository.decide_pending_approval

    async def decide_then_drop_waiter(**kwargs: Any) -> _InMemoryApproval | None:
        decided = await decide_pending_approval(**kwargs)
        in_memory_platform_harness.executor._approval_waiters.pop(approval_id, None)
        return decided

    in_memory_platform_harness.repository.decide_pending_approval = decide_then_drop_waiter

    race_response = await in_memory_platform_harness.client.post(
        f"/api/runs/{run_id}/approvals/{approval_id}",
        json={"answer": "approve", "actor_label": "bob"},
    )
    assert race_response.status_code == 409

    approvals_response = await in_memory_platform_harness.client.get(
        f"/api/runs/{run_id}/approvals"
    )
    approvals = approvals_response.json()["items"]
    assert _approval_summary(approvals) == [("pending", None, "")]


async def test_human_gate_persists_pending_and_decision(
    platform_client: httpx.AsyncClient,
    sample_repo_with_human_gate: Path,
) -> None:
    launch_response = await platform_client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo_with_human_gate),
            "workflow": "approval",
            "actor_label": "alice",
            "inputs": {},
        },
    )

    assert launch_response.status_code == 201
    run_id = launch_response.json()["id"]

    await _wait_for_status(
        platform_client,
        run_id,
        RunStatus.WAITING_FOR_APPROVAL.value,
    )

    approvals_response = await platform_client.get(f"/api/runs/{run_id}/approvals")
    assert approvals_response.status_code == 200
    approvals = approvals_response.json()["items"]
    pending_approvals = [approval for approval in approvals if approval["status"] == "pending"]
    assert len(pending_approvals) == 1

    approval_id = pending_approvals[0]["id"]
    decision_response = await platform_client.post(
        f"/api/runs/{run_id}/approvals/{approval_id}",
        json={"answer": "approve", "actor_label": "bob"},
    )

    assert decision_response.status_code == 200

    await _wait_for_status(
        platform_client,
        run_id,
        RunStatus.COMPLETED.value,
    )
