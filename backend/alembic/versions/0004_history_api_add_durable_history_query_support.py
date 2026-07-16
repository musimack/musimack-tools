"""add durable history query support

Revision ID: 0004_history_api
Revises: 0003_artifact_storage
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_history_api"
down_revision = "0003_artifact_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("jobs") as batch:
        batch.add_column(sa.Column("submitted_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("terminal_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_jobs_run", ["run_id", "created_sequence"])
        batch.create_index("ix_jobs_submitted", ["submitted_at", "job_id"])
        batch.create_index("ix_jobs_terminal_at", ["terminal_at", "job_id"])
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("terminal_at", sa.DateTime(timezone=True)))
        batch.create_index("ix_runs_seed", ["normalized_seed_url"])
        batch.create_index("ix_runs_started", ["started_at", "run_id"])
        batch.create_index("ix_runs_terminal", ["terminal_at", "run_id"])
    with op.batch_alter_table("run_stages") as batch:
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("terminal_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("warnings") as batch:
        batch.add_column(sa.Column("occurred_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("failures") as batch:
        batch.add_column(sa.Column("occurred_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    with op.batch_alter_table("failures") as batch:
        batch.drop_column("occurred_at")
    with op.batch_alter_table("warnings") as batch:
        batch.drop_column("occurred_at")
    with op.batch_alter_table("run_stages") as batch:
        batch.drop_column("terminal_at")
        batch.drop_column("started_at")
    with op.batch_alter_table("runs") as batch:
        batch.drop_index("ix_runs_terminal")
        batch.drop_index("ix_runs_started")
        batch.drop_index("ix_runs_seed")
        batch.drop_column("terminal_at")
        batch.drop_column("started_at")
    with op.batch_alter_table("jobs") as batch:
        batch.drop_index("ix_jobs_terminal_at")
        batch.drop_index("ix_jobs_submitted")
        batch.drop_index("ix_jobs_run")
        batch.drop_column("terminal_at")
        batch.drop_column("started_at")
        batch.drop_column("submitted_at")
