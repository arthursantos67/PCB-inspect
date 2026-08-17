"""add chat_session.attached_inspection_ids

Lets the operator pin specific inspections to a conversation by hand instead of relying on
everything staying in the model's context.

Revision ID: c7d41a0b52e9
Revises: af998a29810a
Create Date: 2026-08-14 20:10:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c7d41a0b52e9'
down_revision: str | Sequence[str] | None = 'af998a29810a'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'chat_session',
        sa.Column(
            'attached_inspection_ids',
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chat_session', 'attached_inspection_ids')
