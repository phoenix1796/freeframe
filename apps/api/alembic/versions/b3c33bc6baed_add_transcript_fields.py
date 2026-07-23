"""add_transcript_fields

Revision ID: b3c33bc6baed
Revises: 54b1ad156f8f
Create Date: 2026-07-23 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c33bc6baed'
down_revision: Union[str, Sequence[str], None] = '54b1ad156f8f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'asset_versions',
        sa.Column('transcript_requested', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column('asset_versions', 'transcript_requested', server_default=None)
    op.add_column('media_files', sa.Column('s3_key_transcript', sa.String(length=1000), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('media_files', 's3_key_transcript')
    op.drop_column('asset_versions', 'transcript_requested')
