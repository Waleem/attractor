from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class RunStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WRITEBACK_PENDING = "writeback_pending"
    WRITEBACK_APPLIED = "writeback_applied"
    WRITEBACK_FAILED = "writeback_failed"


class RegisteredRepoModel(Base):
    __tablename__ = "registered_repos"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    local_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    default_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    current_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    dirty_state: Mapped[str] = mapped_column(String(20), nullable=False)
    project_config_status: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        default="unknown",
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowPackageModel(Base):
    __tablename__ = "workflow_packages"
    __table_args__ = (UniqueConstraint("repo_id", "name", name="uq_workflow_repo_name"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(ForeignKey("registered_repos.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dot_path: Mapped[str] = mapped_column(Text, nullable=False)
    toml_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    diagnostics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    indexed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RunRecordModel(Base):
    __tablename__ = "run_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    repo_id: Mapped[str] = mapped_column(ForeignKey("registered_repos.id", ondelete="RESTRICT"))
    workflow_id: Mapped[str] = mapped_column(
        ForeignKey("workflow_packages.id", ondelete="RESTRICT"),
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    run_spec: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source_commit: Mapped[str] = mapped_column(String(40), nullable=False)
    source_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    worktree_path: Mapped[str | None] = mapped_column(Text)
    managed_branch: Mapped[str | None] = mapped_column(String(300))
    error_category: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    events: Mapped[list[RunEventModel]] = relationship(back_populates="run")


class RunEventModel(Base):
    __tablename__ = "run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
        Index("ix_run_events_run_id_id", "run_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.id", ondelete="CASCADE"))
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    run: Mapped[RunRecordModel] = relationship(back_populates="events")


class ApprovalDecisionModel(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.id", ondelete="CASCADE"))
    node_id: Mapped[str | None] = mapped_column(String(200))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class ArtifactModel(Base):
    __tablename__ = "artifacts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    media_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CheckpointModel(Base):
    __tablename__ = "checkpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.id", ondelete="CASCADE"))
    node_id: Mapped[str] = mapped_column(String(200), nullable=False)
    stage_index: Mapped[int] = mapped_column(Integer, nullable=False)
    commit_sha: Mapped[str] = mapped_column(String(40), nullable=False)
    ref_name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class WriteBackModel(Base):
    __tablename__ = "write_backs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run_records.id", ondelete="CASCADE"))
    source_branch: Mapped[str] = mapped_column(String(300), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(300), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    commit_sha: Mapped[str | None] = mapped_column(String(40))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
