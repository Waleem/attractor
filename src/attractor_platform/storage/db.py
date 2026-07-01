from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def default_database_url(database_path: str | os.PathLike[str] | None = None) -> str:
    path = Path(database_path) if database_path is not None else Path(".attractor-platform.sqlite3")
    return f"sqlite+aiosqlite:///{path.expanduser().resolve()}"


def default_test_database_url(database_path: str | os.PathLike[str] | None = None) -> str:
    path = (
        Path(database_path)
        if database_path is not None
        else Path(tempfile.gettempdir()) / f"attractor-platform-tests-{os.getpid()}.sqlite3"
    )
    return default_database_url(path)


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = field(default_factory=default_database_url)
    echo: bool = False

    @classmethod
    def from_env(cls, env_var: str = "ATTRACTOR_DATABASE_URL") -> DatabaseSettings:
        return cls(url=os.environ.get(env_var) or default_database_url())


def create_platform_engine(settings: DatabaseSettings) -> AsyncEngine:
    return create_async_engine(settings.url, echo=settings.echo, pool_pre_ping=True)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        async with session.begin():
            yield session
