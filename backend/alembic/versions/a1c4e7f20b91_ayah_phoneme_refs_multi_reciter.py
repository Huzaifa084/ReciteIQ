"""ayah_phoneme_refs: one CTC reference per reciter (P0-1)

Adds a per-reciter reference table. `ayahs.phoneme_ids` is left untouched as the
legacy single-reciter (Husary) canonical, so the previous matching path stays
available as a rollback and no existing row is rewritten.

Revision ID: a1c4e7f20b91
Revises: 5966d3da708d
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "a1c4e7f20b91"
down_revision: Union[str, None] = "5966d3da708d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ayah_phoneme_refs",
        sa.Column("ayah_id", sa.Integer(), sa.ForeignKey("ayahs.id"), primary_key=True),
        sa.Column("reciter", sa.String(length=64), primary_key=True),
        sa.Column("ids", JSONB(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
    )
    op.create_index("ix_ayah_phoneme_refs_ayah", "ayah_phoneme_refs", ["ayah_id"])


def downgrade() -> None:
    op.drop_index("ix_ayah_phoneme_refs_ayah", table_name="ayah_phoneme_refs")
    op.drop_table("ayah_phoneme_refs")
