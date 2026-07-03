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

from attractor_agent.tools.core import get_environment
from attractor_pipeline.engine.runner import HandlerResult, Outcome
from attractor_platform.executor import DurableRunExecutor
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
class _Approval:
    id: str
    run_id: str
    node_id: str | None
    question: str
    answer: str | None
    actor_label: str
    status: str
    created_at: dt.datetime
    decided_at: dt.datetime | None = None


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


class _InMemoryE2ERepository:
    def __init__(self) -> None:
        self.repos: dict[str, _Repo] = {}
        self.workflows: dict[str, _Workflow] = {}
        self.runs: dict[str, _Run] = {}
        self.events: dict[str, list[_Event]] = {}
        self.approvals: dict[str, _Approval] = {}
        self.artifacts: dict[str, list[_Artifact]] = {}
        self.checkpoints: dict[str, list[_Checkpoint]] = {}
        self.writebacks: list[_WriteBack] = []

    async def register_repo(
        self,
        repo_id: str,
        name: str,
        local_path: str,
        default_branch: str,
        current_commit: str,
        dirty_state: str,
        timestamp: dt.datetime,
        project_config_status: str = "unknown",
    ) -> _Repo:
        existing = self.repos.get(repo_id)
        repo = _Repo(
            id=repo_id,
            name=name,
            local_path=local_path,
            default_branch=default_branch,
            current_commit=current_commit,
            dirty_state=dirty_state,
            project_config_status=project_config_status,
            created_at=existing.created_at if existing is not None else timestamp,
            updated_at=timestamp,
            last_indexed_at=timestamp,
        )
        self.repos[repo_id] = repo
        return repo

    async def list_repos(self) -> list[_Repo]:
        return sorted(self.repos.values(), key=lambda repo: (repo.name, repo.id))

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
            key=lambda workflow: (workflow.name, workflow.id),
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
        return sorted(self.runs.values(), key=lambda run: (run.created_at, run.id))

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
        events = self.events[run_id]
        event = _Event(
            sequence=len(events) + 1,
            event_type=event_type,
            payload=dict(payload),
            actor_label=actor_label,
            created_at=timestamp or dt.datetime.now(dt.UTC),
        )
        events.append(event)
        return event

    async def list_events(self, run_id: str, after_sequence: int, limit: int) -> list[_Event]:
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
        timestamp: dt.datetime,
    ) -> _Approval:
        approval = _Approval(
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

    async def get_approval(self, approval_id: str) -> _Approval | None:
        return self.approvals.get(approval_id)

    async def list_approvals(self, run_id: str) -> list[_Approval]:
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
        timestamp: dt.datetime,
    ) -> _Approval | None:
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
        decided_at: dt.datetime,
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
        timestamp: dt.datetime,
    ) -> _Artifact:
        artifact = _Artifact(
            id=artifact_id,
            run_id=run_id,
            kind=kind,
            name=name,
            uri=uri,
            media_type=media_type,
            size_bytes=size_bytes,
            sha256=sha256,
            created_at=timestamp,
        )
        self.artifacts[run_id].append(artifact)
        return artifact

    async def list_artifacts(self, run_id: str) -> list[_Artifact]:
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
        timestamp: dt.datetime,
    ) -> _Checkpoint:
        checkpoint = _Checkpoint(
            id=checkpoint_id,
            run_id=run_id,
            node_id=node_id,
            stage_index=stage_index,
            commit_sha=commit_sha,
            ref_name=ref_name,
            created_at=timestamp,
        )
        self.checkpoints[run_id].append(checkpoint)
        return checkpoint

    async def list_checkpoints(self, run_id: str) -> list[_Checkpoint]:
        return list(self.checkpoints[run_id])

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


