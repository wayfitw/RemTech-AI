"""part_queries + part_listings — мониторинг объявлений о запчастях (#46)

Revision ID: f6b7c8d9e0f1
Revises: e5a6b7c8d9e0
Create Date: 2026-08-03 12:00:00.000000
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = 'f6b7c8d9e0f1'
down_revision: Union[str, None] = 'e5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'part_queries',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('query', sa.String(length=200), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='all'),
        sa.Column('region', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint('query', 'source', 'region', name='uq_part_query'),
    )
    op.create_table(
        'part_listings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('external_id', sa.String(length=64), nullable=False),
        sa.Column('query_id', sa.Integer(),
                  sa.ForeignKey('part_queries.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.Text(), nullable=False, server_default=''),
        sa.Column('url', sa.Text(), nullable=False, server_default=''),
        sa.Column('region', sa.String(length=100), nullable=False, server_default=''),
        sa.Column('price', sa.Integer(), nullable=True),
        sa.Column('price_initial', sa.Integer(), nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('source', 'external_id', name='uq_part_listing'),
    )
    op.create_index('ix_part_listings_source', 'part_listings', ['source'])
    op.create_index('ix_part_listings_query_id', 'part_listings', ['query_id'])


def downgrade() -> None:
    op.drop_index('ix_part_listings_query_id', table_name='part_listings')
    op.drop_index('ix_part_listings_source', table_name='part_listings')
    op.drop_table('part_listings')
    op.drop_table('part_queries')
