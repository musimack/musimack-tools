"""retain durable result projections

Revision ID: 0014_durable_result_projection
Revises: 0013_website_migration_qa
"""

# ruff: noqa: TC003

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_durable_result_projection"
down_revision: str | Sequence[str] | None = "0013_website_migration_qa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("result_projection_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("runs", "result_projection_json")
