"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-15

The baseline: exactly what `Base.metadata` (app/db.py) defines as of this
revision. This app starts from nothing, so unlike kanji-trainer's 0001 there
is no pre-Alembic deployment to bridge -- every database reaches this schema
by running this file via `upgrade head`.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("openai_api_key", sa.Text(), nullable=True),
        sa.Column("generation_model", sa.String(), nullable=True),
        sa.Column("help_model", sa.String(), nullable=True),
        sa.Column("kanji_trainer_mcp_url", sa.String(), nullable=True),
        sa.Column("web_search_enabled", sa.Boolean(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="app_settings_single_row"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
