from __future__ import annotations


def test_phase2_modules_are_importable() -> None:
    import attractor_platform.artifacts
    import attractor_platform.checkpoints
    import attractor_platform.executor
    import attractor_platform.git
    import attractor_platform.redaction
    import attractor_platform.run_environment
    import attractor_platform.storage.db
    import attractor_platform.storage.models
    import attractor_platform.storage.repositories
    import attractor_server.platform_app
    import attractor_server.platform_sse
