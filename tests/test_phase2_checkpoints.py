from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from attractor_platform.checkpoints import GitCheckpointService
from attractor_platform.git import GitRunner


def test_git_checkpoint_service_creates_checkpoint_ref(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    base_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "generated.txt").write_text("generated\n", encoding="utf-8")

    service = GitCheckpointService(GitRunner())

    checkpoint = service.create_checkpoint(
        worktree_path=repo,
        run_id="run_1",
        workflow_name="release",
        node_id="build",
        stage_index=2,
        event_sequence=7,
        base_commit=base_commit,
    )

    assert checkpoint.node_id == "build"
    assert checkpoint.stage_index == 2
    assert checkpoint.ref_name == "refs/attractor/runs/run_1/checkpoints/0002-build"
    assert len(checkpoint.commit_sha) == 40
    ref_commit = subprocess.check_output(
        ["git", "rev-parse", checkpoint.ref_name], cwd=repo, text=True
    ).strip()
    assert ref_commit == checkpoint.commit_sha


@pytest.mark.parametrize(
    ("run_id", "node_id"),
    [
        (".", "build"),
        ("run_1", "foo..bar"),
    ],
)
def test_git_checkpoint_service_rejects_invalid_checkpoint_ref(
    tmp_path: Path, run_id: str, node_id: str
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)

    base_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    (repo / "generated.txt").write_text("generated\n", encoding="utf-8")

    service = GitCheckpointService(GitRunner())

    with pytest.raises(RuntimeError, match=r"^invalid checkpoint ref name: refs/attractor/runs/"):
        service.create_checkpoint(
            worktree_path=repo,
            run_id=run_id,
            workflow_name="release",
            node_id=node_id,
            stage_index=2,
            event_sequence=7,
            base_commit=base_commit,
        )

    head_after = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    assert head_after == base_commit
