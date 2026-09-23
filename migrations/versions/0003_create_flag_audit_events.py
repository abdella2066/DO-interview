"""create flag_audit_events

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23 10:55:43.880467
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "flag_audit_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("flag_key", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_flag_audit_events_flag_key_created_at_id",
        "flag_audit_events",
        ["flag_key", "created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_flag_audit_events_flag_key_created_at_id", table_name="flag_audit_events")
    op.drop_table("flag_audit_events")
