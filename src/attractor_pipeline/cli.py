"""CLI entry point for Attractor pipeline runner.

Usage:
    attractor run release-checks --repo /repo --server-url http://127.0.0.1:8080
    attractor run --legacy-local pipeline.dot --provider openai
    attractor validate pipeline.dot
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

from attractor_llm.catalog import get_default_model
from attractor_pipeline.validation import Severity, validate


def _console_event_printer(event: Any) -> None:
    """Print pipeline events to stdout for --verbose mode."""
    description = getattr(event, "description", str(event))
    print(f"  [event] {description}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="attractor",
        description="DOT-based pipeline runner for multi-stage AI workflows",
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- run command ---
    run_parser = subparsers.add_parser("run", help="Launch a platform workflow run")
    run_parser.add_argument(
        "workflow",
        nargs="?",
        type=str,
        help="Workflow name to launch on the platform",
    )
    run_parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Local repository path for the platform run",
    )
    run_parser.add_argument(
        "--server-url",
        type=str,
        default=None,
        help="Platform server URL. Defaults to ATTRACTOR_PLATFORM_URL.",
    )
    run_parser.add_argument(
        "--input",
        action="append",
        default=[],
        help="Workflow input as key=value. May be provided more than once.",
    )
    run_parser.add_argument(
        "--environment",
        type=str,
        default="",
        help="Requested platform execution environment",
    )
    run_parser.add_argument(
        "--actor-label",
        type=str,
        default="",
        help="Actor label recorded on the durable run",
    )
    run_parser.add_argument(
        "--legacy-local",
        type=str,
        default=None,
        metavar="DOTFILE",
        help="Run a DOT file with the legacy local runner",
    )
    run_parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="LLM provider (anthropic, openai, gemini). Auto-detected from model.",
    )
    run_parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="LLM model ID. Default: claude-sonnet-5",
    )
    run_parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate the DOT file without executing",
    )
    run_parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Use DirectLLMBackend (no agent tools)",
    )
    run_parser.add_argument(
        "--logs-dir",
        type=str,
        default=None,
        help="Directory for logs and checkpoints",
    )
    run_parser.add_argument(
        "--docker",
        action="store_true",
        help="Run agent tools inside a Docker container (sandboxed)",
    )
    run_parser.add_argument(
        "--docker-image",
        type=str,
        default="python:3.12-slim",
        help="Docker image to use (default: python:3.12-slim)",
    )
    run_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show real-time pipeline events during execution",
    )

    # --- validate command ---
    val_parser = subparsers.add_parser("validate", help="Validate a DOT pipeline file")
    val_parser.add_argument("dotfile", type=str, help="Path to the DOT pipeline file")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    if args.command == "validate":
        _cmd_validate(args.dotfile)
    elif args.command == "run":
        if args.legacy_local:
            args.dotfile = args.legacy_local
            if args.validate_only:
                _cmd_validate(args.dotfile)
            else:
                asyncio.run(_cmd_run(args))
        else:
            _cmd_platform_run(args, parser)


def _cmd_platform_run(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Launch a durable platform run through the HTTP API."""
    from attractor_cli.platform import launch_platform_run

    if args.validate_only:
        parser.error("run --validate-only requires --legacy-local")
    if not args.workflow:
        parser.error("run requires a workflow name or --legacy-local DOTFILE")
    if not args.repo:
        parser.error("run requires --repo for platform launches")
    server_url = args.server_url or os.environ.get("ATTRACTOR_PLATFORM_URL", "")
    if not server_url:
        parser.error(
            "run requires --server-url or ATTRACTOR_PLATFORM_URL for platform launches"
        )

    try:
        exit_code = launch_platform_run(
            workflow_name=args.workflow,
            repo_path=args.repo,
            server_url=server_url,
            inputs=args.input,
            actor_label=args.actor_label,
            requested_environment=args.environment,
        )
    except ValueError as exc:
        print(f"Error: {exc}")
        sys.exit(1)
    if exit_code:
        sys.exit(exit_code)


