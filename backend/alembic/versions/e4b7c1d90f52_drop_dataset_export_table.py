"""drop dataset_export table

The YOLO dataset export / retrain flow was removed: retraining
needs a GPU that the inspection station may not have, so the training cycle stays entirely in
the external notebook and the software only swaps and versions weights (FR-12). Nothing reads
this table any more.

The ZIP files that were already generated are not touched by this migration — they stay under
the configured reports/exports directory and can be deleted by hand.

Revision ID: e4b7c1d90f52
Revises: c7d41a0b52e9
Create Date: 2026-08-15 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e4b7c1d90f52"
down_revision: Union[str, Sequence[str], None] = "c7d41a0b52e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_table("dataset_export")


def downgrade() -> None:
    op.create_table(
        "dataset_export",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("filters", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "COMPLETED",
                "FAILED",
                name="dataset_export_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("file_path", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("requested_by", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"], ["user.id"], name=op.f("fk_dataset_export_requested_by_user")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dataset_export")),
    )
