"""Entry point for running the Attractor HTTP server.

Usage:
    uv run python -m attractor_server
    uv run python -m attractor_server --port 8080
    uv run python -m attractor_server --host 0.0.0.0 --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import os
from importlib import resources
from pathlib import Path

import uvicorn

from attractor_server.app import create_app
from attractor_server.pipeline_manager import PipelineManager


def _existing_spa_dist(path: Path) -> Path | None:
    resolved = path.expanduser().resolve()
    if resolved.is_dir() and (resolved / "index.html").is_file():
        return resolved
    return None


def _configured_spa_dist(path: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Configured SPA dist directory does not exist: {resolved}")
    if not resolved.is_dir():
        raise FileNotFoundError(f"Configured SPA dist path is not a directory: {resolved}")
    if not (resolved / "index.html").is_file():
        raise FileNotFoundError(f"SPA dist directory must contain index.html: {resolved}")
    return resolved


def _resolve_platform_spa_dist(explicit_spa_dist: str | None) -> Path | None:
    if explicit_spa_dist:
        return _configured_spa_dist(explicit_spa_dist)

    env_spa_dist = os.environ.get("ATTRACTOR_SPA_DIST", "").strip()
    if env_spa_dist:
        return _configured_spa_dist(env_spa_dist)

    try:
        packaged_dist = resources.files("attractor_server").joinpath("web", "dist")
    except (AttributeError, ModuleNotFoundError):
        packaged_dist = None
    if packaged_dist is not None and packaged_dist.is_dir():
        packaged_path = Path(str(packaged_dist))
        existing_packaged_dist = _existing_spa_dist(packaged_path)
        if existing_packaged_dist is not None:
            return existing_packaged_dist

    dev_dist = Path.cwd() / "web" / "dist"
    return _existing_spa_dist(dev_dist)


def main() -> None:
    parser = argparse.ArgumentParser(description="Attractor HTTP Server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=5,
        help="Max concurrent pipelines",
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Default LLM provider (anthropic, openai, gemini)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Default LLM model",
    )
    parser.add_argument(
        "--platform",
        action="store_true",
        help="Run the Phase 2 operations platform API instead of the legacy pipeline API",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("ATTRACTOR_DATABASE_URL"),
        help="Platform database URL (defaults to ATTRACTOR_DATABASE_URL or local SQLite)",
    )
    parser.add_argument(
        "--worktree-root",
        default=os.environ.get("ATTRACTOR_WORKTREE_ROOT", ".attractor-worktrees"),
        help="Platform managed worktree root",
    )
    parser.add_argument(
        "--artifact-root",
        default=os.environ.get("ATTRACTOR_ARTIFACT_ROOT", ".attractor-artifacts"),
        help="Platform artifact root",
    )
    parser.add_argument(
        "--spa-dist",
        default=None,
        help=(
            "Platform SPA dist directory "
            "(defaults to ATTRACTOR_SPA_DIST, bundled web/dist, or local web/dist)"
        ),
    )
    args = parser.parse_args()

    if args.platform:
        from attractor_platform.executor import DurableRunExecutor
        from attractor_platform.llm_backend import build_platform_codergen_backend
        from attractor_platform.secrets import SecretVault, load_provider_secret_values
        from attractor_platform.storage.db import (
            DatabaseSettings,
            create_platform_engine,
            create_session_factory,
            initialize_platform_schema,
        )
        from attractor_server.platform_app import create_platform_app

        engine = create_platform_engine(
            DatabaseSettings(url=args.database_url)
            if args.database_url
            else DatabaseSettings.from_env()
        )
        session_factory = create_session_factory(engine)
        secret_vault = SecretVault()

        async def load_provider_api_keys() -> dict[str, str]:
            await initialize_platform_schema(engine)
            return await load_provider_secret_values(
                session_factory=session_factory,
                secret_vault=secret_vault,
                provider_names=("anthropic", "openai", "gemini"),
            )

        runtime_default_provider = (
            args.provider or os.environ.get("ATTRACTOR_DEFAULT_PROVIDER", "").strip() or None
        )
        runtime_default_model = (
            args.model or os.environ.get("ATTRACTOR_DEFAULT_MODEL", "").strip() or None
        )
        codergen_backend = build_platform_codergen_backend(
            default_provider=runtime_default_provider,
            default_model=runtime_default_model,
            provider_api_keys=asyncio.run(load_provider_api_keys()),
        )
        executor = DurableRunExecutor(
            session_factory=session_factory,
            worktree_root=Path(args.worktree_root),
            artifact_root=Path(args.artifact_root),
            codergen_backend=codergen_backend,
        )
        app = create_platform_app(
            session_factory=session_factory,
            executor=executor,
            engine=engine,
            default_provider=runtime_default_provider,
            default_model=runtime_default_model,
            spa_dist=_resolve_platform_spa_dist(args.spa_dist),
        )

        print(f"Attractor platform server starting on http://{args.host}:{args.port}")
        print()
        print("Endpoints:")
        print(f"  POST http://{args.host}:{args.port}/api/repos")
        print(f"  GET  http://{args.host}:{args.port}/api/repos")
        print(f"  POST http://{args.host}:{args.port}/api/runs")
        print(f"  GET  http://{args.host}:{args.port}/api/runs")
        print(f"  GET  http://{args.host}:{args.port}/api/system/health")
        print()

        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return

    # Create manager with configured handlers
    manager = PipelineManager(max_concurrent=args.max_concurrent)

    # Register default handlers (with optional LLM backend)
    from attractor_pipeline import HandlerRegistry, register_default_handlers

    registry = HandlerRegistry()

    # If provider credentials are available, set up a real LLM backend
    provider = args.provider
    model = args.model

    if provider or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"):
        try:
            from attractor_llm.client import Client
            from attractor_pipeline.backends import DirectLLMBackend

            client = Client()

            # Register available adapters
            if os.environ.get("ANTHROPIC_API_KEY"):
                from attractor_llm.adapters.anthropic import AnthropicAdapter
                from attractor_llm.adapters.base import ProviderConfig

                client.register_adapter(
                    "anthropic",
                    AnthropicAdapter(
                        ProviderConfig(
                            api_key=os.environ["ANTHROPIC_API_KEY"],
                            timeout=120.0,
                        )
                    ),
                )
                if not provider:
                    provider = "anthropic"
                    model = model or "claude-sonnet-4-5"

            if os.environ.get("OPENAI_API_KEY"):
                from attractor_llm.adapters.base import ProviderConfig
                from attractor_llm.adapters.openai import OpenAIAdapter

                client.register_adapter(
                    "openai",
                    OpenAIAdapter(
                        ProviderConfig(
                            api_key=os.environ["OPENAI_API_KEY"],
                            timeout=120.0,
                        )
                    ),
                )
                if not provider:
                    provider = "openai"
                    model = model or "gpt-4.1-mini"

            backend = DirectLLMBackend(
                client,
                default_model=model or "claude-sonnet-4-5",
                default_provider=provider,
            )
            register_default_handlers(registry, codergen_backend=backend)
            print(f"LLM backend: {provider}/{model}")
        except Exception as e:  # noqa: BLE001
            print(f"Warning: Failed to set up LLM backend: {e}")
            register_default_handlers(registry)
    else:
        register_default_handlers(registry)
        print("No LLM backend configured (dry run mode)")

    manager.set_handlers(registry)

    app = create_app(manager)

    print(f"Attractor server starting on http://{args.host}:{args.port}")
    print(f"Max concurrent pipelines: {args.max_concurrent}")
    print()
    print("Endpoints:")
    print(f"  POST http://{args.host}:{args.port}/pipelines")
    print(f"  GET  http://{args.host}:{args.port}/pipelines/{{id}}")
    print(f"  GET  http://{args.host}:{args.port}/pipelines/{{id}}/events")
    print(f"  POST http://{args.host}:{args.port}/pipelines/{{id}}/cancel")
    print()

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
