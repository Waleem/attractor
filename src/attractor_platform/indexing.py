from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from attractor_platform.packages import WorkflowPackage, discover_workflow_packages
from attractor_platform.runspec import read_git_metadata


@dataclass(frozen=True)
class WorkflowIndexResult:
    repo: Any
    packages: list[WorkflowPackage]
    changed: bool
    removed_workflow_count: int
    active_workflow_ids: set[str]
    workflow_count: int


def workflow_tree_signature(repo_path: str | Path) -> int:
    root = Path(repo_path).expanduser().resolve() / ".attractor" / "workflows"
    if not root.exists():
        return 0
    return max(
        [int(root.stat().st_mtime_ns), *(int(path.stat().st_mtime_ns) for path in root.rglob("*"))]
    )


def _last_index_signature(timestamp: dt.datetime | None) -> int:
    if timestamp is None:
        return 0
    return int(timestamp.timestamp() * 1_000_000_000)


async def reindex_registered_repo(services: Any, repo: Any, force: bool) -> WorkflowIndexResult:
    signature = workflow_tree_signature(repo.local_path)
    changed = force or signature > _last_index_signature(getattr(repo, "last_indexed_at", None))
    if not changed:
        active_workflows = await _indexed_active_workflows(services, repo.id)
        return WorkflowIndexResult(
            repo=repo,
            packages=[],
            changed=False,
            removed_workflow_count=0,
            active_workflow_ids={workflow.id for workflow in active_workflows},
            workflow_count=len(active_workflows),
        )

    timestamp = dt.datetime.now(dt.UTC)
    metadata = read_git_metadata(repo.local_path)
    packages = discover_workflow_packages(repo.local_path)
    updated_repo = await services.repository.update_repo_index_metadata(
        repo.id,
        default_branch=metadata.branch,
        current_commit=metadata.commit,
        dirty_state=metadata.dirty_state.value,
        timestamp=timestamp,
    )
    workflow_ids: set[str] = set()
    for package in packages:
        workflow_id = _workflow_identifier(repo.id, package.name)
        workflow_ids.add(workflow_id)
        await services.repository.upsert_workflow(
            workflow_id=workflow_id,
            repo_id=repo.id,
            name=package.name,
            dot_path=str(package.dot_path),
            toml_path=str(package.toml_path) if package.toml_path is not None else None,
            status=package.status.value,
            diagnostics=_serialize_diagnostics(package),
            timestamp=timestamp,
        )
    removed_workflow_count = await services.repository.delete_workflows_not_in(
        repo.id,
        workflow_ids,
    )
    return WorkflowIndexResult(
        repo=updated_repo,
        packages=packages,
        changed=True,
        removed_workflow_count=removed_workflow_count,
        active_workflow_ids=workflow_ids,
        workflow_count=len(packages),
    )


async def _indexed_active_workflows(services: Any, repo_id: str) -> list[Any]:
    list_workflows = cast(
        Callable[[str], Awaitable[list[Any]]] | None,
        getattr(services.repository, "list_workflows", None),
    )
    if list_workflows is not None:
        workflows = list(await list_workflows(repo_id))
    else:
        workflows_by_id = getattr(services.repository, "workflows", None)
        if not isinstance(workflows_by_id, dict):
            workflows = []
        else:
            workflows = [
                workflow
                for workflow in workflows_by_id.values()
                if getattr(workflow, "repo_id", None) == repo_id
            ]
    return [workflow for workflow in workflows if Path(workflow.dot_path).is_file()]


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
