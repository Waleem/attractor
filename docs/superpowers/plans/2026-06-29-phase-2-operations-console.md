# Phase 2 Operations Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the trusted-LAN Operations Console vertical slice: register a repo, discover and validate a workflow, launch one worktree-isolated local run, persist durable run/event/artifact/checkpoint records, gate for human approval, and promote the managed branch after approval.

**Architecture:** Build the durability and isolation spines first, then attach a backend-backed FastAPI surface and minimal React console to those spines. The existing engine, handlers, `RunSpec`, and `ExecutionEnvironment` stay intact; Phase 2 adds durable orchestration around them and uses worktree-local execution for shared-server runs.

**Tech Stack:** Python 3.12, pydantic v2, FastAPI, SQLAlchemy 2 async ORM, asyncpg, Alembic, Postgres, subprocess `git`, existing Attractor pipeline engine, existing `ExecutionEnvironment`, React/Vite/TypeScript.

---

## Live Repo Baseline

- Verified on `main` after `git fetch --prune`.
- `HEAD` and `origin/main` both point at `4a6b32d` (`Merge pull request #1 from Waleem/codex/phase-1-engine-contracts`).
- Working tree has an untracked `.superpowers/` directory; leave it untouched.
- Phase 1 contracts are present in `src/attractor_platform/`: `errors.py`, `config.py`, `packages.py`, and `runspec.py`.
- The current server is Starlette plus an in-memory `PipelineManager`; `RunRecord` and durable `RunEvent` do not exist.
- The engine already accepts `on_event` in `run_pipeline()`, which is the correct append seam for durable events.
- `LocalEnvironment` is direct host execution and must remain CLI/dev/trusted only. Shared-server local execution must be worktree-isolated.

## Scope Boundary

This plan implements the first Phase 2 milestone and the required safety chain:

1. register repo
2. discover and validate workflow package
3. launch run using worktree-local execution
4. persist `RunRecord` and append-only `RunEvent`
5. stream SSE from durable events
6. create git checkpoint commits and checkpoint refs
7. pause for human approval
8. capture artifacts
9. approve write-back
10. promote the managed branch

This plan also adds Docker as a Phase 2 follow-on environment after the worktree-local vertical slice is working. It does not implement GitHub PR creation, auth/SSO, scheduled automations, MCP, lifecycle hooks, cloud sandboxes, Slack, or control-plane governance.

## Key Decisions

- **Git driver:** use subprocess `git` through a narrow `GitRunner`; reject GitPython/pygit2 because shelling out preserves exact CLI semantics for worktrees, refs, config, and failure messages while avoiding native-library packaging risk.
- **Postgres access layer:** use SQLAlchemy 2 async ORM on `asyncpg` with Alembic migrations; reject raw `asyncpg` because schema evolution and relationship-heavy run/event/artifact queries need migrations and typed models.
- **`RunEnvironment` boundary:** add a platform-level `RunEnvironment` lifecycle that prepares a workspace and installs a task-local existing `ExecutionEnvironment`; reject replacing `ExecutionEnvironment` or using process-global mutation because agent tools already depend on the protocol and concurrent server runs must not share environment or allowed-root state.
- **Engine-to-durable-event seam:** append durable events through a composed `on_event` callback passed to `run_pipeline()` plus explicit orchestration events around queue/prep/approval/write-back; reject forking the engine because the existing emit path is stable and already used by tests.
- **Checkpoint refs and commits:** use worktree branch `attractor/runs/{run_id}` plus refs `refs/attractor/runs/{run_id}/checkpoints/{stage_index}-{node_id}` and commit subjects `attractor: checkpoint {run_id} stage {stage_index} {node_id}`; reject tags and patch files because branch commits plus refs support resume, trace, and promotion without mutating the registered repo.

## File Structure

- Modify `pyproject.toml`
  Add FastAPI, SQLAlchemy async, asyncpg, Alembic, and frontend/test support dependencies.
- Create `src/attractor_platform/redaction.py`
  Centralized event/log/config redaction used before persistence or artifact capture.
- Create `src/attractor_platform/storage/db.py`
  Async SQLAlchemy engine/session factory and settings.
- Create `src/attractor_platform/storage/models.py`
  ORM models for repos, workflows, runs, events, approvals, artifacts, checkpoints, and write-back records.
- Create `src/attractor_platform/storage/repositories.py`
  Repository methods for atomic run/event/artifact/checkpoint/approval/write-back operations.
- Create `src/attractor_platform/storage/alembic/env.py`
  Alembic migration environment for platform metadata.
- Create `src/attractor_platform/storage/alembic/versions/0001_phase2_platform_spines.py`
  Initial Postgres schema.
- Create `src/attractor_platform/artifacts.py`
  Filesystem artifact store interface and local implementation.
- Create `src/attractor_platform/git.py`
  Subprocess git driver, worktree creation/removal, branch/ref operations, and base checks.
- Create `src/attractor_platform/run_environment.py`
  `RunEnvironment` protocol plus worktree-local and Docker environment implementations.
- Create `src/attractor_platform/checkpoints.py`
  Git checkpoint commit/ref service.
- Create `src/attractor_platform/executor.py`
  Durable run orchestrator that bridges `RunSpec`, worktree environment, engine, artifacts, checkpoints, and repositories.
- Create `src/attractor_server/platform_app.py`
  FastAPI app exposing repos, workflows, runs, events, approvals, artifacts, health, capacity, and write-back.
- Create `src/attractor_server/platform_sse.py`
  SSE projection over durable events.
- Modify `src/attractor_server/__main__.py`
  Run the FastAPI app for platform mode while retaining the old Starlette app for compatibility tests until migrated.
- Create `web/`
  React/Vite Operations Console with repo registration, workflow launch, run detail, approval, artifact, and write-back views.
- Create focused tests under `tests/`:
  `test_phase2_redaction.py`, `test_phase2_storage.py`, `test_phase2_artifacts.py`, `test_phase2_git_worktree.py`, `test_phase2_run_environment.py`, `test_phase2_checkpoints.py`, `test_phase2_executor.py`, `test_phase2_api.py`, `test_phase2_sse.py`, `test_phase2_writeback.py`, and `test_phase2_e2e.py`.

---

### Task 1: Dependencies and Package Scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `src/attractor_platform/storage/__init__.py`
- Create: `src/attractor_platform/storage/db.py`
- Create: `tests/test_phase2_imports.py`

- [ ] **Step 1: Write import contract tests**

Create `tests/test_phase2_imports.py`:

