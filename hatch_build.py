from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import (  # type: ignore[import-not-found]
    BuildHookInterface,
)

SPA_DIST_SOURCE = "web/dist"
BUNDLED_SPA_DIST_TARGET = "attractor_server/web/dist"


class BuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        spa_dist = Path(self.root, SPA_DIST_SOURCE)
        if not spa_dist.is_dir() or not (spa_dist / "index.html").is_file():
            return

        build_data.setdefault("force_include", {})[SPA_DIST_SOURCE] = BUNDLED_SPA_DIST_TARGET


def get_build_hook() -> type[BuildHook]:
    return BuildHook
