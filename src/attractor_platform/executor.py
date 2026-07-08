"""Durable Phase 2 worktree run executor."""

from __future__ import annotations

import asyncio
import contextvars
import datetime as dt
import hashlib
import inspect
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from attractor_agent.abort import AbortSignal
from attractor_pipeline.engine.events import (
    CheckpointSaved,
    PipelineCompleted,
    PipelineEvent,
    PipelineFailed,
    PipelineStarted,
    StageCompleted,
    StageFailed,
    StageRetrying,
    StageStarted,
)
from attractor_pipeline.engine.runner import (
    HandlerRegistry,
    HandlerResult,
    Outcome,
    PipelineResult,
    PipelineStatus,
    run_pipeline,
)
from attractor_pipeline.graph import Graph, Node
from attractor_pipeline.handlers import CodergenBackend, CodergenHandler, register_default_handlers
from attractor_pipeline.handlers.human import Answer, HumanHandler, Question
from attractor_platform.artifacts import FileSystemArtifactStore
from attractor_platform.checkpoints import GitCheckpointService
from attractor_platform.git import GitRunner, PreparedWorktree, WorktreeManager
from attractor_platform.packages import WorkflowPackage, load_workflow_package
from attractor_platform.redaction import redact_text
from attractor_platform.run_environment import (
    materialize_run_environment_request,
    select_run_environment,
)
from attractor_platform.runspec import RunSpec, build_run_spec
from attractor_platform.storage.db import session_scope
from attractor_platform.storage.models import (
    ApprovalDecisionModel,
    ArtifactModel,
    RunRecordModel,
    RunStatus,
)
from attractor_platform.storage.repositories import PlatformRepository

_QUEUE_SENTINEL = object()
CODERGEN_OUTPUT_PREVIEW_MAX_CHARS = 4096


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


@dataclass(frozen=True)
class _PersistedTerminalEvent:
    result_status: PipelineStatus
    result_error: str | None
    event_type: str
    payload: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class _PersistedTerminalResult:
    event: _PersistedTerminalEvent
    result: PipelineResult
    error_category: str | None
    error_message: str | None


@dataclass(frozen=True)
class _RunInterviewerContext:
    run_id: str
    actor_label: str


@dataclass
class _PendingApprovalWaiter:
    run_id: str
    approval_id: str
    wake_event: asyncio.Event
    allowed_options: tuple[str, ...] | None = None


class _NoopHandler:
    async def execute(
        self,
        node: Node,
        context: dict[str, Any],
        graph: Graph,
        logs_root: Path | None,
        abort_signal: AbortSignal | None = None,
    ) -> HandlerResult:
        del node, context, graph, logs_root, abort_signal
        return HandlerResult(status=Outcome.SUCCESS, output="noop")


class _ServerRunInterviewer:
    def __init__(self, executor: DurableRunExecutor) -> None:
        self._executor = executor

    async def ask(self, question: Question) -> Answer:
        return await self._executor._request_human_approval(question)

    async def ask_question(self, question: Question) -> Answer:
        return await self.ask(question)


