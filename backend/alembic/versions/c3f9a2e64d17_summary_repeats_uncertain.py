"""session_summaries: count repeats and uncertain separately

A repeat and an unplaceable stretch of audio are not errors, but a summary that
does not show them tells the reciter nothing: someone who restarted an ayah sees
the same screen as someone who recited it once, and audio we failed to place
looks like a clean run. The phoneme path already tracked `uncertain` but buried
it in the JSON detail blob, where the summary view could not reach it.

Revision ID: c3f9a2e64d17
Revises: a1c4e7f20b91
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3f9a2e64d17"
down_revision: Union[str, None] = "a1c4e7f20b91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_summaries",
                  sa.Column("repeats", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("session_summaries",
                  sa.Column("uncertain", sa.Integer(), nullable=False, server_default="0"))
    # Backfill the phoneme path's existing value out of the detail blob.
    op.execute("""
        UPDATE session_summaries
        SET uncertain = COALESCE((detail ->> 'uncertain')::int, 0)
        WHERE detail ? 'uncertain'
    """)


def downgrade() -> None:
    op.drop_column("session_summaries", "uncertain")
    op.drop_column("session_summaries", "repeats")
