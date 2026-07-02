"""HTTP client helpers for platform-backed CLI runs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx


def _parse_inputs(values: Sequence[str]) -> dict[str, str]:
    inputs: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid --input value '{value}'. Expected key=value.")
        key, parsed_value = value.split("=", 1)
        if not key:
            raise ValueError("Invalid --input value. Key must not be empty.")
        inputs[key] = parsed_value
    return inputs


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        return response.text.strip() or response.reason_phrase

    if isinstance(body, dict):
        for key in ("error", "message", "detail"):
            value = body.get(key)
            if isinstance(value, str) and value:
                return value
        return json.dumps(body, sort_keys=True)
    return response.text.strip() or response.reason_phrase


def launch_platform_run(
    *,
    workflow_name: str,
    repo_path: str,
    server_url: str,
    inputs: Sequence[str] = (),
    actor_label: str = "",
    requested_environment: str = "",
    timeout: float = 30.0,
) -> int:
    """Launch a durable platform run through the HTTP API."""
    base_url = server_url.rstrip("/")
    request_body: dict[str, Any] = {
        "repo_path": repo_path,
        "workflow_name": workflow_name,
        "inputs": _parse_inputs(inputs),
    }
    if actor_label:
        request_body["actor_label"] = actor_label
    if requested_environment:
        request_body["requested_environment"] = requested_environment

    run_collection_url = f"{base_url}/api/runs"
    try:
        response = httpx.post(run_collection_url, json=request_body, timeout=timeout)
    except httpx.HTTPError as exc:
        print(f"Error: {exc}")
        return 1

    if response.status_code >= 400:
        print(f"Error: {_error_text(response)}")
        return 1

    try:
        run = response.json()
    except json.JSONDecodeError:
        print("Error: Platform returned an invalid JSON response")
        return 1

    run_id = run.get("id")
    if not isinstance(run_id, str) or not run_id:
        print("Error: Platform response did not include a run id")
        return 1

    status = run.get("status", "unknown")
    print(f"Run: {run_id}")
    print(f"Status: {status}")
    print(f"URL: {base_url}/api/runs/{run_id}")
    return 0