```python
from __future__ import annotations


def test_phase2_modules_are_importable() -> None:
    import attractor_platform.artifacts
    import attractor_platform.checkpoints
    import attractor_platform.executor
    import attractor_platform.git
    import attractor_platform.redaction
    import attractor_platform.run_environment
    import attractor_platform.storage.db
    import attractor_platform.storage.models
    import attractor_platform.storage.repositories
    import attractor_server.platform_app
    import attractor_server.platform_sse
```

- [ ] **Step 2: Run the failing import test**

Run:

```bash
pytest tests/test_phase2_imports.py -v
```

Expected: FAIL because the Phase 2 modules do not exist yet.

- [ ] **Step 3: Add dependencies**

In `pyproject.toml`, extend `[project].dependencies`:

```toml
    "fastapi>=0.115",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
```

Extend `[project.optional-dependencies].dev`:

```toml
    "pytest-postgresql>=6.0",
```

- [ ] **Step 4: Add storage package and session factory**

Create `src/attractor_platform/storage/__init__.py`:

```python
"""Durable storage for the Phase 2 platform."""
```

Create `src/attractor_platform/storage/db.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


@dataclass(frozen=True)
class DatabaseSettings:
    url: str
    echo: bool = False


def create_platform_engine(settings: DatabaseSettings) -> AsyncEngine:
    return create_async_engine(settings.url, echo=settings.echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        async with session.begin():
            yield session
```

- [ ] **Step 5: Create empty module files for the next tasks**

Create these files with a module docstring only:

```text
src/attractor_platform/artifacts.py
src/attractor_platform/checkpoints.py
src/attractor_platform/executor.py
src/attractor_platform/git.py
src/attractor_platform/redaction.py
src/attractor_platform/run_environment.py
src/attractor_platform/storage/models.py
src/attractor_platform/storage/repositories.py
src/attractor_server/platform_app.py
src/attractor_server/platform_sse.py
```

- [ ] **Step 6: Verify imports**

Run:

```bash
pytest tests/test_phase2_imports.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml src/attractor_platform src/attractor_server tests/test_phase2_imports.py
git commit -m "chore: scaffold phase 2 platform modules"
```

---

### Task 2: Durable Schema and Migrations

**Files:**
- Modify: `src/attractor_platform/storage/models.py`
- Create: `src/attractor_platform/storage/alembic/env.py`
- Create: `src/attractor_platform/storage/alembic/versions/0001_phase2_platform_spines.py`
- Create: `tests/test_phase2_storage_models.py`

- [ ] **Step 1: Write model contract tests**

Create `tests/test_phase2_storage_models.py`:

```python
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
```

- [ ] **Step 2: Run failing model tests**

Run:

```bash
pytest tests/test_phase2_storage_models.py -v
```

Expected: FAIL because models are not defined.

- [ ] **Step 3: Define ORM base and status enums**

Implement `src/attractor_platform/storage/models.py` with:

```python
from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
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
    project_config_status: Mapped[str] = mapped_column(String(40), nullable=False, default="unknown")
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
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflow_packages.id", ondelete="RESTRICT"))
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
```

- [ ] **Step 4: Add Alembic migration**

Create migration file `src/attractor_platform/storage/alembic/versions/0001_phase2_platform_spines.py` with tables matching the ORM models and Postgres JSONB columns. Use `revision = "0001_phase2_platform_spines"` and `down_revision = None`.

- [ ] **Step 5: Verify model contracts**

Run:

```bash
pytest tests/test_phase2_storage_models.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_platform/storage tests/test_phase2_storage_models.py
git commit -m "feat: add phase 2 durable schema"
```

---

### Task 3: Repository Layer and Central Redaction

**Files:**
- Modify: `src/attractor_platform/redaction.py`
- Modify: `src/attractor_platform/storage/repositories.py`
- Create: `tests/test_phase2_redaction.py`
- Create: `tests/test_phase2_storage.py`

- [ ] **Step 1: Write redaction tests**

Create `tests/test_phase2_redaction.py`:

```python
from __future__ import annotations

from attractor_platform.redaction import redact_mapping, redact_text


def test_redact_text_masks_common_secret_shapes() -> None:
    text = "OPENAI_API_KEY=sk-test-secret password=hunter2 normal=value"

    redacted = redact_text(text)

    assert "sk-test-secret" not in redacted
    assert "hunter2" not in redacted
    assert "normal=value" in redacted


def test_redact_mapping_recurses() -> None:
    payload = {
        "safe": "ok",
        "token": "abc123",
        "nested": {"api_key": "secret", "items": ["plain", {"password": "pw"}]},
    }

    assert redact_mapping(payload) == {
        "safe": "ok",
        "token": "[REDACTED]",
        "nested": {"api_key": "[REDACTED]", "items": ["plain", {"password": "[REDACTED]"}]},
    }
```

- [ ] **Step 2: Write repository tests**

Create `tests/test_phase2_storage.py` using a Postgres test database:

```python
from __future__ import annotations

import datetime as dt

import pytest

from attractor_platform.storage.models import RunStatus
from attractor_platform.storage.repositories import PlatformRepository


pytestmark = pytest.mark.asyncio


async def test_run_events_are_append_only_and_ordered(platform_session_factory) -> None:
    repo = PlatformRepository(platform_session_factory)
    now = dt.datetime.now(dt.UTC)

    await repo.register_repo(
        repo_id="repo_1",
        name="demo",
        local_path="/tmp/demo",
        default_branch="main",
        current_commit="1" * 40,
        dirty_state="clean",
        timestamp=now,
    )
    await repo.upsert_workflow(
        workflow_id="wf_1",
        repo_id="repo_1",
        name="release",
        dot_path="/tmp/demo/.attractor/workflows/release/workflow.dot",
        toml_path=None,
        status="valid",
        diagnostics={},
        timestamp=now,
    )
    await repo.create_run(
        run_id="run_1",
        repo_id="repo_1",
        workflow_id="wf_1",
        run_spec={"actor_label": "alice"},
        actor_label="alice",
        source_commit="1" * 40,
        source_branch="main",
        timestamp=now,
    )

    first = await repo.append_event("run_1", "run.queued", {"secret": "value"}, timestamp=now)
    second = await repo.append_event("run_1", "run.started", {"node": "start"}, timestamp=now)

    events = await repo.list_events("run_1", after_sequence=0, limit=100)
    assert [event.sequence for event in events] == [first.sequence, second.sequence]
    assert events[0].payload == {"secret": "[REDACTED]"}


async def test_run_status_updates(platform_session_factory) -> None:
    repo = PlatformRepository(platform_session_factory)
    await repo.create_minimal_run_for_test("run_status")

    await repo.update_run_status("run_status", RunStatus.RUNNING)
    record = await repo.get_run("run_status")

    assert record is not None
    assert record.status == RunStatus.RUNNING.value
```

