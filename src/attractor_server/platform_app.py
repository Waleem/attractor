"""Phase 2 platform app endpoints for run launch and approvals."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from attractor_platform.errors import AttractorPlatformError
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import session_scope
from attractor_platform.storage.models import ApprovalDecisionModel, RunRecordModel
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

    async with session_scope(services.session_factory) as session:
        approvals = list(
            await session.scalars(
                select(ApprovalDecisionModel)
                .where(ApprovalDecisionModel.run_id == run_id)
                .order_by(ApprovalDecisionModel.created_at, ApprovalDecisionModel.id)
            )
        )

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

    async with session_scope(services.session_factory) as session:
        approval = await session.scalar(
            select(ApprovalDecisionModel).where(
                ApprovalDecisionModel.id == approval_id,
                ApprovalDecisionModel.run_id == run_id,
            )
        )

    if approval is None:
        return _json_error(f"Approval {approval_id} not found for run {run_id}", 404)
    if approval.status != "pending":
        return _json_error(f"Approval {approval_id} is already {approval.status}", 409)

    decided = await services.repository.decide_approval(
        approval_id=approval_id,
        answer=answer,
        actor_label=actor_label,
        timestamp=dt.datetime.now(dt.UTC),
    )
    services.executor.notify_approval_decision(run_id, approval_id)
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
