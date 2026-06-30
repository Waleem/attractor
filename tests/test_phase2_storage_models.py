from __future__ import annotations

from attractor_platform.storage.models import (
    ApprovalDecisionModel,
    ArtifactModel,
    CheckpointModel,
    RegisteredRepoModel,
    RunEventModel,
    RunRecordModel,
    RunStatus,
    WriteBackModel,
)


def test_phase2_tables_have_expected_names() -> None:
    assert RegisteredRepoModel.__tablename__ == "registered_repos"
    assert RunRecordModel.__tablename__ == "run_records"
    assert RunEventModel.__tablename__ == "run_events"
    assert ApprovalDecisionModel.__tablename__ == "approval_decisions"
    assert ArtifactModel.__tablename__ == "artifacts"
    assert CheckpointModel.__tablename__ == "checkpoints"
    assert WriteBackModel.__tablename__ == "write_backs"


def test_run_status_values_match_design() -> None:
    assert [status.value for status in RunStatus] == [
        "queued",
        "preparing",
        "running",
        "waiting_for_approval",
        "completed",
        "failed",
        "cancelled",
        "writeback_pending",
        "writeback_applied",
        "writeback_failed",
    ]