- [ ] **Step 3: Implement redaction**

Implement `src/attractor_platform/redaction.py`:

```python
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

SECRET_KEY_FRAGMENTS = ("api_key", "apikey", "token", "secret", "password", "credential")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|credential)\s*=\s*([^\s]+)"
)


def is_secret_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(fragment in normalized for fragment in SECRET_KEY_FRAGMENTS)


def redact_text(value: str) -> str:
    return SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def redact_value(key: str, value: Any) -> Any:
    if is_secret_key(key):
        return "[REDACTED]"
    return redact_any(value)


def redact_any(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        return {str(key): redact_value(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_any(item) for item in value]
    return value


def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): redact_value(str(key), value) for key, value in payload.items()}
```

- [ ] **Step 4: Implement repository methods**

Implement `PlatformRepository` with these concrete async methods. Each method opens a transaction through `session_scope()`, writes or reads only the named ORM model, and returns the ORM instance or list described here:

- `register_repo(repo_id, name, local_path, default_branch, current_commit, dirty_state, timestamp) -> RegisteredRepoModel`
- `upsert_workflow(workflow_id, repo_id, name, dot_path, toml_path, status, diagnostics, timestamp) -> WorkflowPackageModel`
- `create_run(run_id, repo_id, workflow_id, run_spec, actor_label, source_commit, source_branch, timestamp) -> RunRecordModel`
- `update_run_status(run_id, status, error_category=None, error_message=None) -> RunRecordModel`
- `append_event(run_id, event_type, payload, actor_label="", timestamp) -> RunEventModel`
- `list_events(run_id, after_sequence, limit) -> list[RunEventModel]`
- `get_run(run_id) -> RunRecordModel | None`
- `create_approval(approval_id, run_id, node_id, question, timestamp) -> ApprovalDecisionModel`
- `decide_approval(approval_id, answer, actor_label, timestamp) -> ApprovalDecisionModel`
- `create_artifact(artifact_id, run_id, kind, name, uri, media_type, size_bytes, sha256, timestamp) -> ArtifactModel`
- `create_checkpoint(checkpoint_id, run_id, node_id, stage_index, commit_sha, ref_name, timestamp) -> CheckpointModel`
- `list_checkpoints(run_id) -> list[CheckpointModel]`
- `create_writeback(writeback_id, run_id, source_branch, target_branch, actor_label, status, commit_sha, error_message, timestamp) -> WriteBackModel`

`append_event()` must compute `sequence = max(sequence) + 1` within the transaction and must call `redact_mapping()` before writing JSONB.

- [ ] **Step 5: Verify**

Run:

```bash
pytest tests/test_phase2_redaction.py tests/test_phase2_storage.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/attractor_platform/redaction.py src/attractor_platform/storage/repositories.py tests/test_phase2_redaction.py tests/test_phase2_storage.py
git commit -m "feat: add durable repositories and redaction"
```

---

### Task 4: Filesystem Artifact Store

**Files:**
- Modify: `src/attractor_platform/artifacts.py`
- Create: `tests/test_phase2_artifacts.py`

- [ ] **Step 1: Write artifact store tests**

Create `tests/test_phase2_artifacts.py`:

```python
from __future__ import annotations

from attractor_platform.artifacts import FileSystemArtifactStore


def test_filesystem_artifact_store_writes_content_addressed_file(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    record = store.write_bytes(
        run_id="run_1",
        kind="log",
        name="stdout.txt",
        data=b"hello",
        media_type="text/plain",
    )

    assert record.run_id == "run_1"
    assert record.kind == "log"
    assert record.name == "stdout.txt"
    assert record.size_bytes == 5
    assert len(record.sha256) == 64
    assert record.uri.startswith("file://")
    assert store.read_bytes(record.uri) == b"hello"


def test_artifact_store_rejects_path_escape_names(tmp_path) -> None:
    store = FileSystemArtifactStore(tmp_path)

    try:
        store.write_bytes("run_1", "log", "../secret.txt", b"x", "text/plain")
    except ValueError as exc:
        assert "artifact name" in str(exc)
    else:
        raise AssertionError("expected ValueError")
```

- [ ] **Step 2: Implement store**

Implement `src/attractor_platform/artifacts.py`:

```python
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredArtifact:
    run_id: str
    kind: str
    name: str
    uri: str
    media_type: str
    size_bytes: int
    sha256: str


class FileSystemArtifactStore:
    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def write_bytes(
        self,
        run_id: str,
        kind: str,
        name: str,
        data: bytes,
        media_type: str,
    ) -> StoredArtifact:
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("artifact name must be relative and contained")
        digest = hashlib.sha256(data).hexdigest()
        target = self._root / run_id / kind / digest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return StoredArtifact(
            run_id=run_id,
            kind=kind,
            name=name,
            uri=target.as_uri(),
            media_type=media_type,
            size_bytes=len(data),
            sha256=digest,
        )

    def read_bytes(self, uri: str) -> bytes:
        path = Path(uri.removeprefix("file://")).resolve()
        path.relative_to(self._root)
        return path.read_bytes()
```

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_artifacts.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_platform/artifacts.py tests/test_phase2_artifacts.py
git commit -m "feat: add filesystem artifact store"
```

---

### Task 5: Subprocess Git Driver and Worktree Sandbox

**Files:**
- Modify: `src/attractor_platform/git.py`
- Create: `tests/test_phase2_git_worktree.py`

- [ ] **Step 1: Write git worktree tests**

Create `tests/test_phase2_git_worktree.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

from attractor_platform.git import GitRunner, WorktreeManager


def make_repo(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=path, check=True)
    (path / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True)
    return path


def test_worktree_manager_creates_managed_branch_without_mutating_repo(tmp_path) -> None:
    repo_path = make_repo(tmp_path / "repo")
    root = tmp_path / "worktrees"
    manager = WorktreeManager(GitRunner(), root)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path, text=True).strip()

    prepared = manager.prepare(repo_path, run_id="run_abc", base_commit=base)
    (prepared.path / "generated.txt").write_text("created in worktree\n", encoding="utf-8")

    assert prepared.branch == "attractor/runs/run_abc"
    assert prepared.path.exists()
    assert not (repo_path / "generated.txt").exists()


