"""reminders (личные напоминания ассистента)

Revision ID: a1c2d3e4f5a6
Revises: fececcffeb78
Create Date: 2026-07-16 18:10:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'a1c2d3e4f5a6'
down_revision: Union[str, None] = 'fececcffeb78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'reminders',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('due_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('lead_pending', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_reminders_user_id', 'reminders', ['user_id'])
    op.create_index('ix_reminders_due_at', 'reminders', ['due_at'])


def downgrade() -> None:
    op.drop_index('ix_reminders_due_at', table_name='reminders')
    op.drop_index('ix_reminders_user_id', table_name='reminders')
    op.drop_table('reminders')
