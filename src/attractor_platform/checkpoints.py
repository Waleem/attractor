from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from attractor_platform.git import GitRunner


@dataclass(frozen=True)
class GitCheckpoint:
    run_id: str
    node_id: str
    stage_index: int
    commit_sha: str
    ref_name: str


def safe_ref_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-") or "node"


class GitCheckpointService:
    def __init__(self, git: GitRunner) -> None:
        self._git = git

    def create_checkpoint(
        self,
        *,
        worktree_path: str | Path,
        run_id: str,
        workflow_name: str,
        node_id: str,
        stage_index: int,
        event_sequence: int,
        base_commit: str,
    ) -> GitCheckpoint:
        path = Path(worktree_path)
        ref_name = (
            f"refs/attractor/runs/{safe_ref_part(run_id)}/checkpoints/"
            f"{stage_index:04d}-{safe_ref_part(node_id)}"
        )
        self._validate_ref_name(path, ref_name)

        self._git.run(path, "add", "-A")

        if self._git.status_porcelain(path):
            subject = f"attractor: checkpoint {run_id} stage {stage_index} {node_id}"
            body = "\n".join(
                [
                    f"Run-ID: {run_id}",
                    f"Workflow: {workflow_name}",
                    f"Base-Commit: {base_commit}",
                    f"Node-ID: {node_id}",
                    f"Stage-Index: {stage_index}",
                    f"Event-Sequence: {event_sequence}",
                ]
            )
            self._git.run(path, "commit", "-m", subject, "-m", body)

        commit_sha = self._git.commit(path)
        self._git.run(path, "update-ref", ref_name, commit_sha)
        return GitCheckpoint(
            run_id=run_id,
            node_id=node_id,
            stage_index=stage_index,
            commit_sha=commit_sha,
            ref_name=ref_name,
        )

    def _validate_ref_name(self, repo_path: Path, ref_name: str) -> None:
        try:
            self._git.run(repo_path, "check-ref-format", ref_name)
        except RuntimeError as exc:
            raise RuntimeError(f"invalid checkpoint ref name: {ref_name}") from exc
