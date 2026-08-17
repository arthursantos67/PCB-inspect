"""add analysis.language and analysis.translations

The station now runs in one language and every operator-facing text follows it (issue #50),
including the analysis prose the agent chain writes. Two columns carry that:

`language` records which language a stored analysis was actually written in, so a report in
the other language knows there is something to translate. Existing rows are backfilled to
'en': they were all written by English-only prompts.

`translations` caches the same analysis rendered in another language, keyed by language code,
so the LLM translation is paid for once per analysis per language rather than once per
generated report. Left NULL for everything that has never been asked for in another language.

Revision ID: a3f7d21c9b04
Revises: e4b7c1d90f52
Create Date: 2026-08-16 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3f7d21c9b04"
down_revision: Union[str, Sequence[str], None] = "e4b7c1d90f52"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis", sa.Column("language", sa.String(), nullable=True))
    op.add_column(
        "analysis",
        sa.Column("translations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    # Backfill rather than defaulting the column: only rows that already exist were written in
    # English by definition, and a server default would silently mislabel every future row
    # written while the station is set to Portuguese.
    op.execute("UPDATE analysis SET language = 'en' WHERE language IS NULL")


def downgrade() -> None:
    op.drop_column("analysis", "translations")
    op.drop_column("analysis", "language")