@dataclass
class _Harness:
    client: httpx.AsyncClient
    executor: DurableRunExecutor
    repository: _InMemoryE2ERepository


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
def sample_repo_with_human_gate(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    _git(repo_path, "init", "-b", "main")
    _git(repo_path, "config", "user.email", "tests@example.com")
    _git(repo_path, "config", "user.name", "Tests")

    workflow_dir = repo_path / ".attractor" / "workflows" / "approval"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(
        """
        digraph Approval {
          graph [goal="approval"]
          start [shape=Mdiamond]
          review [shape=house, prompt="Approve release?"]
          write [shape=box, handler="e2e.write", prompt="write accepted marker"]
          done [shape=Msquare]
          start -> review
          review -> write [label="approve"]
          write -> done
        }
        """,
        encoding="utf-8",
    )
    (repo_path / ".attractor" / "project.toml").write_text(
        'default_environment = "local"\nallowed_execution_modes = ["local"]\n',
        encoding="utf-8",
    )
    _commit_all(repo_path, "init")
    return repo_path


@pytest_asyncio.fixture
async def platform_harness(tmp_path: Path) -> AsyncIterator[_Harness]:
    executor = DurableRunExecutor.for_tests(
        session_factory=cast(Any, None),
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    repository = _InMemoryE2ERepository()
    executor_any = cast(Any, executor)
    executor_any.repository = repository

    class _WriteHandler:
        async def execute(
            self,
            node: Any,
            context: dict[str, Any],
            graph: Any,
            logs_root: Path | None,
            abort_signal: Any | None = None,
        ) -> HandlerResult:
            del node, context, graph, abort_signal
            # The event writer checkpoints the prior human gate in the background;
            # keep this test-only worktree mutation out of that checkpoint window.
            for _ in range(100):
                if any(
                    checkpoint.node_id == "review"
                    for checkpoints in repository.checkpoints.values()
                    for checkpoint in checkpoints
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("review checkpoint was not persisted before write stage")

            worktree_path = Path(await get_environment().working_directory())
            (worktree_path / "accepted.txt").write_text("approved by e2e\n", encoding="utf-8")
            if logs_root is not None:
                logs_root.mkdir(parents=True, exist_ok=True)
                (logs_root / "accepted.log").write_text("accepted\n", encoding="utf-8")

            return HandlerResult(status=Outcome.SUCCESS, output="accepted")

    executor_any._handlers.register("e2e.write", _WriteHandler())

    async def _update_run_record(
        run_id: str,
        *,
        status: RunStatus | None = None,
        worktree_path: str | None = None,
        managed_branch: str | None = None,
        started_at: dt.datetime | None = None,
        completed_at: dt.datetime | None = None,
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
        run.updated_at = dt.datetime.now(dt.UTC)

    async def _get_approval_decision(approval_id: str) -> _Approval | None:
        return await repository.get_approval(approval_id)

    executor_any._update_run_record = _update_run_record
    executor_any._get_approval_decision = _get_approval_decision

    app = create_platform_app(session_factory=cast(Any, None), executor=executor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield _Harness(client=client, executor=executor, repository=repository)

    tasks = [task for task in executor.active_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _wait_for_status(
    client: httpx.AsyncClient,
    run_id: str,
    status: str,
    *,
    attempts: int = 100,
) -> dict[str, Any]:
    last_payload: dict[str, Any] | None = None
    for _ in range(attempts):
        response = await client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        payload: dict[str, Any] = response.json()
        last_payload = payload
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    if last_payload is None:
        pytest.fail(f"Run {run_id} did not reach {status!r}; no payload received")
    pytest.fail(f"Run {run_id} did not reach {status!r}; last payload: {last_payload!r}")


async def test_phase2_vertical_slice_register_run_approve_promote(
    platform_harness: _Harness,
    sample_repo_with_human_gate: Path,
) -> None:
    repo_response = await platform_harness.client.post(
        "/api/repos",
        json={"name": "sample", "local_path": str(sample_repo_with_human_gate)},
    )
    assert repo_response.status_code == 201
    repo = repo_response.json()

    workflows_response = await platform_harness.client.get(
        f"/api/repos/{repo['id']}/workflows"
    )
    assert workflows_response.status_code == 200
    workflows = workflows_response.json()
    assert [workflow["name"] for workflow in workflows] == ["approval"]

    validation_response = await platform_harness.client.post(
        f"/api/workflows/{workflows[0]['id']}/validate"
    )
    assert validation_response.status_code == 200
    assert validation_response.json()["status"] == "valid"

    run_response = await platform_harness.client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo_with_human_gate),
            "workflow_name": workflows[0]["name"],
            "actor_label": "alice",
            "inputs": {},
        },
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["id"]

    waiting_run = await _wait_for_status(
        platform_harness.client,
        run_id,
        RunStatus.WAITING_FOR_APPROVAL.value,
    )
    assert waiting_run["worktree_path"] is not None
    assert waiting_run["managed_branch"] is not None
    assert Path(waiting_run["worktree_path"]).is_dir()

    approvals_response = await platform_harness.client.get(f"/api/runs/{run_id}/approvals")
    assert approvals_response.status_code == 200
    approvals = approvals_response.json()["items"]
    pending_approval = next(
        approval for approval in approvals if approval["status"] == "pending"
    )
    assert pending_approval["question"] == "Approve release?"

    approval_response = await platform_harness.client.post(
        f"/api/runs/{run_id}/approvals/{pending_approval['id']}",
        json={"answer": "approve", "actor_label": "alice"},
    )
    assert approval_response.status_code == 200
    assert approval_response.json()["status"] == "decided"

    completed_run = await _wait_for_status(
        platform_harness.client,
        run_id,
        RunStatus.COMPLETED.value,
    )

    events_response = await platform_harness.client.get(f"/api/runs/{run_id}/events")
    checkpoints_response = await platform_harness.client.get(f"/api/runs/{run_id}/checkpoints")
    artifacts_response = await platform_harness.client.get(f"/api/runs/{run_id}/artifacts")
    assert events_response.status_code == 200
    assert checkpoints_response.status_code == 200
    assert artifacts_response.status_code == 200
    event_types = [event["event_type"] for event in events_response.json()["items"]]
    assert "run.started" in event_types
    assert "approval.requested" in event_types
    assert "approval.decided" in event_types
    assert "pipeline.completed" in event_types
    assert "accepted.log" in {
        artifact["name"] for artifact in artifacts_response.json()["items"]
    }
    assert checkpoints_response.json()["items"]

    writeback_response = await platform_harness.client.post(
        f"/api/runs/{run_id}/writeback",
        json={"target_branch": "attractor/accepted/e2e", "actor_label": "alice"},
    )
    assert writeback_response.status_code == 200
    writeback = writeback_response.json()
    assert writeback["status"] == "applied"
    assert writeback["commit_sha"] == _git(
        sample_repo_with_human_gate,
        "rev-parse",
        "attractor/accepted/e2e",
    )

    run_after_writeback_response = await platform_harness.client.get(f"/api/runs/{run_id}")
    assert run_after_writeback_response.status_code == 200
    assert run_after_writeback_response.json()["status"] == RunStatus.WRITEBACK_APPLIED.value
    assert platform_harness.repository.writebacks[-1].status == "applied"
    assert (sample_repo_with_human_gate / "accepted.txt").exists() is False

    promoted_content = subprocess.run(
        ["git", "show", "attractor/accepted/e2e:accepted.txt"],
        cwd=sample_repo_with_human_gate,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert promoted_content == "approved by e2e\n"
    assert completed_run["status"] == RunStatus.COMPLETED.value