def _cmd_validate(dotfile: str) -> None:
    """Validate a DOT file and print diagnostics."""
    from attractor_pipeline.parser import parse_dot
    from attractor_pipeline.parser.parser import ParseError

    path = Path(dotfile)
    if not path.exists():
        print(f"Error: File not found: {dotfile}")
        sys.exit(1)

    source = path.read_text(encoding="utf-8")

    # Parse
    try:
        graph = parse_dot(source)
    except ParseError as e:
        print(f"Parse error: {e}")
        sys.exit(1)

    print(f"Parsed: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    if graph.goal:
        print(f"Goal: {graph.goal}")

    # Validate
    diagnostics = validate(graph)

    if not diagnostics:
        print("Validation: PASS (no issues)")
        return

    errors = 0
    warnings = 0
    for d in diagnostics:
        icon = {"error": "E", "warning": "W", "info": "I"}[d.severity]
        loc = f" (node: {d.node_id})" if d.node_id else ""
        print(f"  [{icon}] {d.rule}: {d.message}{loc}")
        if d.severity == Severity.ERROR:
            errors += 1
        elif d.severity == Severity.WARNING:
            warnings += 1

    print(
        f"\nValidation: {errors} error(s), {warnings} warning(s), "
        f"{len(diagnostics) - errors - warnings} info"
    )

    if errors > 0:
        print("FAIL: Fix errors before running this pipeline.")
        sys.exit(1)


async def _cmd_run(args: argparse.Namespace) -> None:
    """Execute a DOT pipeline."""
    from attractor_llm.client import Client
    from attractor_pipeline import (
        HandlerRegistry,
        PipelineStatus,
        parse_dot,
        register_default_handlers,
        run_pipeline,
    )
    from attractor_pipeline.backends import AgentLoopBackend, DirectLLMBackend
    from attractor_pipeline.parser.parser import ParseError
    from attractor_pipeline.validation import validate_or_raise

    dotfile = args.dotfile
    path = Path(dotfile)
    if not path.exists():
        print(f"Error: File not found: {dotfile}")
        sys.exit(1)

    source = path.read_text(encoding="utf-8")

    # Parse
    try:
        graph = parse_dot(source)
    except ParseError as e:
        print(f"Parse error: {e}")
        sys.exit(1)

    # Validate
    try:
        validate_or_raise(graph)
    except ValueError as e:
        print(str(e))
        sys.exit(1)

    print(f"Pipeline: {graph.name}")
    print(f"Goal: {graph.goal or '(none)'}")
    print(f"Nodes: {len(graph.nodes)}, Edges: {len(graph.edges)}")
    print()

    # Resolve provider and model
    model = args.model or get_default_model("anthropic").id
    provider = args.provider

    # Auto-detect provider from model name
    if provider is None:
        if model.startswith("claude"):
            provider = "anthropic"
        elif model.startswith(("gpt", "o1", "o3", "o4")):
            provider = "openai"
        elif model.startswith("gemini"):
            provider = "gemini"
        else:
            print(
                f"Warning: Could not auto-detect provider from model '{model}'. "
                f"Defaulting to anthropic. Use --provider to specify explicitly."
            )
            provider = "anthropic"

    # Get API key
    key_env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }
    env_var = key_env_map.get(provider, "ANTHROPIC_API_KEY")
    api_key = os.environ.get(env_var)
    if not api_key:
        print(f"Error: Set {env_var} environment variable")
        sys.exit(1)

    # Set up LLM client — register ALL available providers so per-node
    # llm_provider= overrides work without needing multiple CLI invocations.
    client = Client()
    all_providers = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GOOGLE_API_KEY",
    }
    registered = []
    for p, env in all_providers.items():
        key = os.environ.get(env)
        if key:
            client.register_adapter(p, _create_adapter(p, key))
            registered.append(p)
    # If the selected provider wasn't auto-detected above (e.g. custom key),
    # ensure it's registered using the key we already validated.
    if provider not in registered:
        client.register_adapter(provider, _create_adapter(provider, api_key))
        registered.append(provider)
    print(f"Provider: {provider} ({model})")

    # Set up execution environment
    docker_env = None
    if getattr(args, "docker", False):
        from attractor_agent.environment import DockerEnvironment
        from attractor_agent.tools.core import set_allowed_roots, set_environment

        docker_image = getattr(args, "docker_image", "python:3.12-slim")
        docker_env = DockerEnvironment(image=docker_image)
        print(f"Environment: Docker ({docker_image})")
        print("Starting container...")
        await docker_env.start()
        set_environment(docker_env)
        # Set allowed roots to the container workspace so path
        # confinement doesn't block container paths
        set_allowed_roots([docker_env._workspace, "/tmp"])
        print(f"Container: {docker_env.container_id}")
    else:
        print("Environment: Local")

    # Set up backend
    if args.no_tools:
        backend = DirectLLMBackend(
            client,
            default_model=model,
            default_provider=provider,
        )
        print("Backend: DirectLLM (no tools)")
    else:
        backend = AgentLoopBackend(
            client,
            default_model=model,
            default_provider=provider,
        )
        print("Backend: AgentLoop (with tools)")

    # Set up handlers
    registry = HandlerRegistry()
    register_default_handlers(registry, codergen_backend=backend)

    # Set up logs directory
    logs_root = None
    if args.logs_dir:
        logs_root = Path(args.logs_dir)
        logs_root.mkdir(parents=True, exist_ok=True)

    # Execute
    print()
    print("Executing pipeline...")
    print("-" * 40)
    start_time = time.monotonic()

    on_event = _console_event_printer if getattr(args, "verbose", False) else None

    async with client:
        result = await run_pipeline(
            graph,
            registry,
            logs_root=logs_root,
            on_event=on_event,
        )

    duration = time.monotonic() - start_time

    # Report results
    print("-" * 40)
    print()
    print(f"Status: {result.status}")
    print(f"Duration: {duration:.1f}s")
    print(f"Nodes: {' -> '.join(result.completed_nodes)}")

    if result.error:
        print(f"Error: {result.error}")

    # Print codergen outputs
    print()
    for key, value in result.context.items():
        if key.startswith("codergen.") and key.endswith(".output"):
            node_id = key.split(".")[1]
            print(f"--- {node_id} output ---")
            print(str(value)[:2000])
            print()

    # Clean up Docker container if used
    if docker_env:
        print("Stopping Docker container...")
        await docker_env.stop()
        from attractor_agent.environment import LocalEnvironment
        from attractor_agent.tools.core import set_environment

        set_environment(LocalEnvironment())
        print("Container stopped.")

    if result.status == PipelineStatus.COMPLETED:
        print("Pipeline completed successfully.")
    else:
        sys.exit(1)


def _create_adapter(provider: str, api_key: str) -> Any:
    """Create the appropriate provider adapter."""
    from attractor_llm.adapters.base import ProviderConfig

    config = ProviderConfig(api_key=api_key, timeout=120.0)

    if provider == "anthropic":
        from attractor_llm.adapters.anthropic import AnthropicAdapter

        return AnthropicAdapter(config)
    elif provider == "openai":
        from attractor_llm.adapters.openai import OpenAIAdapter

        return OpenAIAdapter(config)
    elif provider == "gemini":
        from attractor_llm.adapters.gemini import GeminiAdapter

        return GeminiAdapter(config)
    else:
        print(f"Unknown provider: {provider}")
        sys.exit(1)


if __name__ == "__main__":
    main()
