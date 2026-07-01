from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass
from typing import Any, cast

import httpx
import pytest
import pytest_asyncio

from attractor_platform.storage.models import RunStatus
from attractor_server.platform_app import create_platform_app
from attractor_server.platform_sse import durable_run_event_stream

pytestmark = pytest.mark.asyncio


@dataclass
class _Run:
    id: str
    repo_id: str
    workflow_id: str
    run_spec: dict[str, Any]
    actor_label: str
    source_commit: str
    source_branch: str
    status: str
    worktree_path: str | None
    managed_branch: str | None
    error_category: str | None
    error_message: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    started_at: dt.datetime | None = None
    completed_at: dt.datetime | None = None


@dataclass
class _Event:
    sequence: int
    event_type: str
    payload: dict[str, Any]
    actor_label: str
    created_at: dt.datetime


class _InMemoryRepository:
    def __init__(self) -> None:
        now = dt.datetime.now(dt.UTC)
        self.runs = {
            "run_1": _Run(
                id="run_1",
                repo_id="repo_1",
                workflow_id="workflow_1",
                run_spec={},
                actor_label="alice",
                source_commit="a" * 40,
                source_branch="main",
                status=RunStatus.COMPLETED.value,
                worktree_path=None,
                managed_branch=None,
                error_category=None,
                error_message=None,
                created_at=now,
                updated_at=now,
                completed_at=now,
            )
        }
        self.events = {
            "run_1": [
                _Event(
                    sequence=1,
                    event_type="run.queued",
                    payload={"workflow_name": "release"},
                    actor_label="alice",
                    created_at=now,
                ),
                _Event(
                    sequence=2,
                    event_type="run.completed",
                    payload={"status": "ok"},
                    actor_label="alice",
                    created_at=now,
                ),
            ]
        }

    async def get_run(self, run_id: str) -> _Run | None:
        return self.runs.get(run_id)

    async def list_events(self, run_id: str, after_sequence: int, limit: int) -> list[_Event]:
        return [
            event for event in self.events.get(run_id, []) if event.sequence > after_sequence
        ][:limit]


class _FakeExecutor:
    def __init__(self, repository: _InMemoryRepository) -> None:
        self.repository = repository
        self.active_tasks: dict[str, asyncio.Task[Any]] = {}
        self.max_concurrent_runs = 3


@dataclass
class _Harness:
    client: httpx.AsyncClient
    repository: _InMemoryRepository


@pytest_asyncio.fixture
async def platform_sse_harness() -> AsyncIterator[_Harness]:
    repository = _InMemoryRepository()
    executor = _FakeExecutor(repository)
    app = create_platform_app(session_factory=cast(Any, None), executor=cast(Any, executor))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield _Harness(client=client, repository=repository)


async def _read_sse_text(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str] | None = None,
) -> tuple[int, str]:
    async with client.stream("GET", url, headers=headers) as response:
        text = "".join([chunk async for chunk in response.aiter_text()])
        return response.status_code, text


async def test_sse_replays_persisted_events(platform_sse_harness: _Harness) -> None:
    status_code, text = await _read_sse_text(
        platform_sse_harness.client,
        "/api/runs/run_1/events/stream",
    )

    assert status_code == 200
    first_chunk = text.split("\n\n", 1)[0]
    assert "id: 1" in first_chunk
    assert "event: run.queued" in first_chunk
    assert "data:" in first_chunk


async def test_sse_replay_honors_last_event_id(platform_sse_harness: _Harness) -> None:
    status_code, text = await _read_sse_text(
        platform_sse_harness.client,
        "/api/runs/run_1/events/stream",
        headers={"Last-Event-ID": "1"},
    )

    assert status_code == 200
    assert "event: run.queued" not in text
    assert "id: 2" in text
    assert "event: run.completed" in text


async def test_sse_replay_honors_after_sequence(platform_sse_harness: _Harness) -> None:
    status_code, text = await _read_sse_text(
        platform_sse_harness.client,
        "/api/runs/run_1/events/stream?after_sequence=1",
    )

    assert status_code == 200
    assert "event: run.queued" not in text
    assert "event: run.completed" in text


async def test_sse_unknown_run_returns_404(platform_sse_harness: _Harness) -> None:
    response = await platform_sse_harness.client.get("/api/runs/missing/events/stream")

    assert response.status_code == 404


async def test_sse_keepalive_does_not_require_real_interval(
    platform_sse_harness: _Harness,
) -> None:
    platform_sse_harness.repository.runs["run_1"].status = RunStatus.RUNNING.value
    platform_sse_harness.repository.events["run_1"] = []
    stream = cast(
        AsyncGenerator[str, None],
        durable_run_event_stream(
            platform_sse_harness.repository,
            "run_1",
            poll_interval_seconds=0.01,
            keepalive_interval_seconds=0,
        ),
    )

    try:
        chunk = await asyncio.wait_for(anext(stream), timeout=0.2)
    finally:
        await stream.aclose()

    assert chunk == ": keepalive\n\n"