def test_worktree_manager_refuses_dirty_registered_repo(tmp_path) -> None:
    repo_path = make_repo(tmp_path / "repo")
    (repo_path / "README.md").write_text("# dirty\n", encoding="utf-8")
    manager = WorktreeManager(GitRunner(), tmp_path / "worktrees")
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path, text=True).strip()

    try:
        manager.prepare(repo_path, run_id="run_dirty", base_commit=base)
    except RuntimeError as exc:
        assert "dirty" in str(exc).lower()
    else:
        raise AssertionError("expected dirty repo failure")
```

- [ ] **Step 2: Implement git driver**

Implement `src/attractor_platform/git.py` with:

```python
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


SAFE_REF = re.compile(r"^[A-Za-z0-9._/-]+$")


@dataclass(frozen=True)
class GitResult:
    stdout: str
    stderr: str


class GitRunner:
    def run(self, repo_path: str | Path, *args: str) -> GitResult:
        result = subprocess.run(
            ["git", *args],
            cwd=Path(repo_path),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return GitResult(stdout=result.stdout.strip(), stderr=result.stderr.strip())

    def commit(self, repo_path: str | Path) -> str:
        return self.run(repo_path, "rev-parse", "HEAD").stdout

    def status_porcelain(self, repo_path: str | Path) -> str:
        return self.run(repo_path, "status", "--porcelain").stdout


@dataclass(frozen=True)
class PreparedWorktree:
    repo_path: Path
    path: Path
    branch: str
    base_commit: str


class WorktreeManager:
    def __init__(self, git: GitRunner, root: str | Path) -> None:
        self._git = git
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def prepare(self, repo_path: str | Path, *, run_id: str, base_commit: str) -> PreparedWorktree:
        repo = Path(repo_path).expanduser().resolve()
        if self._git.status_porcelain(repo):
            raise RuntimeError("registered repo must be clean before server worktree run")
        if self._git.commit(repo) != base_commit:
            raise RuntimeError("registered repo HEAD does not match RunSpec source commit")
        branch = f"attractor/runs/{run_id}"
        if not SAFE_REF.match(branch):
            raise RuntimeError("unsafe managed branch name")
        path = self._root / run_id
        self._git.run(repo, "worktree", "add", "-b", branch, str(path), base_commit)
        return PreparedWorktree(repo_path=repo, path=path, branch=branch, base_commit=base_commit)
```

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_git_worktree.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_platform/git.py tests/test_phase2_git_worktree.py
git commit -m "feat: add worktree git driver"
```

---

### Task 6: Concurrency-Safe `RunEnvironment` over Existing `ExecutionEnvironment`

**Files:**
- Modify: `src/attractor_platform/run_environment.py`
- Modify: `src/attractor_agent/tools/core.py`
- Create: `tests/test_phase2_run_environment.py`

- [ ] **Step 1: Write boundary and concurrency tests**

Create `tests/test_phase2_run_environment.py`:

```python
from __future__ import annotations

import asyncio

from attractor_agent.environment import ExecutionEnvironment, LocalEnvironment
from attractor_agent.tools.core import get_allowed_roots, get_environment
from attractor_platform.git import PreparedWorktree
from attractor_platform.run_environment import WorktreeLocalRunEnvironment


def prepared_worktree(tmp_path, run_id: str) -> PreparedWorktree:
    path = tmp_path / run_id
    path.mkdir(parents=True)
    return PreparedWorktree(
        repo_path=tmp_path / "repo",
        path=path,
        branch=f"attractor/runs/{run_id}",
        base_commit="1" * 40,
    )


async def test_worktree_local_environment_installs_local_environment(tmp_path) -> None:
    prepared = prepared_worktree(tmp_path, "run_1")
    env = WorktreeLocalRunEnvironment(prepared)

    async with env.activate() as execution_env:
        assert isinstance(execution_env, LocalEnvironment)
        assert await execution_env.working_directory() == str(prepared.path)
        assert get_environment() is execution_env
        assert get_allowed_roots() == [prepared.path.resolve()]


async def test_worktree_environment_is_task_local_for_concurrent_runs(tmp_path) -> None:
    async def run_in_context(prepared: PreparedWorktree) -> tuple[str, list[str], bool]:
        env = WorktreeLocalRunEnvironment(prepared)
        async with env.activate() as execution_env:
            await asyncio.sleep(0)
            active_env: ExecutionEnvironment = get_environment()
            return (
                await active_env.working_directory(),
                [str(root) for root in get_allowed_roots()],
                active_env is execution_env,
            )

    run_a = prepared_worktree(tmp_path, "run_a")
    run_b = prepared_worktree(tmp_path, "run_b")

    result_a, result_b = await asyncio.gather(
        asyncio.create_task(run_in_context(run_a)),
        asyncio.create_task(run_in_context(run_b)),
    )

    assert result_a == (str(run_a.path), [str(run_a.path.resolve())], True)
    assert result_b == (str(run_b.path), [str(run_b.path.resolve())], True)
```

- [ ] **Step 2: Replace process-global tool state with task-local ContextVars**

Modify `src/attractor_agent/tools/core.py`:

```python
import contextvars

_DEFAULT_ENVIRONMENT: ExecutionEnvironment = LocalEnvironment()
_DEFAULT_ALLOWED_ROOTS: tuple[Path, ...] = (Path.cwd().resolve(),)

_environment_var: contextvars.ContextVar[ExecutionEnvironment] = contextvars.ContextVar(
    "attractor_environment",
    default=_DEFAULT_ENVIRONMENT,
)
_allowed_roots_var: contextvars.ContextVar[tuple[Path, ...]] = contextvars.ContextVar(
    "attractor_allowed_roots",
    default=_DEFAULT_ALLOWED_ROOTS,
)


def set_environment(env: ExecutionEnvironment) -> contextvars.Token[ExecutionEnvironment]:
    """Set the execution environment for the current context."""
    return _environment_var.set(env)


def get_environment() -> ExecutionEnvironment:
    """Get the execution environment for the current context."""
    return _environment_var.get()


def set_allowed_roots(roots: list[str | Path]) -> contextvars.Token[tuple[Path, ...]]:
    """Configure allowed roots for the current context."""
    return _allowed_roots_var.set(tuple(Path(root).resolve() for root in roots))


def get_allowed_roots() -> list[Path]:
    """Return the current allowed roots for tests and platform environment guards."""
    return list(_allowed_roots_var.get())


def reset_environment(token: contextvars.Token[ExecutionEnvironment]) -> None:
    """Restore the previous execution environment for the current context."""
    _environment_var.reset(token)


def reset_allowed_roots(token: contextvars.Token[tuple[Path, ...]]) -> None:
    """Restore the previous allowed roots for the current context."""
    _allowed_roots_var.reset(token)
```

After adding the ContextVars, replace every direct `_environment` read in `src/attractor_agent/tools/core.py` with `get_environment()` and every direct `_allowed_roots` read with `get_allowed_roots()`. This includes all `isinstance(_environment, LocalEnvironment)` checks, every `await _environment.<operation>(...)` call, the path-confinement loop, and the path-confinement error message. No tool should read the old module globals directly after this step.

- [ ] **Step 3: Implement token-resetting `RunEnvironment`**

Implement `src/attractor_platform/run_environment.py`:

```python
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from attractor_agent.environment import DockerEnvironment, ExecutionEnvironment, LocalEnvironment
from attractor_agent.tools.core import (
    reset_allowed_roots,
    reset_environment,
    set_allowed_roots,
    set_environment,
)
from attractor_platform.git import PreparedWorktree


class RunEnvironment(Protocol):
    @asynccontextmanager
    async def activate(self) -> AsyncIterator[ExecutionEnvironment]:
        yield


class WorktreeLocalRunEnvironment:
    def __init__(self, prepared: PreparedWorktree) -> None:
        self._prepared = prepared

    @asynccontextmanager
    async def activate(self) -> AsyncIterator[ExecutionEnvironment]:
        env = LocalEnvironment(working_dir=str(self._prepared.path))
        env_token = set_environment(env)
        roots_token = set_allowed_roots([self._prepared.path])
        try:
            await env.start()
            yield env
        finally:
            await env.stop()
            reset_allowed_roots(roots_token)
            reset_environment(env_token)


class DockerRunEnvironment:
    def __init__(self, image: str, workspace: str = "/workspace") -> None:
        self._image = image
        self._workspace = workspace

    @asynccontextmanager
    async def activate(self) -> AsyncIterator[ExecutionEnvironment]:
        env = DockerEnvironment(image=self._image, workspace=self._workspace)
        env_token = set_environment(env)
        roots_token = set_allowed_roots([self._workspace, "/tmp"])
        try:
            await env.start()
            yield env
        finally:
            await env.stop()
            reset_allowed_roots(roots_token)
            reset_environment(env_token)
```

- [ ] **Step 4: Verify**

Run:

```bash
rg -n "_environment\\b|_allowed_roots\\b" src/attractor_agent/tools/core.py
```

Expected: PASS only if matches are limited to the ContextVar definitions and reset helper bodies. No tool function should read `_environment`, `_allowed_roots`, `_environment_var`, or `_allowed_roots_var` directly; tool functions should use `get_environment()` and `get_allowed_roots()`.

Run:

```bash
pytest tests/test_phase2_run_environment.py tests/test_environment.py tests/test_wave5_agent_loop.py tests/test_wave12_agent_session.py -v
```

Expected: PASS. The new two-task test proves cross-run worktree and allowed-root isolation; the existing tests prove callers that ignore `set_environment()` and `set_allowed_roots()` return tokens still work.

- [ ] **Step 5: Commit**

```bash
git add src/attractor_agent/tools/core.py src/attractor_platform/run_environment.py tests/test_phase2_run_environment.py
git commit -m "feat: add run environment boundary"
```

---

### Task 7: Git Checkpoint Commits and Refs

**Files:**
- Modify: `src/attractor_platform/checkpoints.py`
- Create: `tests/test_phase2_checkpoints.py`

- [ ] **Step 1: Write checkpoint tests**

Create `tests/test_phase2_checkpoints.py`:

```python
from __future__ import annotations

import subprocess

from attractor_platform.checkpoints import GitCheckpointService
from attractor_platform.git import GitRunner


def test_checkpoint_service_commits_and_updates_ref(tmp_path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo, check=True)
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    (repo / "generated.txt").write_text("hello\n", encoding="utf-8")

    service = GitCheckpointService(GitRunner())
    checkpoint = service.create_checkpoint(
        worktree_path=repo,
        run_id="run_1",
        workflow_name="release",
        node_id="build",
        stage_index=2,
        event_sequence=7,
        base_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
    )

    assert checkpoint.node_id == "build"
    assert checkpoint.stage_index == 2
    assert checkpoint.ref_name == "refs/attractor/runs/run_1/checkpoints/0002-build"
    assert len(checkpoint.commit_sha) == 40
```

- [ ] **Step 2: Implement checkpoint service**

Implement `src/attractor_platform/checkpoints.py`:

```python
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
        self._git.run(path, "add", "-A")
        if not self._git.status_porcelain(path):
            commit_sha = self._git.commit(path)
        else:
            subject = f"attractor: checkpoint {run_id} stage {stage_index} {node_id}"
            body = (
                f"Run-ID: {run_id}\n"
                f"Workflow: {workflow_name}\n"
                f"Base-Commit: {base_commit}\n"
                f"Node-ID: {node_id}\n"
                f"Stage-Index: {stage_index}\n"
                f"Event-Sequence: {event_sequence}\n"
            )
            self._git.run(path, "commit", "-m", subject, "-m", body)
            commit_sha = self._git.commit(path)
        ref_name = (
            f"refs/attractor/runs/{safe_ref_part(run_id)}/checkpoints/"
            f"{stage_index:04d}-{safe_ref_part(node_id)}"
        )
        self._git.run(path, "update-ref", ref_name, commit_sha)
        return GitCheckpoint(
            run_id=run_id,
            node_id=node_id,
            stage_index=stage_index,
            commit_sha=commit_sha,
            ref_name=ref_name,
        )
```

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_checkpoints.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_platform/checkpoints.py tests/test_phase2_checkpoints.py
git commit -m "feat: add git checkpoint service"
```

---

### Task 8: Durable Worktree Run Executor

**Files:**
- Modify: `src/attractor_platform/executor.py`
- Create: `tests/test_phase2_executor.py`

- [ ] **Step 1: Write executor integration test**

Create `tests/test_phase2_executor.py`:

```python
from __future__ import annotations

import subprocess

import pytest

from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.models import RunStatus


pytestmark = pytest.mark.asyncio


async def test_executor_runs_workflow_in_worktree_and_persists_events(
    tmp_path,
    platform_session_factory,
) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)
    workflow_dir = repo_path / ".attractor" / "workflows" / "release"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(
        '''
        digraph Release {
          graph [goal="release"]
          start [shape=Mdiamond]
          task [shape=box, handler="noop", prompt="run"]
          done [shape=Msquare]
          start -> task -> done
        }
        ''',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)

    executor = DurableRunExecutor.for_tests(
        session_factory=platform_session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )

    run_id = await executor.register_and_launch(
        repo_path=repo_path,
        workflow_name="release",
        actor_label="tester",
        inputs={},
    )
    assert run_id in executor.active_tasks
    result = await executor.wait(run_id)

    run = await executor.repository.get_run(run_id)
    events = await executor.repository.list_events(run_id, after_sequence=0, limit=100)
    checkpoints = await executor.repository.list_checkpoints(run_id)

    assert result.status.value == "success"
    assert run is not None
    assert run.status == RunStatus.COMPLETED.value
    assert [event.event_type for event in events][0] == "run.queued"
    assert "pipeline.started" in [event.event_type for event in events]
    assert checkpoints
