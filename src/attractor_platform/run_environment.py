from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from attractor_agent.environment import DockerEnvironment, ExecutionEnvironment, LocalEnvironment
from attractor_agent.tools.core import (
    reset_allowed_roots,
    reset_environment,
    set_allowed_roots,
    set_environment,
    set_non_local_allowed_roots,
)
from attractor_platform.git import PreparedWorktree
from attractor_platform.runspec import RunEnvironmentRequest

DEFAULT_DOCKER_IMAGE = "python:3.12-slim"


class RunEnvironment(Protocol):
    def activate(self) -> AbstractAsyncContextManager[ExecutionEnvironment]:
        ...


class WorktreeLocalRunEnvironment:
    def __init__(self, prepared: PreparedWorktree) -> None:
        self._prepared = prepared

    @asynccontextmanager
    async def activate(self) -> AsyncIterator[ExecutionEnvironment]:
        env = LocalEnvironment(working_dir=str(self._prepared.path))
        environment_token = set_environment(env)
        roots_token = set_allowed_roots([self._prepared.path])
        try:
            await env.start()
            yield env
        finally:
            try:
                await env.stop()
            finally:
                reset_allowed_roots(roots_token)
                reset_environment(environment_token)


class _MountedDockerEnvironment(DockerEnvironment):
    def __init__(
        self,
        *,
        image: str,
        host_workspace: str,
        workspace: str,
    ) -> None:
        super().__init__(image=image, workspace=workspace)
        self._host_workspace = host_workspace

    async def start(self) -> None:
        if self._container_id:
            return

        cmd = [
            "docker",
            "run",
            "-d",
            "--rm",
            "-w",
            self._workspace,
            "--mount",
            f"type=bind,source={self._host_workspace},target={self._workspace}",
        ]
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        if self._name:
            cmd.extend(["--name", self._name])
        cmd.extend([self._image, "sleep", "infinity"])

        result = await self._run_host_command(cmd)
        if result.returncode != 0:
            raise RuntimeError(f"Failed to start Docker container: {result.stderr.strip()}")
        self._container_id = result.stdout.strip()[:12]


class DockerRunEnvironment:
    def __init__(
        self,
        prepared: PreparedWorktree | str | None = None,
        image: str = DEFAULT_DOCKER_IMAGE,
        workspace: str = "/workspace",
    ) -> None:
        if isinstance(prepared, str):
            image = prepared
            prepared = None
        self._prepared = prepared
        self._image = image
        self._workspace = workspace

    @asynccontextmanager
    async def activate(self) -> AsyncIterator[ExecutionEnvironment]:
        if self._prepared is None:
            env = DockerEnvironment(image=self._image, workspace=self._workspace)
        else:
            env = _MountedDockerEnvironment(
                image=self._image,
                host_workspace=str(self._prepared.path),
                workspace=self._workspace,
            )
        environment_token = set_environment(env)
        roots_token = set_non_local_allowed_roots([self._workspace, "/tmp"])
        try:
            await env.start()
            yield env
        finally:
            try:
                await env.stop()
            finally:
                reset_allowed_roots(roots_token)
                reset_environment(environment_token)


def select_run_environment(
    request: RunEnvironmentRequest,
    prepared_worktree: PreparedWorktree | None,
) -> RunEnvironment:
    if request.mode == "local":
        if prepared_worktree is None:
            raise ValueError("local run environments require a prepared worktree")
        return WorktreeLocalRunEnvironment(prepared_worktree)
    if request.mode == "docker":
        effective = materialize_run_environment_request(request)
        return DockerRunEnvironment(
            prepared_worktree,
            image=effective.image,
        )
    raise ValueError("remote run environments are not implemented in Phase 2")


def materialize_run_environment_request(
    request: RunEnvironmentRequest,
) -> RunEnvironmentRequest:
    if request.mode != "docker" or request.image:
        return request
    return request.model_copy(update={"image": DEFAULT_DOCKER_IMAGE})
