from __future__ import annotations

import importlib

PHASE2_MODULES = [
    "attractor_platform.artifacts",
    "attractor_platform.checkpoints",
    "attractor_platform.executor",
    "attractor_platform.git",
    "attractor_platform.redaction",
    "attractor_platform.run_environment",
    "attractor_platform.storage.db",
    "attractor_platform.storage.models",
    "attractor_platform.storage.repositories",
    "attractor_server.platform_app",
    "attractor_server.platform_sse",
]


def test_phase2_modules_are_importable() -> None:
    for module_name in PHASE2_MODULES:
        assert importlib.import_module(module_name)
