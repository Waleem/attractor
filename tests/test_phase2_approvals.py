from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from attractor_platform.executor import DurableRunExecutor
from attractor_platform.storage.db import create_session_factory
from attractor_platform.storage.models import Base, RunStatus
from attractor_server.platform_app import create_app

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def platform_session_factory(
    request: pytest.FixtureRequest,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    database_url = os.environ.get("ATTRACTOR_TEST_DATABASE_URL")
    if not database_url:
        if shutil.which("pg_config") is None or shutil.which("pg_ctl") is None:
            pytest.skip(
                "Neither ATTRACTOR_TEST_DATABASE_URL nor local PostgreSQL tooling is available"
            )
        postgresql = request.getfixturevalue("postgresql")
        database_url = (
            "postgresql+asyncpg://"
            f"{postgresql.info.user}:{postgresql.info.password}@"
            f"{postgresql.info.host}:{postgresql.info.port}/{postgresql.info.dbname}"
        )

    engine = create_async_engine(database_url, pool_pre_ping=True)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        yield create_session_factory(engine)
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
def sample_repo_with_human_gate(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Tests"], cwd=repo_path, check=True)

    workflow_dir = repo_path / ".attractor" / "workflows" / "approval"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.dot").write_text(
        """
        digraph Approval {
          graph [goal="approval"]
          start [shape=Mdiamond]
          review [shape=house, prompt="Approve release?"]
          done [shape=Msquare]
          start -> review
          review -> done [label="approve"]
        }
        """,
        encoding="utf-8",
    )

    subprocess.run(["git", "add", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


@pytest_asyncio.fixture
async def platform_client(
    tmp_path: Path,
    platform_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    executor = DurableRunExecutor(
        session_factory=platform_session_factory,
        worktree_root=tmp_path / "worktrees",
        artifact_root=tmp_path / "artifacts",
    )
    app = create_app(
        session_factory=platform_session_factory,
        executor=executor,
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


async def _wait_for_status(
    client: httpx.AsyncClient,
    run_id: str,
    status: str,
    *,
    attempts: int = 80,
) -> dict[str, object]:
    for _ in range(attempts):
        response = await client.get(f"/api/runs/{run_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == status:
            return payload
        await asyncio.sleep(0.05)
    pytest.fail(f"Run {run_id} did not reach status {status!r}")


async def test_human_gate_persists_pending_and_decision(
    platform_client: httpx.AsyncClient,
    sample_repo_with_human_gate: Path,
) -> None:
    launch_response = await platform_client.post(
        "/api/runs",
        json={
            "repo_path": str(sample_repo_with_human_gate),
            "workflow": "approval",
            "actor_label": "alice",
            "inputs": {},
        },
    )

    assert launch_response.status_code == 201
    run_id = launch_response.json()["id"]

    await _wait_for_status(
        platform_client,
        run_id,
        RunStatus.WAITING_FOR_APPROVAL.value,
    )

    approvals_response = await platform_client.get(f"/api/runs/{run_id}/approvals")
    assert approvals_response.status_code == 200
    approvals = approvals_response.json()["items"]
    pending_approvals = [approval for approval in approvals if approval["status"] == "pending"]
    assert len(pending_approvals) == 1

    approval_id = pending_approvals[0]["id"]
    decision_response = await platform_client.post(
        f"/api/runs/{run_id}/approvals/{approval_id}",
        json={"answer": "approve", "actor_label": "bob"},
    )

    assert decision_response.status_code == 200

    await _wait_for_status(
        platform_client,
        run_id,
        RunStatus.COMPLETED.value,
    )
