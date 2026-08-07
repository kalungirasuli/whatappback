"""store search images on chat interactions and interests

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "chat_interactions",
        sa.Column("image_urls", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "interest_events",
        sa.Column("result_code", sa.String(length=8), nullable=True),
    )
    op.add_column(
        "interest_events",
        sa.Column("search_image_urls", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.create_index(
        "ix_interest_events_result_code",
        "interest_events",
        ["result_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_interest_events_result_code", table_name="interest_events")
    op.drop_column("interest_events", "search_image_urls")
    op.drop_column("interest_events", "result_code")
    op.drop_column("chat_interactions", "image_urls")
