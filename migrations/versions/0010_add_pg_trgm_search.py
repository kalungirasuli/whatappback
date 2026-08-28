"""add pg_trgm extension and trigram indexes for lexical search fallback

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-09

"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_index(
        "ix_products_name_trgm",
        "products",
        [postgresql.text("name gin_trgm_ops")],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_products_brand_trgm",
        "products",
        [postgresql.text("brand gin_trgm_ops")],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_products_brand_trgm", table_name="products")
    op.drop_index("ix_products_name_trgm", table_name="products")
