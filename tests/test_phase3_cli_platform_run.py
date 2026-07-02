from __future__ import annotations

import json
import sys
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
import respx

from attractor_pipeline import cli


@respx.mock
def test_run_launches_platform_run_and_prints_durable_run_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    route = respx.post("http://platform/api/runs").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": "run_123",
                "status": "queued",
                "repo_id": "repo_123",
                "workflow_id": "wf_123",
            },
        )
    )

    with patch.object(
        sys,
        "argv",
        [
            "attractor",
            "run",
            "release-checks",
            "--repo",
            "/repo",
            "--server-url",
            "http://platform",
            "--input",
            "target=wheel",
            "--environment",
            "docker-ci",
        ],
    ):
        cli.main()

    assert route.called
    assert route.call_count == 1
    request_body = json.loads(route.calls[0].request.content)
    assert request_body == {
        "repo_path": "/repo",
        "workflow_name": "release-checks",
        "inputs": {"target": "wheel"},
        "requested_environment": "docker-ci",
    }

    output = capsys.readouterr().out
    assert "run_123" in output
    assert "queued" in output
    assert "http://platform/api/runs/run_123" in output


def test_run_legacy_local_uses_existing_dot_runner(tmp_path: Path) -> None:
    dotfile = tmp_path / "workflow.dot"
    dotfile.write_text("digraph Legacy { start [shape=Mdiamond] }", encoding="utf-8")
    seen_args: list[Namespace] = []

    async def fake_cmd_run(args: Namespace) -> None:
        seen_args.append(args)

    with (
        patch.object(cli, "_cmd_run", side_effect=fake_cmd_run),
        patch.object(
            sys,
            "argv",
            [
                "attractor",
                "run",
                "--legacy-local",
                str(dotfile),
                "--provider",
                "openai",
                "--model",
                "gpt-5.2",
                "--no-tools",
            ],
        ),
    ):
        cli.main()

    assert len(seen_args) == 1
    assert seen_args[0].dotfile == str(dotfile)
    assert seen_args[0].provider == "openai"
    assert seen_args[0].model == "gpt-5.2"
    assert seen_args[0].no_tools is True
