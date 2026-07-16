"""add analysis review, board disposition, detection provenance

Revision ID: 75a0904387fd
Revises: fb90cc29a723
Create Date: 2026-07-16 01:08:41.235249

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '75a0904387fd'
down_revision: str | Sequence[str] | None = 'fb90cc29a723'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('board_disposition',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('image_id', sa.UUID(), nullable=False),
    sa.Column('decision', sa.Enum('approved', 'rework', 'discarded', name='board_disposition_decision', native_enum=False), nullable=False),
    sa.Column('decided_by', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['decided_by'], ['user.id'], name=op.f('fk_board_disposition_decided_by_user')),
    sa.ForeignKeyConstraint(['image_id'], ['inspection_image.id'], name=op.f('fk_board_disposition_image_id_inspection_image'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_board_disposition')),
    sa.UniqueConstraint('image_id', name=op.f('uq_board_disposition_image_id'))
    )
    op.create_table('analysis_review',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('analysis_id', sa.UUID(), nullable=False),
    sa.Column('reviewer_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.Enum('validated', 'rejected', name='analysis_review_action', native_enum=False), nullable=False),
    sa.Column('comment', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['analysis_id'], ['analysis.id'], name=op.f('fk_analysis_review_analysis_id_analysis'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewer_id'], ['user.id'], name=op.f('fk_analysis_review_reviewer_id_user')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_analysis_review'))
    )
    # server_default backfills existing rows (all pre-existing detections came from the
    # model, never from a manual annotation) so this stays a safe online migration.
    op.add_column(
        'detection',
        sa.Column(
            'source',
            sa.Enum('model', 'manual', name='detection_source', native_enum=False),
            server_default='model',
            nullable=False,
        ),
    )
    # Manually-drawn detections (source=manual) have no producing model version.
    op.alter_column('detection', 'model_version_id',
               existing_type=sa.UUID(),
               nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('detection', 'model_version_id',
               existing_type=sa.UUID(),
               nullable=False)
    op.drop_column('detection', 'source')
    op.drop_table('analysis_review')
    op.drop_table('board_disposition')
