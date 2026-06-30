from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

from attractor_agent.environment import DockerEnvironment, ExecutionEnvironment, LocalEnvironment
from attractor_agent.tools.core import (
    reset_allowed_roots,
    reset_environment,
    set_allowed_roots,
    set_environment,
)
from attractor_platform.git import PreparedWorktree


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


class DockerRunEnvironment:
    def __init__(self, image: str, workspace: str = "/workspace") -> None:
        self._image = image
        self._workspace = workspace

    @asynccontextmanager
    async def activate(self) -> AsyncIterator[ExecutionEnvironment]:
        env = DockerEnvironment(image=self._image, workspace=self._workspace)
        environment_token = set_environment(env)
        roots_token = set_allowed_roots([self._workspace, "/tmp"])
        try:
            await env.start()
            yield env
        finally:
            try:
                await env.stop()
            finally:
                reset_allowed_roots(roots_token)
                reset_environment(environment_token)
