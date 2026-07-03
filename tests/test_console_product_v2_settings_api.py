from __future__ import annotations

from typing import Any

import pytest

from tests.test_phase3_settings_api import _client

pytestmark = pytest.mark.asyncio


async def test_deep_settings_overview_contains_operator_knobs(tmp_path) -> None:
    client, engine = await _client(tmp_path)
    try:
        response = await client.get("/api/settings")

        assert response.status_code == 200
        payload: dict[str, Any] = response.json()
        pages = payload["pages"]
        page_ids = {page["id"] for page in pages}
        assert {
            "models",
            "integrations",
            "sandboxes",
            "environments",
            "variables",
            "secrets",
            "run-defaults",
            "server",
            "security",
            "storage",
            "monitoring",
            "live-events",
        } <= page_ids
        for page in pages:
            assert page["title"]
            assert page["description"]
            for group in page["groups"]:
                assert group["title"]
                for row in group["rows"]:
                    assert row["editability"] in {
                        "editable",
                        "restart-required",
                        "read-only",
                        "reserved",
                    }
                    assert {"label", "description", "value", "editability"} <= set(row)
    finally:
        await client.aclose()
        await engine.dispose()
