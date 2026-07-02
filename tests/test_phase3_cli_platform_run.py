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


@respx.mock
def test_run_uses_platform_url_from_environment(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTRACTOR_PLATFORM_URL", "http://platform")
    route = respx.post("http://platform/api/runs").mock(
        return_value=httpx.Response(201, json={"id": "run_env", "status": "queued"})
    )

    with patch.object(
        sys,
        "argv",
        ["attractor", "run", "release-checks", "--repo", "/repo"],
    ):
        cli.main()

    assert route.called
    request_body = json.loads(route.calls[0].request.content)
    assert request_body["repo_path"] == "/repo"
    assert request_body["workflow_name"] == "release-checks"
    assert "run_env" in capsys.readouterr().out


@respx.mock
def test_run_server_url_flag_takes_precedence_over_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTRACTOR_PLATFORM_URL", "http://env-platform")
    env_route = respx.post("http://env-platform/api/runs").mock(
        return_value=httpx.Response(201, json={"id": "run_env", "status": "queued"})
    )
    flag_route = respx.post("http://flag-platform/api/runs").mock(
        return_value=httpx.Response(201, json={"id": "run_flag", "status": "queued"})
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
            "http://flag-platform",
        ],
    ):
        cli.main()

    assert flag_route.called
    assert not env_route.called


def test_run_invalid_input_returns_nonzero_and_useful_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch.object(
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
                "badvalue",
            ],
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli.main()

    assert exc_info.value.code == 1
    output = capsys.readouterr().out
    assert "Invalid --input value 'badvalue'" in output
    assert "Expected key=value" in output


@pytest.mark.parametrize(
    ("status_code", "error_body", "expected_text"),
    [
        (400, {"error": "workflow not found"}, "workflow not found"),
        (500, {"detail": "database unavailable"}, "database unavailable"),
    ],
)
@respx.mock
def test_run_server_error_returns_nonzero_and_prints_error_text(
    capsys: pytest.CaptureFixture[str],
    status_code: int,
    error_body: dict[str, str],
    expected_text: str,
) -> None:
    respx.post("http://platform/api/runs").mock(
        return_value=httpx.Response(status_code, json=error_body)
    )

    with (
        patch.object(
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
            ],
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        cli.main()

    assert exc_info.value.code == 1
    assert expected_text in capsys.readouterr().out


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
