"""content_channels + content_topics_seen — контент-дайджест ТГ-каналов (#47)

Revision ID: e5a6b7c8d9e0
Revises: d4f5a6b7c8d9
Create Date: 2026-07-21 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'e5a6b7c8d9e0'
down_revision: Union[str, None] = 'd4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'content_channels',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ref', sa.String(length=200), nullable=False, unique=True),
        sa.Column('title', sa.Text(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        'content_topics_seen',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('topic_hash', sa.String(length=64), nullable=False, unique=True),
        sa.Column('topic', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table('content_topics_seen')
    op.drop_table('content_channels')
