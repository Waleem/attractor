from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Select

from attractor_platform.redaction import redact_mapping
from attractor_platform.storage.db import session_scope
from attractor_platform.storage.models import (
    ApprovalDecisionModel,
    ArtifactModel,
    CheckpointModel,
    RegisteredRepoModel,
    RunEventModel,
    RunRecordModel,
    RunStatus,
    WorkflowPackageModel,
    WriteBackModel,
)


def _select_run_for_append_lock(run_id: str) -> Select[tuple[RunRecordModel]]:
    return select(RunRecordModel).where(RunRecordModel.id == run_id).with_for_update()


def _is_run_event_sequence_conflict(error: IntegrityError) -> bool:
    message = str(error.orig)
    return (
        "uq_run_events_run_sequence" in message
        or "run_events.run_id, run_events.sequence" in message
    )


class PlatformRepository:
    """Repository methods return scalar-loaded ORM instances from committed transactions.

    Callers should not rely on lazy relationships after a method returns because the
    repository-owned session is already closed.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_repo(self, repo_id: str) -> RegisteredRepoModel | None:
        async with session_scope(self._session_factory) as session:
            return await session.get(RegisteredRepoModel, repo_id)

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
    ) -> RegisteredRepoModel:
        async with session_scope(self._session_factory) as session:
            repo = await session.get(RegisteredRepoModel, repo_id)
            if repo is None:
                repo = RegisteredRepoModel(
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
                session.add(repo)
            else:
                repo.name = name
                repo.local_path = local_path
                repo.default_branch = default_branch
                repo.current_commit = current_commit
                repo.dirty_state = dirty_state
                repo.project_config_status = project_config_status
                repo.updated_at = timestamp
                repo.last_indexed_at = timestamp
            await session.flush()
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
    ) -> WorkflowPackageModel:
        async with session_scope(self._session_factory) as session:
            workflow = await session.get(WorkflowPackageModel, workflow_id)
            if workflow is None:
                workflow = WorkflowPackageModel(
                    id=workflow_id,
                    repo_id=repo_id,
                    name=name,
                    dot_path=dot_path,
                    toml_path=toml_path,
                    status=status,
                    diagnostics=diagnostics,
                    indexed_at=timestamp,
                )
                session.add(workflow)
            else:
                workflow.repo_id = repo_id
                workflow.name = name
                workflow.dot_path = dot_path
                workflow.toml_path = toml_path
                workflow.status = status
                workflow.diagnostics = diagnostics
                workflow.indexed_at = timestamp
            await session.flush()
            return workflow

    async def update_repo_index_metadata(
        self,
        repo_id: str,
        *,
        default_branch: str,
        current_commit: str,
        dirty_state: str,
        timestamp: dt.datetime,
    ) -> RegisteredRepoModel:
        async with session_scope(self._session_factory) as session:
            repo = await session.get(RegisteredRepoModel, repo_id)
            if repo is None:
                raise KeyError(f"Repository not found: {repo_id}")
            repo.default_branch = default_branch
            repo.current_commit = current_commit
            repo.dirty_state = dirty_state
            repo.updated_at = timestamp
            repo.last_indexed_at = timestamp
            await session.flush()
            return repo

    async def delete_workflows_not_in(self, repo_id: str, workflow_ids: set[str]) -> int:
        async with session_scope(self._session_factory) as session:
            current = await session.scalars(
                select(WorkflowPackageModel.id).where(WorkflowPackageModel.repo_id == repo_id)
            )
            stale_ids = [workflow_id for workflow_id in current if workflow_id not in workflow_ids]
            if not stale_ids:
                return 0
            referenced_ids = set(
                await session.scalars(
                    select(RunRecordModel.workflow_id)
                    .where(RunRecordModel.workflow_id.in_(stale_ids))
                    .distinct()
                )
            )
            removed_count = 0
            for workflow_id in stale_ids:
                if workflow_id in referenced_ids:
                    continue
                workflow = await session.get(WorkflowPackageModel, workflow_id)
                if workflow is not None:
                    await session.delete(workflow)
                    removed_count += 1
            return removed_count

    async def create_run(
        self,
        run_id: str,
        repo_id: str,
        workflow_id: str,
        run_spec: dict[str, Any],
        actor_label: str,
        source_commit: str,
        source_branch: str,
        timestamp: dt.datetime,
    ) -> RunRecordModel:
        async with session_scope(self._session_factory) as session:
            run = RunRecordModel(
                id=run_id,
                repo_id=repo_id,
                workflow_id=workflow_id,
                status=RunStatus.QUEUED.value,
                run_spec=run_spec,
                actor_label=actor_label,
                source_commit=source_commit,
                source_branch=source_branch,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(run)
            await session.flush()
            return run

    async def update_run_status(
        self,
        run_id: str,
        status: RunStatus | str,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> RunRecordModel:
        async with session_scope(self._session_factory) as session:
            run = await session.get(RunRecordModel, run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
            run.status = status.value if isinstance(status, RunStatus) else status
            run.error_category = error_category
            run.error_message = error_message
            run.updated_at = dt.datetime.now(dt.UTC)
            await session.flush()
            return run

    async def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: dt.datetime | None = None,
    ) -> RunEventModel:
        for _ in range(20):
            try:
                return await self._append_event_once(
                    run_id,
                    event_type,
                    payload,
                    actor_label=actor_label,
                    timestamp=timestamp,
                )
            except IntegrityError as error:
                if not _is_run_event_sequence_conflict(error):
                    raise
                await asyncio.sleep(0)
        return await self._append_event_once(
            run_id,
            event_type,
            payload,
            actor_label=actor_label,
            timestamp=timestamp,
        )

    async def _append_event_once(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        actor_label: str = "",
        timestamp: dt.datetime | None = None,
    ) -> RunEventModel:
        async with session_scope(self._session_factory) as session:
            locked_run = await session.scalar(_select_run_for_append_lock(run_id))
            if locked_run is None:
                raise KeyError(f"Run not found: {run_id}")
            max_sequence = await session.scalar(
                select(func.max(RunEventModel.sequence)).where(RunEventModel.run_id == run_id)
            )
            event = RunEventModel(
                run_id=run_id,
                sequence=(max_sequence or 0) + 1,
                event_type=event_type,
                payload=redact_mapping(payload),
                actor_label=actor_label,
                created_at=timestamp or dt.datetime.now(dt.UTC),
            )
            session.add(event)
            await session.flush()
            return event

    async def list_events(
        self,
        run_id: str,
        after_sequence: int,
        limit: int,
    ) -> list[RunEventModel]:
        async with session_scope(self._session_factory) as session:
            result = await session.scalars(
                select(RunEventModel)
                .where(
                    RunEventModel.run_id == run_id,
                    RunEventModel.sequence > after_sequence,
                )
                .order_by(RunEventModel.sequence)
                .limit(limit)
            )
            return list(result)

    async def get_run(self, run_id: str) -> RunRecordModel | None:
        async with session_scope(self._session_factory) as session:
            return await session.get(RunRecordModel, run_id)

    async def create_approval(
        self,
        approval_id: str,
        run_id: str,
        node_id: str | None,
        question: str,
        timestamp: dt.datetime,
    ) -> ApprovalDecisionModel:
        async with session_scope(self._session_factory) as session:
            approval = ApprovalDecisionModel(
                id=approval_id,
                run_id=run_id,
                node_id=node_id,
                question=question,
                answer=None,
                actor_label="",
                status="pending",
                created_at=timestamp,
            )
            session.add(approval)
            await session.flush()
            return approval

    async def decide_approval(
        self,
        approval_id: str,
        answer: str,
        actor_label: str,
        timestamp: dt.datetime,
    ) -> ApprovalDecisionModel:
        async with session_scope(self._session_factory) as session:
            approval = await session.get(ApprovalDecisionModel, approval_id)
            if approval is None:
                raise KeyError(f"Approval not found: {approval_id}")
            approval.answer = answer
            approval.actor_label = actor_label
            approval.status = "decided"
            approval.decided_at = timestamp
            await session.flush()
            return approval

    async def create_artifact(
        self,
        artifact_id: str,
        run_id: str,
        kind: str,
        name: str,
        uri: str,
        media_type: str,
        size_bytes: int,
        sha256: str,
        timestamp: dt.datetime,
    ) -> ArtifactModel:
        async with session_scope(self._session_factory) as session:
            artifact = ArtifactModel(
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
            session.add(artifact)
            await session.flush()
            return artifact

    async def list_artifacts(self, run_id: str) -> list[ArtifactModel]:
        async with session_scope(self._session_factory) as session:
            result = await session.scalars(
                select(ArtifactModel)
                .where(ArtifactModel.run_id == run_id)
                .order_by(ArtifactModel.created_at, ArtifactModel.id)
            )
            return list(result)

    async def create_checkpoint(
        self,
        checkpoint_id: str,
        run_id: str,
        node_id: str,
        stage_index: int,
        commit_sha: str,
        ref_name: str,
        timestamp: dt.datetime,
    ) -> CheckpointModel:
        async with session_scope(self._session_factory) as session:
            checkpoint = CheckpointModel(
                id=checkpoint_id,
                run_id=run_id,
                node_id=node_id,
                stage_index=stage_index,
                commit_sha=commit_sha,
                ref_name=ref_name,
                created_at=timestamp,
            )
            session.add(checkpoint)
            await session.flush()
            return checkpoint

    async def list_checkpoints(self, run_id: str) -> list[CheckpointModel]:
        async with session_scope(self._session_factory) as session:
            result = await session.scalars(
                select(CheckpointModel)
                .where(CheckpointModel.run_id == run_id)
                .order_by(CheckpointModel.stage_index, CheckpointModel.created_at)
            )
            return list(result)

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
    ) -> WriteBackModel:
        async with session_scope(self._session_factory) as session:
            writeback = WriteBackModel(
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
            session.add(writeback)
            await session.flush()
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
    ) -> WriteBackModel:
        async with session_scope(self._session_factory) as session:
            locked_run = await session.scalar(_select_run_for_append_lock(run_id))
            if locked_run is None:
                raise KeyError(f"Run not found: {run_id}")
            writeback = WriteBackModel(
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
            session.add(writeback)
            max_sequence = await session.scalar(
                select(func.max(RunEventModel.sequence)).where(RunEventModel.run_id == run_id)
            )
            event_type = "writeback.applied" if status == "applied" else "writeback.failed"
            event = RunEventModel(
                run_id=run_id,
                sequence=(max_sequence or 0) + 1,
                event_type=event_type,
                payload=redact_mapping(
                    {
                        "source_branch": source_branch,
                        "target_branch": target_branch,
                        "commit_sha": commit_sha,
                        "error_message": error_message,
                    }
                ),
                actor_label=actor_label,
                created_at=timestamp,
            )
            session.add(event)
            locked_run.status = (
                RunStatus.WRITEBACK_APPLIED.value
                if status == "applied"
                else RunStatus.WRITEBACK_FAILED.value
            )
            locked_run.error_category = None if status == "applied" else "writeback_failed"
            locked_run.error_message = error_message if status != "applied" else None
            locked_run.updated_at = dt.datetime.now(dt.UTC)
            await session.flush()
            return writeback
