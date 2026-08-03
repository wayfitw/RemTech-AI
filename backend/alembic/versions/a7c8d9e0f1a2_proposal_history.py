"""proposal_history — история последних 30 КП-презентаций менеджера (#54)

Revision ID: a7c8d9e0f1a2
Revises: f6b7c8d9e0f1
Create Date: 2026-08-03 15:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'a7c8d9e0f1a2'
down_revision: Union[str, None] = 'f6b7c8d9e0f1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'proposal_history',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_id', sa.Integer(),
                  sa.ForeignKey('uploaded_files.id', ondelete='SET NULL'), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('client_name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('machine', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('template', sa.String(length=32), nullable=False, server_default='standard'),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
    )
    op.create_index('ix_proposal_history_user_id', 'proposal_history', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_proposal_history_user_id', table_name='proposal_history')
    op.drop_table('proposal_history')
