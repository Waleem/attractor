from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_unregister_preserves_runs"
down_revision: str | None = "0002_phase3_settings_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _recreate_sqlite_run_records(
            repo_nullable=True,
            workflow_nullable=True,
            on_delete="SET NULL",
        )
        return

    op.drop_constraint("run_records_repo_id_fkey", "run_records", type_="foreignkey")
    op.drop_constraint("run_records_workflow_id_fkey", "run_records", type_="foreignkey")
    op.alter_column("run_records", "repo_id", existing_type=sa.String(length=64), nullable=True)
    op.alter_column(
        "run_records",
        "workflow_id",
        existing_type=sa.String(length=64),
        nullable=True,
    )
    op.create_foreign_key(
        "run_records_repo_id_fkey",
        "run_records",
        "registered_repos",
        ["repo_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "run_records_workflow_id_fkey",
        "run_records",
        "workflow_packages",
        ["workflow_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        _recreate_sqlite_run_records(
            repo_nullable=False,
            workflow_nullable=False,
            on_delete="RESTRICT",
        )
        return

    op.drop_constraint("run_records_repo_id_fkey", "run_records", type_="foreignkey")
    op.drop_constraint("run_records_workflow_id_fkey", "run_records", type_="foreignkey")
    op.alter_column("run_records", "repo_id", existing_type=sa.String(length=64), nullable=False)
    op.alter_column(
        "run_records",
        "workflow_id",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.create_foreign_key(
        "run_records_repo_id_fkey",
        "run_records",
        "registered_repos",
        ["repo_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "run_records_workflow_id_fkey",
        "run_records",
        "workflow_packages",
        ["workflow_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def _recreate_sqlite_run_records(
    *,
    repo_nullable: bool,
    workflow_nullable: bool,
    on_delete: str,
) -> None:
    repo_null = "" if repo_nullable else " NOT NULL"
    workflow_null = "" if workflow_nullable else " NOT NULL"
    op.execute("PRAGMA foreign_keys=OFF")
    op.execute("DROP TABLE IF EXISTS run_records_new")
    op.execute(
        f"""
        CREATE TABLE run_records_new (
            id VARCHAR(64) NOT NULL,
            repo_id VARCHAR(64){repo_null},
            workflow_id VARCHAR(64){workflow_null},
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
            FOREIGN KEY(repo_id) REFERENCES registered_repos (id) ON DELETE {on_delete},
            FOREIGN KEY(workflow_id) REFERENCES workflow_packages (id) ON DELETE {on_delete}
        )
        """
    )
    op.execute(
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
    op.execute("DROP TABLE run_records")
    op.execute("ALTER TABLE run_records_new RENAME TO run_records")
    op.execute("CREATE INDEX IF NOT EXISTS ix_run_records_status ON run_records (status)")
    op.execute("PRAGMA foreign_keys=ON")
