"""make inspection_image width/height nullable

Revision ID: 93a85fbf998e
Revises: 45e32f1c8b8f
Create Date: 2026-07-10 20:00:00.000000

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '93a85fbf998e'
down_revision: str | Sequence[str] | None = '45e32f1c8b8f'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # A FAILED (corrupted/unreadable) file has no dimensions to report (FR-03).
    op.alter_column('inspection_image', 'width', existing_type=sa.Integer(), nullable=True)
    op.alter_column('inspection_image', 'height', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('inspection_image', 'height', existing_type=sa.Integer(), nullable=False)
    op.alter_column('inspection_image', 'width', existing_type=sa.Integer(), nullable=False)
