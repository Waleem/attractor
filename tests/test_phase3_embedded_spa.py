from __future__ import annotations

import importlib.util
import sys
import tomllib
import types
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


def _load_hatch_build_hook(monkeypatch: Any) -> Any:
    class _BuildHookInterface:
        def __init__(
            self,
            root: str,
            config: dict[str, Any] | None = None,
            *args: Any,
            **kwargs: Any,
        ) -> None:
            self.root = root
            self.config = config or {}

    module_names = [
        "hatchling",
        "hatchling.builders",
        "hatchling.builders.hooks",
        "hatchling.builders.hooks.plugin",
        "hatchling.builders.hooks.plugin.interface",
    ]
    for module_name in module_names:
        monkeypatch.setitem(sys.modules, module_name, types.ModuleType(module_name))

    interface_module = sys.modules["hatchling.builders.hooks.plugin.interface"]
    interface_module.BuildHookInterface = _BuildHookInterface

    hook_path = Path(__file__).resolve().parents[1] / "hatch_build.py"
    spec = importlib.util.spec_from_file_location("attractor_test_hatch_build", hook_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wheel_build_config_uses_conditional_spa_bundle_hook() -> None:
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    wheel_config = pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]

    assert wheel_config["hooks"]["custom"]["path"] == "hatch_build.py"


def test_wheel_build_hook_bundles_platform_spa_dist_when_present(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    hook_module = _load_hatch_build_hook(monkeypatch)
    spa_dist = tmp_path / "web" / "dist"
    spa_dist.mkdir(parents=True)
    (spa_dist / "index.html").write_text("<div>Attractor Console</div>", encoding="utf-8")
    build_data: dict[str, Any] = {"force_include": {}}

    hook = hook_module.BuildHook(str(tmp_path), {})
    hook.initialize("standard", build_data)

    assert build_data["force_include"]["web/dist"] == "src/attractor_server/web/dist"


def test_wheel_build_hook_skips_platform_spa_dist_when_missing(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    hook_module = _load_hatch_build_hook(monkeypatch)
    build_data: dict[str, Any] = {"force_include": {}}

    hook = hook_module.BuildHook(str(tmp_path), {})
    hook.initialize("standard", build_data)

    assert build_data["force_include"] == {}
