"""Phase 2 platform app endpoints for run launch and approvals."""

from __future__ import annotations

import datetime as dt
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from attractor_platform.errors import AttractorPlatformError
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.packages import load_workflow_package
from attractor_platform.storage.db import session_scope
from attractor_platform.storage.models import ApprovalDecisionModel, RunRecordModel, RunStatus
from attractor_platform.storage.repositories import PlatformRepository


@dataclass(frozen=True)
class _PlatformServices:
    executor: DurableRunExecutor
    repository: PlatformRepository
    session_factory: async_sessionmaker[AsyncSession]


def _services(request: Request) -> _PlatformServices:
    return request.app.state.platform_services


def _json_error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


def _serialize_timestamp(timestamp: dt.datetime | None) -> str | None:
    return timestamp.isoformat() if timestamp is not None else None


def _serialize_run(run: RunRecordModel) -> dict[str, Any]:
    return {
        "id": run.id,
        "status": run.status,
        "repo_id": run.repo_id,
        "workflow_id": run.workflow_id,
        "actor_label": run.actor_label,
        "worktree_path": run.worktree_path,
        "managed_branch": run.managed_branch,
        "error_category": run.error_category,
        "error_message": run.error_message,
        "created_at": _serialize_timestamp(run.created_at),
        "updated_at": _serialize_timestamp(run.updated_at),
        "started_at": _serialize_timestamp(run.started_at),
        "completed_at": _serialize_timestamp(run.completed_at),
    }


def _serialize_approval(approval: ApprovalDecisionModel) -> dict[str, Any]:
    return {
        "id": approval.id,
        "run_id": approval.run_id,
        "node_id": approval.node_id,
        "question": approval.question,
        "answer": approval.answer,
        "actor_label": approval.actor_label,
        "status": approval.status,
        "created_at": _serialize_timestamp(approval.created_at),
        "decided_at": _serialize_timestamp(approval.decided_at),
    }


async def _get_run_or_404(
    repository: PlatformRepository,
    run_id: str,
) -> RunRecordModel | JSONResponse:
    run = await repository.get_run(run_id)
    if run is None:
        return _json_error(f"Run {run_id} not found", 404)
    return run