```

- [ ] **Step 2: Implement executor event mapping**

Implement `DurableRunExecutor` so it:

- registers or updates a `RegisteredRepoModel`
- loads `WorkflowPackage` through Phase 1 `load_workflow_package()`
- builds immutable `RunSpec`
- creates a `RunRecord`
- schedules each run with `asyncio.create_task(self._run_one(run_id, run_spec, package))`
- stores the task in `active_tasks[run_id]` until completion
- creates a worktree using `WorktreeManager`
- updates run status to `preparing` and `running`
- activates `WorktreeLocalRunEnvironment`
- calls `run_pipeline(graph, handlers, context=inputs, logs_root=artifact_run_dir, on_event=callback)`
- maps each `PipelineEvent` class to a durable event type such as `pipeline.started`, `stage.started`, `stage.completed`, `checkpoint.saved`, `pipeline.completed`, and `pipeline.failed`
- creates a git checkpoint when the engine emits `CheckpointSaved`
- captures `logs_root` files through `FileSystemArtifactStore`
- updates final `RunStatus`
- removes the task from `active_tasks` in a `finally` block after result capture

`register_and_launch()` must not run the workflow inline. It should persist the queued run, create the task, append `run.queued`, and return the durable run id. `wait(run_id)` should await the stored task. This is required even while the first vertical slice is effectively single-run, because `ContextVar` environment isolation depends on each concurrent run having its own asyncio task context.

The `on_event` callback should not block the engine on network I/O. In implementation, enqueue events to an `asyncio.Queue` and have a per-run writer task append them in order; the test can use direct append for deterministic unit coverage if needed.

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_executor.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_platform/executor.py tests/test_phase2_executor.py
git commit -m "feat: launch durable worktree runs"
```

