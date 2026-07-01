"""Durable SSE projection for Phase 2 platform run events."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, cast

from attractor_platform.storage.models import RunStatus

TERMINAL_RUN_STATUSES = {
    RunStatus.COMPLETED.value,
    RunStatus.FAILED.value,
    RunStatus.CANCELLED.value,
    RunStatus.WRITEBACK_APPLIED.value,
    RunStatus.WRITEBACK_FAILED.value,
}


def parse_sse_after_sequence(
    *,
    after_sequence: int,
    last_event_id: str | None,
) -> int:
    """Resolve SSE replay offset from query params and Last-Event-ID."""
    if last_event_id is None:
        return after_sequence
    try:
        parsed = int(last_event_id)
    except ValueError:
        return after_sequence
    return max(parsed, 0)


def format_durable_sse_event(event: Any) -> str:
    """Format a persisted run event as a Server-Sent Event frame."""
    data_json = json.dumps(event.payload, default=str, separators=(",", ":"))
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data_json}\n\n"


async def durable_run_event_stream(
    repository: Any,
    run_id: str,
    *,
    after_sequence: int = 0,
    poll_interval_seconds: float = 1.0,
    keepalive_interval_seconds: float = 30.0,
    batch_size: int = 100,
) -> AsyncIterator[str]:
    """Yield SSE frames by polling durable run events.

    This intentionally reads from the repository on every iteration so reconnecting
    clients replay persisted rows rather than subscribing to process-local memory.
    """
    last_sequence = after_sequence
    last_keepalive_at = time.monotonic()

    while True:
        events = await _list_events(repository, run_id, last_sequence, batch_size)
        if events:
            for event in events:
                yield format_durable_sse_event(event)
                last_sequence = max(last_sequence, int(event.sequence))
            last_keepalive_at = time.monotonic()
            continue

        run = await _get_run(repository, run_id)
        if run is None or _is_terminal_status(getattr(run, "status", None)):
            return

        now = time.monotonic()
        if now - last_keepalive_at >= keepalive_interval_seconds:
            yield ": keepalive\n\n"
            last_keepalive_at = now

        await asyncio.sleep(poll_interval_seconds)


async def _get_run(repository: Any, run_id: str) -> Any | None:
    get_run = cast(
        Callable[[str], Awaitable[Any | None]] | None,
        getattr(repository, "get_run", None),
    )
    if get_run is not None:
        return await get_run(run_id)

    runs = getattr(repository, "runs", None)
    if isinstance(runs, dict):
        return runs.get(run_id)

    raise RuntimeError("Repository does not support loading runs")


async def _list_events(
    repository: Any,
    run_id: str,
    after_sequence: int,
    limit: int,
) -> list[Any]:
    list_events = cast(
        Callable[[str, int, int], Awaitable[list[Any]]] | None,
        getattr(repository, "list_events", None),
    )
    if list_events is not None:
        return list(await list_events(run_id, after_sequence, limit))

    events = getattr(repository, "events", None)
    if isinstance(events, dict):
        run_events = events.get(run_id, [])
        return [event for event in run_events if int(event.sequence) > after_sequence][:limit]

    raise RuntimeError("Repository does not support listing events")


def _is_terminal_status(status: Any) -> bool:
    status_value = status.value if isinstance(status, RunStatus) else status
    return status_value in TERMINAL_RUN_STATUSES