async def _list_approvals_for_run(
    services: _PlatformServices,
    run_id: str,
) -> list[Any]:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return list(
                await session.scalars(
                    select(ApprovalDecisionModel)
                    .where(ApprovalDecisionModel.run_id == run_id)
                    .order_by(ApprovalDecisionModel.created_at, ApprovalDecisionModel.id)
                )
            )

    list_approvals = cast(
        Callable[[str], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_approvals", None),
    )
    if list_approvals is not None:
        return list(await list_approvals(run_id))

    raise RuntimeError("Repository does not support listing approvals")


async def _get_approval_for_run(
    services: _PlatformServices,
    run_id: str,
    approval_id: str,
) -> Any | None:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return await session.scalar(
                select(ApprovalDecisionModel).where(
                    ApprovalDecisionModel.id == approval_id,
                    ApprovalDecisionModel.run_id == run_id,
                )
            )

    get_approval = cast(
        Callable[[str], Awaitable[Any | None]] | None,
        getattr(services.repository, "get_approval", None),
    )
    if get_approval is not None:
        approval = await get_approval(approval_id)
        if approval is None or approval.run_id != run_id:
            return None
        return approval

    raise RuntimeError("Repository does not support loading approvals")


def _allowed_approval_answers(
    run: Any,
    approval: Any,
    waiter: Any,
) -> tuple[str, ...] | None:
    waiter_options = getattr(waiter, "allowed_options", None)
    if isinstance(waiter_options, tuple):
        return waiter_options or None

    run_spec = getattr(run, "run_spec", None)
    if not isinstance(run_spec, dict):
        return None

    repo_path = run_spec.get("repo_path")
    workflow_name = run_spec.get("workflow_name")
    if not isinstance(repo_path, str) or not isinstance(workflow_name, str):
        return None
    if not isinstance(approval.node_id, str) or not approval.node_id:
        return None

    package = load_workflow_package(repo_path, workflow_name)
    if package.graph is None:
        return None
    node = package.graph.get_node(approval.node_id)
    if node is None:
        return None

    options = tuple(edge.label for edge in package.graph.outgoing_edges(node.id) if edge.label)
    return options or None


async def _decide_pending_approval(
    services: _PlatformServices,
    *,
    run_id: str,
    approval_id: str,
    answer: str,
    actor_label: str,
    timestamp: dt.datetime,
) -> tuple[str, Any | None]:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            result = await session.execute(
                update(ApprovalDecisionModel)
                .where(
                    ApprovalDecisionModel.id == approval_id,
                    ApprovalDecisionModel.run_id == run_id,
                    ApprovalDecisionModel.status == "pending",
                )
                .values(
                    answer=answer,
                    actor_label=actor_label,
                    status="decided",
                    decided_at=timestamp,
                )
            )
            rowcount = cast(int | None, cast(Any, result).rowcount)
            if rowcount == 1:
                decided = await session.scalar(
                    select(ApprovalDecisionModel).where(
                        ApprovalDecisionModel.id == approval_id,
                        ApprovalDecisionModel.run_id == run_id,
                    )
                )
                return "updated", decided

            current = await session.scalar(
                select(ApprovalDecisionModel).where(
                    ApprovalDecisionModel.id == approval_id,
                    ApprovalDecisionModel.run_id == run_id,
                )
            )
            return ("not_found", None) if current is None else ("conflict", current)

    decide_pending_approval = cast(
        Callable[..., Awaitable[Any | None]] | None,
        getattr(services.repository, "decide_pending_approval", None),
    )
    if decide_pending_approval is not None:
        decided = await decide_pending_approval(
            approval_id=approval_id,
            run_id=run_id,
            answer=answer,
            actor_label=actor_label,
            timestamp=timestamp,
        )
        if decided is not None:
            return "updated", decided
        current = await _get_approval_for_run(services, run_id, approval_id)
        return ("not_found", None) if current is None else ("conflict", current)

    raise RuntimeError("Repository does not support deciding approvals")


async def _revert_decided_approval(
    services: _PlatformServices,
    *,
    run_id: str,
    approval_id: str,
    answer: str,
    actor_label: str,
    decided_at: dt.datetime,
) -> bool:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            result = await session.execute(
                update(ApprovalDecisionModel)
                .where(
                    ApprovalDecisionModel.id == approval_id,
                    ApprovalDecisionModel.run_id == run_id,
                    ApprovalDecisionModel.status == "decided",
                    ApprovalDecisionModel.answer == answer,
                    ApprovalDecisionModel.actor_label == actor_label,
                    ApprovalDecisionModel.decided_at == decided_at,
                )
                .values(
                    answer=None,
                    actor_label="",
                    status="pending",
                    decided_at=None,
                )
            )
            return cast(int | None, cast(Any, result).rowcount) == 1

    revert_decided_approval = cast(
        Callable[..., Awaitable[bool]] | None,
        getattr(services.repository, "revert_decided_approval", None),
    )
    if revert_decided_approval is not None:
        return await revert_decided_approval(
            approval_id=approval_id,
            run_id=run_id,
            answer=answer,
            actor_label=actor_label,
            decided_at=decided_at,
        )

    raise RuntimeError("Repository does not support reverting approvals")


async def create_run(request: Request) -> JSONResponse:
    services = _services(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json_error("Invalid JSON body", 400)

    repo_path = body.get("repo_path")
    workflow_name = body.get("workflow")
    actor_label = body.get("actor_label", "")
    inputs = body.get("inputs", {})

    if not isinstance(repo_path, str) or not repo_path:
        return _json_error("Missing 'repo_path' field", 400)
    if not isinstance(workflow_name, str) or not workflow_name:
        return _json_error("Missing 'workflow' field", 400)
    if not isinstance(actor_label, str):
        return _json_error("'actor_label' must be a string", 400)
    if not isinstance(inputs, dict):
        return _json_error("'inputs' must be an object", 400)

    try:
        run_id = await services.executor.register_and_launch(
            repo_path=repo_path,
            workflow_name=workflow_name,
            actor_label=actor_label,
            inputs=inputs,
        )
    except AttractorPlatformError as exc:
        return JSONResponse(exc.to_dict(), status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _json_error(str(exc), 500)

    run = await services.repository.get_run(run_id)
    if run is None:
        return _json_error(f"Run {run_id} was not persisted", 500)
    return JSONResponse(_serialize_run(run), status_code=201)


async def get_run(request: Request) -> JSONResponse:
    services = _services(request)
    run = await _get_run_or_404(services.repository, request.path_params["run_id"])
    if isinstance(run, JSONResponse):
        return run
    return JSONResponse(_serialize_run(run))


async def list_approvals(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    approvals = await _list_approvals_for_run(services, run_id)
    return JSONResponse({"items": [_serialize_approval(approval) for approval in approvals]})


async def decide_approval(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    approval_id = request.path_params["approval_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json_error("Invalid JSON body", 400)

    answer = body.get("answer")
    actor_label = body.get("actor_label")
    if not isinstance(answer, str) or not answer:
        return _json_error("Missing 'answer' field", 400)
    if not isinstance(actor_label, str) or not actor_label:
        return _json_error("Missing 'actor_label' field", 400)

    approval = await _get_approval_for_run(services, run_id, approval_id)
    if approval is None:
        return _json_error(f"Approval {approval_id} not found for run {run_id}", 404)
    if approval.status != "pending":
        return _json_error(f"Approval {approval_id} is already {approval.status}", 409)
    if run.status != RunStatus.WAITING_FOR_APPROVAL.value:
        return _json_error(f"Run {run_id} is not waiting for approval", 409)

    waiter = services.executor.get_waiting_approval(run_id, approval_id)
    if waiter is None:
        return _json_error(f"Approval {approval_id} is not waiting in this process", 409)

    allowed_answers = _allowed_approval_answers(run, approval, waiter)
    if allowed_answers is not None and answer not in allowed_answers:
        return _json_error(
            f"Answer {answer!r} is not allowed; expected one of {list(allowed_answers)!r}",
            400,
        )

    decided_at = dt.datetime.now(dt.UTC)
    decision_status, decided = await _decide_pending_approval(
        services,
        run_id=run_id,
        approval_id=approval_id,
        answer=answer,
        actor_label=actor_label,
        timestamp=decided_at,
    )
    if decision_status == "not_found":
        return _json_error(f"Approval {approval_id} not found for run {run_id}", 404)
    if decision_status != "updated" or decided is None:
        return _json_error(f"Approval {approval_id} is already decided", 409)
    if not services.executor.resume_waiting_approval(waiter):
        reverted = await _revert_decided_approval(
            services,
            run_id=run_id,
            approval_id=approval_id,
            answer=answer,
            actor_label=actor_label,
            decided_at=decided_at,
        )
        if not reverted:
            return _json_error(
                f"Approval {approval_id} could not be resumed or restored",
                500,
            )
        return _json_error(f"Approval {approval_id} is not waiting in this process", 409)
    return JSONResponse(_serialize_approval(decided))


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    executor: DurableRunExecutor,
) -> Starlette:
    app = Starlette(
        routes=[
            Route("/api/runs", create_run, methods=["POST"]),
            Route("/api/runs/{run_id}", get_run, methods=["GET"]),
            Route("/api/runs/{run_id}/approvals", list_approvals, methods=["GET"]),
            Route(
                "/api/runs/{run_id}/approvals/{approval_id}",
                decide_approval,
                methods=["POST"],
            ),
        ]
    )
    app.state.platform_services = _PlatformServices(
        executor=executor,
        repository=executor.repository,
        session_factory=session_factory,
    )
    return app
