"""conversations.channel — изоляция историй по каналу web/telegram

Revision ID: d4f5a6b7c8d9
Revises: c3e4f5a6b7c8
Create Date: 2026-07-18 21:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'd4f5a6b7c8d9'
down_revision: Union[str, None] = 'c3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Существующие строки получают server_default 'web'. Бэкфилл telegram-историй
    # (где надо) выполняется отдельным скриптом — исторически канал неразличим.
    op.add_column('conversations',
                  sa.Column('channel', sa.String(length=16), nullable=False, server_default='web'))
    op.create_index('ix_conversations_channel', 'conversations', ['channel'])


def downgrade() -> None:
    op.drop_index('ix_conversations_channel', table_name='conversations')
    op.drop_column('conversations', 'channel')
