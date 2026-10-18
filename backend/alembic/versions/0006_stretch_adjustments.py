"""stretch_adjustments

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-18

Adds the one table issue #13 (Stretch's adaptive difficulty) needs --
generated against `Base.metadata` (`app/db.py`'s `StretchAdjustment`) and
hand-checked -- the `compare_metadata` guard in `tests/test_migrations.py`
is green against this revision.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "stretch_adjustments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("d_before", sa.Float(), nullable=False),
        sa.Column("d_after", sa.Float(), nullable=False),
        sa.Column("helps_per_100_words", sa.Float(), nullable=False),
        sa.Column("comprehension", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["session_id"], ["reading_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_stretch_adjustments_session"),
    )


def downgrade() -> None:
    op.drop_table("stretch_adjustments")