---

### Task 9: Durable Human Gates and Approval Decisions

**Files:**
- Modify: `src/attractor_platform/executor.py`
- Modify: `src/attractor_server/platform_app.py`
- Create: `tests/test_phase2_approvals.py`

- [ ] **Step 1: Write approval test**

Create `tests/test_phase2_approvals.py`:

```python
from __future__ import annotations

import pytest

from attractor_platform.storage.models import RunStatus


pytestmark = pytest.mark.asyncio


async def test_human_gate_persists_pending_and_decision(platform_client, sample_repo_with_human_gate):
    response = await platform_client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo_with_human_gate),
            "workflow_name": "approval",
            "actor_label": "alice",
            "inputs": {},
        },
    )
    run_id = response.json()["id"]

    await platform_client.wait_for_status(run_id, RunStatus.WAITING_FOR_APPROVAL.value)
    approvals = (await platform_client.get(f"/api/runs/{run_id}/approvals")).json()

    assert len(approvals) == 1
    decision = await platform_client.post(
        f"/api/runs/{run_id}/approvals/{approvals[0]['id']}",
        json={"answer": "approve", "actor_label": "bob"},
    )

    assert decision.status_code == 200
    await platform_client.wait_for_status(run_id, RunStatus.COMPLETED.value)
```

- [ ] **Step 2: Implement durable interviewer**

Add a server-run interviewer inside `executor.py` that:

- appends `approval.requested`
- creates `ApprovalDecisionModel(status="pending")`
- sets run status to `waiting_for_approval`
- blocks on an in-process `asyncio.Event` for this server process
- resumes when `POST /api/runs/{run_id}/approvals/{approval_id}` records the answer
- appends `approval.decided`
- sets run status back to `running`

Restart-safe waiting can be expanded in a later task by the durable queue worker. The persisted pending approval is still the source of truth for UI and audit.

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_approvals.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_platform/executor.py src/attractor_server/platform_app.py tests/test_phase2_approvals.py
git commit -m "feat: persist human gate approvals"
```

---

### Task 10: FastAPI Platform Surface

**Files:**
- Modify: `src/attractor_server/platform_app.py`
- Modify: `src/attractor_server/__main__.py`
- Create: `tests/test_phase2_api.py`

- [ ] **Step 1: Write API tests**

Create `tests/test_phase2_api.py`:

```python
from __future__ import annotations


def test_platform_health(platform_test_client) -> None:
    response = platform_test_client.get("/api/system/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_repo_and_list_workflows(platform_test_client, sample_repo) -> None:
    response = platform_test_client.post(
        "/api/repos",
        json={"name": "sample", "local_path": str(sample_repo)},
    )
    assert response.status_code == 201
    repo_id = response.json()["id"]

    workflows = platform_test_client.get(f"/api/repos/{repo_id}/workflows")
    assert workflows.status_code == 200
    assert workflows.json()[0]["name"] == "release"


def test_launch_run_returns_durable_id(platform_test_client, sample_repo) -> None:
    platform_test_client.post("/api/repos", json={"name": "sample", "local_path": str(sample_repo)})
    response = platform_test_client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo),
            "workflow_name": "release",
            "actor_label": "alice",
            "inputs": {},
        },
    )
    assert response.status_code == 201
    assert response.json()["id"].startswith("run_")
```

- [ ] **Step 2: Implement FastAPI app**

Create `create_platform_app()` exposing:

```text
POST /api/repos
GET  /api/repos
GET  /api/repos/{repo_id}
GET  /api/repos/{repo_id}/project-config
GET  /api/repos/{repo_id}/workflows
POST /api/workflows/{workflow_id}/validate
POST /api/runs
GET  /api/runs
GET  /api/runs/{run_id}
GET  /api/runs/{run_id}/events
GET  /api/runs/{run_id}/approvals
POST /api/runs/{run_id}/approvals/{approval_id}
GET  /api/runs/{run_id}/artifacts
GET  /api/runs/{run_id}/checkpoints
POST /api/runs/{run_id}/cancel
POST /api/runs/{run_id}/writeback
GET  /api/system/health
GET  /api/system/capacity
```

All approval and write-back request bodies must accept `actor_label`.

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_api.py tests/test_server.py -v
```

