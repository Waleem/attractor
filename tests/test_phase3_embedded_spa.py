from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from starlette.testclient import TestClient

from attractor_server import __main__ as server_main
from attractor_server.platform_app import create_platform_app


class _Executor:
    repository = None
    active_tasks: dict[str, object] = {}


def test_platform_app_serves_embedded_spa_without_intercepting_api(
    tmp_path: Path,
) -> None:
    spa_dist = tmp_path / "web" / "dist"
    assets_dir = spa_dist / "assets"
    assets_dir.mkdir(parents=True)
    (spa_dist / "index.html").write_text(
        '<div id="root">Attractor Console</div><script src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text(
        'document.querySelector("#root").dataset.loaded = "true";',
        encoding="utf-8",
    )

    app = create_platform_app(
        session_factory=cast(Any, None),
        executor=cast(Any, _Executor()),
        spa_dist=spa_dist,
    )

    with TestClient(app) as client:
        root = client.get("/")
        client_route = client.get("/runs/abc")
        asset = client.get("/assets/app.js")
        health = client.get("/api/system/health")
        unknown_api = client.get("/api/unknown")

    assert root.status_code == 200
    assert root.text == (
        '<div id="root">Attractor Console</div><script src="/assets/app.js"></script>'
    )
    assert client_route.status_code == 200
    assert client_route.text == root.text
    assert asset.status_code == 200
    assert "dataset.loaded" in asset.text
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert unknown_api.status_code == 404
    assert "Attractor Console" not in unknown_api.text


def test_platform_spa_dist_resolver_prefers_explicit_path_then_environment(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    explicit_dist = tmp_path / "explicit"
    explicit_dist.mkdir()
    env_dist = tmp_path / "env"
    env_dist.mkdir()
    monkeypatch.setenv("ATTRACTOR_SPA_DIST", str(env_dist))

    assert server_main._resolve_platform_spa_dist(str(explicit_dist)) == explicit_dist.resolve()
    assert server_main._resolve_platform_spa_dist(None) == env_dist.resolve()
