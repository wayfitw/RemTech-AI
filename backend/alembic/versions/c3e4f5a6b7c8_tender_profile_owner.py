"""tender_subscriptions.user_id — владелец профиля (#44)

Revision ID: c3e4f5a6b7c8
Revises: b2d3e4f5a6b7
Create Date: 2026-07-17 14:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'c3e4f5a6b7c8'
down_revision: Union[str, None] = 'b2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('tender_subscriptions',
                  sa.Column('user_id', sa.Integer(),
                            sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=True))
    op.create_index('ix_tender_subscriptions_user_id', 'tender_subscriptions', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_tender_subscriptions_user_id', table_name='tender_subscriptions')
    op.drop_column('tender_subscriptions', 'user_id')