Expected: PASS. Existing Starlette server tests should still pass unless they are intentionally migrated in this task.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_server/platform_app.py src/attractor_server/__main__.py tests/test_phase2_api.py
git commit -m "feat: expose phase 2 FastAPI surface"
```

---

### Task 11: Durable SSE Projection

**Files:**
- Modify: `src/attractor_server/platform_sse.py`
- Modify: `src/attractor_server/platform_app.py`
- Create: `tests/test_phase2_sse.py`

- [ ] **Step 1: Write SSE replay test**

Create `tests/test_phase2_sse.py`:

```python
from __future__ import annotations


def test_sse_replays_persisted_events(platform_test_client, seeded_run_with_events) -> None:
    run_id = seeded_run_with_events
    with platform_test_client.stream("GET", f"/api/runs/{run_id}/events/stream") as response:
        assert response.status_code == 200
        first_chunk = next(response.iter_text())

    assert "event: run.queued" in first_chunk
    assert "data:" in first_chunk
```

- [ ] **Step 2: Implement SSE projection**

Implement `platform_sse.py` so it:

- queries `RunEventModel` ordered by sequence
- supports `Last-Event-ID` or `after_sequence`
- formats `id: {sequence}`, `event: {event_type}`, and JSON `data`
- polls for new durable rows while run status is non-terminal
- sends keepalive comments every 30 seconds

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_sse.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_server/platform_sse.py src/attractor_server/platform_app.py tests/test_phase2_sse.py
git commit -m "feat: stream durable run events"
```

---

### Task 12: Branch-from-Worktree Write-Back

**Files:**
- Modify: `src/attractor_platform/git.py`
- Modify: `src/attractor_platform/executor.py`
- Modify: `src/attractor_server/platform_app.py`
- Create: `tests/test_phase2_writeback.py`

- [ ] **Step 1: Write write-back tests**

Create `tests/test_phase2_writeback.py`:

```python
from __future__ import annotations


def test_writeback_promotes_managed_branch(platform_test_client, completed_run_with_worktree_branch) -> None:
    run_id = completed_run_with_worktree_branch
    response = platform_test_client.post(
        f"/api/runs/{run_id}/writeback",
        json={"target_branch": "attractor/accepted/run_1", "actor_label": "alice"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "writeback_applied"
    assert response.json()["target_branch"] == "attractor/accepted/run_1"


def test_writeback_rejects_protected_branch(platform_test_client, completed_run_with_worktree_branch) -> None:
    run_id = completed_run_with_worktree_branch
    response = platform_test_client.post(
        f"/api/runs/{run_id}/writeback",
        json={"target_branch": "main", "actor_label": "alice"},
    )

    assert response.status_code == 409
    assert "protected" in response.json()["error"].lower()
```

- [ ] **Step 2: Implement write-back checks**

Add `GitRunner.promote_branch()` and server write-back orchestration that refuses when:

- registered repo path is missing
- managed worktree path is missing
- managed branch is not based on `RunSpec.source_commit`
- registered repo cannot resolve the managed branch
- target branch is protected (`main`, `master`, `develop`, `release/*` unless explicitly allowed)
- target branch already exists and overwrite is not requested
- filesystem permissions prevent refs from being updated

Promotion should create or update a local branch in the registered repo pointing at the managed worktree branch commit. It must not patch files into the live working tree.

- [ ] **Step 3: Persist write-back records and events**

On success:

- create `WriteBackModel(status="applied")`
- append `writeback.applied`
- update run status to `writeback_applied`

On failure:

- create `WriteBackModel(status="failed")`
- append `writeback.failed`
- update run status to `writeback_failed`

- [ ] **Step 4: Verify**

Run:

```bash
pytest tests/test_phase2_writeback.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/attractor_platform/git.py src/attractor_platform/executor.py src/attractor_server/platform_app.py tests/test_phase2_writeback.py
git commit -m "feat: promote approved worktree branches"
```

---

### Task 13: Minimal React Operations Console

