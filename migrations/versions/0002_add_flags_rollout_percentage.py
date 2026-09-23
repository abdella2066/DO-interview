"""add flags.rollout_percentage

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23 10:51:39.757941
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "flags",
        sa.Column(
            "rollout_percentage", sa.Integer(), server_default=sa.text("100"), nullable=False
        ),
    )
    op.create_check_constraint(
        "flags_rollout_percentage_check",
        "flags",
        "rollout_percentage >= 0 AND rollout_percentage <= 100",
    )


def downgrade() -> None:
    op.drop_constraint("flags_rollout_percentage_check", "flags", type_="check")
    op.drop_column("flags", "rollout_percentage")
