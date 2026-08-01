"""add result_codes table

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-30

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "result_codes",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("code", sa.String(length=8), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=True),
        sa.Column("image_description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("price_min", sa.Float(), nullable=True),
        sa.Column("price_max", sa.Float(), nullable=True),
        sa.Column("product_ids", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("sample_products", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_result_codes_code"), "result_codes", ["code"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_result_codes_code"), table_name="result_codes")
    op.drop_table("result_codes")