**Files:**
- Create: `web/package.json`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/api.ts`
- Create: `web/src/styles.css`
- Create: `web/src/components/*`
- Create: `web/src/routes/*`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`

- [ ] **Step 1: Create console routes**

Implement these routes against the FastAPI backend:

```text
/                       active runs, queued runs, waiting approvals, recent failures
/repos                  registered repos and register-local-path form
/repos/:repoId          workflows discovered for a repo
/workflows/:workflowId  validation status, launch form, environment policy
/runs                   run list
/runs/:runId            timeline, status, events, checkpoints, artifacts, approvals, write-back action
/approvals              pending human gates and write-back approvals
/system                 health and capacity
```

- [ ] **Step 2: Implement API client**

Create `web/src/api.ts` with typed functions for:

```typescript
export async function registerRepo(input: { name: string; local_path: string }): Promise<Repo>
export async function listRepos(): Promise<Repo[]>
export async function listWorkflows(repoId: string): Promise<Workflow[]>
export async function launchRun(input: LaunchRunInput): Promise<RunRecord>
export async function getRun(runId: string): Promise<RunRecord>
export async function listRunEvents(runId: string): Promise<RunEvent[]>
export async function answerApproval(runId: string, approvalId: string, input: ApprovalInput): Promise<ApprovalDecision>
export async function promoteWriteBack(runId: string, input: WriteBackInput): Promise<WriteBackRecord>
export function openRunEventSource(runId: string): EventSource
```

- [ ] **Step 3: Build the Run Detail first**

Run Detail must show:

- durable run status
- source commit and managed branch
- event timeline from persisted events plus live SSE updates
- pending approval controls when status is `waiting_for_approval`
- artifact list
- checkpoint list
- write-back action when run is completed and branch exists

- [ ] **Step 4: Verify frontend**

Run:

```bash
cd web
npm install
npm run build
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web
git commit -m "feat: add minimal operations console"
```

---

### Task 14: Docker RunEnvironment Follow-On

**Files:**
- Modify: `src/attractor_platform/run_environment.py`
- Modify: `src/attractor_platform/executor.py`
- Create: `tests/test_phase2_docker_environment.py`

- [ ] **Step 1: Write Docker selection tests**

Create `tests/test_phase2_docker_environment.py`:

```python
from __future__ import annotations

from attractor_platform.run_environment import DockerRunEnvironment, select_run_environment
from attractor_platform.runspec import RunEnvironmentRequest


def test_select_docker_run_environment() -> None:
    env = select_run_environment(
        RunEnvironmentRequest(mode="docker", name="docker", image="python:3.12-slim"),
        prepared_worktree=None,
    )

    assert isinstance(env, DockerRunEnvironment)
```

- [ ] **Step 2: Implement environment selection**

Add `select_run_environment()`:

```python
def select_run_environment(
    request: RunEnvironmentRequest,
    prepared_worktree: PreparedWorktree | None,
) -> RunEnvironment:
    if request.mode == "local":
        if prepared_worktree is None:
            raise ValueError("worktree-local server runs require a prepared worktree")
        return WorktreeLocalRunEnvironment(prepared_worktree)
    if request.mode == "docker":
        return DockerRunEnvironment(image=request.image or "python:3.12-slim")
    raise ValueError("remote run environments are not implemented in Phase 2")
```

The executor should still prepare a worktree for Docker runs so write-back and checkpoints have the same branch provenance.

- [ ] **Step 3: Verify**

Run:

```bash
pytest tests/test_phase2_docker_environment.py -v
```

Expected: PASS. Add a real Docker integration test marked with `@pytest.mark.docker` if Docker is available in CI.

- [ ] **Step 4: Commit**

```bash
git add src/attractor_platform/run_environment.py src/attractor_platform/executor.py tests/test_phase2_docker_environment.py
git commit -m "feat: select docker run environments"
```

---

### Task 15: End-to-End Phase 2 Verification

**Files:**
- Create: `tests/test_phase2_e2e.py`

- [ ] **Step 1: Write the trusted-LAN milestone test**

Create `tests/test_phase2_e2e.py`:

```python
from __future__ import annotations


def test_phase2_vertical_slice_register_run_approve_promote(platform_test_client, sample_repo_with_human_gate) -> None:
    repo = platform_test_client.post(
        "/api/repos",
        json={"name": "sample", "local_path": str(sample_repo_with_human_gate)},
    ).json()

    workflows = platform_test_client.get(f"/api/repos/{repo['id']}/workflows").json()
    assert workflows[0]["status"] == "valid"

    run = platform_test_client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo_with_human_gate),
            "workflow_name": workflows[0]["name"],
            "actor_label": "alice",
            "inputs": {},
        },
    ).json()

    run_id = run["id"]
    platform_test_client.wait_for_status(run_id, "waiting_for_approval")
    approval = platform_test_client.get(f"/api/runs/{run_id}/approvals").json()[0]
    platform_test_client.post(
        f"/api/runs/{run_id}/approvals/{approval['id']}",
        json={"answer": "approve", "actor_label": "alice"},
    )
    platform_test_client.wait_for_status(run_id, "completed")

    writeback = platform_test_client.post(
        f"/api/runs/{run_id}/writeback",
        json={"target_branch": "attractor/accepted/e2e", "actor_label": "alice"},
    )

    assert writeback.status_code == 200
    assert writeback.json()["status"] == "writeback_applied"
```

- [ ] **Step 2: Run focused Phase 2 suite**

Run:

```bash
pytest \
  tests/test_phase2_imports.py \
  tests/test_phase2_storage_models.py \
  tests/test_phase2_redaction.py \
  tests/test_phase2_storage.py \
  tests/test_phase2_artifacts.py \
  tests/test_phase2_git_worktree.py \
  tests/test_phase2_run_environment.py \
  tests/test_phase2_checkpoints.py \
  tests/test_phase2_executor.py \
  tests/test_phase2_approvals.py \
  tests/test_phase2_api.py \
  tests/test_phase2_sse.py \
  tests/test_phase2_writeback.py \
  tests/test_phase2_e2e.py \
  -v
```

Expected: PASS.

- [ ] **Step 3: Run regression suite for Phase 1 and existing engine/server**

Run:

```bash
pytest \
  tests/test_platform_errors.py \
  tests/test_platform_config.py \
  tests/test_workflow_packages.py \
  tests/test_runspec.py \
  tests/test_phase1_regressions.py \
  tests/test_pipeline_engine.py \
  tests/test_environment.py \
  tests/test_server.py \
  -v
```

Expected: PASS.

- [ ] **Step 4: Run static checks**

Run:

```bash
ruff check src tests
pyright src
```

Expected: PASS.

- [ ] **Step 5: Run frontend build**

Run:

```bash
cd web
npm run build
```

Expected: PASS.

- [ ] **Step 6: Commit final verification fixes**

If verification exposes mechanical fixes, commit them:

```bash
git add src tests web pyproject.toml
git commit -m "chore: verify phase 2 vertical slice"
```

---

## Self-Review

**Spec coverage**

- Durability spine: Tasks 2, 3, 4, 8, 9, 11, and 15.
- Isolation spine: Tasks 5, 6, 7, 8, 12, and 14.
- Worktree-local shared-server execution: Tasks 5, 6, and 8.
- Git checkpointing: Task 7 and executor integration in Task 8.
- Branch-from-worktree write-back: Task 12.
- Durable SSE projection: Task 11.
- Human gates and `ApprovalDecision`: Task 9.
- Artifact capture: Task 4 and executor integration in Task 8.
- FastAPI surface: Task 10.
- Minimal Operations Console: Task 13.
- Docker later in Phase 2, after worktree-local: Task 14.

**Risk notes**

- Task 6 must convert agent tool environment and allowed-root state from process-global mutation to task-local `ContextVar` state before any server run executor ships. Cross-run worktree isolation is a security boundary, not just a correctness convenience.
- Task 8 must launch each run in its own `asyncio.Task`; otherwise task-local environment state cannot isolate concurrent durable-queue runs.
- Durable event appends from `on_event` need ordering guarantees. Use a per-run writer queue and persist sequence numbers in one repository method.
- SQLite is the default local/test durable storage path; Alembic remains the Postgres production migration path when `ATTRACTOR_DATABASE_URL` or `ATTRACTOR_TEST_DATABASE_URL` points at Postgres.
- [ ] Follow-up: run the full DB test suite once against real Postgres with `ATTRACTOR_TEST_DATABASE_URL=postgresql+asyncpg://...` before enabling the shared concurrent multi-user server. Do not add concurrent Postgres-specific work before that verification pass.
- Worktree cleanup should be policy-based. Keep worktrees for completed runs until write-back or retention cleanup so branch promotion can inspect the managed branch.

**Execution notes**

- Build the two spines before the API and console. The first useful demo should not launch raw-host server runs.
- Keep the old Starlette in-memory server behavior passing until the FastAPI platform surface intentionally replaces it.
- Use small commits exactly as listed; each task is reviewable on its own.
