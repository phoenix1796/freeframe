"""add_transcript_error

Revision ID: 28fa0f3bff11
Revises: b3c33bc6baed
Create Date: 2026-07-23 14:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28fa0f3bff11'
down_revision: Union[str, Sequence[str], None] = 'b3c33bc6baed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('media_files', sa.Column('transcript_error', sa.String(length=500), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('media_files', 'transcript_error')
