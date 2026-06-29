from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path
from typing import Any

from attractor_pipeline import (
    HandlerRegistry,
    HandlerResult,
    Outcome,
    PipelineStatus,
    register_default_handlers,
    run_pipeline,
    validate,
    validate_or_raise,
)
from attractor_pipeline.engine.runner import Handler
from attractor_pipeline.graph import Graph, Node
from attractor_pipeline.parser import parse_dot


class LocalTestHandler(Handler):
    async def execute(
        self,
        node: Node,
        context: dict[str, object],
        graph: Graph,
        logs_root: Path | None,
        abort_signal: Any = None,
    ) -> HandlerResult:
        return HandlerResult(
            status=Outcome.SUCCESS,
            context_updates={"ran_without_docker": True},
            output="local execution ok",
        )


DOT = """
digraph LocalPath {
  graph [goal="Prove local path still works"]
  start [shape=Mdiamond]
  task [shape=box, handler="local.test", prompt="Run locally"]
  done [shape=Msquare]
  start -> task -> done
}
"""


def test_validate_exports_are_available_from_public_pipeline_api() -> None:
    graph = parse_dot(DOT)

    assert validate(graph) == []
    validate_or_raise(graph)


def test_library_run_pipeline_still_executes_without_docker(tmp_path: Path) -> None:
    graph = parse_dot(DOT)
    registry = HandlerRegistry()
    register_default_handlers(registry)
    registry.register("local.test", LocalTestHandler())

    result = asyncio.run(run_pipeline(graph, registry, logs_root=tmp_path))

    assert result.status == PipelineStatus.COMPLETED
    assert result.context["ran_without_docker"] is True


def test_cli_validate_still_accepts_plain_dot_file(tmp_path: Path) -> None:
    dot_path = tmp_path / "workflow.dot"
    dot_path.write_text(DOT, encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "-m", "attractor_pipeline.cli", "validate", str(dot_path)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "Validation: PASS" in result.stdout
