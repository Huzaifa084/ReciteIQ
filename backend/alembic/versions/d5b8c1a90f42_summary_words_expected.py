"""session_summaries: words_expected as the accuracy denominator

The UI derived accuracy from words_ok / (words_ok + words_missed). Words inside
a skipped ayah aggregate into MISSED_AYAH and never reach words_missed, so they
left the denominator entirely and a reciter who skipped three ayahs of
Al-Fatihah was shown 100% accuracy. The denominator now comes from the server.

Backfill is deliberately conservative: for existing rows we can only recover
words_ok + words_missed, which is what the old UI already assumed, so no
historical summary gets a WORSE number than it displayed. Rows with a skipped
ayah stay understated until re-finalised — flagged rather than invented.

Revision ID: d5b8c1a90f42
Revises: c3f9a2e64d17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d5b8c1a90f42"
down_revision: Union[str, None] = "c3f9a2e64d17"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("session_summaries",
                  sa.Column("words_expected", sa.Integer(), nullable=False, server_default="0"))
    op.execute("UPDATE session_summaries SET words_expected = words_ok + words_missed")


def downgrade() -> None:
    op.drop_column("session_summaries", "words_expected")
