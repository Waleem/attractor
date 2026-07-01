"""Phase 2 platform app endpoints for repository registration, runs, and approvals."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import inspect
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from attractor_platform.config import load_project_config
from attractor_platform.errors import AttractorPlatformError
from attractor_platform.executor import DurableRunExecutor
from attractor_platform.git import GitRunner
from attractor_platform.packages import (
    WorkflowPackage,
    discover_workflow_packages,
    inspect_workflow_package,
    load_workflow_package,
)
from attractor_platform.runspec import read_git_metadata
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
)
from attractor_platform.storage.repositories import PlatformRepository
from attractor_server.platform_sse import durable_run_event_stream, parse_sse_after_sequence


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
        "source_commit": getattr(run, "source_commit", None),
        "source_branch": getattr(run, "source_branch", None),
        "worktree_path": run.worktree_path,
        "managed_branch": run.managed_branch,
        "error_category": run.error_category,
        "error_message": run.error_message,
        "created_at": _serialize_timestamp(run.created_at),
        "updated_at": _serialize_timestamp(run.updated_at),
        "started_at": _serialize_timestamp(run.started_at),
        "completed_at": _serialize_timestamp(run.completed_at),
    }


def _serialize_repo(repo: Any) -> dict[str, Any]:
    return {
        "id": repo.id,
        "name": repo.name,
        "local_path": repo.local_path,
        "default_branch": repo.default_branch,
        "current_commit": repo.current_commit,
        "dirty_state": repo.dirty_state,
        "project_config_status": getattr(repo, "project_config_status", "unknown"),
        "created_at": _serialize_timestamp(repo.created_at),
        "updated_at": _serialize_timestamp(repo.updated_at),
        "last_indexed_at": _serialize_timestamp(repo.last_indexed_at),
    }


def _serialize_workflow(workflow: Any) -> dict[str, Any]:
    return {
        "id": workflow.id,
        "repo_id": workflow.repo_id,
        "name": workflow.name,
        "dot_path": workflow.dot_path,
        "toml_path": workflow.toml_path,
        "status": workflow.status,
        "diagnostics": workflow.diagnostics,
        "indexed_at": _serialize_timestamp(workflow.indexed_at),
    }


def _serialize_workflow_package(
    workflow_id: str,
    repo_id: str,
    package: WorkflowPackage,
) -> dict[str, Any]:
    return {
        "id": workflow_id,
        "repo_id": repo_id,
        "name": package.name,
        "dot_path": str(package.dot_path),
        "toml_path": str(package.toml_path) if package.toml_path is not None else None,
        "status": package.status.value,
        "diagnostics": _serialize_diagnostics(package),
    }


def _serialize_event(event: Any) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "event_type": event.event_type,
        "payload": event.payload,
        "actor_label": event.actor_label,
        "created_at": _serialize_timestamp(getattr(event, "created_at", None)),
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


def _serialize_artifact(artifact: Any) -> dict[str, Any]:
    return {
        "id": getattr(artifact, "id", None),
        "run_id": getattr(artifact, "run_id", None),
        "kind": artifact.kind,
        "name": artifact.name,
        "uri": artifact.uri,
        "media_type": artifact.media_type,
        "size_bytes": artifact.size_bytes,
        "sha256": artifact.sha256,
        "created_at": _serialize_timestamp(getattr(artifact, "created_at", None)),
    }


def _serialize_checkpoint(checkpoint: Any) -> dict[str, Any]:
    return {
        "id": getattr(checkpoint, "id", None),
        "run_id": getattr(checkpoint, "run_id", None),
        "node_id": checkpoint.node_id,
        "stage_index": checkpoint.stage_index,
        "commit_sha": checkpoint.commit_sha,
        "ref_name": checkpoint.ref_name,
        "created_at": _serialize_timestamp(getattr(checkpoint, "created_at", None)),
    }


def _serialize_writeback(writeback: Any) -> dict[str, Any]:
    return {
        "id": getattr(writeback, "id", None),
        "run_id": getattr(writeback, "run_id", None),
        "source_branch": writeback.source_branch,
        "target_branch": writeback.target_branch,
        "actor_label": writeback.actor_label,
        "status": writeback.status,
        "commit_sha": writeback.commit_sha,
        "error_message": writeback.error_message,
        "created_at": _serialize_timestamp(getattr(writeback, "created_at", None)),
        "applied_at": _serialize_timestamp(getattr(writeback, "applied_at", None)),
    }


def _repo_identifier(repo_path: str | Path) -> str:
    resolved = str(Path(repo_path).expanduser().resolve())
    digest = hashlib.sha1(resolved.encode()).hexdigest()
    return f"repo_{digest[:32]}"


def _workflow_identifier(repo_id: str, workflow_name: str) -> str:
    digest = hashlib.sha1(f"{repo_id}:{workflow_name}".encode()).hexdigest()
    return f"wf_{digest[:32]}"


def _serialize_diagnostics(package: WorkflowPackage) -> dict[str, Any]:
    if package.error is not None:
        return {"error": package.error, "items": []}
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


def _parse_non_negative_int(value: str | None, default: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(parsed, 0)


async def _get_run_or_404(
    repository: PlatformRepository,
    run_id: str,
) -> RunRecordModel | JSONResponse:
    run = await repository.get_run(run_id)
    if run is None:
        return _json_error(f"Run {run_id} not found", 404)
    return run


async def _list_repos(services: _PlatformServices) -> list[Any]:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return list(
                await session.scalars(
                    select(RegisteredRepoModel).order_by(
                        RegisteredRepoModel.name,
                        RegisteredRepoModel.id,
                    )
                )
            )

    list_repos = cast(
        Callable[[], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_repos", None),
    )
    if list_repos is not None:
        return list(await list_repos())

    repos = getattr(services.repository, "repos", None)
    if isinstance(repos, dict):
        return sorted(repos.values(), key=lambda repo: (repo.name, repo.id))

    raise RuntimeError("Repository does not support listing repositories")


async def _get_repo(services: _PlatformServices, repo_id: str) -> Any | None:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return await session.get(RegisteredRepoModel, repo_id)

    get_repo = cast(
        Callable[[str], Awaitable[Any | None]] | None,
        getattr(services.repository, "get_repo", None),
    )
    if get_repo is not None:
        return await get_repo(repo_id)

    repos = getattr(services.repository, "repos", None)
    if isinstance(repos, dict):
        return repos.get(repo_id)

    raise RuntimeError("Repository does not support loading repositories")


async def _list_workflows(services: _PlatformServices, repo_id: str) -> list[Any]:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return list(
                await session.scalars(
                    select(WorkflowPackageModel)
                    .where(WorkflowPackageModel.repo_id == repo_id)
                    .order_by(WorkflowPackageModel.name, WorkflowPackageModel.id)
                )
            )

    list_workflows = cast(
        Callable[[str], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_workflows", None),
    )
    if list_workflows is not None:
        return list(await list_workflows(repo_id))

    workflows = getattr(services.repository, "workflows", None)
    if isinstance(workflows, dict):
        return sorted(
            [workflow for workflow in workflows.values() if workflow.repo_id == repo_id],
            key=lambda workflow: (workflow.name, workflow.id),
        )

    raise RuntimeError("Repository does not support listing workflows")


async def _get_workflow(services: _PlatformServices, workflow_id: str) -> Any | None:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return await session.get(WorkflowPackageModel, workflow_id)

    get_workflow = cast(
        Callable[[str], Awaitable[Any | None]] | None,
        getattr(services.repository, "get_workflow", None),
    )
    if get_workflow is not None:
        return await get_workflow(workflow_id)

    workflows = getattr(services.repository, "workflows", None)
    if isinstance(workflows, dict):
        return workflows.get(workflow_id)

    raise RuntimeError("Repository does not support loading workflows")


async def _list_runs(services: _PlatformServices) -> list[Any]:
    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return list(
                await session.scalars(
                    select(RunRecordModel).order_by(
                        RunRecordModel.created_at,
                        RunRecordModel.id,
                    )
                )
            )

    list_runs = cast(
        Callable[[], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_runs", None),
    )
    if list_runs is not None:
        return list(await list_runs())

    runs = getattr(services.repository, "runs", None)
    if isinstance(runs, dict):
        return sorted(runs.values(), key=lambda run: (run.created_at, run.id))

    raise RuntimeError("Repository does not support listing runs")


async def _list_events_for_run(
    services: _PlatformServices,
    run_id: str,
    after_sequence: int,
    limit: int,
) -> list[Any]:
    list_events = cast(
        Callable[[str, int, int], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_events", None),
    )
    if list_events is not None:
        return list(await list_events(run_id, after_sequence, limit))

    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return list(
                await session.scalars(
                    select(RunEventModel)
                    .where(
                        RunEventModel.run_id == run_id,
                        RunEventModel.sequence > after_sequence,
                    )
                    .order_by(RunEventModel.sequence)
                    .limit(limit)
                )
            )

    raise RuntimeError("Repository does not support listing events")


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


async def _list_artifacts_for_run(services: _PlatformServices, run_id: str) -> list[Any]:
    list_artifacts = cast(
        Callable[[str], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_artifacts", None),
    )
    if list_artifacts is not None:
        return list(await list_artifacts(run_id))

    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return list(
                await session.scalars(
                    select(ArtifactModel)
                    .where(ArtifactModel.run_id == run_id)
                    .order_by(ArtifactModel.created_at, ArtifactModel.id)
                )
            )

    artifacts = getattr(services.repository, "artifacts", None)
    if isinstance(artifacts, dict):
        return list(artifacts.get(run_id, []))

    raise RuntimeError("Repository does not support listing artifacts")


async def _list_checkpoints_for_run(services: _PlatformServices, run_id: str) -> list[Any]:
    list_checkpoints = cast(
        Callable[[str], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_checkpoints", None),
    )
    if list_checkpoints is not None:
        return list(await list_checkpoints(run_id))

    if isinstance(services.repository, PlatformRepository):
        async with session_scope(services.session_factory) as session:
            return list(
                await session.scalars(
                    select(CheckpointModel)
                    .where(CheckpointModel.run_id == run_id)
                    .order_by(CheckpointModel.stage_index, CheckpointModel.created_at)
                )
            )

    checkpoints = getattr(services.repository, "checkpoints", None)
    if isinstance(checkpoints, dict):
        return list(checkpoints.get(run_id, []))

    raise RuntimeError("Repository does not support listing checkpoints")


async def register_repo(request: Request) -> JSONResponse:
    services = _services(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json_error("Invalid JSON body", 400)

    name = body.get("name")
    local_path = body.get("local_path")
    if not isinstance(name, str) or not name:
        return _json_error("Missing 'name' field", 400)
    if not isinstance(local_path, str) or not local_path:
        return _json_error("Missing 'local_path' field", 400)

    repo_path = Path(local_path).expanduser().resolve()
    if not repo_path.is_dir():
        return _json_error(f"Repository path {repo_path} does not exist", 400)

    try:
        metadata = read_git_metadata(repo_path)
        project_config = load_project_config(repo_path / ".attractor" / "project.toml")
        packages = discover_workflow_packages(repo_path)
    except AttractorPlatformError as exc:
        return JSONResponse(exc.to_dict(), status_code=400)
    except Exception as exc:  # noqa: BLE001
        return _json_error(str(exc), 500)

    now = dt.datetime.now(dt.UTC)
    repo_id = _repo_identifier(repo_path)
    register_repo_kwargs = {
        "repo_id": repo_id,
        "name": name,
        "local_path": str(repo_path),
        "default_branch": metadata.branch,
        "current_commit": metadata.commit,
        "dirty_state": metadata.dirty_state.value,
        "timestamp": now,
    }
    register_repo_parameters = inspect.signature(
        services.repository.register_repo,
    ).parameters
    if "project_config_status" in register_repo_parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in register_repo_parameters.values()
    ):
        register_repo_kwargs["project_config_status"] = "valid"
    repo = await services.repository.register_repo(**register_repo_kwargs)
    for package in packages:
        await services.repository.upsert_workflow(
            workflow_id=_workflow_identifier(repo_id, package.name),
            repo_id=repo_id,
            name=package.name,
            dot_path=str(package.dot_path),
            toml_path=str(package.toml_path) if package.toml_path is not None else None,
            status=package.status.value,
            diagnostics=_serialize_diagnostics(package),
            timestamp=now,
        )

    payload = _serialize_repo(repo)
    payload["project_config"] = project_config.model_dump(mode="json")
    payload["workflow_count"] = len(packages)
    return JSONResponse(payload, status_code=201)


async def list_repos(request: Request) -> JSONResponse:
    services = _services(request)
    repos = await _list_repos(services)
    return JSONResponse({"items": [_serialize_repo(repo) for repo in repos]})


async def get_repo(request: Request) -> JSONResponse:
    services = _services(request)
    repo = await _get_repo(services, request.path_params["repo_id"])
    if repo is None:
        return _json_error(f"Repository {request.path_params['repo_id']} not found", 404)
    return JSONResponse(_serialize_repo(repo))


async def get_project_config(request: Request) -> JSONResponse:
    services = _services(request)
    repo = await _get_repo(services, request.path_params["repo_id"])
    if repo is None:
        return _json_error(f"Repository {request.path_params['repo_id']} not found", 404)

    try:
        config = load_project_config(Path(repo.local_path) / ".attractor" / "project.toml")
    except AttractorPlatformError as exc:
        return JSONResponse(exc.to_dict(), status_code=400)
    return JSONResponse(
        {
            "repo_id": repo.id,
            "status": "valid",
            "config": config.model_dump(mode="json"),
        }
    )


async def list_workflows(request: Request) -> JSONResponse:
    services = _services(request)
    repo_id = request.path_params["repo_id"]
    repo = await _get_repo(services, repo_id)
    if repo is None:
        return _json_error(f"Repository {repo_id} not found", 404)

    workflows = await _list_workflows(services, repo_id)
    return JSONResponse([_serialize_workflow(workflow) for workflow in workflows])


async def validate_workflow(request: Request) -> JSONResponse:
    services = _services(request)
    workflow_id = request.path_params["workflow_id"]
    workflow = await _get_workflow(services, workflow_id)
    if workflow is None:
        return _json_error(f"Workflow {workflow_id} not found", 404)

    repo = await _get_repo(services, workflow.repo_id)
    if repo is None:
        return _json_error(f"Repository {workflow.repo_id} not found", 404)

    package = inspect_workflow_package(repo.local_path, workflow.name)
    if package.status.value != workflow.status or package.error is not None:
        await services.repository.upsert_workflow(
            workflow_id=workflow_id,
            repo_id=repo.id,
            name=package.name,
            dot_path=str(package.dot_path),
            toml_path=str(package.toml_path) if package.toml_path is not None else None,
            status=package.status.value,
            diagnostics=_serialize_diagnostics(package),
            timestamp=dt.datetime.now(dt.UTC),
        )
    return JSONResponse(_serialize_workflow_package(workflow_id, repo.id, package))


async def create_run(request: Request) -> JSONResponse:
    services = _services(request)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json_error("Invalid JSON body", 400)

    repo_path = body.get("repo_path")
    workflow_name = body.get("workflow_name", body.get("workflow"))
    actor_label = body.get("actor_label", "")
    inputs = body.get("inputs", {})

    if not isinstance(repo_path, str) or not repo_path:
        return _json_error("Missing 'repo_path' field", 400)
    if not isinstance(workflow_name, str) or not workflow_name:
        return _json_error("Missing 'workflow_name' or 'workflow' field", 400)
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


async def list_runs(request: Request) -> JSONResponse:
    services = _services(request)
    runs = await _list_runs(services)
    return JSONResponse({"items": [_serialize_run(run) for run in runs]})


async def get_run(request: Request) -> JSONResponse:
    services = _services(request)
    run = await _get_run_or_404(services.repository, request.path_params["run_id"])
    if isinstance(run, JSONResponse):
        return run
    return JSONResponse(_serialize_run(run))


async def list_run_events(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    after_sequence = _parse_non_negative_int(request.query_params.get("after_sequence"), 0)
    limit = min(_parse_non_negative_int(request.query_params.get("limit"), 100), 500)
    events = await _list_events_for_run(services, run_id, after_sequence, limit)
    return JSONResponse({"items": [_serialize_event(event) for event in events]})


async def stream_run_events(request: Request) -> JSONResponse | StreamingResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    after_sequence = _parse_non_negative_int(request.query_params.get("after_sequence"), 0)
    replay_after = parse_sse_after_sequence(
        after_sequence=after_sequence,
        last_event_id=request.headers.get("last-event-id"),
    )
    return StreamingResponse(
        durable_run_event_stream(services.repository, run_id, after_sequence=replay_after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def list_approvals(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    approvals = await _list_approvals_for_run(services, run_id)
    return JSONResponse({"items": [_serialize_approval(approval) for approval in approvals]})


async def list_artifacts(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    artifacts = await _list_artifacts_for_run(services, run_id)
    return JSONResponse({"items": [_serialize_artifact(artifact) for artifact in artifacts]})


async def list_checkpoints(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    checkpoints = await _list_checkpoints_for_run(services, run_id)
    return JSONResponse(
        {"items": [_serialize_checkpoint(checkpoint) for checkpoint in checkpoints]}
    )


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


async def cancel_run(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    task = getattr(services.executor, "active_tasks", {}).get(run_id)
    if isinstance(task, asyncio.Task) and not task.done():
        task.cancel()
        return JSONResponse({"id": run_id, "status": "cancelling"})

    if run.status in {
        RunStatus.COMPLETED.value,
        RunStatus.FAILED.value,
        RunStatus.CANCELLED.value,
        RunStatus.WRITEBACK_APPLIED.value,
        RunStatus.WRITEBACK_FAILED.value,
    }:
        return _json_error(f"Run {run_id} is already {run.status}", 409)

    return _json_error(f"Run {run_id} has no active executor task in this process", 409)


def _executor_git_runner(executor: Any) -> GitRunner:
    git = getattr(executor, "git", None)
    if isinstance(git, GitRunner):
        return git
    private_git = getattr(executor, "_git", None)
    if isinstance(private_git, GitRunner):
        return private_git
    return GitRunner()


def _run_source_commit(run: Any) -> str | None:
    run_spec = getattr(run, "run_spec", None)
    if isinstance(run_spec, dict):
        source_commit = run_spec.get("source_commit")
        if isinstance(source_commit, str) and source_commit:
            return source_commit
    source_commit = getattr(run, "source_commit", None)
    return source_commit if isinstance(source_commit, str) and source_commit else None


async def _persist_writeback_result(
    services: _PlatformServices,
    *,
    run: Any,
    target_branch: str,
    actor_label: str,
    status: str,
    commit_sha: str | None,
    error_message: str | None,
    timestamp: dt.datetime,
) -> Any:
    source_branch = getattr(run, "managed_branch", None) or ""
    writeback_id = f"wb_{uuid.uuid4().hex}"
    record_writeback_result = cast(
        Callable[..., Awaitable[Any]] | None,
        getattr(services.repository, "record_writeback_result", None),
    )
    if record_writeback_result is not None:
        return await record_writeback_result(
            writeback_id=writeback_id,
            run_id=run.id,
            source_branch=source_branch,
            target_branch=target_branch,
            actor_label=actor_label,
            status=status,
            commit_sha=commit_sha,
            error_message=error_message,
            timestamp=timestamp,
        )

    writeback = await services.repository.create_writeback(
        writeback_id=writeback_id,
        run_id=run.id,
        source_branch=source_branch,
        target_branch=target_branch,
        actor_label=actor_label,
        status=status,
        commit_sha=commit_sha,
        error_message=error_message,
        timestamp=timestamp,
    )
    event_type = "writeback.applied" if status == "applied" else "writeback.failed"
    await services.repository.append_event(
        run_id=run.id,
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
    await services.repository.update_run_status(
        run.id,
        RunStatus.WRITEBACK_APPLIED if status == "applied" else RunStatus.WRITEBACK_FAILED,
        error_category=None if status == "applied" else "writeback_failed",
        error_message=error_message if status != "applied" else None,
    )
    return writeback


async def _record_writeback_failure(
    services: _PlatformServices,
    *,
    run: Any,
    target_branch: str,
    actor_label: str,
    error_message: str,
) -> JSONResponse:
    try:
        await _persist_writeback_result(
            services,
            run=run,
            target_branch=target_branch,
            actor_label=actor_label,
            status="failed",
            commit_sha=None,
            error_message=error_message,
            timestamp=dt.datetime.now(dt.UTC),
        )
    except Exception as exc:  # noqa: BLE001
        return _json_error(
            f"Write-back failed and failure persistence also failed: {exc}",
            500,
        )
    return JSONResponse(
        {
            "error": error_message,
            "run_id": run.id,
            "target_branch": target_branch,
            "status": "failed",
        },
        status_code=409,
    )


async def request_writeback(request: Request) -> JSONResponse:
    services = _services(request)
    run_id = request.path_params["run_id"]
    run = await _get_run_or_404(services.repository, run_id)
    if isinstance(run, JSONResponse):
        return run

    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return _json_error("Invalid JSON body", 400)

    actor_label = body.get("actor_label")
    if not isinstance(actor_label, str) or not actor_label:
        return _json_error("Missing 'actor_label' field", 400)
    target_branch = body.get("target_branch")
    if not isinstance(target_branch, str) or not target_branch:
        return _json_error("Missing 'target_branch' field", 400)
    overwrite = body.get("overwrite", False)
    if not isinstance(overwrite, bool):
        return _json_error("'overwrite' must be a boolean", 400)
    allow_protected = body.get("allow_protected", False)
    if not isinstance(allow_protected, bool):
        return _json_error("'allow_protected' must be a boolean", 400)

    if run.status != RunStatus.COMPLETED.value:
        return _json_error(
            f"Run {run_id} must be completed before write-back; current status is {run.status}",
            409,
        )

    repo = await _get_repo(services, run.repo_id)
    if repo is None:
        return await _record_writeback_failure(
            services,
            run=run,
            target_branch=target_branch,
            actor_label=actor_label,
            error_message=f"Registered repo {run.repo_id} is missing",
        )
    worktree_path = getattr(run, "worktree_path", None)
    if not isinstance(worktree_path, str) or not worktree_path:
        return await _record_writeback_failure(
            services,
            run=run,
            target_branch=target_branch,
            actor_label=actor_label,
            error_message="Managed worktree path is missing",
        )
    managed_branch = getattr(run, "managed_branch", None)
    if not isinstance(managed_branch, str) or not managed_branch:
        return await _record_writeback_failure(
            services,
            run=run,
            target_branch=target_branch,
            actor_label=actor_label,
            error_message="Managed branch is missing",
        )
    source_commit = _run_source_commit(run)
    if source_commit is None:
        return await _record_writeback_failure(
            services,
            run=run,
            target_branch=target_branch,
            actor_label=actor_label,
            error_message="RunSpec.source_commit is missing",
        )

    try:
        commit_sha = _executor_git_runner(services.executor).promote_branch(
            repo.local_path,
            worktree_path=worktree_path,
            managed_branch=managed_branch,
            source_commit=source_commit,
            target_branch=target_branch,
            overwrite=overwrite,
            allow_protected=allow_protected,
        )
    except RuntimeError as exc:
        return await _record_writeback_failure(
            services,
            run=run,
            target_branch=target_branch,
            actor_label=actor_label,
            error_message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001
        return _json_error(f"Unexpected write-back failure: {exc}", 500)

    try:
        writeback = await _persist_writeback_result(
            services,
            run=run,
            target_branch=target_branch,
            actor_label=actor_label,
            status="applied",
            commit_sha=commit_sha,
            error_message=None,
            timestamp=dt.datetime.now(dt.UTC),
        )
    except Exception as exc:  # noqa: BLE001
        return _json_error(f"Write-back applied but persistence failed: {exc}", 500)
    return JSONResponse(_serialize_writeback(writeback))


async def system_health(request: Request) -> JSONResponse:
    _services(request)
    return JSONResponse({"status": "ok"})


async def system_capacity(request: Request) -> JSONResponse:
    services = _services(request)
    active_tasks = getattr(services.executor, "active_tasks", {})
    active_count = sum(1 for task in active_tasks.values() if not task.done())
    max_concurrent = getattr(services.executor, "max_concurrent_runs", None)
    return JSONResponse(
        {
            "active_runs": active_count,
            "max_concurrent_runs": max_concurrent,
            "available_slots": None
            if not isinstance(max_concurrent, int)
            else max(max_concurrent - active_count, 0),
        }
    )


def create_platform_app(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    executor: DurableRunExecutor,
) -> Starlette:
    app = Starlette(
        routes=[
            Route("/api/repos", register_repo, methods=["POST"]),
            Route("/api/repos", list_repos, methods=["GET"]),
            Route("/api/repos/{repo_id}", get_repo, methods=["GET"]),
            Route("/api/repos/{repo_id}/project-config", get_project_config, methods=["GET"]),
            Route("/api/repos/{repo_id}/workflows", list_workflows, methods=["GET"]),
            Route("/api/workflows/{workflow_id}/validate", validate_workflow, methods=["POST"]),
            Route("/api/runs", create_run, methods=["POST"]),
            Route("/api/runs", list_runs, methods=["GET"]),
            Route("/api/runs/{run_id}", get_run, methods=["GET"]),
            Route("/api/runs/{run_id}/events", list_run_events, methods=["GET"]),
            Route("/api/runs/{run_id}/events/stream", stream_run_events, methods=["GET"]),
            Route("/api/runs/{run_id}/approvals", list_approvals, methods=["GET"]),
            Route(
                "/api/runs/{run_id}/approvals/{approval_id}",
                decide_approval,
                methods=["POST"],
            ),
            Route("/api/runs/{run_id}/artifacts", list_artifacts, methods=["GET"]),
            Route("/api/runs/{run_id}/checkpoints", list_checkpoints, methods=["GET"]),
            Route("/api/runs/{run_id}/cancel", cancel_run, methods=["POST"]),
            Route("/api/runs/{run_id}/writeback", request_writeback, methods=["POST"]),
            Route("/api/system/health", system_health, methods=["GET"]),
            Route("/api/system/capacity", system_capacity, methods=["GET"]),
        ]
    )
    app.state.platform_services = _PlatformServices(
        executor=executor,
        repository=executor.repository,
        session_factory=session_factory,
    )
    return app


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    executor: DurableRunExecutor,
) -> Starlette:
    return create_platform_app(session_factory=session_factory, executor=executor)