class DurableRunExecutor:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        worktree_root: str | Path,
        artifact_root: str | Path,
        git: GitRunner | None = None,
        codergen_backend: CodergenBackend | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.repository = PlatformRepository(session_factory)
        self._git = git or GitRunner()
        self._worktree_manager = WorktreeManager(self._git, worktree_root)
        self._artifact_root = Path(artifact_root).expanduser().resolve()
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._artifact_store = FileSystemArtifactStore(self._artifact_root)
        self._checkpoint_service = GitCheckpointService(self._git)
        self._handlers = HandlerRegistry()
        register_default_handlers(self._handlers, codergen_backend=codergen_backend)
        self._handlers.register(
            "wait.human",
            cast(Any, HumanHandler(interviewer=_ServerRunInterviewer(self))),
        )
        self._handlers.register("noop", _NoopHandler())
        self.active_tasks: dict[str, asyncio.Task[PipelineResult]] = {}
        self._completed_results: dict[str, PipelineResult] = {}
        self._completed_failures: dict[str, Exception] = {}
        self._captured_terminal_artifacts: set[tuple[str, str]] = set()
        self._captured_terminal_artifact_files: dict[tuple[str, str], set[str]] = {}
        self._persisted_terminal_results: dict[str, _PersistedTerminalResult] = {}
        self._approval_waiters: dict[str, _PendingApprovalWaiter] = {}
        self._run_interviewer_context: contextvars.ContextVar[_RunInterviewerContext | None] = (
            contextvars.ContextVar("durable_run_interviewer_context", default=None)
        )

    def configure_codergen_backend(self, codergen_backend: CodergenBackend | None) -> None:
        handler = self._handlers.get("codergen")
        if isinstance(handler, CodergenHandler):
            handler._backend = codergen_backend
            return
        self._handlers.register("codergen", CodergenHandler(backend=codergen_backend))

    @classmethod
    def for_tests(
        cls,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        worktree_root: str | Path,
        artifact_root: str | Path,
        codergen_backend: CodergenBackend | None = None,
    ) -> DurableRunExecutor:
        return cls(
            session_factory=session_factory,
            worktree_root=worktree_root,
            artifact_root=artifact_root,
            codergen_backend=codergen_backend,
        )

    async def register_and_launch(
        self,
        *,
        repo_path: str | Path,
        workflow_name: str,
        actor_label: str,
        inputs: dict[str, str],
        requested_environment: str = "",
    ) -> str:
        package = load_workflow_package(repo_path, workflow_name)
        get_repo = cast(
            Callable[[str], Awaitable[Any | None]] | None,
            getattr(self.repository, "get_repo", None),
        )
        existing_repo = None
        if get_repo is not None:
            existing_repo = await get_repo(_repo_identifier(package.repo_path))
        run_spec = build_run_spec(
            package,
            inputs=inputs,
            actor_label=actor_label,
            requested_environment=requested_environment,
        )
        run_spec = run_spec.model_copy(
            update={"repo_id": _repo_identifier(package.repo_path)}
        )
        persisted_run_spec = run_spec.model_copy(
            update={
                "effective_environment": materialize_run_environment_request(
                    run_spec.effective_environment
                )
            }
        )
        workflow_id = _workflow_identifier(run_spec.repo_id, package.name)
        now = _utc_now()

        register_repo_kwargs: dict[str, Any] = {
            "repo_id": run_spec.repo_id,
            "name": existing_repo.name if existing_repo is not None else package.repo_path.name,
            "local_path": str(package.repo_path),
            "default_branch": run_spec.source_branch,
            "current_commit": run_spec.source_commit,
            "dirty_state": run_spec.dirty_state.value,
            "timestamp": now,
        }
        if _accepts_project_config_status(self.repository.register_repo):
            register_repo_kwargs["project_config_status"] = "valid"
        await self.repository.register_repo(**register_repo_kwargs)
        await self.repository.upsert_workflow(
            workflow_id=workflow_id,
            repo_id=run_spec.repo_id,
            name=package.name,
            dot_path=str(package.dot_path),
            toml_path=str(package.toml_path) if package.toml_path is not None else None,
            status=package.status.value,
            diagnostics=_serialize_diagnostics(package),
            timestamp=now,
        )
        await self.repository.create_run(
            run_id=run_spec.run_id,
            repo_id=run_spec.repo_id,
            workflow_id=workflow_id,
            run_spec=persisted_run_spec.model_dump(mode="json"),
            actor_label=actor_label,
            source_commit=run_spec.source_commit,
            source_branch=run_spec.source_branch,
            timestamp=now,
        )
        await self.repository.append_event(
            run_id=run_spec.run_id,
            event_type="run.queued",
            payload={
                "workflow_name": package.name,
                "repo_path": str(package.repo_path),
                "actor_label": actor_label,
            },
            actor_label=actor_label,
            timestamp=now,
        )

        task = asyncio.create_task(
            self._run_one(run_spec.run_id, run_spec, package),
            name=f"durable-run-{run_spec.run_id}",
        )
        self.active_tasks[run_spec.run_id] = task
        return run_spec.run_id

    async def wait(self, run_id: str) -> PipelineResult:
        task = self.active_tasks.get(run_id)
        if task is not None:
            return await task
        if run_id in self._completed_results:
            return self._completed_results[run_id]
        if run_id in self._completed_failures:
            raise self._completed_failures[run_id]
        raise KeyError(f"Unknown run id: {run_id}")

    def notify_approval_decision(self, run_id: str, approval_id: str) -> bool:
        waiter = self.get_waiting_approval(run_id, approval_id)
        if waiter is None:
            return False
        waiter.wake_event.set()
        return True

    def get_waiting_approval(
        self,
        run_id: str,
        approval_id: str,
    ) -> _PendingApprovalWaiter | None:
        waiter = self._approval_waiters.get(approval_id)
        if waiter is None or waiter.run_id != run_id or waiter.wake_event.is_set():
            return None
        return waiter

    def resume_waiting_approval(self, waiter: _PendingApprovalWaiter) -> bool:
        current = self._approval_waiters.get(waiter.approval_id)
        if current is None:
            return False
        if current is not waiter or current.run_id != waiter.run_id or current.wake_event.is_set():
            return False
        current.wake_event.set()
        return True

    async def _run_one(
        self,
        run_id: str,
        run_spec: RunSpec,
        package: WorkflowPackage,
    ) -> PipelineResult:
        prepared: PreparedWorktree | None = None
        result: PipelineResult | None = None
        logs_root = self._artifact_root / "_runtime" / run_id
        logs_root.mkdir(parents=True, exist_ok=True)
        event_queue: asyncio.Queue[PipelineEvent | object] | None = None
        writer_task: asyncio.Task[None] | None = None
        writer_closed = False

        try:
            await self._update_run_record(run_id, status=RunStatus.PREPARING)
            await self.repository.append_event(
                run_id,
                "run.preparing",
                {"workflow_name": package.name},
                actor_label=run_spec.actor_label,
            )

            prepared = await asyncio.to_thread(
                self._worktree_manager.prepare,
                run_spec.repo_path,
                run_id=run_id,
                base_commit=run_spec.source_commit,
            )

            await self._update_run_record(
                run_id,
                status=RunStatus.RUNNING,
                worktree_path=str(prepared.path),
                managed_branch=prepared.branch,
                started_at=_utc_now(),
            )
            await self.repository.append_event(
                run_id,
                "run.started",
                {
                    "worktree_path": str(prepared.path),
                    "managed_branch": prepared.branch,
                    "base_commit": prepared.base_commit,
                },
                actor_label=run_spec.actor_label,
            )

            event_queue = asyncio.Queue()
            writer_task = asyncio.create_task(
                self._write_pipeline_events(
                    run_id=run_id,
                    workflow_name=package.name,
                    actor_label=run_spec.actor_label,
                    prepared=prepared,
                    event_queue=event_queue,
                    base_commit=run_spec.source_commit,
                ),
                name=f"durable-run-events-{run_id}",
            )
            try:
                graph = package.graph
                if graph is None:
                    raise RuntimeError(f"Workflow package has no graph: {package.name}")

                def _on_event(event: PipelineEvent) -> None:
                    if writer_task is not None and writer_task.done():
                        exc = writer_task.exception()
                        if exc is not None:
                            raise RuntimeError("pipeline event writer failed") from exc
                    event_queue.put_nowait(event)

                run_context = _RunInterviewerContext(
                    run_id=run_id,
                    actor_label=run_spec.actor_label,
                )
                context_token = self._run_interviewer_context.set(run_context)
                try:
                    run_environment = select_run_environment(
                        run_spec.effective_environment,
                        prepared,
                    )
                    async with run_environment.activate():
                        result = await run_pipeline(
                            graph,
                            self._handlers,
                            context=dict(run_spec.inputs),
                            logs_root=logs_root,
                            on_event=_on_event,
                        )
                finally:
                    self._run_interviewer_context.reset(context_token)
            finally:
                if not writer_closed:
                    await self._close_event_writer(event_queue, writer_task)
                    writer_closed = True

            assert result is not None
            return await self._record_terminal_result(
                run_id=run_id,
                run_spec=run_spec,
                prepared=prepared,
                logs_root=logs_root,
                result=result,
            )
        except asyncio.CancelledError as exc:
            external_cancellation = self._current_task_cancel_requested()
            self._clear_current_task_cancellation()
            if external_cancellation:
                async def _finalize_cancelled() -> PipelineResult:
                    nonlocal writer_closed

                    if not writer_closed:
                        await self._close_event_writer(event_queue, writer_task)
                        writer_closed = True

                    cancelled = PipelineResult(
                        status=PipelineStatus.CANCELLED,
                        error="Run cancelled",
                    )
                    return await self._record_terminal_result(
                        run_id=run_id,
                        run_spec=run_spec,
                        prepared=prepared,
                        logs_root=logs_root,
                        result=cancelled,
                        terminal_event_type="run.cancelled",
                        terminal_payload={"reason": "external cancellation"},
                        error_category="CancelledError",
                        error_message="Run cancelled",
                    )

                return await self._await_terminal_finalization(
                    run_id=run_id,
                    finalizer=_finalize_cancelled(),
                    on_finalizer_cancelled=lambda: self._persist_terminal_result_fallback(
                        run_id=run_id,
                        run_spec=run_spec,
                        prepared=prepared,
                        result=PipelineResult(
                            status=PipelineStatus.CANCELLED,
                            error="Run cancelled",
                        ),
                        terminal_event_type="run.cancelled",
                        terminal_payload={"reason": "external cancellation"},
                        error_category="CancelledError",
                        error_message="Run cancelled",
                    ),
                )

            failure_message = str(exc) or "Terminal finalization cancelled"
            failure_error = f"CancelledError: {failure_message}"

            async def _finalize_internal_cancellation() -> PipelineResult:
                nonlocal writer_closed

                if not writer_closed:
                    with suppress(Exception):
                        await self._close_event_writer(event_queue, writer_task)
                    writer_closed = True

                failed = PipelineResult(
                    status=PipelineStatus.FAILED,
                    error=failure_error,
                )
                return await self._record_terminal_result(
                    run_id=run_id,
                    run_spec=run_spec,
                    prepared=prepared,
                    logs_root=logs_root,
                    result=failed,
                    terminal_event_type="run.failed",
                    terminal_payload={"error": failed.error or "unknown"},
                    error_category="CancelledError",
                    error_message=failure_message,
                )

            return await self._await_terminal_finalization(
                run_id=run_id,
                finalizer=_finalize_internal_cancellation(),
                on_finalizer_cancelled=lambda: self._persist_terminal_result_fallback(
                    run_id=run_id,
                    run_spec=run_spec,
                    prepared=prepared,
                    result=PipelineResult(
                        status=PipelineStatus.FAILED,
                        error="Terminal finalization cancelled",
                    ),
                    terminal_event_type="run.failed",
                    terminal_payload={"error": "Terminal finalization cancelled"},
                    error_category="CancelledError",
                    error_message="Terminal finalization cancelled",
                ),
            )
        except Exception as exc:  # noqa: BLE001
            failure_category = type(exc).__name__
            failure_message = str(exc)
            failure_error = f"{failure_category}: {exc}"

            async def _finalize_failed() -> PipelineResult:
                nonlocal writer_closed

                if not writer_closed:
                    with suppress(Exception):
                        await self._close_event_writer(event_queue, writer_task)
                    writer_closed = True

                result = PipelineResult(
                    status=PipelineStatus.FAILED,
                    error=failure_error,
                )
                return await self._record_terminal_result(
                    run_id=run_id,
                    run_spec=run_spec,
                    prepared=prepared,
                    logs_root=logs_root,
                    result=result,
                    terminal_event_type="run.failed",
                    terminal_payload={"error": result.error or "unknown"},
                    error_category=failure_category,
                    error_message=failure_message,
                )

            return await self._await_terminal_finalization(
                run_id=run_id,
                finalizer=_finalize_failed(),
                on_finalizer_cancelled=lambda: self._persist_terminal_result_fallback(
                    run_id=run_id,
                    run_spec=run_spec,
                    prepared=prepared,
                    result=PipelineResult(
                        status=PipelineStatus.FAILED,
                        error="Terminal finalization cancelled",
                    ),
                    terminal_event_type="run.failed",
                    terminal_payload={"error": "Terminal finalization cancelled"},
                    error_category=failure_category,
                    error_message="Terminal finalization cancelled",
                ),
            )
        finally:
            self.active_tasks.pop(run_id, None)

    async def _write_pipeline_events(
        self,
        *,
        run_id: str,
        workflow_name: str,
        actor_label: str,
        prepared: PreparedWorktree,
        event_queue: asyncio.Queue[PipelineEvent | object],
        base_commit: str,
    ) -> None:
        stage_indices: dict[str, int] = {}
        existing_events = await self.repository.list_events(run_id, after_sequence=0, limit=100)
        last_sequence = existing_events[-1].sequence if existing_events else 0

        while True:
            item = await event_queue.get()
            if item is _QUEUE_SENTINEL:
                return

            event = cast(PipelineEvent, item)
            event_type, payload = _durable_event_payload(event)
            if isinstance(event, (StageStarted, StageCompleted, StageFailed, StageRetrying)):
                stage_indices[event.name] = event.index

            new_events = await self.repository.list_events(
                run_id,
                after_sequence=last_sequence,
                limit=100,
            )
            if new_events:
                last_sequence = new_events[-1].sequence
            expected_sequence = last_sequence + 1

            if isinstance(event, CheckpointSaved):
                checkpoint = await asyncio.to_thread(
                    self._checkpoint_service.create_checkpoint,
                    worktree_path=prepared.path,
                    run_id=run_id,
                    workflow_name=workflow_name,
                    node_id=event.node_id,
                    stage_index=stage_indices.get(event.node_id, 0),
                    event_sequence=expected_sequence,
                    base_commit=base_commit,
                )
                await self.repository.create_checkpoint(
                    checkpoint_id=f"ckpt_{uuid.uuid4().hex}",
                    run_id=run_id,
                    node_id=checkpoint.node_id,
                    stage_index=checkpoint.stage_index,
                    commit_sha=checkpoint.commit_sha,
                    ref_name=checkpoint.ref_name,
                    timestamp=_utc_now(),
                )

            event_record = await self.repository.append_event(
                run_id=run_id,
                event_type=event_type,
                payload=payload,
                actor_label=actor_label,
            )
            if event_record.sequence < expected_sequence:
                raise RuntimeError("event sequence regressed during pipeline event persistence")
            last_sequence = event_record.sequence

    async def _capture_artifacts(self, run_id: str, logs_root: Path) -> None:
        capture_key = _artifact_capture_key(run_id, logs_root)
        captured_files = self._captured_terminal_artifact_files.setdefault(capture_key, set())
        for file_path in sorted(path for path in logs_root.rglob("*") if path.is_file()):
            relative_path = file_path.relative_to(logs_root)
            relative_key = relative_path.as_posix()
            if relative_key in captured_files:
                continue
            kind, name = _artifact_identity(relative_path)
            stored = self._artifact_store.write_bytes(
                run_id=run_id,
                kind=kind,
                name=name,
                data=file_path.read_bytes(),
                media_type=_media_type(file_path),
            )
            try:
                await self.repository.create_artifact(
                    artifact_id=f"artifact_{uuid.uuid4().hex}",
                    run_id=run_id,
                    kind=stored.kind,
                    name=stored.name,
                    uri=stored.uri,
                    media_type=stored.media_type,
                    size_bytes=stored.size_bytes,
                    sha256=stored.sha256,
                    timestamp=_utc_now(),
                )
            except asyncio.CancelledError:
                if await self._artifact_row_exists(
                    run_id=run_id,
                    kind=stored.kind,
                    name=stored.name,
                    uri=stored.uri,
                ):
                    self._clear_current_task_cancellation()
                else:
                    raise
            except Exception:
                if not await self._artifact_row_exists(
                    run_id=run_id,
                    kind=stored.kind,
                    name=stored.name,
                    uri=stored.uri,
                ):
                    raise
            captured_files.add(relative_key)

    async def _capture_artifacts_once(self, run_id: str, logs_root: Path) -> None:
        capture_key = _artifact_capture_key(run_id, logs_root)
        if capture_key in self._captured_terminal_artifacts or not logs_root.exists():
            return
        await self._capture_artifacts(run_id, logs_root)
        self._captured_terminal_artifacts.add(capture_key)

    async def _update_run_record(
        self,
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
        async with session_scope(self._session_factory) as session:
            run = await session.get(RunRecordModel, run_id)
            if run is None:
                raise KeyError(f"Run not found: {run_id}")
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
            run.updated_at = _utc_now()
            await session.flush()

    async def _record_terminal_result(
        self,
        *,
        run_id: str,
        run_spec: RunSpec,
        prepared: PreparedWorktree | None,
        logs_root: Path,
        result: PipelineResult,
        terminal_event_type: str | None = None,
        terminal_payload: dict[str, Any] | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> PipelineResult:
        await self._capture_artifacts_once(run_id, logs_root)

        persisted_terminal = self._persisted_terminal_results.get(run_id)
        if persisted_terminal is not None:
            result = persisted_terminal.result
            terminal_event_type = persisted_terminal.event.event_type
            terminal_payload = dict(persisted_terminal.event.payload)
            error_category = persisted_terminal.error_category
            error_message = persisted_terminal.error_message
        else:
            terminal_event_type, terminal_payload = self._resolve_terminal_event(
                result=result,
                terminal_event_type=terminal_event_type,
                terminal_payload=terminal_payload,
            )
        await self._persist_terminal_event_if_needed(
            run_id=run_id,
            result=result,
            actor_label=run_spec.actor_label,
            terminal_event_type=terminal_event_type,
            terminal_payload=terminal_payload,
            error_category=error_category,
            error_message=error_message,
            retry_on_cancellation=False,
        )

        await self._update_run_record(
            run_id,
            status=_run_status_for_result(result),
            worktree_path=str(prepared.path) if prepared is not None else None,
            managed_branch=prepared.branch if prepared is not None else None,
            completed_at=_utc_now(),
            error_category=error_category if error_category is not None else (
                "pipeline" if result.error else None
            ),
            error_message=error_message if error_message is not None else result.error,
        )
        self._store_completed_result(run_id, result)
        return result

    async def _close_event_writer(
        self,
        event_queue: asyncio.Queue[PipelineEvent | object] | None,
        writer_task: asyncio.Task[None] | None,
    ) -> None:
        if event_queue is None or writer_task is None:
            return
        if not writer_task.done():
            event_queue.put_nowait(_QUEUE_SENTINEL)
        await writer_task

    async def _persist_terminal_result_fallback(
        self,
        *,
        run_id: str,
        run_spec: RunSpec,
        prepared: PreparedWorktree | None,
        result: PipelineResult,
        terminal_event_type: str | None = None,
        terminal_payload: dict[str, Any] | None = None,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> PipelineResult:
        persisted_terminal = self._persisted_terminal_results.get(run_id)
        if persisted_terminal is not None:
            result = persisted_terminal.result
            terminal_event_type = persisted_terminal.event.event_type
            terminal_payload = dict(persisted_terminal.event.payload)
            error_category = persisted_terminal.error_category
            error_message = persisted_terminal.error_message
        else:
            terminal_event_type, terminal_payload = self._resolve_terminal_event(
                result=result,
                terminal_event_type=terminal_event_type,
                terminal_payload=terminal_payload,
            )
        await self._persist_terminal_event_if_needed(
            run_id=run_id,
            result=result,
            actor_label=run_spec.actor_label,
            terminal_event_type=terminal_event_type,
            terminal_payload=terminal_payload,
            error_category=error_category,
            error_message=error_message,
            retry_on_cancellation=True,
        )

        await self._update_run_record(
            run_id,
            status=_run_status_for_result(result),
            worktree_path=str(prepared.path) if prepared is not None else None,
            managed_branch=prepared.branch if prepared is not None else None,
            completed_at=_utc_now(),
            error_category=error_category if error_category is not None else (
                "pipeline" if result.error else None
            ),
            error_message=error_message if error_message is not None else result.error,
        )
        self._store_completed_result(run_id, result)

        return result

    async def _await_terminal_finalization(
        self,
        *,
        run_id: str,
        finalizer: Coroutine[Any, Any, PipelineResult],
        on_finalizer_cancelled: Callable[[], Coroutine[Any, Any, PipelineResult]] | None = None,
    ) -> PipelineResult:
        # External cancellation should not interrupt terminal durable writes once cleanup starts.
        finalizer_task = asyncio.create_task(finalizer, name=f"durable-run-finalize-{run_id}")
        while True:
            try:
                return await self._await_terminal_task(run_id, finalizer_task)
            except asyncio.CancelledError:
                self._clear_current_task_cancellation()
                if finalizer_task.done():
                    if finalizer_task.cancelled():
                        if on_finalizer_cancelled is not None:
                            fallback_task = asyncio.create_task(
                                on_finalizer_cancelled(),
                                name=f"durable-run-finalize-fallback-{run_id}",
                            )
                            while True:
                                try:
                                    return await self._await_terminal_task(run_id, fallback_task)
                                except asyncio.CancelledError:
                                    self._clear_current_task_cancellation()
                                    if fallback_task.done():
                                        if fallback_task.cancelled():
                                            break
                                        try:
                                            return fallback_task.result()
                                        except Exception as exc:
                                            self._store_completed_failure(run_id, exc)
                                            raise
                        failure = RuntimeError(
                            "Terminal finalization cancelled before terminal event persisted"
                        )
                        self._store_completed_failure(run_id, failure)
                        raise failure from None
                    try:
                        return finalizer_task.result()
                    except Exception as exc:
                        self._store_completed_failure(run_id, exc)
                        raise

    async def _await_terminal_task(
        self,
        run_id: str,
        task: asyncio.Task[PipelineResult],
    ) -> PipelineResult:
        try:
            return await asyncio.shield(task)
        except Exception as exc:
            self._store_completed_failure(run_id, exc)
            raise

    def _store_completed_result(self, run_id: str, result: PipelineResult) -> None:
        self._clear_artifact_capture_state(run_id)
        self._persisted_terminal_results.pop(run_id, None)
        self._completed_failures.pop(run_id, None)
        self._completed_results[run_id] = result

    def _store_completed_failure(self, run_id: str, exc: Exception) -> None:
        self._completed_results.pop(run_id, None)
        self._completed_failures[run_id] = exc

    def _clear_artifact_capture_state(self, run_id: str) -> None:
        capture_keys = [key for key in self._captured_terminal_artifacts if key[0] == run_id]
        for capture_key in capture_keys:
            self._captured_terminal_artifacts.discard(capture_key)
        file_keys = [key for key in self._captured_terminal_artifact_files if key[0] == run_id]
        for file_key in file_keys:
            self._captured_terminal_artifact_files.pop(file_key, None)

    def _clear_current_task_cancellation(self) -> None:
        current = asyncio.current_task()
        if current is None:
            return
        while current.cancelling():
            current.uncancel()

    def _current_task_cancel_requested(self) -> bool:
        current = asyncio.current_task()
        return current is not None and current.cancelling() > 0

    def _resolve_terminal_event(
        self,
        *,
        result: PipelineResult,
        terminal_event_type: str | None,
        terminal_payload: dict[str, Any] | None,
    ) -> tuple[str | None, dict[str, Any] | None]:
        if terminal_event_type is None and result.status == PipelineStatus.COMPLETED:
            outputs = {
                key: _preview_codergen_output(value)
                for key, value in result.context.items()
                if (
                    key.startswith("codergen.")
                    and key.endswith(".output")
                    and isinstance(value, str)
                )
            }
            return "run.completed", {"outputs": outputs}
        if terminal_event_type is None and result.status == PipelineStatus.FAILED:
            return "run.failed", {"error": result.error or "unknown"}
        return terminal_event_type, terminal_payload

    async def _persist_terminal_event_if_needed(
        self,
        *,
        run_id: str,
        result: PipelineResult,
        actor_label: str,
        terminal_event_type: str | None,
        terminal_payload: dict[str, Any] | None,
        error_category: str | None,
        error_message: str | None,
        retry_on_cancellation: bool,
    ) -> None:
        persistence_key = _terminal_event_persistence_key(
            result=result,
            terminal_event_type=terminal_event_type,
            terminal_payload=terminal_payload,
        )
        if persistence_key is None:
            return
        persisted_terminal = self._persisted_terminal_results.get(run_id)
        if persisted_terminal is not None and persisted_terminal.event == persistence_key:
            return

        attempts = 2 if retry_on_cancellation else 1
        last_cancellation: asyncio.CancelledError | None = None
        for attempt in range(attempts):
            try:
                assert terminal_event_type is not None
                assert terminal_payload is not None
                await self.repository.append_event(
                    run_id,
                    terminal_event_type,
                    terminal_payload,
                    actor_label=actor_label,
                )
                self._cache_persisted_terminal_result(
                    run_id=run_id,
                    persistence_key=persistence_key,
                    result=result,
                    error_category=error_category,
                    error_message=error_message,
                )
                return
            except asyncio.CancelledError as exc:
                if await self._reconcile_terminal_event_persistence(
                    run_id=run_id,
                    persistence_key=persistence_key,
                    result=result,
                    error_category=error_category,
                    error_message=error_message,
                ):
                    self._clear_current_task_cancellation()
                    return
                last_cancellation = exc
                self._clear_current_task_cancellation()
                if not retry_on_cancellation or attempt == attempts - 1:
                    if retry_on_cancellation:
                        failure = RuntimeError(
                            "terminal event persistence failed during terminal finalization"
                        )
                        self._store_completed_failure(run_id, failure)
                        raise failure from last_cancellation
                    raise
            except Exception:
                if await self._reconcile_terminal_event_persistence(
                    run_id=run_id,
                    persistence_key=persistence_key,
                    result=result,
                    error_category=error_category,
                    error_message=error_message,
                ):
                    return
                raise

    def _cache_persisted_terminal_result(
        self,
        *,
        run_id: str,
        persistence_key: _PersistedTerminalEvent,
        result: PipelineResult,
        error_category: str | None,
        error_message: str | None,
    ) -> None:
        self._persisted_terminal_results[run_id] = _PersistedTerminalResult(
            event=persistence_key,
            result=result,
            error_category=error_category if error_category is not None else (
                "pipeline" if result.error else None
            ),
            error_message=error_message if error_message is not None else result.error,
        )

    async def _reconcile_terminal_event_persistence(
        self,
        *,
        run_id: str,
        persistence_key: _PersistedTerminalEvent,
        result: PipelineResult,
        error_category: str | None,
        error_message: str | None,
    ) -> bool:
        if not await self._terminal_event_exists(run_id, persistence_key):
            return False
        self._cache_persisted_terminal_result(
            run_id=run_id,
            persistence_key=persistence_key,
            result=result,
            error_category=error_category,
            error_message=error_message,
        )
        return True

    async def _terminal_event_exists(
        self,
        run_id: str,
        persistence_key: _PersistedTerminalEvent,
    ) -> bool:
        after_sequence = 0
        while True:
            events = await self.repository.list_events(
                run_id,
                after_sequence=after_sequence,
                limit=100,
            )
            if not events:
                return False
            for event in events:
                if _event_matches_persistence_key(event, persistence_key):
                    return True
            after_sequence = events[-1].sequence

    async def _artifact_row_exists(
        self,
        *,
        run_id: str,
        kind: str,
        name: str,
        uri: str,
    ) -> bool:
        list_artifacts = cast(
            Callable[[str], Awaitable[list[Any]]] | None,
            getattr(self.repository, "list_artifacts", None),
        )
        if list_artifacts is not None:
            artifacts = await list_artifacts(run_id)
            return any(
                artifact.kind == kind and artifact.name == name and artifact.uri == uri
                for artifact in artifacts
            )

        if isinstance(self.repository, PlatformRepository):
            async with session_scope(self._session_factory) as session:
                existing = await session.scalar(
                    select(ArtifactModel).where(
                        ArtifactModel.run_id == run_id,
                        ArtifactModel.kind == kind,
                        ArtifactModel.name == name,
                        ArtifactModel.uri == uri,
                    )
                )
                return existing is not None

        artifacts = getattr(self.repository, "artifacts", None)
        if isinstance(artifacts, dict):
            return any(
                artifact.kind == kind and artifact.name == name and artifact.uri == uri
                for artifact in artifacts.get(run_id, [])
            )

        return False

    async def _request_human_approval(self, question: Question) -> Answer:
        run_context = self._run_interviewer_context.get()
        if run_context is None:
            raise RuntimeError("Server-run interviewer requires an active run context")

        approval_id = f"approval_{uuid.uuid4().hex}"
        waiter = _PendingApprovalWaiter(
            run_id=run_context.run_id,
            approval_id=approval_id,
            wake_event=asyncio.Event(),
            allowed_options=tuple(question.options) if question.options is not None else None,
        )
        self._approval_waiters[approval_id] = waiter
        timestamp = _utc_now()

        try:
            await self.repository.create_approval(
                approval_id=approval_id,
                run_id=run_context.run_id,
                node_id=question.stage or None,
                question=question.text,
                timestamp=timestamp,
            )
            await self.repository.append_event(
                run_context.run_id,
                "approval.requested",
                {
                    "approval_id": approval_id,
                    "node_id": question.stage,
                    "question": question.text,
                    "status": "pending",
                },
                actor_label=run_context.actor_label,
                timestamp=timestamp,
            )
            await self._update_run_record(
                run_context.run_id,
                status=RunStatus.WAITING_FOR_APPROVAL,
            )
            await waiter.wake_event.wait()
            approval = await self._get_approval_decision(approval_id)
            if approval is None or approval.status != "decided" or approval.answer is None:
                raise RuntimeError(f"Approval decision missing for {approval_id}")
            await self.repository.append_event(
                run_context.run_id,
                "approval.decided",
                {
                    "approval_id": approval.id,
                    "node_id": approval.node_id or question.stage,
                    "question": approval.question,
                    "answer": approval.answer,
                    "actor_label": approval.actor_label,
                    "status": approval.status,
                },
                actor_label=approval.actor_label,
            )
            await self._update_run_record(
                run_context.run_id,
                status=RunStatus.RUNNING,
            )
            selected_option = (
                approval.answer
                if question.options is not None and approval.answer in question.options
                else None
            )
            return Answer(
                value=approval.answer,
                selected_option=selected_option,
                text=approval.answer,
            )
        finally:
            self._approval_waiters.pop(approval_id, None)

    async def _get_approval_decision(self, approval_id: str) -> ApprovalDecisionModel | None:
        async with session_scope(self._session_factory) as session:
            return await session.get(ApprovalDecisionModel, approval_id)


def _durable_event_payload(event: PipelineEvent) -> tuple[str, dict[str, Any]]:
    payload = asdict(event)
    payload["description"] = event.description

    if isinstance(event, PipelineStarted):
        return "pipeline.started", payload
    if isinstance(event, StageStarted):
        return "stage.started", payload
    if isinstance(event, StageCompleted):
        return "stage.completed", payload
    if isinstance(event, StageFailed):
        return "stage.failed", payload
    if isinstance(event, StageRetrying):
        return "stage.retrying", payload
    if isinstance(event, CheckpointSaved):
        return "checkpoint.saved", payload
    if isinstance(event, PipelineCompleted):
        return "pipeline.completed", payload
    if isinstance(event, PipelineFailed):
        return "pipeline.failed", payload
    return "pipeline.event", payload


def _preview_codergen_output(value: str) -> str:
    redacted = redact_text(value)
    if len(redacted) <= CODERGEN_OUTPUT_PREVIEW_MAX_CHARS:
        return redacted
    return (
        redacted[:CODERGEN_OUTPUT_PREVIEW_MAX_CHARS]
        + f"\n[truncated to {CODERGEN_OUTPUT_PREVIEW_MAX_CHARS} of {len(redacted)} characters]"
    )


def _serialize_diagnostics(package: WorkflowPackage) -> dict[str, Any]:
    return {
        "items": [
            {
                "rule": diagnostic.rule,
                "severity": diagnostic.severity.value,
                "message": diagnostic.message,
                "node_id": diagnostic.node_id,
                "edge_index": diagnostic.edge_index,
                "edge_id": diagnostic.edge_id,
            }
            for diagnostic in package.diagnostics
        ]
    }


def _repo_identifier(repo_path: Path) -> str:
    digest = hashlib.sha1(str(repo_path).encode()).hexdigest()
    return f"repo_{digest[:32]}"


def _workflow_identifier(repo_id: str, workflow_name: str) -> str:
    digest = hashlib.sha1(f"{repo_id}:{workflow_name}".encode()).hexdigest()
    return f"wf_{digest[:32]}"


def _accepts_project_config_status(
    register_repo: Callable[..., Awaitable[Any]],
) -> bool:
    parameters = inspect.signature(register_repo).parameters.values()
    return any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or parameter.name == "project_config_status"
        for parameter in parameters
    )


def _run_status_for_result(result: PipelineResult) -> RunStatus:
    if result.status == PipelineStatus.COMPLETED:
        return RunStatus.COMPLETED
    if result.status == PipelineStatus.CANCELLED:
        return RunStatus.CANCELLED
    return RunStatus.FAILED


def _artifact_identity(relative_path: Path) -> tuple[str, str]:
    if len(relative_path.parts) == 1:
        return "run", relative_path.name
    return relative_path.parts[0], relative_path.name


def _artifact_capture_key(run_id: str, logs_root: Path) -> tuple[str, str]:
    return run_id, str(logs_root.resolve())


def _media_type(path: Path) -> str:
    if path.suffix == ".json":
        return "application/json"
    if path.suffix == ".md":
        return "text/markdown"
    if path.suffix == ".txt":
        return "text/plain"
    return "application/octet-stream"


def _terminal_event_persistence_key(
    *,
    result: PipelineResult,
    terminal_event_type: str | None,
    terminal_payload: dict[str, Any] | None,
) -> _PersistedTerminalEvent | None:
    if terminal_event_type is None or terminal_payload is None:
        return None
    return _PersistedTerminalEvent(
        result_status=result.status,
        result_error=result.error,
        event_type=terminal_event_type,
        payload=tuple(
            sorted(
                (key, _freeze_terminal_payload_value(value))
                for key, value in terminal_payload.items()
            )
        ),
    )


def _freeze_terminal_payload_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(
            sorted((key, _freeze_terminal_payload_value(item)) for key, item in value.items())
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_terminal_payload_value(item) for item in value)
    return value


def _event_matches_persistence_key(
    event: Any,
    persistence_key: _PersistedTerminalEvent,
) -> bool:
    return (
        event.event_type == persistence_key.event_type
        and tuple(
            sorted(
                (key, _freeze_terminal_payload_value(value))
                for key, value in event.payload.items()
            )
        )
        == persistence_key.payload
    )
