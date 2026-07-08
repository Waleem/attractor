from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from attractor_platform.storage.models import Base


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


async def initialize_platform_schema(engine: AsyncEngine) -> None:
    """Create SQLite platform tables on startup.

    SQLite is the local first-run path, so the platform can safely create its
    own tables before serving requests. Postgres remains Alembic-managed; this
    helper intentionally avoids mutating non-SQLite schemas.
    """

    if engine.url.get_backend_name() != "sqlite":
        return

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
        await _ensure_sqlite_run_records_preserve_unregistered_history(connection)


async def _ensure_sqlite_run_records_preserve_unregistered_history(
    connection: AsyncConnection,
) -> None:
    columns = list(await connection.execute(text("PRAGMA table_info(run_records)")))
    if not columns:
        return
    column_nullability = {row[1]: bool(row[3]) for row in columns}
    foreign_keys = list(await connection.execute(text("PRAGMA foreign_key_list(run_records)")))
    on_delete_by_column = {row[3]: str(row[6]).upper() for row in foreign_keys}
    if (
        column_nullability.get("repo_id") is False
        and column_nullability.get("workflow_id") is False
        and on_delete_by_column.get("repo_id") == "SET NULL"
        and on_delete_by_column.get("workflow_id") == "SET NULL"
    ):
        return

    await connection.execute(text("PRAGMA foreign_keys=OFF"))
    await connection.execute(text("DROP TABLE IF EXISTS run_records_new"))
    await connection.execute(
        text(
            """
            CREATE TABLE run_records_new (
                id VARCHAR(64) NOT NULL,
                repo_id VARCHAR(64),
                workflow_id VARCHAR(64),
                status VARCHAR(40) NOT NULL,
                run_spec JSON NOT NULL,
                actor_label VARCHAR(200) NOT NULL,
                source_commit VARCHAR(40) NOT NULL,
                source_branch VARCHAR(200) NOT NULL,
                worktree_path TEXT,
                managed_branch VARCHAR(300),
                error_category VARCHAR(100),
                error_message TEXT,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL,
                started_at DATETIME,
                completed_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(repo_id) REFERENCES registered_repos (id) ON DELETE SET NULL,
                FOREIGN KEY(workflow_id) REFERENCES workflow_packages (id) ON DELETE SET NULL
            )
            """
        )
    )
    await connection.execute(
        text(
            """
            INSERT INTO run_records_new (
                id,
                repo_id,
                workflow_id,
                status,
                run_spec,
                actor_label,
                source_commit,
                source_branch,
                worktree_path,
                managed_branch,
                error_category,
                error_message,
                created_at,
                updated_at,
                started_at,
                completed_at
            )
            SELECT
                id,
                repo_id,
                workflow_id,
                status,
                run_spec,
                actor_label,
                source_commit,
                source_branch,
                worktree_path,
                managed_branch,
                error_category,
                error_message,
                created_at,
                updated_at,
                started_at,
                completed_at
            FROM run_records
            """
        )
    )
    await connection.execute(text("DROP TABLE run_records"))
    await connection.execute(text("ALTER TABLE run_records_new RENAME TO run_records"))
    await connection.execute(
        text("CREATE INDEX IF NOT EXISTS ix_run_records_status ON run_records (status)")
    )
    await connection.execute(text("PRAGMA foreign_keys=ON"))


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with factory() as session:
        async with session.begin():
            yield session
