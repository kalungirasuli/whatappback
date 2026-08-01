"""add chat_interactions table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-01

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "chat_interactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("correlation_id", sa.String(length=100), nullable=True),
        sa.Column("user_message_type", sa.String(length=20), nullable=False),
        sa.Column("user_text", sa.Text(), nullable=True),
        sa.Column("image_count", sa.Integer(), nullable=False),
        sa.Column("image_description", sa.Text(), nullable=True),
        sa.Column("nlu_intents", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("text_topic", sa.String(length=100), nullable=True),
        sa.Column("text_family", sa.String(length=100), nullable=True),
        sa.Column("image_family", sa.String(length=100), nullable=True),
        sa.Column("reply_type", sa.String(length=50), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("result_code", sa.String(length=8), nullable=True),
        sa.Column("follow_up", postgresql.JSONB(), nullable=True),
        sa.Column("top_results", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_chat_interactions_phone_number"), "chat_interactions", ["phone_number"], unique=False)
    op.create_index(op.f("ix_chat_interactions_user_id"), "chat_interactions", ["user_id"], unique=False)
    op.create_index(op.f("ix_chat_interactions_result_code"), "chat_interactions", ["result_code"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_interactions_result_code"), table_name="chat_interactions")
    op.drop_index(op.f("ix_chat_interactions_user_id"), table_name="chat_interactions")
    op.drop_index(op.f("ix_chat_interactions_phone_number"), table_name="chat_interactions")
    op.drop_table("chat_interactions")
